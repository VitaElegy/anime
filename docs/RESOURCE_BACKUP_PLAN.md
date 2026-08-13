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
| **AnimePahe**（animepahe.ru/api） | 可播（m3u8+Kwik） | ⚠️ 301 → animepahe.su，Cloudflare 首页 | 需 cloudscraper/CF 绕过（参考 `_reference/Animepahe-API`），P2 |
| **AllAnime**（api.mkissa.net/api） | 目录 + 官方外链（可升级为可播） | ✅ GraphQL 实测可用（2026-08-13，0.45s，主番 28 sub/28 dub） | **已落地 v1**（2026-08-13）：search + external，`priority=62`；完整流需 aaReq AES-GCM token + 混淆 bundle 密钥推导（P1，见 §2.4） |
| **ReAnime.to** | 可播（flixcloud HLS AES-256） | ❌ 2026-08-13 实测 `/api/search` 404、搜索页 SPA 空壳 + Cloudflare challenge（`can_request:false`） | **确认失效**：参考实现（`_reference/ReAnime.to-API`，2026-06）已失效，保留记录避免重复调研 |
| **HiAnime / Zoro** | 可播 | ❌ 走代理超时（000） | 不可用，保留记录 |
| **Consumet 官方** | 聚合流 API | ❌ 官方不再直接提供（301/500） | 可参考其 provider 模式（GogoanimeProvider），不自建 |
| **Nyaa / Mikan / AnimeGarden / SubsPlease** | BT 聚合 | ✅ 已接入现有四源 | 属于下载/聚合，不是在线渠道，不重复实现 |
| **Bangumi**（api.bgm.tv） | 元数据 | ⚠️ 本机不可达（P0-1 已快速失败兜底） | 元数据主源保持，备选库提供第二来源 |

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
5. AnimePahe 可播源（P2）：cloudscraper 绕过 CF，需引入依赖并评估稳定性。
6. ~~ReAnime.to~~（已确认失效 2026-08-13）：`/api/search` 404 + SPA 空壳
   + Cloudflare challenge，参考实现已失效，保留记录不再投入。
7. AniAPI（JS 挑战解除后）：无挑战时按契约接入，优先级高于 AnimePahe。

## 8. 移植声明

- AnimeHeaven 端点/选择器参考本地 `~/work/Project/_reference/Anivault-Scraper`
  （`src/scrapers/animeheaven.ts`，SH0MIK；仓库未声明 License，故本实现为独立
  实现，仅参考端点与选择器，不复制代码）。
- Kitsu 官方 API（https://kitsu.io/api/edge），开放无需鉴权，本文为独立实现。
- AnimePahe 思路参考 [Kylart/Animepahe-API](https://github.com/Kylart/Animepahe-API)
  （MIT），落地时在文件头保留版权声明。
- ReAnime.to 思路参考本地 `~/work/Project/_reference/ReAnime.to-API`，落地时署名。
