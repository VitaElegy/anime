# 开源项目调研与角色规范来源

> 状态：持续维护 · 最后更新 2026-08-13
> 本文件记录 `~/work/Project/_reference/` 下已下载研究的开源项目，以及
> 「角色抽象 → 接口规范」的推导来源。**写任何渠道/播放相关代码之前先读本文与
> [CHANNEL_ARCHITECTURE.md](./CHANNEL_ARCHITECTURE.md)。**

## 0. 角色总览（从开源项目提炼）

用户旅程「中文输入 → 动漫卡片 → 渠道 → 集数 → 观看」被拆成 7 个角色，
每个角色只做一件事，接口由 Pydantic 模型固定（见 CHANNEL_ARCHITECTURE §3）：

| 角色 | 职责 | 不负责 | 主要参考来源 |
|---|---|---|---|
| SearchAggregator | 并行聚合、翻译扩展、去重排序 | 播放、下载 | Anime-API、movie-web |
| ChannelProvider | 一个源站的 search/detail/streams | 聚合、前端 | Miru repo、Anivault-Scraper |
| EpisodeResolver | detail_ref → 集数分组 | 流解析 | Miru repo、aniyomi-extensions |
| StreamResolver | 集数 → 可播放流（解密/解混淆） | 渲染 | ReAnime.to-API、Anime-API |
| Cache | TTL 缓存搜索结果/详情/短效流 | 持久化 | movie-web（sw cache 思路） |
| StreamProxy | 后端代理 m3u8/分片、防盗链、SSRF 白名单 | 解析源 | Anime-API（proxy 层） |
| Renderer | 拿到视频流 → 输出（hls.js → video），卸载销毁实例 | 搜索/解析/鉴权 | movie-web、ani-web |

## 1. 已下载参考项目（19 个）

### 后端/API 型
- **Anime-API**（zaxtyson，MIT）：异步资源解析框架，弹幕+多站解析。
  → 移植：`libvio`/`zzzfun` 解析逻辑（文件头已署名）；借鉴超时/重试/UA 规范。
- **AnimeKAI-API**：anikai.to 抓取 + token 加密 + m3u8 直链。
  → anikai.to 已关站（2026-05），流程（SvelteKit SSR 数据块 + 加密流解密）
  已内化为「SPA 站反代套路」，用于 AllAnime/ReAnime 调研。
- **Animepahe-API**（Kylart，MIT）：animepahe.si + cloudscraper 过 CF。
  → animepahe 已死（广告墙），保留思路（cloudscraper 例外）备用。
- **Miruro-API**（walterwhite-69）：miruro.to `/api/secure/pipe` + AniList。
  → 落地：`MiruroChannel`（curl_cffi Chrome 指纹例外，§2.5 先声明）。
- **luffytv-miruro-api**：Miruro 另一实现，pipe 端点结构参考。
- **ReAnime.to-API**：reanime.to + flixcloud.cc WASM AES-256-CBC 解密。
  → 调研：`/api/v1/*` 部分开放、流 401（§2.9）；解密套路（SvelteKit SSR +
  WASM + PBKDF2）为 AllAnime keygen 提供思路。
- **goganime-api / gogoanime-api**：Gogoanime 抓取（gogoanime3.co 等）。
  → gogoanime 主站普遍 JS challenge；Anikoto 克隆（HiAnime/Zoro）落地替代。
- **anime_api**（aniwatch-api）：hianime.to 抓取。
  → hianime 已死（2026-08-13 复测 000），保留为 HiAnime 家族 DOM 结构参考。
- **akatsuki**（rl404）：MAL 数据库 dump + REST。
  → 元数据备用思路（未引入，AniList/Bangumi 已够用）。
- **Anivault-Scraper**（SH0MIK）：senshi/animeheaven/miruro/anikoto 抓取。
  → 落地：`AnimeHeavenChannel`（端点/选择器参考）、`AnikotoChannel`（选择器以
  实测为准）、miruro 结构交叉验证。
- **ani-web**：本地优先的动漫媒体客户端（Node）。
  → Renderer 角色参考：轻量、只渲染、卸载释放。

### 前端/客户端型
- **movie-web**：开源流媒体前端（多后端）。
  → Renderer/SearchAggregator 角色参考：播放器独立组件、流失效自动换源、
  hls.js 实例销毁、缓存策略。
- **Tatakai**：AnimeList 安卓客户端。
  → 渠道→集数→播放器的用户旅程参考。
- **GoAnime**（alvarorichard，TUI 客户端）：
  → 资源聚合（AniList 元数据 + gogoanime 流）的组织方式参考。

### 扩展/生态型
- **aniyomi-extensions-archive** / **extensions-source**（Apache-2.0）：
  → 落地：`AnimeXinChannel`（animestream 模板 + animexin 扩展 +
  dailymotion-extractor，独立实现）；Maccms 家族（360zy/ikunzy 等）的
  API 直链字段与 `from=` 提示思路来自 Miru 扩展（repo 仓库）。
- **repo**（miru-project/repo，MIT）：Miru 扩展源。
  → 落地：`AgeChannel` 接口套路（独立实现）、Maccms 家族扩展参考。
- **free-anime-apis**：免费动漫 API 汇总。
  → 调研起点（候选源清单），结论见 RESOURCE_BACKUP_PLAN §2.9。

## 2. 角色规范要点（写码前必读）

1. **Renderer 只做渲染**：接收 `ChannelStream[]` → 选流 → hls.js/原生 video
   → 输出；卸载时 `hls.destroy()` + 清 `src`；错误时只做「换流/提示」，
   不重新搜索、不解析、不鉴权（`frontend/src/components/ChannelPlayer.tsx`）。
2. **Provider 只碰一个站**：`search/get_detail/get_streams` 三方法；
   外部请求必须带 UA/Referer；失败抛 `ChannelError(channel, stage, msg, retryable)`
   （`app/services/channels/base.py`），由 Registry 熔断降级。
3. **聚合器不碰播放**：并行 + 8s 硬超时 + 去重 + 按优先级排序
   （`app/services/channels/registry.py`）。
4. **代理是唯一出网口**：所有可播流经 `/api/watch/proxy/stream`，域名白名单
   防 SSRF，日志脱敏（`app/routers/watch.py`）。
5. **测试用 fixture，不依赖外网**：每个 Provider 有本地 HTML/JSON 样本单测；
   每轮测试后 `ps aux | awk '$8 ~ /^Z/'` 必须无输出（防僵尸进程卡顿）。

## 3. 移植声明

各项目授权与署名声明见 CHANNEL_ARCHITECTURE §8 与 RESOURCE_BACKUP_PLAN §8。
原则：**只参考端点/选择器/流程，不复制代码**；MIT/Apache 项目按许可署名，
未声明 License 的仓库（如 Anivault-Scraper）只做独立实现。
