# 高清影视资源源站目录 · 2026-04-24

本文件汇总**电影 / 电视剧 / 动漫**的高清资源来源，按 **"信息完整度"** 而非道德色彩排序。每条条目都会标注：

- **定位**：综合 / 动漫 / 电影 / 剧集 / 公共域 / 测试素材
- **访问门槛**：公开 / 需邀请 / 需订阅 / 商业
- **典型码率**：直链能拿到什么画质
- **项目使用建议**：本项目（anime）该怎么用它

> 合规声明：本目录仅作信息整理；下载任何仍受版权保护的内容都应在符合所在司法辖区法律的前提下进行。**本项目默认推荐走「公共域 / CC 协议 / 官方商业授权」路径**，PT / BT 信息仅为研究记录。

---

## 一、公共域 & 官方开放测试素材（开发首选）

这是**项目开发阶段必须优先用的素材**——没版权顾虑、URL 稳定、分辨率明确、可以拿去反复自动化测试。

### 1.1 Netflix Open Content（**最强 4K HDR 测试集**）

- **URL**：https://opencontent.netflix.com/
- **下载入口**：http://download.opencontent.netflix.com/ （或 `aws s3 --no-sign-request`）
- **协议**：Creative Commons Attribution 4.0
- **片名清单**：

| 片名 | 年份 | 分辨率 | 帧率 | HDR | 适用测试 |
|------|------|--------|------|-----|----------|
| **Sol Levante** | 2020 | 4K UHD | 24fps | HDR10 + Dolby Vision | 动画 HDR workflow |
| **Nocturne** | 2018 | — | 120/60fps | Dolby Vision | 高帧率编解码压测 |
| **Sparks** | 2017 | 4K | HFR | Dolby Vision 4000nit | 极亮 HDR / ACES |
| **Meridian** | 2016 | UHD 4K | 59.94 | Dolby Vision | 多语种叙事片 |
| **Cosmos Laundromat** | 2016 | 2K | 24p | Dolby Vision | Blender 动画 HDR |
| **Chimera** | 2014 | DCI 4K | 23.98/59.94 | HDR P3/PQ | 高复杂度场景 |
| **El Fuente** | 2013 | 4K 4096×2160 | 48/60fps | 非 HDR | 早期 4K HFR |

- **给本项目的用法**：
  - 直接把 `Meridian` / `Sparks` 作为 HDR/HEVC/多音轨转码测试的"黄金基准"
  - `Cosmos Laundromat` 是 2K 动画 + HDR，非常适合**本项目动漫场景**的端到端测试
  - 文件大多是 IMF / EXR 序列，想要能直接塞进 `<video>` 的 MP4 要自己 mux

### 1.2 Blender Open Movies（**动画测试首选**）

- **URL**：https://studio.blender.org/films/ ｜ https://video.blender.org/c/blender_open_movies/videos
- **协议**：Creative Commons Attribution
- **代表作**：
  - **Sintel** (2010) — 1080p / 4K，14 分钟奇幻短片，**多语种字幕（30+）**，`<video>` 字幕测试必备
  - **Big Buck Bunny** (2008) — 1080p / 4K / 8K，已是全球 streaming 测试事实标准
  - **Tears of Steel** (2012) — 1080p / 4K，真人 + CG，带多音轨
  - **Agent 327**、**Charge**、**Caminandes** 等 10+ 部
- **给本项目的用法**：**项目的 `docs/` 与 HLS 自动化测试里就在用 Big Buck Bunny**（596 秒那个）。Sintel 的**多语种字幕**是字幕轨选择功能上线后的现成验证素材。

### 1.3 Internet Archive — Moving Image Archive

- **URL**：https://archive.org/details/movies
- **子集**：
  - https://archive.org/details/publicmovies212 — 经典公共域电影（《Night of the Living Dead》、Chaplin、Metropolis）
  - https://archive.org/details/opensource_movies — 社区上传
  - https://archive.org/details/feature_films — 完整片长
- **码率**：老片多为 720p / 1080p H.264 MP4，可直接 `<video>` 播放
- **给本项目的用法**：项目里做"正片库"的**免责 demo 数据**，随便点播不用担心版权投诉

### 1.4 视频测试文件集合仓库

- **`joshuatz/video-test-file-links`** — https://github.com/joshuatz/video-test-file-links
  汇总了各家（Netflix / Apple / Bitmovin / Unified Streaming / Akamai / Jellyfin）的公开 test clip，按"编解码 / 分辨率 / HDR"索引
- **`ietf/video-test-vectors`** — 各种编解码器标准测试序列
- **给本项目的用法**：写 CI 测试时按需抓一个 mini clip（几秒的 HEVC / AV1 / 10-bit / 多音轨等**特定边角条件**），不用自己合成

---

## 二、合法 / 商业授权高清平台

**4K HDR 真正稳定的来源**，但都在各自 DRM 墙后（Widevine L1 / FairPlay / PlayReady），**直链下载不可能**。本项目作为"自建播放服务"只能作为对标对象，不能嵌入。

| 平台 | 最高清晰度 | HDR | 典型码率 | 备注 |
|------|-----------|------|----------|------|
| **Apple TV+** | 4K Dolby Vision | DV P5 | ~40 Mbps | 业界公认**画质标杆**，原生片最多 |
| **Netflix** | 4K Dolby Vision | DV + HDR10 | 15-25 Mbps | 用 **Per-Title Encoding**，高码率需 Premium |
| **Disney+** | 4K Dolby Vision | DV + HDR10+ | ~20 Mbps | Marvel / SW 的 IMAX Enhanced |
| **Max (HBO)** | 4K Dolby Vision | DV + HDR10 | 20-25 Mbps | 只对部分内容提供 4K |
| **Amazon Prime Video** | 4K HDR10+ | HDR10+ | ~15 Mbps | 支持 HDR10+ 较多 |
| **Hulu** | 最高 4K | 有限 | — | 只有少量原创支持 4K |
| **iQIYI / 腾讯视频 / 爱奇艺 / 优酷** | 4K | 部分 HDR | 10-20 Mbps | 国内版权剧集主要渠道 |
| **bilibili 大会员** | 1080P+ / 4K HDR | 部分 HDR | 8-16 Mbps | **番剧 / 国创** 最全中文正版 |
| **Crunchyroll** | 1080p | 无 | — | 全球**海外动漫**正版龙头 |
| **HIDIVE** | 1080p | 无 | — | 补 Crunchyroll 没覆盖的小众动漫 |

**给本项目的策略建议**：
- 如果未来做商业化，应该**向商业平台学画质配方**（码率阶梯、HDR 透传）而非去对抗它们的 DRM
- 本项目当前的 3 档 ABR（1080p@5M / 720p@3M / 480p@1.3M）参考的就是 Netflix 的 `per-title-encoding` 公开论文

---

## 三、公共广播电视台免费直播流（IPTV）

**完全合法**的直播源，m3u8 HLS 协议，可以直接塞进 `<video>` / hls.js 播放。对本项目极有价值——**天然的多房间同看素材**。

### 3.1 `freecasthub/public-iptv`

- **URL**：https://github.com/freecasthub/public-iptv
- **内容**：仅官方公共广播电视台，英美日德法等 20+ 国
- **代表频道**：BBC iPlayer 国际版、NHK World、ARD、France 24、DW、CGTN、Al Jazeera
- **协议**：m3u8 HLS，大部分 1080p
- **给本项目的用法**：在"同看房间"里做一个"**正在直播**" tab，选频道 → 所有人 SSE 同步，零版权顾虑

### 3.2 IPTV 聚合项目

- **`iptv-org/iptv`** — GitHub 上 90k star 的全球直播聚合（注意国家/频道分类合法性差异）
- **`gitlink.org.cn/iptv/iptv`** — 国内镜像，按 24 小时自动同步
- **Global Free TV** — https://www.globalfreetv.com/channels

### 3.3 NHK World Japan（动漫 / 纪录片方向重点推荐）

- **URL**：https://www3.nhk.or.jp/nhkworld/en/live/
- **直接 m3u8**：公开，可搜索"NHK World Live HLS"
- **内容**：日本文化、大量动画纪录片、日剧精选
- **给本项目的用法**：动漫站 + 日语直播 = 目标用户高度重合，天生契合

---

## 四、动漫资源生态（公开 BT 索引为主）

**这是本项目的核心用户场景** —— 动漫更新快、字幕组生态活跃、公开 BT 索引文化成熟。

| 站点 | 域名（2026-04 活跃） | 定位 | 语言 | 码率上限 | 特点 |
|------|---------------------|------|------|----------|------|
| **Nyaa** | `nyaa.si` | 全球最大动漫 BT 索引 | 英文为主 | 原盘 / REMUX / BDRip | **资源最全**，字幕组源头 |
| **动漫花园 DMHY** | `share.dmhy.org` | 华语字幕组聚合 | 简中 / 繁中 | 1080p WebRip 为主 | **中文圈主战场** |
| **ACG.RIP** | `acg.rip` | 中文合集站 | 简中 / 繁中 | BDRip 合集多 | 界面简洁，合集丰富 |
| **蜜柑计划 Mikan** | `mikanani.me` | 按番组 + 字幕组聚合 | 中/英 | — | **RSS 追番神器** |
| **萌番组 BangumiMoe** | `bangumi.moe` | 字幕组标签精细分类 | 中文 | 1080p | 活跃度下降但元数据仍好 |
| **SubsPlease** | `subsplease.org` | 英文新番速度王 | 英文 | 1080p WebRip | 新番 30 分钟内发布 |
| **U2** | `u2.dmhy.org` | 高品质 BDRip（**PT**） | 中文 | 原盘 / REMUX | **需邀请**，收藏级 |
| **AnimeTosho** | `animetosho.org` | Nyaa 镜像 + 直链 | 英文 | 同 Nyaa | HTTP 直链下载方便 |
| **Anidex** | `anidex.info` | Nyaa 替代 | 多语 | — | 备胎用 |
| **动漫花园镜像 AnimeGarden** | `animes.garden` | 多源聚合 API | 中英 | — | **开放 API**，适合程序拉数据 |

### 4.1 AnimeGarden API（**项目可直接集成**）

- **项目**：https://github.com/yjl9903/AnimeGarden
- **价值**：封装了 DMHY / Mikan / ACG.RIP 的聚合搜索，**提供 REST API**
- **给本项目的用法**：本项目的 `/api/search/torrents` 完全可以换成调用 AnimeGarden 的 API，一下就拿到三个源的联合结果

### 4.2 推荐 Tracker 列表

任何从公开 BT 站拖下来的磁力链接，追加这个 tracker list 能显著提速：
- https://github.com/DeSireFire/animeTrackerList
- https://github.com/ngosang/trackerslist

---

## 五、中文 PT 私人种子站（研究参考 · 不推荐集成）

> ⚠️ **为什么不推荐集成**：PT 需要**保种 seed ratio**、需要**邀请**、站规严（删号后禁 IP）、法律风险高。本项目作为自建服务不应自动化爬 PT。

数据源：PT邀请码网（ptyqm.com）截至 **2026-02**。

### 5.1 老牌综合大站（邀请制）

| 站点 | 代称 | 域名 | 强项 |
|------|------|------|------|
| **M-Team** | 馒头 | `kp.m-team.cc` | 综合，**0day 最快** |
| **HDSky** | 天空 | `hdsky.me` | 综合高清影视 |
| **CHDBits** | 彩虹猫 | `chdbits.co` | 高清电影 |
| **HDChina** | 瓷器 | `hdchina.org` | 高清电影/剧集 |
| **TTG** | 听听歌 | `totheglory.im` | 综合高清 |
| **HDHome** | 家园 | `hdhome.org` | 高清综合 |
| **HDArea** | 高清地带 | `hdarea.co` | 高清电影 |
| **HDTime** | 高清时光 | `hdtime.org` | 高清电影 |

### 5.2 近期开放 / 新站

| 站点 | 状态（2026-02）| 备注 |
|------|---------------|------|
| LemonHD 柠檬 | 开放注册中 | `lemonhd.club` |
| HDPT 明教 | 开放注册中 | `hdpt.xyz` |
| NovaHD 星云 | 开放注册中 | 综合+短剧 |
| BTSCHOOL 学校 | 元旦开放 | `pt.btschool.club` |
| 1PTBA 壹PT吧 | 春节开放 | `1ptba.com` |
| U2（动漫 PT）| 邀请制 | `u2.dmhy.org`，动漫 BDRip 圣地 |
| 聆音 | 开放注册（音乐） | — |

### 5.3 重要操作提醒

1. **M-Team**：2025-04 起强制二级验证，不开启无法修改邮箱
2. **新站死亡率极高**：近期"库非 Kufei"等多个新站被报告"稳定后删种"
3. **PT 生存最低要求**：保种上传量 >= 下载量，大部分站要求 1.0 ratio 以上

---

## 六、国际（欧美）Scene / P2P 发布生态

### 6.1 PreDB（发布名数据库，不是下载）

| 站点 | URL | 用途 |
|------|-----|------|
| **PreDB.net** | `https://predb.net/` | Scene 发布名 + NFO |
| **PREdb.live** | `https://predb.live/` | PRE tracker + 通知 |
| **PreDB.org** | `https://predb.org/` | 纯信息库 |
| **crowdNFO** | `https://crowdnfo.net/` | 社区 NFO + MediaInfo |

**用途**：知道某部剧"第 3 季第 8 集"是否已有发布、由哪个组发、码率和分辨率——**搜索元数据**而非下载。

### 6.2 主流剧集发布组（知名度排序）

| 发布组 | 专长 | 特征 |
|--------|------|------|
| **FLUX** | Netflix / Amazon WebRip | 现役顶级通用组 |
| **NTb** | 通用 WebRip | 老牌高质 |
| **SuccessfulCrab** | 美剧 WEB-DL | 出片速度极快 |
| **GalaxyTV / GalaxyRG** | 体积优化 | 压缩小体积 1080p |
| **RARBG 时代留存** | — | RARBG 虽死，归档分散在各聚合站 |
| **Vyndros** | 1080p x265 | 精修 x265 |

### 6.3 聚合索引站（公开但法律灰）

- **1337x** — `1337x.to`
- **The Pirate Bay** — 多次被封，镜像多变
- **YTS** — `yts.mx`（**电影 1080p 小体积** 知名）
- **EZTV** — 美剧专项
- **LimeTorrents** — 综合

**给本项目的态度**：这些不应集成。项目如果要搜索元数据，应该用 `predb.live` 的 API 这种纯信息层。

---

## 七、按本项目视角的"该用什么"对照表

| 场景 | 推荐源 | 理由 |
|------|--------|------|
| **开发 / 单元测试** | Blender Big Buck Bunny + Sintel | 稳定 URL，多语种字幕，零版权顾虑 |
| **HDR / HEVC / 4K 转码基准** | Netflix Open Content | 业界黄金基准 |
| **公共域 demo 内容库** | Internet Archive | 整库随便嵌 |
| **"正在直播"同看房间** | `freecasthub/public-iptv` NHK / BBC | 合法 HLS m3u8 |
| **动漫搜索集成** | **AnimeGarden API** | 一个 API 打通 3 个源 |
| **动漫用户手动下种** | Nyaa / 蜜柑计划 / 动漫花园 | 用户圈子最活跃 |
| **电影元数据查询** | TMDB / PreDB | 纯信息层，无版权风险 |
| **高端用户自持** | PT（U2 动漫 / M-Team 综合） | 由用户自行取得，项目只负责播放 |

---

## 八、本项目已落地的集成现状

| 功能 | 当前实现 | 对应本目录哪条 |
|------|----------|---------------|
| 搜索 anime 元数据 | `app/routers/search.py` + `app/services/bangumi.py` / `anilist.py` / `bilibili.py` | 对接 Bangumi / AniList / Bilibili（元数据，未列入本目录） |
| 搜索种子 | `app/routers/search.py` + `app/services/nyaa.py` / `subsplease.py` / `mikan.py` / `anime_garden.py` | 四源并行聚合：Nyaa / SubsPlease / Mikan / AnimeGarden（§ 4） |
| 下载与保种 | `app/services/qbittorrent.py`（qBittorrent WebUI API） | — |
| 转码 | `app/services/media_transcode.py`（3 档 ABR + HW 加速）| — |
| 同看 | `app/services/watch_room.py` + `room_events.py`（SSE 房间同步） | — |
| 测试素材 | `data/downloads/hd-test/[字幕组] 高清测试片 1080p HEVC.mkv` | Blender 合成（§ 1.2） |

## 九、下一步可落地的集成（按 ROI 排序）

1. **新建 `/api/live-tv` 端点**（§ 3.1 freecasthub/public-iptv）— 1 天工作量，"直播同看"是同看房间的最佳用武场景
2. **Netflix Open Content 作为转码回归测试**（§ 1.1）— 在 CI 里跑 Sol Levante 的 4K HDR 到本项目 HLS 管线的端到端，半天工作量，能反复发现隐性回归
3. **PreDB 接入元数据侧**（§ 6.1）— 让用户搜电影时看到"有没有新发布"，0.5 天
4. **Comicat / DMHY / AnimeTosho 源移植**（§ 4）— 目前只在 `feature/watch-party` 远程分支存在，评估并入四源聚合

> ✅ 已完成：AnimeGarden 聚合 API（§ 4.1）已于 2026-08 接入四源并行搜索，本项从下一步清单移除。

---

**最后更新**：2026-08-13  
**维护人**：请在调整时把失效域名 / 新站直接在本目录 §四 / §五 更新。资源站平均每 12 个月换一次域名，过期信息反而有害。
