# 在线渠道（Channel）架构规范

> 状态：v1.0 生效稿 · 2026-08-13
> 本文件是「在线观看渠道」功能的**唯一实现依据**。任何代码改动必须先满足本文定义的
> 角色边界与接口契约；若需调整契约，先改本文并注明原因。

## 0. 目标与用户旅程

用户只需要：

1. 输入中文（或日文/英文）→ 看到动漫卡片
2. 点击动漫 → 看到「有哪些渠道」可在线观看
3. 点击渠道 → 看到对应集数列表
4. 点击某一集 → **直接播放**（hls.js / 原生 video），尽量清晰流畅、不卡顿、低内存

系统背后可以有多达 N 个渠道（AGE动漫 / 樱花 / Libvio / Zzzfun / B站 外链…），
但用户不关心每个渠道的内部差异；渠道对用户是「可选项」，坏一个不影响其它。

## 1. 角色总览（职责边界）

```
┌───────────────┐   ┌────────────────────┐   ┌───────────────────┐
│  SearchAggregator │→│  ChannelProvider*N   │→│  ChannelRegistry    │
│  (搜索聚合器)     │   │  (渠道提供者)       │   │  (渠道注册/健康)    │
└───────┬───────┘   └─────────┬──────────┘   └─────────┬─────────┘
        │                     │                        │
        ▼                     ▼                        ▼
┌───────────────┐   ┌────────────────────┐   ┌───────────────────┐
│  EpisodeResolver│  │  StreamResolver     │   │  Cache             │
│  (集数解析器)    │   │  (播放流解析器)     │   │  (TTL 缓存)        │
└───────────────┘   └─────────┬──────────┘   └───────────────────┘
                              ▼
                    ┌────────────────────┐
                    │  StreamProxy        │  后端代理 m3u8/分片，解决 CORS/防盗链
                    └─────────┬──────────┘
                              ▼
                    ┌────────────────────┐
                    │  Renderer           │  前端渲染器：只做「拿到视频流→输出」
                    └────────────────────┘
```

### 1.1 ChannelProvider（渠道提供者）— 唯一的外网接触点

**职责**：针对一个具体资源站，实现三件事——
- `search(keyword, page)`：按关键词在该站搜索，返回标准化 `ChannelSearchResult`
- `get_detail(detail_ref)`：由搜索结果/收藏的引用取详情 + **集数列表**（`ChannelDetail`）
- `get_streams(episode_ref)`：由某一集的引用解析出**可播放流**（`ChannelStream[]`）

**不负责**：跨渠道聚合、排序去重、前端展示、播放。

**约定**：
- 每个 Provider 用 `id` 唯一标识（如 `age` / `libvio` / `zzzfun` / `bilibili`）
- 所有外部请求必须设置 `User-Agent`（可配）与必要 `Referer`
- 解析失败必须抛 `ChannelError`（带 `channel` / `stage`），由 Registry 统一降级
- Provider 内部**不得**自行做长时间重试；超时由公共 HTTP 客户端控制（默认 8s）

### 1.2 SearchAggregator（搜索聚合器）

**职责**：
- 并行调用所有 `healthy` 渠道的 `search`
- 对中文/日文关键词做翻译扩展（复用现有 `search.py::_translate_keyword` 思路）
- 去重（按规范化标题）、合并、排序（渠道优先级 + 标题相似度）
- 输出「聚合后的渠道命中列表」，前端据此展示「渠道选项卡」

**不负责**：播放、下载、元数据（元数据搜索仍走现有 Bangumi/AniList）。

### 1.3 EpisodeResolver（集数解析器）

**职责**：`detail_ref → 集数分组列表`。
一个渠道可能有多条线路（如「第一线路 / 第二线路」），每组内含若干集。

**输出契约**：`ChannelDetail.groups[]`，每集只携带**不透明引用** `episode_ref`，
不携带播放地址（播放地址只在 `get_streams` 阶段解析，避免一次性拉爆）。

### 1.4 StreamResolver（播放流解析器）

**职责**：`episode_ref → ChannelStream[]`（清晰度、格式、有效期、需要的 headers）。

**输出契约**：见 §3 `ChannelStream`。**允许返回空数组**（该集暂不可播）。

### 1.5 Renderer（渲染器）— 前端播放组件

**这是用户特别强调的角色，边界必须最严格：**

**职责（只做这些）**：
- 接收「流地址 + 可选 headers / referer」→ 通过 StreamProxy 输出到 hls.js 或原生 `<video>`
- 提供播放控制（播放/暂停/进度/倍速/音量/全屏/清晰度切换）
- 自动选择最合适的清晰度；自动降级（m3u8 失败 → 尝试 mp4 直链）
- 保证流畅：`hls.startLevel = -1`（auto），开启 `lowLatencyMode`，播放结束/组件卸载时
  **必须销毁 Hls 实例与 MediaSource**，释放内存
- 显示加载/错误状态

**不负责（禁止做）**：
- ❌ 不做搜索、不渲染搜索结果
- ❌ 不解析资源站、不拼播放地址、不处理鉴权/登录
- ❌ 不负责下载/转码/同看房间逻辑
- ❌ 不直接访问外网（所有视频流量走 StreamProxy，规避 CORS/防盗链）
- ❌ 不持有全局状态污染其它页面

### 1.6 StreamProxy（播放流代理）— 后端

**职责**：
- `GET /api/watch/proxy/stream?url=...` 转发 m3u8 清单与 TS 分片
- 转发时自动带上该渠道要求的 `Referer` / `User-Agent` / 其它自定义 headers
- 支持 HTTP Range（分片播放必需）；返回正确的 Content-Type（`application/vnd.apple.mpegurl` / `video/mp2t`）
- 只允许代理 `http(s)` 且带 `host` 白名单（防 SSRF：仅放行渠道注册表中的域名前缀）
- 对已知会掺广告段的镜像（megaplay 系）做 HLS 清单实时过滤：丢弃 `tiktokcdn` 等
  广告 EXTINF+URI 对，保证 hls.js 只收到纯视频分片

**不负责**：解析、转码、缓存分片（m3u8 清单可短 TTL 缓存，分片不缓存）。

### 1.7 Cache（缓存层）

- 搜索结果 TTL 300s；详情（含集数）TTL 600s；播放流 TTL 120s（地址常短期有效）
- 复用现有 `app/services/response_cache.py`；缓存键 = `channel + stage + ref`
- 播放流**不落盘**（只内存 TTL），避免失效地址被复用

### 1.8 ChannelRegistry（渠道注册与健康）

**职责**：
- 启动时注册所有 Provider；提供 `list_channels()`（含健康状态）
- 维护每渠道「连续失败计数 + 熔断冷却」：连续 3 次失败 → 标记 `unhealthy`，
  冷却 120s 后自动重试一次探测；成功即恢复
- 聚合搜索/详情/流解析统一走 Registry，自动跳过 `unhealthy` 渠道
- 所有渠道可配置 `enabled`（`.env` / 环境变量），默认开

## 2. 渠道注册表（首批）

| id | 名称 | 类型 | 实现来源 | 状态 |
|---|---|---|---|---|
| `age` | AGE动漫 | 在线播放（JSON API） | Miru `agedm.org.js` 套路，`api.agedm.org/v2` | 实现（2026-08 实测 TLS 阻断，**已禁用待恢复**） |
| `libvio` | Libvio 在线 | 在线播放（HTML+签名） | Anime-API `libvio.py`（MIT，移植+署名） | 实现（2026-08 实测 403/超时，**已禁用待恢复**） |
| `zzzfun` | Zzzfun | 在线播放（App API） | Anime-API `zzzfun.py`（MIT，移植+署名） | 实现（2026-08 实测域名失效，**已禁用待恢复**） |
| `anilibria` | Anilibria | 在线播放（开放 JSON API） | 官方 `api/v1`，`cache.libria.fun` 直连 HLS | 实现（2026-08 实测可播） |
| `gogoanime` | Gogoanime | 在线播放（HTML + megaplay HLS） | 独立实现，`getSourcesNew` 无广告 | 实现（2026-08 实测可播） |
| `bilibili` | Bilibili 番剧 | 元数据+官方外链（不代理播放） | 现有 `app/services/bilibili.py` | 实现 |

> 渠道可用性会漂移：2026-08-13 实测 AGE/Libvio/Zzzfun 全部不可用（已 `enabled=False`
> 禁用，避免每次聚合搜索都等它们的超时；恢复后移除 `enabled=False` 即可），Anilibria 与
> Gogoanime 为当时验证过的可用备选。聚合搜索整体有 8s 硬超时（§6.1），即使有渠道挂起，
> 用户也能在预算内拿到健康渠道的结果。新源候选：`yhdm`（樱花动漫，需移植 AES 解密）、
> `hianime`（英文源）、`animepahe`（参考 Animepahe-API，需 TLS fingerprint）。
> 增渠道 = 新增一个 Provider 文件 + 注册一行 + 白名单加域名，前端无需改动。

## 3. 接口契约（Pydantic）

```python
class ChannelInfo(BaseModel):
    id: str                    # "age"
    name: str                  # "AGE动漫"
    enabled: bool = True
    healthy: bool = True
    supports_search: bool = True
    supports_detail: bool = True
    supports_streams: bool = True
    language: str = "zh"       # "zh" | "ja" | "en" | "zh-en"
    description: str = ""
    external: bool = False     # True = 仅外链（如 bilibili），无 get_streams

class ChannelSearchResult(BaseModel):
    channel: str               # 渠道 id
    title: str                 # 展示标题（中文优先）
    title_original: str = ""
    cover_url: str = ""
    description: str = ""
    year: str = ""
    detail_ref: str            # 不透明引用，传给 get_detail
    extra: dict = Field(default_factory=dict)

class ChannelEpisode(BaseModel):
    title: str                 # "第1集"
    episode_ref: str           # 不透明引用，传给 get_streams
    extra: dict = Field(default_factory=dict)

class ChannelEpisodeGroup(BaseModel):
    title: str                 # "第一线路"
    episodes: list[ChannelEpisode] = Field(default_factory=list)

class ChannelDetail(BaseModel):
    channel: str
    title: str = ""
    cover_url: str = ""
    description: str = ""
    groups: list[ChannelEpisodeGroup] = Field(default_factory=list)

class ChannelStream(BaseModel):
    type: str = "hls"          # "hls" | "mp4" | "web"
    url: str                   # 绝对 URL（经 proxy 或直链）
    quality: str = ""          # "1080p" / "720p" / "auto"
    format: str = ""           # "m3u8" / "mp4"
    headers: dict[str, str] = Field(default_factory=dict)  # Referer/UA 等
    expires_in: int = 0        # 有效期秒，0 = 未知
    note: str = ""
```

## 4. HTTP API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/watch/channels` | 渠道列表 + 健康状态 |
| GET | `/api/watch/search?q=&page=` | 聚合搜索（跳过 unhealthy） |
| GET | `/api/watch/{channel}/detail?ref=` | 详情 + 集数分组 |
| GET | `/api/watch/{channel}/streams?ref=` | 解析播放流 |
| GET | `/api/watch/proxy/stream?url=&referer=&ua=` | 播放流代理（m3u8/分片，Range 支持） |
| GET | `/api/watch/{channel}/external?ref=` | （仅 external 渠道）返回官方跳转 URL |

错误约定：渠道级失败返回 `200` + 空列表（前端友好降级）；参数错误返回 `400`；
未知渠道返回 `404`；代理拒绝（非白名单域名）返回 `403`。

## 5. 前端交互流程

```
SearchPage(输入中文)
   │  searchAnimeNew(q)  ── 元数据卡片（现有）
   │  watchSearch(q)     ── 渠道命中（新增，聚合）
   ▼
AnimeDetailPage（点击卡片进入，带 title/rawTitle）
   │  watchChannels() ── 渲染「可在线观看」渠道列表
   │  （external 渠道显示「前往 B站」外链；在线渠道可展开）
   ├─ 点击渠道 → watchDetail(channel, ref) → 集数分组（折叠面板）
   │     └─ 点击某集 → 打开 ChannelPlayer（全屏浮层）
   │           ├─ watchStreams(channel, ref) → 取流
   │           └─ hls.js 经 /api/watch/proxy/stream 播放
   ▼
Renderer：hls.js → <video>；卸载时销毁实例释放内存
```

## 6. 健壮性与降级

1. 单渠道超时/失败 → 聚合搜索返回其它渠道结果，前端显示「该渠道暂时不可用」
   （聚合整体 8s 硬超时，挂起渠道的结果会被丢弃，健康渠道照常返回）
2. 渠道熔断（连续 3 次失败冷却 120s）→ 自动跳过，恢复后自动放行
3. 播放流失效（过期/防盗链）→ Renderer 捕获 hls 错误 → 自动尝试同集其它流 →
   仍失败则提示「该线路失效，请换渠道」
4. 所有外部请求都有超时、重试上限（1 次）、UA/Referer 规范
5. StreamProxy 域名白名单防 SSRF；日志脱敏（不打印完整带签名的 URL）
6. 测试用 mock 渠道，绝不依赖真实外网

## 7. 测试要求

- 后端：每个 Provider 用**本地 fixture**（HTML/JSON 样本）做解析单测；
  Registry 熔断/降级单测；API 路由用 mock Provider 测契约
- 前端：渠道列表/集数展开/播放器状态用 vitest + mock api
- 每次测试后执行僵尸进程检查：
  ```bash
  ps aux | awk '$8 ~ /^Z/'   # 必须无输出
  ps aux | grep -E 'pytest|vitest|node' | grep -v grep   # 无本项目残留
  ```

## 8. 移植声明

- `libvio` / `zzzfun` 解析逻辑移植自
  [zaxtyson/Anime-API](https://github.com/zaxtyson/Anime-API)（MIT License,
  Copyright (c) 2020 zaxtyson），已在 `app/services/channels/` 文件头保留版权声明。
- `age` 渠道参考 Miru 扩展 [miru-project/repo](https://github.com/miru-project/repo)
  的 `agedm.org.js`（MIT），接口套路已内化，代码为独立实现。
