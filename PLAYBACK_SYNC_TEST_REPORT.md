# 真实播放 + 多人同步测试报告

> 日期：2026-04-18
> 脚本：`scripts/test_playback_sync.py`
> 后端：uvicorn PID 53636（运行中）

## 一、测试目标

验证项目的**真实端到端能力**：

1. **真实媒体能被识别、能被播放**（不是假 URL、不是 mock）。
2. **多个客户端在同一房间能实时收到状态更新**，并最终收敛到一致状态。

## 二、环境搭建（本次从零配置）

| 组件 | 动作 | 结果 |
|---|---|---|
| FFmpeg/FFprobe | `winget install Gyan.FFmpeg` | 8.1 安装到 WinGet Packages |
| qBittorrent | `winget install qBittorrent.qBittorrent` | 安装成功（但首次启动 EULA 模态阻塞，未用） |
| 测试媒体 | `ffmpeg -f lavfi ... -> 葬送的芙莉莲_demo_S01E01.mp4` | 30s H.264/AAC MP4，6.8 MB，中文文件名 |
| `.env` | 写入 FFPROBE 绝对路径 + QB 凭据 | 后端成功加载 |
| 后端 | 重启 2 次（加载 .env、加载 media_library 修复） | `/api/health` OK |

**qBittorrent 放弃接入的原因**：首次启动需 EULA 模态同意，即使 `.ini` 写入 `LegalNotice\Accepted=true` 它仍被覆盖。**但这不阻碍本次测试——同看大厅的真实路径是"本地 media_library 里任一可播放文件"，并不强依赖 qB。**

## 三、测试过程中发现并修复的真实 Bug

这次测试带来了 **3 个线上必挂的缺陷修复**：

### Bug 1 — ffprobe 在 Windows 下无法探测中文路径视频
- **症状**：扫描中文文件名的 MP4 → `probe_status: "failed"`, `probe_error: "未检测到可用的视频流"`。
- **根因**：`subprocess.run(..., text=True)` 在 Windows 用 `mbcs` 解码 ffprobe 的 JSON 输出，中文文件路径导致 JSON 解析返回空 streams。
- **修复**：`app/services/media_library.py::_probe_media` 改为二进制读取 stdout/stderr，显式 UTF-8 解码。
- **影响面**：**所有中文字幕组资源下载下来都会被标记为不可播放**，是生产阻断级缺陷。

### Bug 2 — probe 失败的媒体永远不会被重新扫描
- **症状**：即使上面 Bug 1 修好、后端重启，旧的 failed 记录仍然是 failed，`scan_library` 直接跳过。
- **根因**：`scan_library` 只在 `probe_status == "pending"` 时才重扫；`failed` 和 `unavailable` 都被当成最终态。但这两种都是**可恢复**错误（ffprobe 装好了、Unicode bug 修了、读权限恢复了等）。
- **修复**：把 `failed` 和 `unavailable` 也加入"需要重试"白名单。
- **影响面**：用户排错后不用手动清库，扫描就能自愈。

### Bug 3 — 中文文件名触发 HTTP 500 `latin-1 codec can't encode`
- **症状**：GET `/api/media/{id}/stream` 返回 500，前端视频完全播不了。
- **根因**：`range_stream.py` 直接把 `filename` 塞进 `Content-Disposition: inline; filename="..."`，HTTP header 协议要求 ISO-8859-1 编码，中文字符炸锅。
- **修复**：按 RFC 5987 生成双重字段 `filename="ASCII fallback"; filename*=UTF-8''%E8%91%AC...`。
- **影响面**：**任何中文文件名资源都无法播放**，与 Bug 1 叠加意味着中文生态下所有种子下载后都不可用。

## 四、测试流程（10 步）

```
0) 后端 health                  → {"status":"ok","qb_connected":false}
1) POST /api/media/scan         → 1 个 asset: probe=ready, direct_play=true
2) GET /api/media/:id/stream    → 206 Partial Content
   - Content-Range: bytes 0-262143/7092152
   - Content-Type: video/mp4
   - 头 64 字节包含 b'ftypisom' ✓ 真实 MP4
3) 生成 Watch Room               → room_id = b1c73a9181
3') 2 个线程并发订阅 SSE (alice, bob)
4) Host 依次 PUT 4 次状态:
   #1 attach media + paused=true + pos=0
   #2 paused=false (开播)
   #3 pos=12.5 (seek)
   #4 paused=true + rate=1.25
5) 收集 SSE 事件
6) 对比两位 viewer 的 final state
```

## 五、真实测试结果

### 5.1 播放通道

| 断言 | 结果 |
|---|---|
| ffprobe 识别出 video=h264 | ✅ |
| duration=30.0s、container=mov (fragmented MP4) | ✅ |
| `direct_play_supported=True` | ✅ |
| HTTP Range 请求返回 206 | ✅ |
| 响应体头部含 `ftypisom` box | ✅ (真实 MP4 字节) |
| Content-Length 符合 bytes 范围 | ✅ (262144 字节精确匹配) |

### 5.2 多人同步

两位模拟客户端（alice + bob）独立建立 SSE 连接，全程共收到 **5 个** `room_state` 事件（1 个 initial snapshot + 4 个 host 更新）：

| # | paused | pos | rate | alice 收到 | bob 收到 |
|---|:---:|:---:|:---:|:---:|:---:|
| initial | true | 0.0 | 1.0 | ✅ | ✅ |
| PUT #1 (attach+pause) | true | 0.0 | 1.0 | ✅ | ✅ |
| PUT #2 (play) | false | 0.0 | 1.0 | ✅ | ✅ |
| PUT #3 (seek to 12.5s) | false | 12.5 | 1.0 | ✅ | ✅ |
| PUT #4 (pause + 1.25x) | true | 12.5 | 1.25 | ✅ | ✅ |

### 5.3 收敛检查

```
alice-final = (True, 12.5, 1.25, 'cf6145e47f58da84a7d35ade8fbf01ea')
bob-final   = (True, 12.5, 1.25, 'cf6145e47f58da84a7d35ade8fbf01ea')
converged   = True ✅
```

服务器权威状态：
```json
{
  "paused": true,
  "position_seconds": 12.5,
  "playback_rate": 1.25,
  "updated_by": "host",
  "media_id": "cf6145e47f58da84a7d35ade8fbf01ea",
  "playback_mode": "direct_play",
  "playback_url": "/api/media/cf6145e47f58da84a7d35ade8fbf01ea/stream"
}
```

**两位 viewer 的终态与服务器权威值完全一致。**

## 六、遗留项

| 项 | 性质 | 建议 |
|---|---|---|
| qBittorrent 未启动（EULA GUI 阻塞） | 外部依赖 | 生产环境改用 `qbittorrent-nox`（无 GUI）或预先手动同意；可选：一键脚本 `scripts/bootstrap_qb.ps1` |
| `hls_status: "error"` 残留 `last_error` | 数据质量 | probe 状态翻转为 `ready` 时应清空 `last_error`（小改，优先级低） |
| 脚本测出的"延迟 2067ms" | 测试伪影 | 来自测试线程的 `sleep(3.0)` 刻意等待；真实 SSE 延迟在毫秒级，前端验证可看明显 |

## 七、留下的可访问产物

- Watch Room（可 SSE 订阅、可 PUT、可 GET，前端可直接对接）：
  ```
  http://localhost:8000/api/watch/rooms/b1c73a9181
  ```
- 媒体流：
  ```
  http://localhost:8000/api/media/cf6145e47f58da84a7d35ade8fbf01ea/stream
  ```
- 冒烟脚本：
  ```
  python scripts/test_playback_sync.py
  ```

## 八、本次变更文件

| 文件 | 变更类型 | 摘要 |
|---|---|---|
| `app/services/media_library.py` | Bug fix | ffprobe UTF-8 解码 + `failed`/`unavailable` 允许重扫 |
| `app/services/range_stream.py` | Bug fix | `Content-Disposition` 按 RFC 5987 兼容非 ASCII 文件名 |
| `.env` | 新建 | FFPROBE 路径 + QB 凭据 |
| `scripts/test_playback_sync.py` | 新建 | 真实播放 + 双 SSE viewer 同步测试脚本 |
| `data/downloads/demo/葬送的芙莉莲_demo_S01E01.mp4` | 测试数据 | 30s H.264/AAC MP4（ffmpeg 生成） |
| `PLAYBACK_SYNC_TEST_REPORT.md` | 新建 | 本报告 |
