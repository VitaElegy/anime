# 同看多人同步协议（Watch Party Sync Protocol）

> 版本：v1（2026-04-18）
> 适用：`WatchRoomPage.tsx` 与 `/api/watch/rooms/{id}/state` + SSE `/events`
> 前置阅读：[`MULTIVIEWER_SYNC_REPORT.md`](../MULTIVIEWER_SYNC_REPORT.md)

---

## 1. 数据模型

### 1.1 权威状态字段（服务端持有）

| 字段 | 类型 | 语义 |
|------|------|------|
| `media_id` | string | 当前片源 ID，决定播放哪个视频 |
| `playback_mode` | `'direct_play' \| 'hls'` | 播放模式 |
| `playback_url` | string | 相对路径，如 `/api/media/{id}/stream` |
| `paused` | boolean | 是否暂停 |
| `position_seconds` | number | 播放位置（秒，float） |
| `playback_rate` | number | 倍速（0.5 / 1 / 1.25 / 1.5 / 2 等） |
| `updated_by` | string | 最后一次修改者用户名（审计） |
| `updated_at` | number | 最后修改时间戳（毫秒） |

### 1.2 HTTP API

#### PUT `/api/watch/rooms/{room_id}/state`
Body：
```json
{
  "media_id": "cf6145e4...",        // 可选（切片源时必填）
  "playback_mode": "direct_play",    // 可选
  "playback_url": "/api/media/.../stream",  // 可选
  "paused": false,
  "position_seconds": 123.4,
  "playback_rate": 1.0,
  "updated_by": "alice"
}
```
返回完整 `WatchRoom`，并通过 SSE `room_state` 事件广播给所有订阅者。

#### GET `/api/watch/rooms/{room_id}/events`（SSE）
事件类型：
- `room_state` — 权威状态变化（payload 为完整 `WatchRoom`）
- 初始 snapshot —— 连接后立即发送一次当前状态

---

## 2. 前端双向同步协议

### 2.1 两条链路

```
                ┌─────────────────────────────────────────────┐
                │   服务端权威 WatchRoom.state (SQLite + mem) │
                └────────────┬──────────────────▲─────────────┘
                             │ SSE              │ PUT
                             ▼                  │
    链路 A: 远程→本地 effect  │  链路 B: 本地→远程 effect
  (room.state 变 → 写 video) │  (video 事件 → PUT)
                             │                  │
                             ▼                  │
                       ┌──────────────────────────┐
                       │   <video> DOM element    │
                       └──────────────────────────┘
```

### 2.2 链路 A：远程 → 本地

触发：`room.state` 发生变化（paused / position / rate / updated_at）。

规则：
- 仅当 `|video.currentTime - remote.position| > 1.5s` 时才强制 seek
- `paused` 差异时调用 `video.pause()` / `video.play()`
- `|playbackRate - remote.rate| > 0.01` 时调整倍速
- 在 `readyState < 1` 时把目标位置暂存到 `pendingSeekRef`，`onLoadedMetadata` 再应用
- **每次写 video 前后必须 `suppressBroadcastRef++ / --`**（见 §3）

### 2.3 链路 B：本地 → 远程

触发：DOM 事件 `play` / `pause` / `seeked` / `ratechange`。

规则：
- 事件进入时先查 `suppressBroadcastRef.current > 0`，是则丢弃（回声抑制）
- `seeked` 事件必须 200ms debounce
- 发 PUT 前对比 `lastBroadcastRef`，内容几乎一致且 <350ms 内则跳过
- PUT 响应的 `WatchRoom` 直接 `setRoom(next)`，避免等 SSE 自回环

---

## 3. 回环抑制（Echo Suppression）

### 3.1 为什么必要

`video.pause()` 会触发 DOM 的 `pause` 事件。如果不加保护：

```
Host 点暂停 → PUT → SSE → Guest 收到 → video.pause()
     ↑                        ↓
     │                        DOM 发出 pause 事件
     │                        ↓
     │            Guest 的 broadcast effect 发出 PUT
     │                        ↓
     └─── SSE 回环到 Host ────┘  (无限循环)
```

### 3.2 三道闸门

| # | 机制 | 作用时间窗 | 触发条件 |
|---|------|------|------|
| 1 | `suppressBroadcastRef` 计数器 | 250ms | 远程 effect 每写一次 video 就 `++` |
| 2 | `lastBroadcastRef` 内容比对 | 350ms | 差值 `|Δpos|<0.5 && |Δrate|<0.01 && paused 相同` |
| 3 | `seeked` debounce | 200ms | 拖动进度条的连发 seeked 合并 |

注意：闸 1 是主防线，闸 2 是兜底（防止写多个字段时计数器不够用），闸 3 是性能优化。

---

## 4. 阈值定义

| 常量 | 值 | 出处 |
|------|---|------|
| `SEEK_THRESHOLD_SECONDS` | `1.5` | 链路 A 是否强制 seek |
| suppression TTL | `250 ms` | armSuppression 的 setTimeout |
| broadcast dedup TTL | `350 ms` | lastBroadcastRef 比对窗口 |
| seek debounce | `200 ms` | seeked → PUT 合并窗口 |
| position 比对容差 | `0.5 s` | dedup 时 Δpos 判定 |
| rate 比对容差 | `0.01` | dedup 时 Δrate 判定 |

---

## 5. 事件时序示例

### 5.1 Host 暂停视频

```
t=0ms    [Host]  user clicks pause on <video>
                 └─ DOM emits 'pause' event
                 └─ broadcast(): suppressRef=0 → PUT /state {paused:true, pos:115.4}

t=20ms   [Server] writes SQLite, fans out SSE room_state
t=60ms   [Host]   receives own SSE → remote effect sees paused=true, already true, noop
                  (闸 1/2 均生效)
t=80ms   [Guest]  receives SSE → remote effect:
                    - armSuppression (ref=1)
                    - video.pause() → DOM emits 'pause' event
                    - lastBroadcastRef = {paused:true, pos:115.3, ...}
t=81ms   [Guest]  'pause' DOM event fires → broadcast():
                    suppressRef=1 > 0 → DROP (闸 1)
t=330ms  [Guest]  suppressRef TTL 到，--
```

### 5.2 Host 快速拖动进度条到 300s

```
t=0   [Host] seeked → debounce timer armed (200ms)
t=50  [Host] seeked (still dragging) → reset timer
t=150 [Host] seeked                   → reset timer
t=200 [Host] 停止拖动
t=400 [Host] debounce fires → PUT /state {pos:300}
```

只发 1 次 PUT，不论用户多快滑动。

---

## 6. 失败模式与降级

| 场景 | 当前行为 | 未来可优化 |
|------|------|------|
| PUT 返回 401/403 | `setPlayerHint('同步失败：...')` 提示 | 按角色限制 UI 可操作性 |
| PUT 返回 5xx / 网络错误 | 静默（避免骚扰） | 重试队列 |
| SSE 断线 | 浏览器默认重连 | 主动 re-subscribe + 重拉快照 |
| autoplay 被浏览器阻止 | 设 `playerHint` 提示用户点一下 | 首次进入时显示大播放按钮 |
| remote position 跳到视频尾部 | video 会自然触发 `ended` | 广播 `ended` 让 host 换片 |

---

## 7. 开发与调试

### 7.1 本地验证双 Tab 同步

```powershell
# 启动后端
cd D:\Project\anime\anime
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 启动前端
cd frontend
npm run dev

# 打开两个浏览器窗口（必须不同 session 更真实，本地同一 session 也可）
# 都进入 http://localhost:3000/watch/<room_id>
```

一方操作，另一方应在 1-2 秒内跟随。

### 7.2 Playwright 自动化

见 `PLAYBACK_SYNC_TEST_REPORT.md` 与 `MULTIVIEWER_SYNC_REPORT.md §四`。核心命令：

```powershell
playwright-cli tab-select 0
playwright-cli eval "() => document.querySelector('video').pause()"
# 等 2s
playwright-cli tab-select 1
playwright-cli eval "() => document.querySelector('video').paused"  # 应为 true
```

### 7.3 常见排错

| 症状 | 检查 |
|------|------|
| 一方操作完全不广播 | F12 Network 看有没有 PUT `/state`；看 `suppressBroadcastRef` 是否被卡住 > 0 |
| 两方无限抖动 | 闸门被绕过，检查是否有 effect 在 video.play() 后没 armSuppression |
| 拖进度条卡顿 | seek debounce 是否工作，Network 里应只有 1 个 PUT |
| SSE 收到但 video 不跟随 | 看 `videoElementReady` 是否 true，`assetBlocked` 是否 false |

---

## 8. 协议保留位（未来）

预留字段（当前未启用，前端忽略即可）：
- `captions_url` — 当前字幕
- `audio_track` — 多音轨选择
- `buffering` — viewer 缓冲状态聚合
- `presence[]` — 在场成员列表与状态

这些字段将在后续版本中启用，本协议 v1 只覆盖播放/暂停/进度/倍速四大核心操作。
