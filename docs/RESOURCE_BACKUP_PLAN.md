# 资源备选库（Backup Resource Library）规范

> 状态：v1.0 生效稿 · 2026-08-13
> 本文件是「备选资源库」功能的**唯一实现依据**，是
> [CHANNEL_ARCHITECTURE.md](./CHANNEL_ARCHITECTURE.md) 的扩展角色。
> 所有代码改动必须先满足本文定义的角色边界与接口契约；若需调整契约，
> 先改本文并注明原因。

## 0. 为什么需要备选库

现有渠道（Anilibria / Gogoanime / Bilibili）是**在线播放**主力，但它们都是
外部站点：域名会漂移、反爬会升级、区域会封锁。用户的核心承诺是
「中文搜 → 卡片 → 渠道 → 集数 → **实际观看**」，这个承诺不能被单一站点
的宕机绑架。备选资源库的目标：

1. 当主力渠道全部不可用时，仍有**可播放**或**可跳转官方**的兜底来源；
2. 为元数据（封面/简介/中文名）提供独立于 Bangumi 的第二来源；
3. 所有来源都遵循统一 `ChannelProvider` 契约，前端零改动即可接入。

## 1. 角色总览

```
┌────────────────────────────────────────────────────────────┐
│                   Backup Resource Library                    │
│  (备选资源库 — 新增角色，不是新系统，是 ChannelProvider 的     │
│   一类实现：metadata-only / external / stream-capable)        │
└────────────────────────────────────────────────────────────┘
```

备选资源库**不新建抽象**，复用现有角色：

| 现有角色 | 备选库如何复用 |
|---|---|
| `ChannelProvider`（§1.1） | 每个备选源都是一个 Provider：`search` / `get_detail` / `get_streams` |
| `ChannelRegistry`（§1.8） | 自动获得健康检查、熔断、缓存、聚合搜索 |
| `SearchAggregator`（§1.2） | 备选源自动参与中文关键词扩展后的聚合搜索 |
| `EpisodeResolver`（§1.3） | 备选源实现 `get_detail` 返回集数分组 |
| `StreamResolver`（§1.4） | 可播源实现 `get_streams`；仅外链源不实现（`external=True`） |
| `Renderer`（§1.5） | **不感知**来源差异，只拿到流就播放 |
| `StreamProxy`（§1.6） | 可播源的分片/清单照常走代理；外链源直接跳官方 |

### 1.1 BackupSource（备选源）职责

**职责**（针对一个外部资源站）：
- 按 `ChannelProvider` 契约实现 `search(keyword, page)` → `ChannelSearchResult[]`
- 按契约实现 `get_detail(detail_ref)` → `ChannelDetail`（含集数分组）
- 若该源可播：实现 `get_streams(episode_ref)` → `ChannelStream[]`
- 若该源仅外链：`external=True`，实现 `external_url(detail_ref)` 返回官方跳转
- 必须携带 `language` 元信息（`zh` / `en` / `ru` / `zh-en`）供前端排序

**不负责**（禁止做）：
- ❌ 不聚合、不去重、不排序（那是 SearchAggregator）
- ❌ 不渲染、不播放（那是 Renderer / 前端）
- ❌ 不缓存、不熔断（那是 Registry / Cache）
- ❌ 不自己实现重试风暴：超时由公共 HTTP 客户端控制（默认 8s，见 §6）

### 1.2 与主力渠道的关系

- 备选源与主力源**平级**注册在同一个 `ChannelRegistry`，没有「主备切换」
  的特殊代码路径——这正是接口化的收益：Registry 只按健康状态分发。
- 前端渠道选项卡按 `priority` 排序（主力在前、备选在后），备选源
  `priority` 恒低于主力源。
- 备选源失败 = 普通渠道失败：连续 3 次熔断冷却 120s，自动跳过，
  用户无感知（CHANNEL_ARCHITECTURE.md §6.2）。

## 2. 候选源清单（2026-08-13 实测）

> 实测走本机 Clash 7892 代理。`✅` = 本轮实测可用；`⚠️` = 不稳定/需绕行；
> `❌` = 已确认不可用（保留记录，避免未来重复调研）。

| 源 | 类型 | 实测 | 结论 |
|---|---|---|---|
| **AnimeHeaven**（animeheaven.me） | 可播（mp4 直链，无 CF） | ✅ 全链路实测可播（2026-08-13） | **P0 可播备选**：搜索/集数/gate.php 直链 mp4，无需解密、无需绕 CF，是「实际观看」的关键兜底 |
| **Kitsu**（kitsu.io/api/edge） | 元数据 + 集数 + 官方外链 | ✅ HTTP 200，4.4s 偏慢 | **第一优先落地**：`zh_cn` 中文标题、封面、简介、评分、集数（number/title/thumbnail）、Crunchyroll streaming-links |
| **Shikimori**（shikimori.one/api） | 元数据 + 官方外链 | ✅ 301 → shikimori.io → 200，实测可搜索 | **已落地**（2026-08-13）：search + external，`priority=65`，无中文名（英/俄显示），相关性弱于 Kitsu，仅作第二元数据备选 |
| **AniAPI**（api.aniapi.com/v1） | 元数据 + 流 | ⚠️ 2026-08-13 起返回 JS 挑战页（JWT redirect），此前 200 | 暂缓：需 JS 能力客户端或 cookie，留作「挑战解除后优先」 |
| **Jikan**（api.jikan.moe/v4） | 元数据 | ❌ 504（上游 MyAnimeList 拒绝） | 不可用，保留记录 |
| **AnimePahe**（animepahe.tv / .net / .com / .ru / .si） | 可播（m3u8+Kwik） | ❌ 2026-08-13 全域名实测不可编程接入：`.com/.org`→`.pw` 403 CF；`.ru`→`.su` 域名出售页；`.si` NXDOMAIN；`.tv/.net` 存活但 API 302→`ch=1`→广告落地页（p-tracking/thefinancesgator），真实 Chrome 也不返回 JSON；`.me` 403 CF | **确认不可用**：站点已广告墙化，参考实现（`_reference/Animepahe-API`）失效，保留记录避免重复调研 |
| **AllAnime**（api.mkissa.net/api） | 目录 + 官方外链（可升级为可播） | ✅ GraphQL 实测可用（2026-08-13，0.45s，主番 28 sub/28 dub） | **已落地 v1**（2026-08-13）：search + external，`priority=62`；完整流需 aaReq AES-GCM token + 混淆 bundle 密钥推导（P1，见 §2.4） |
| **Miruro**（miruro.tv + AniList GraphQL） | 可播（AniDB HLS，绕 CF） | ✅ 全链路实测可播（2026-08-13，pewe→hls.anidb.app 1080/720/360，分片可播） | **P0 可播备选**：AniList 搜索 + `/api/secure/pipe` 集数/流，需 curl_cffi Chrome 指纹绕 CF（显式例外 §2.5）；已探明 `pewe` 稳定，`ally`（Animedao 上游）已死 |
| **AnimeKai**（anikai.to） | 可播（enc-dec 解密） | ❌ 2026-05 关站，anikai.to NXDOMAIN（2026-08-13 复测） | **确认关站**：参考实现（`_reference/AnimeKAI-API`）依赖的 enc-dec.app 仍存活但已无站点可查，保留记录避免重复调研 |
| **ReAnime.to** | 可播（flixcloud HLS AES-256） | ❌ 2026-08-13 实测 `/api/search` 404、搜索页 SPA 空壳 + Cloudflare challenge（`can_request:false`） | **确认失效**：参考实现（`_reference/ReAnime.to-API`，2026-06）已失效，保留记录避免重复调研 |
| **HiAnime / Zoro** | 可播 | ❌ 走代理超时（000） | 不可用，保留记录 |
| **Consumet 官方** | 聚合流 API | ❌ 官方不再直接提供（301/500） | 可参考其 provider 模式（GogoanimeProvider），不自建 |
| **Nyaa / Mikan / AnimeGarden / SubsPlease** | BT 聚合 | ✅ 已接入现有四源 | 属于下载/聚合，不是在线渠道，不重复实现 |
| **Bangumi**（api.bgm.tv） | 元数据 | ⚠️ 本机不可达（P0-1 已快速失败兜底） | 元数据主源保持，备选库提供第二来源 |
| **AnimeXin**（animexin.dev，原 animexin.vip） | 可播（Dailymotion HLS，国漫/多语言字幕） | ✅ 全链路实测可播（2026-08-13：搜索→详情→集数→embed→HLS master/子清单均 200） | **P0 可播备选（国漫）**：AnimeStream WP 模板；embed 以 Dailymotion 为主；DM CDN 需 curl_cffi `chrome124` 指纹（显式例外 §2.6） |
| **Anikoto**（anikoto.net） | 可播（HiAnime/Zoro 克隆，megaplay/vidtube HLS） | ✅ 全链路实测可播（2026-08-13：搜索→详情→集数→server→megaplay/vidtube 双 CDN master/子清单/分片均 200） | **P0 可播备选（英文索引）**：无 CF、无解密；megaplay 分片为 252B PNG 前缀 + 真 MPEG-TS（代理 SegmentStrip 可播）；vidtube→akirax 分片为 `.jpg` 后缀真 TS；Kiwi Mapper 仅 server-code 路径可用（§2.7） |
| **Goyabu**（goyabu.io） | 可播（WP REST API，葡语配音） | ⚠️ 代理可访问（200），搜索 API 需 nonce；直连 403 | 暂缓：仅葡语配音，对中文用户价值低，保留记录 |
| **Bde4**（bde4.icu） | 可播（m3u8，综合影视非动漫专站） | ⚠️ 存活但 JS 挑战（JWT `ch=1` + `sid` cookie）+ SSL 抖动 | 暂缓：非动漫专站、挑战不稳定，保留记录 |
| **ChineseAnime**（chineseanime.vip） | 可播（AnimeStream 模板） | ❌ 域名已停靠（跳 `router.parklogic.com`） | 确认失效，保留记录 |
| **HahoMoe**（haho.moe） | 可播 | ❌ 实为 Hentai 站，非一般动漫 | 排除，保留记录 |
| **Bimibimi**（api.tianbo17.com） | 可播（中文） | ❌ API 已变为 HTML/混淆 JS 壳（2026-08-13） | 确认失效，保留记录 |
| **LuciferDonghua / DonghuaStream / Kawaiifu / TioDonghua / Sudatchi** | 可播（国漫站） | ❌ 403 / 521 / 000（2026-08-13） | 不可用，保留记录 |
| **Afang / K1080 / 4Kya / Eyunzhu**（Anime-API 中文源） | 可播（2021 中文聚合） | ❌ 全部 000 失联（2026-08-13） | 确认失效，保留记录 |

### 2.1 Kitsu 接口速查（落地依据）

- 搜索：`GET https://kitsu.io/api/edge/anime?filter[text]=<kw>&page[limit]=N`
  - 返回 `data[].attributes`：`titles.zh_cn / titles.en / canonicalTitle`、
    `posterImage.small`、`synopsis`、`episodeCount`、`averageRating`、
    `subtype`、`status`
- 集数：`GET https://kitsu.io/api/edge/episodes?filter[media_id]=<id>&page[limit]=N&page[offset]=0`
  - 返回 `data[].attributes`：`number`、`canonicalTitle`、`thumbnail.small`、
    `airdate`、`length`
- 官方外链：`GET https://kitsu.io/api/edge/anime/<id>/streaming-links`
  - 返回 `data[].attributes.url`（Crunchyroll 等），`subs` / `dubs`
- 注意：Kitsu 的 `filter[text]` 对中文原文匹配差，但**中文关键词扩展
  （CHINESE_TITLE_MAP → 英文/罗马音）后命中率好**，且结果自带 `zh_cn` 标题，
  恰好补全「中文显示」体验。Kitsu 搜索与 Bangumi 互为备份。
- **v1 落地范围（2026-08-13）**：`search` + `external_url`
  （`https://kitsu.io/anime/{id}`，该页列出 Crunchyroll 等官方授权入口）。
  集数/streaming-links 端点**已探明可用**（§2.1），但当前 external 前端流
  只跳官方页、不渲染集数，故 v1 不实现 `get_detail`；待前端支持
  external 渠道集数浏览（P2）时再启用，接口契约不变。

### 2.2 AnimeHeaven 接口速查（落地依据，2026-08-13 实测可播）

AnimeHeaven 是当前少数**无 Cloudflare、直出 mp4** 的免费站，适合作为
「实际观看」的可播备选（英文索引，中文经 CHINESE_TITLE_MAP 扩展后命中）。

- 搜索：`GET https://animeheaven.me/fastsearch.php?xhr=1&s=<keyword>`
  - 返回 HTML，命中为 `<a class='ac' href='/anime.php?<id>'>`；其中
    `.fastimg img.coverimg` 的 `alt` 为标题、`src` 为封面（`/image.php?<k>`）
- 详情+集数：`GET https://animeheaven.me/anime.php?<id>`
  - `<title>` 标题（去掉 ` Anime | AnimeHeaven.Me` 后缀）、
    `img.posterimg` 封面、`div.infodes.c` 简介
  - 集数锚点：`<a ... onmouseover='gateh("<key>")' onclick='gatea("<key>")'
    href='gate.php'>`，其中 `div.watch2` 为集号（页面按 28→1 倒序，需升序）
  - `episode_ref` = gate key（不透明引用）
- 流：`GET https://animeheaven.me/gate.php`，**必须带 Cookie `key=<episode_ref>`**
  与 `Referer: https://animeheaven.me/`
  - 返回 `<video><source src='https://ct.animeheaven.me/video.mp4?<key>&<token>'
    type='video/mp4'>`，取首个含 `/video.mp4` 的 source 为直链 mp4
  - mp4 CDN（`ct.animeheaven.me` / `ck.animeheaven.me`）支持 Range（实测 206），
    播放走 StreamProxy，白名单需加 `animeheaven.me`（覆盖其 CDN 子域）
  - 注意：CDN 对 HEAD 请求可能挂起（实测 20s 超时），健康探测/测试请用
    Range GET 而非 HEAD
- **v1 落地范围（2026-08-13）**：`search` + `get_detail`（单组集数，倒序转升序）
  + `get_streams`（mp4 直链），`external=False`，`priority=55`
  （可播备选，排在 Kitsu 外链备选之前）。


### 2.3 Shikimori 接口速查（落地依据，2026-08-13 实测可用）

Shikimori（shikimori.one）是社区维护的开放动漫数据库，无需鉴权、无 Cloudflare，
适合作为 Kitsu 之后的**第二元数据备选**（英/俄显示，无中文名）。

- 搜索：`GET https://shikimori.one/api/animes?search=<kw>&limit=10&page=1`
  - 返回 JSON 数组：`id`、`name`（罗马音）、`russian`（俄语标题）、
    `image.preview / image.original`（**相对路径**，需拼 `https://shikimori.one` 前缀）、
    `score`、`status`、`kind`、`episodes`、`episodes_aired`、`aired_on`
  - 已知限制：搜索相关性一般（Frieren 首条是 2027 续作 anons）；无中文标题
- 官方外链：`https://shikimori.one/animes/{id}`（页面列出可用的正版流媒体入口）
- **v1 落地范围（2026-08-13）**：`search` + `external_url`，
  `external=True`、`supports_detail=False`、`priority=65`（排在 Kitsu 60 之后）。


### 2.4 AllAnime 接口速查（落地依据，2026-08-13 实测可用）

AllAnime（mkissa 镜像）是免费英文动漫目录中最大的之一；GraphQL 端点
`https://api.mkissa.net/api` 无需鉴权、无 Cloudflare、响应快（~0.5s）。
原直连 `api.allanime.day` 已死（ani-cli PR #1779 于 2026-07-22 迁移到
mkissa），`allanime.to` / `allanime.day` 站点本机走代理超时，但 mkissa.to 可达。

- 搜索：`POST https://api.mkissa.net/api`，GraphQL：
  ```graphql
  query($search: SearchInput, $limit: Int, $page: Int, $translationType: VaildTranslationTypeEnumType, $countryOrigin: VaildCountryOriginEnumType) {
    shows(search: $search, limit: $limit, page: $page, translationType: $translationType, countryOrigin: $countryOrigin) {
      edges { _id name englishName availableEpisodes __typename }
    }
  }
  ```
  - 必须带 `Referer: https://mkissa.to` 与 `Origin: https://mkissa.to`
    （否则镜像可能返回剥离后的空响应）
  - 返回 `data.shows.edges[]`：`_id`、`name`（罗马音）、`englishName`、
    `availableEpisodes.sub / .dub / .raw`（集数）
  - 中文关键词 → `edges: []`（无噪声，无需短路；registry 关键词扩展补拉丁）
  - 无封面/年份字段；按 sub+dub 集数降序排（主番优先，参考 GoAnime 排序）
- 官方外链：`https://mkissa.to/anime/{_id}`（SPA 路由，实测 200）
- **v1 落地范围（2026-08-13）**：`search` + `external_url`，
  `external=True`、`supports_detail=False`、`priority=62`（排在 Kitsu 60 之后、
  Shikimori 65 之前）。
- **P1（完整可播，暂不落地）**：episode 源需 `aaReq` AES-256-GCM 证明 token
  （payload 绑定 5 分钟窗口 + epoch + 持久化查询 hash），密钥通过抓取
  mkissa.to 首页 → CDN `entry/app.*.js` → 前 5 个 chunk 中的 64-hex mask 与
  `partB` 异或推导；源 URL 在 `tobeparsed` AES-256-GCM blob 内。
  参考 GoAnime `internal/scraper/providers/allanime/`（keys.go / crypto.go /
  stream.go），前端混淆 + Turnstile，链路脆弱，收益低于 AnimeHeaven，留 P1。

### 2.5 Miruro 接口速查（落地依据，2026-08-13 实测可播）

Miruro（miruro.tv）是开源前端（VitaElegy 参考 walterwhite-69/Miruro-API v3.0，
`~/work/Project/_reference/Miruro-API`），元数据走 AniList GraphQL，集数/流走自家
`/api/secure/pipe`（Cloudflare 后）。实测 `pewe` provider 的 HLS 分片可播，
是「实际观看」的第二可播兜底（在 AnimeHeaven 之后）。

- 搜索：`POST https://graphql.anilist.co`（**直连可用，无需代理**）
  - GraphQL：`Page(page, perPage){ media(search, type: ANIME, sort: SEARCH_MATCH){ id
    title{ romaji english native } coverImage{ large extraLarge } format episodes
    averageScore } }`
  - 中文关键词 → `media: []`（无噪声，无需短路；registry 关键词扩展补英文/罗马音）
  - `detail_ref` = AniList `id`（如 `154587`）
- 集数：`GET https://www.miruro.tv/api/secure/pipe?e=<base64url(json)>`
  - payload：`{"path":"episodes","method":"GET","query":{"anilistId":154587},"body":None,"version":"0.1.0"}`
  - 响应：**gzip + base64url** 编码 JSON（先补 `=` padding → `urlsafe_b64decode` →
    `gzip.decompress` → `json.loads`）
  - 结构：`mappings`（malId/aniId/anidbId/kitsuId…）+ `providers`
    （`ally/pewe/moo/bee/kiwi/hop/bonk`，每 provider 有 `episodes.sub/.dub[]`；
    Frieren 实测 pewe 28 sub + 28 dub）
  - episode `id` 是 base64url(上游 `provider:realId:number`)；pewe 首集解码为
    `anidbapp:1663:3062`。**注意解码前缀是上游 provider（anidbapp），不是 Miruro
    聚合 key（pewe）**——`episode_ref` 必须同时保留聚合 key、category 与 anilistId。
- 流：`GET .../pipe?e=<base64url({"path":"sources","method":"GET","query":{...}})>`
  - query：`{"episodeId": base64url(decoded_id), "provider": "pewe",
    "category": "sub", "anilistId": 154587}`
  - 返回 `streams[]`：`{url, type, server, referer, default, isActive}`
  - 首选 `pewe`：HLS `https://hls.anidb.app/stream/<token>/master.m3u8`
    （1080/720/360 三档，2026-08-13 实测 manifest 与 `.xls` 后缀分片为真实 MPEG-TS，
    需 `Referer: https://anidb.app/`），另附 `type="embed"` 官方 embed 地址
  - `ally`（Animedao 上游）2026-08-13 实测 444/502 upstream unreachable，不优先；
    mp4upload 直链 403，不可用
- **curl_cffi 显式例外条款**（本文件在此先声明，再实现）：Miruro 的
  `/api/secure/pipe` 在 Cloudflare 后，共享 httpx 客户端（Chrome/126 指纹）返回
  403；必须使用 `curl_cffi.AsyncSession(impersonate="chrome110")` + Clash 7892 代理
  + 完整浏览器头（Referer/Origin/sec-fetch/sec-ch-ua）。这是
  CHANNEL_ARCHITECTURE §1.1「Provider 不自建 HTTP 客户端」的**文档先声明例外**
  （如同 AnimeHeaven 的 CDN 探测例外在文档先声明，再实现）。
- **v1 落地范围（本次）**：`search` + `get_detail` + `get_streams`，
  `external=False`、`language="en"`、`priority=58`（排在 AnimeHeaven 55 之后、
  Kitsu 60 之前）。
- `episode_ref` 内部约定：`{provider}:{category}:{anilist_id}:{decoded_id}`，
  如 `pewe:sub:154587:anidbapp:1663:3062`（对前端不透明；`get_streams` 按
  `split(":", 2)` 解析 provider/category，再取 `anilist_id` 与 decoded_id）。


### 2.6 AnimeXin 接口速查（落地依据，2026-08-13 实测可播）

AnimeXin（animexin.dev，原 animexin.vip 已 301 到 .dev）是国漫（donghua）为主的
WordPress 站，使用 AnimeStream 模板（参考 `aniyomi-extensions-archive` 的
`lib-multisrc/animestream` 与 `src/all/animexin` 扩展）。它补上了现有渠道
「国漫/多语言字幕」空白：搜索/详情/集数走站点 HTML，流以 Dailymotion embed 为主
（实测两集均为 DM；其余 embed 类型见下）。

- 搜索：`GET https://animexin.dev/page/1/?s=<kw>`
  - 返回 HTML；命中卡片 `div.listupd article a.tip`（`href`=详情页 URL、
    `img` 的 `src`/`alt`=封面/标题），详情页形如 `/anime/<slug>/`
  - 站点只收录英文/罗马音名：中文关键词会返回 Not Found（2026-08-13 实测
    `s=无上神帝` → Not Found，`s=Supreme God Emperor` → 命中）。中文搜索依赖
    registry 的离线扩展表 `CHINESE_TITLE_MAP`（keyword_expand.py 国漫段，已按
    本站实测收录 20+ 部，见下「已知限制」），Bangumi 熔断/离线时仍可命中
- 详情+集数：`GET https://animexin.dev/anime/<slug>/`
  - `<title>` 标题（去 ` - AnimeXin` 后缀）、`img` 封面、`.entry-content` 简介
  - 集数锚点：`div.eplister > ul > li > a`，`href`=集数页 URL
    （如 `/supreme-god-emperor-episode-626-indonesia-english-sub/`），
    文本含集号（如 `Episode 626`）；`episode_ref` = 集数页完整 URL
  - 页面较大（300–750KB），共享 httpx 超时 8s 可能不足——本渠道需放宽
    `get_detail` / `get_streams` 单请求超时（显式例外，见下）
- 流：`GET <episode_url>` → 取首个 `iframe[src~=.]` 的 src
  - 若为 Dailymotion embed（`https://www.dailymotion.com/embed/video/<id>`）：
    1. `GET` embed 页 → 从 `dmInternalData` 取 `"ts":<ts>` 与 `"v1st":"<v1st>"`
    2. `GET https://www.dailymotion.com/player/metadata/video/<id>?locale=en-US
       &dmV1st=<v1st>&dmTs=<ts>&is_native_app=0`
    3. 取 `qualities.auto[0].url` = HLS master（实测 720/480/380/240 四档）
  - 若为 dood / gdriveplayer / youtube / ok.ru / vidstreaming 等其他 embed：
    **v1 不实现**，抛出带 embed URL 的明确 `ChannelError`（前端可跳官方 embed）
- **curl_cffi 显式例外条款**（本文件在此先声明，再实现）：AnimeXin 站本身
  共享 httpx 可用（实测 200）；但 Dailymotion embed/metadata/CDN 需要：
  - `curl_cffi.AsyncSession(impersonate="chrome124")`（**较新的 chrome 指纹被
    DM CDN 以 403 拒绝**，chrome124/safari 实测 200）+ Clash 7892 代理
    （系统 curl/LibreSSL 直连握手 SSL_ERROR_SYSCALL，curl_cffi 稳定）
  - 流请求头：`Referer: https://www.dailymotion.com/` + `Origin: ...`
  - **流代理对 DM 域名同样走 curl_cffi**：`/api/watch/proxy/stream` 命中
    `dailymotion.com` / `dmcdn.net` 时，上游用 `CurlAsyncSession(impersonate=
    "chrome124")` + Clash 7892，且 **Referer 固定为 DM Origin、忽略调用方
    referer**（2026-08-13 实测：chrome124 + DM Referer → 200，chrome124 +
    animexin Referer → 403，httpx → 403）；master/子清单里的 `#cell=<cache>`
    片段在拼代理 URL 时剥离，绝不转发给上游；非 DM 域名仍走共享 httpx
  - 这是 CHANNEL_ARCHITECTURE §1.1「Provider 不自建 HTTP 客户端」的
    **文档先声明例外**（同 §2.5 Miruro）；AnimeXin 站点请求本身仍走共享 httpx
  - **超时例外**：详情/集数/embed 页 300–750KB，共享 httpx 8s 不够；
    本渠道 `get_detail` / `get_streams` 允许单请求 20s（文档先声明）
- **v1 落地范围（本次）**：`search` + `get_detail` + `get_streams`（Dailymotion
  提取），`external=False`、`supports_search/detail/streams=True`、
  `language="en"`（英/印尼字幕）、`priority=56`（可播备选：AnimeHeaven 55 之后、
  Miruro 58 之前，因为国漫内容与现有主力互补）。
- 已知限制：站点无中文标题且中文搜索返回 Not Found —— 中文→英文名桥接依赖
  `CHINESE_TITLE_MAP` 国漫段（2026-08-13 实测新增 20+ 部：无上神帝/一念永恒/
  仙逆/遮天/吞噬星空/星辰变/武动乾坤/大主宰/神印王座/元龙/少年歌行/西行纪/
  雾山五行/眷思量/镇魂街/择天记/雪鹰领主/天宝伏妖录/武庚纪/牧神记/剑来等）；
  页面大且慢（搜索 ~7s、详情 ~10s，走共享 httpx 8s 需注意聚合 8s 上限）；
  Dailymotion 依赖第三方 embed，个别集可能换源。

### 2.7 Anikoto 接口速查（落地依据，2026-08-13 实测可播）

Anikoto（anikoto.net）是 HiAnime/Zoro 风格克隆（参考
`~/work/Project/_reference/Anivault-Scraper/src/scrapers/anikoto.ts`，SH0MIK；
仓库未声明 License，本实现为独立实现，仅参考端点/选择器，不复制代码）。
搜索/详情/集数页无 Cloudflare，共享 httpx + Clash 代理即可；流为 HLS 双 CDN。

- 搜索：`GET https://anikoto.net/filter?keyword=<kw>`
  - 返回 HTML；命中块 `div#list-items.ani.items > div.item`，标题锚点
    `a.name.d-title`（`href`=`/watch/<slug>/ep-N`、`data-jp`=罗马音原名、
    文本=英文名），封面取块内首张 `img[src]`；slug 从 `/watch/<slug>` 提取
  - 实测中文关键词依赖 registry 的中文→英文扩展表（同 AnimeXin §2.6 已知限制）
- 详情+集数：`GET https://anikoto.net/watch/<slug>`
  - `<h1 itemprop="name">` 标题（`data-jp`=罗马音原名）、`og:image`/`img[itemprop=image]`
    封面、`.synopsis .content` 简介、`#watch-main[data-id]` 番剧 id
  - 集数通常**不在内联**：AJAX `GET /ajax/episode/list/<data-id>` → JSON
    `result` HTML；集数锚点 `a[data-num][data-id][data-mal][data-timestamp][data-ids]`
    + `span.d-title` 集标题
  - `episode_ref` 内部约定：`{slug}::{num}::{data_ids}::{mal}::{timestamp}::{ep_id}`
- server 列表：`GET /ajax/server/list?servers=<data_ids>`
  - 返回 `<li data-ep-id data-cmid data-sv-id data-link-id>名称</li>`；
    sub/dub 各一份（同名成对出现），按 `(sv, link)` 去重
- embed 解析：`GET /ajax/server?get=<link-id>&sv=<sv-id>` → JSON
  `result.url`（如 `https://megaplay.buzz/stream/s-2/<id>/sub`）
  - **megaplay.buzz**（含 vidwish.live / megacloud.bloggy.click 镜像，重写为
    megaplay.buzz）：embed 页 `<title>File N</title>` →
    `GET https://<host>/stream/getSources?id=N`（X-Requested-With + Referer）
    → `sources.file` = HLS master + `tracks[]` 字幕
    - **分片投毒假象**：master/子清单正常，但分片 URL 在 tiktokcdn.com 且带
      252B PNG 前缀——实测偏移 0xFC 处为真实 MPEG-TS 同步字节 `47 40 00 10`，
      播放走代理 SegmentStrip（watch.py `_STRIP_BYTES=252`）可播（无需新增例外）
  - **vidtube.site**（VidPlay server）：同 megaplay 式 `getSources` →
    `s1.akirax.buzz` / `s1.norami.top` master，分片为 `.jpg` 后缀的原始
    MPEG-TS（实测 `47 40 11 10`），字幕在 `vidtub.shiora.site` / `1oe.lostproject.club`
  - **megacloud.blog**：embed HTML 取 48 位 alphanumeric nonce →
    `GET {origin}/embed-2/v3/e-1/getSources?id=<id>&_k=<nonce>`；加密时尝试
    公开解密 helper（best effort，失败返回空）
  - 未知 host：跟随 iframe 至多 2 跳后再识别；仍未知则丢弃该 server
- **Kiwi Mapper 旁路**（仅作最后兜底）：`GET https://mapper.nekostream.site/
  api/mal/<mal>/<num>/<timestamp>`（备 `mapper.mewcdn.online`）
  - 实测返回 `download` 短链（pahe.nekostream.site 点击页，需 JS，**不可编程
    播放，跳过**）；当返回**短 opaque server code** 时经 `/ajax/server?get=`
    解析 → HLS（Referer `https://kwik.cx2.mewcdn.online/`）可播（server-code 路径）
- **流代理白名单新增**（watch.py `_ALLOWED_STREAM_HOSTS`）：`akirax.buzz`
  （s1.akirax.buzz master/分片）、`shiora.site`（megap.shiora.site master、
  vidtub.shiora.site 字幕）；`shiora.top` / `norami.top` / `lostproject.club` /
  `tiktokcdn.com` 已存在
- **v1 落地范围（本次）**：`search` + `get_detail` + `get_streams`，
  `external=False`、`supports_search/detail/streams=True`、`language="en"`、
  `priority=57`（可播备选：AnimeXin 56 之后、Miruro 58 之前）。
  `tests/test_anikoto_channel.py` 7 例 fixture 测试（含真实结构）。
- 已知限制：仅英文索引（中文依赖扩展表）；megaplay 分片必须经代理播放
  （直链给 hls.js 会被 PNG 前缀卡住）；个别 server（如 pahe 短链）不可编程；
  站点/embed 域名可能轮换（代码已按 host 识别 + 镜像归一化）。

## 3. 接口契约

备选源**不新增 Pydantic 模型**，直接复用 CHANNEL_ARCHITECTURE.md §3 的
`ChannelInfo / ChannelSearchResult / ChannelDetail / ChannelStream`，仅补充：

```python
class ChannelInfo(BaseModel):
    ...
    priority: int = 100          # 新增：数字越小越靠前；主力 0-50，备选 60+
    language: str = "zh"         # 已有："zh" | "ja" | "en" | "ru" | "zh-en"
```

`ChannelSearchResult.title` 规则（备选源专用）：
- 有 `zh_cn` → 用中文标题；否则 `canonicalTitle`；再否则 `titles.en`。
- `title_original` 填英文/罗马音原名。
- `cover_url` 用 `posterImage.small`（小图省流量，Renderer 不放大图）。

`ChannelDetail.groups[]` 规则：
- 按 `seasonNumber` 分组（如「第一季」「第二季」），每组内含该季集数。
- `ChannelEpisode.title` = 「第 N 集 · 英文标题」（无标题时只留「第 N 集」）。
- `episode_ref` = Kitsu episode id（不透明引用）。

`ChannelStream` 规则：
- 可播源照常返回 `hls/mp4` 流；**外链源不返回 streams**（`external=True`，
  前端渲染「前往官方观看」按钮，跳 `external_url`）。

## 4. 健康与降级（复用，不新增）

- 走 `ChannelRegistry`：连续 3 次失败 → 熔断 120s（§1.8）。
- Kitsu 偏慢（~4s）但稳定：搜索 TTL 300s、详情 600s、外链 120s（§1.7），
  聚合搜索 8s 硬超时兜底（§6.1）。
- 备选源**不允许**影响聚合总时长：超过 8s 的结果被丢弃，健康渠道照常返回。

## 5. 前端（零改动原则）

- 渠道选项卡已按 `list_channels()` 渲染；备选源自动出现。
- 外链源：前端现有 `external` 分支（如 Bilibili）自动渲染「前往官网」。
- 可播源：复用 `ChannelPlayer`（hls.js → StreamProxy），Renderer 不感知来源。
- **前端无任何备选库专用代码**——这是接口化的验收标准。

## 6. 测试要求（与 CHANNEL_ARCHITECTURE §7 一致）

- 每个备选源用**本地 fixture**（Kitsu JSON 样本）做解析单测：
  - 搜索命中 → `zh_cn` 标题 / 封面 / detail_ref 正确
  - 详情 → 按季分组、集数排序、episode_ref 不透明
  - 外链 → streaming-links 首条 URL 返回
  - 异常 JSON / 空结果 → 抛 `ChannelError` 或返回空，不崩溃
- Registry 聚合测试已覆盖多 Provider 并行；备选源注册一行 + 断言
  `list_channels()` 含新源即可。
- 真实 API E2E（可选，网络波动时跳过）：`kitsu.io` 搜索 `Frieren` 命中。
- 每轮测试后：`ps aux | awk '$8 ~ /^Z/'` 必须无输出；无本项目残留进程。

## 7. 落地顺序

1. **AnimeHeavenChannel**（本次）：可播 mp4 直链源，`external=False`，
   `priority=55` —— 2026-08-13 实测全链路可播（搜索 / 28 集 / gate.php 直链
   mp4 + Range 206），是「中文搜 → 卡片 → 渠道 → 集数 → **实际观看**」
   承诺的关键兜底。
2. ~~KitsuChannel~~（已落地 2026-08-13）：元数据 + 集数 + 官方外链，
   `external=True`，`priority=60`。
3. ~~Shikimori 元数据~~（已落地 2026-08-13）：`search` + `external_url`，
   `external=True`，`priority=65`（英/俄显示，无中文；相关性弱于 Kitsu，仅备用）。
4. ~~AllAnime v1~~（已落地 2026-08-13）：GraphQL search + external，
   `priority=62`；完整可播（aaReq token + 密钥推导）留 P1（§2.4）。
5. ~~AnimePahe~~（已确认不可用 2026-08-13）：`.tv/.net` 存活但 API 被广告墙劫持
   （302 → `ch=1` → 广告落地页，真实浏览器也不返回 JSON），其余域名失效/CF，
   参考实现失效，保留记录不再投入。
6. ~~ReAnime.to~~（已确认失效 2026-08-13）：`/api/search` 404 + SPA 空壳
   + Cloudflare challenge，参考实现已失效，保留记录不再投入。
7. AniAPI（JS 挑战解除后）：无挑战时按契约接入，优先级高于 AnimePahe。
8. ~~MiruroChannel~~（已落地 2026-08-13）：可播 HLS 备选，`external=False`、
   `priority=58`，AniList 搜索 + pipe 集数/流，curl_cffi 例外（§2.5 已先声明）。
   `tests/test_miruro_channel.py` 11 例 fixture 测试。
9. ~~AnimeKai~~（已确认关站 2026-05，2026-08-13 复测 anikai.to NXDOMAIN）：
   参考实现（`_reference/AnimeKAI-API`）依赖的 enc-dec.app 仍存活但已无站点可查，
   保留记录不再投入。

10. ~~AnimeXinChannel~~（2026-08-13 落地）：可播 HLS 备选（国漫/多语言字幕），
   `external=False`、`priority=56`，AnimeStream WP 模板 + Dailymotion HLS；
   curl_cffi `chrome124` 例外（§2.6 已先声明）。

11. ~~AnikotoChannel~~（2026-08-13 落地）：可播 HLS 备选（英文索引），
   `external=False`、`priority=57`，HiAnime/Zoro 克隆 + megaplay/vidtube 双 CDN；
   megaplay 分片走代理 SegmentStrip（§2.7 已先声明）。


## 8. 移植声明

- AnimeHeaven 端点/选择器参考本地 `~/work/Project/_reference/Anivault-Scraper`
  （`src/scrapers/animeheaven.ts`，SH0MIK；仓库未声明 License，故本实现为独立
  实现，仅参考端点与选择器，不复制代码）。
- Kitsu 官方 API（https://kitsu.io/api/edge），开放无需鉴权，本文为独立实现。
- AnimePahe 思路参考 [Kylart/Animepahe-API](https://github.com/Kylart/Animepahe-API)
  （MIT），落地时在文件头保留版权声明。
- ReAnime.to 思路参考本地 `~/work/Project/_reference/ReAnime.to-API`，落地时署名。
- AnimeXin 端点/选择器/提取流程参考本地
  `~/work/Project/_reference/aniyomi-extensions-archive`（Apache-2.0）：
  `lib-multisrc/animestream` 的 AnimeStream 模板、`src/all/animexin` 扩展、
  `lib/dailymotion-extractor`；本实现为独立实现，仅参考端点/选择器/流程，不复制代码。

- Anikoto 端点/选择器/提取流程参考本地
  `~/work/Project/_reference/Anivault-Scraper`（`src/scrapers/anikoto.ts` +
  `src/resolvers/megacloud.ts`，SH0MIK；仓库未声明 License）：当前站点的
  搜索结果选择器与参考实现不同（`a.name.d-title` 而非 `flw-item`，2026-08-13
  实测），选择器以实测为准；本实现为独立实现，仅参考端点/选择器/流程，不复制代码。
