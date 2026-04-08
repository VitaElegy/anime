# NicoTracker 功能测试 Checklist

> 生成时间: 2026-04-08  
> 覆盖: 全部 35 个后端 API 接口 + 10 种 WebSocket 消息类型 + 前后端对应关系

---

## 一、后端接口 × 前端 UI 对应关系

| # | 后端接口 | 前端函数 | 前端页面 | 状态 |
|---|---------|---------|---------|------|
| 1 | `GET /health` | `getHealth()` | (未直接使用) | ⚠️ 前端已定义但未调用 |
| 2 | `GET /api/search/nyaa` | `searchNyaa()` | SearchPage | ✅ |
| 3 | `GET /api/search/subsplease` | `searchSubsPlease()` | SearchPage, HomePage, CalendarPage | ✅ |
| 4 | `GET /api/search/dmhy` | `searchDmhy()` | SearchPage | ✅ |
| 5 | `GET /api/search/mikan` | `searchMikan()` | SearchPage | ✅ |
| 6 | `GET /api/search/animetosho` | `searchAnimeTosho()` | SearchPage | ✅ |
| 7 | `GET /api/search/all` | `searchAll()` | (未直接使用) | ⚠️ 前端已定义但未调用 |
| 8 | `POST /api/download` | `addDownload()` | SearchPage | ✅ |
| 9 | `POST /api/download/batch` | `addBatchDownload()` | (未直接使用) | ⚠️ 前端已定义但未调用 |
| 10 | `GET /api/download/progress` | `getDownloadProgress()` | DownloadsPage, HomePage | ✅ |
| 11 | `GET /api/download/progress/{hash}` | `getSingleProgress()` | (未直接使用) | ⚠️ |
| 12 | `PUT /api/download/{hash}/pause` | `pauseTorrent()` | DownloadsPage | ✅ |
| 13 | `PUT /api/download/{hash}/resume` | `resumeTorrent()` | DownloadsPage | ✅ |
| 14 | `DELETE /api/download/{hash}` | `deleteTorrent()` | DownloadsPage | ✅ |
| 15 | `GET /api/metadata/search` | `searchMetadata()` | LibraryPage | ✅ |
| 16 | `GET /api/metadata/{id}` | `getMetadata()` | (未直接使用) | ⚠️ |
| 17 | `GET /api/metadata/{id}/cover` | `getCoverUrl()` (拼URL) | LibraryPage | ✅ |
| 18 | `GET /api/favorites` | `getFavorites()` | LibraryPage, HomePage | ✅ |
| 19 | `POST /api/favorites` | `addFavorite()` | LibraryPage | ✅ |
| 20 | `GET /api/favorites/{id}` | — | — | ❌ 无前端调用 |
| 21 | `PUT /api/favorites/{id}` | `updateFavorite()` | LibraryPage | ✅ |
| 22 | `DELETE /api/favorites/{id}` | `removeFavorite()` | LibraryPage | ✅ |
| 23 | `GET /api/crawl/stream` (SSE) | `fetch()` 直接调用 | CrawlPage | ✅ |
| 24 | `GET /api/crawl/history` | `getCrawlHistory()` | CrawlPage | ✅ |
| 25 | `GET /api/schedule` | `getWeeklySchedule()` | CalendarPage | ✅ |
| 26 | `GET /api/image/proxy` | `proxyImageUrl()` (拼URL) | HomePage, SearchPage, CalendarPage | ✅ |
| 27 | `GET /api/image/batch_prefetch` | `prefetchImages()` | (未直接使用) | ⚠️ |
| 28 | `POST /api/covers/batch` | `batchResolveCovers()` | HomePage, CalendarPage | ✅ |
| 29 | `GET /api/anilist/search` | `anilistSearch()` | SearchPage | ✅ |
| 30 | `GET /api/anilist/trending` | `anilistTrending()` | (未直接使用) | ⚠️ |
| 31 | `GET /api/anilist/schedule` | `anilistSchedule()` | (未直接使用) | ⚠️ |
| 32 | `GET /api/watchparty/rooms` | `fetch()` 直接调用 | WatchPartyPage | ✅ |
| 33 | `POST /api/watchparty/rooms` | `fetch()` 直接调用 | WatchPartyPage | ✅ |
| 34 | `GET /api/watchparty/rooms/{id}` | — | (WS init 获取) | ⚠️ |
| 35 | `DELETE /api/watchparty/rooms/{id}` | — | — | ❌ 无前端调用 |
| 36 | `WS /api/watchparty/ws/{id}` | WebSocket 直接连接 | WatchPartyPage | ✅ |

---

## 二、功能测试点（按模块）

### A. 搜索模块 (Search) — 18 个测试点

| ID | 测试点 | 边际条件 | 优先级 |
|----|-------|---------|-------|
| S-01 | Nyaa 英文搜索返回结果 | keyword="frieren" | P0 |
| S-02 | Nyaa 中文搜索自动翻译 | keyword="葬送的芙莉莲" | P0 |
| S-03 | Nyaa 日文搜索自动翻译 | keyword="ぼっちざろっく" | P1 |
| S-04 | Nyaa 空关键词返回 422 | keyword="" (必填参数) | P0 |
| S-05 | Nyaa 分页参数 page=0 返回 422 | ge=1 约束 | P1 |
| S-06 | Nyaa filter 参数超范围 filter=5 | le=2 约束 | P1 |
| S-07 | SubsPlease 空关键词返回全部 | q="" 应返回当季所有 | P0 |
| S-08 | SubsPlease 画质参数 720/480 | quality=720 | P1 |
| S-09 | DMHY 中文搜索 | q="我推的孩子" | P0 |
| S-10 | DMHY 分页 | page=2 | P1 |
| S-11 | DMHY 分类参数 | category="31" (完结) | P1 |
| S-12 | Mikan 空搜索返回当季列表 | q="" | P0 |
| S-13 | Mikan 中文搜索 | q="间谍家家酒" | P0 |
| S-14 | AnimeTosho 英文搜索 | q="frieren" | P0 |
| S-15 | AnimeTosho 中文搜索自动翻译 | q="芙莉莲" | P1 |
| S-16 | 聚合搜索 /all 5源并行 | q="frieren" → 5个SearchResult | P0 |
| S-17 | 搜索结果结构验证 | items[].title/magnet/source 非空 | P0 |
| S-18 | 超长关键词搜索 | 200字符关键词 | P2 |

### B. 下载模块 (Download) — 10 个测试点

| ID | 测试点 | 边际条件 | 优先级 |
|----|-------|---------|-------|
| D-01 | qBittorrent 未连接时返回 503 | 所有接口 | P0 |
| D-02 | 添加磁力链接下载 | magnet="magnet:?xt=..." | P0 |
| D-03 | 添加 torrent URL 下载 | torrent_url="https://..." | P0 |
| D-04 | 两者都为空时返回 400 | magnet="" torrent_url="" | P0 |
| D-05 | 批量下载 | items 含 3 条 | P1 |
| D-06 | 查询全部下载进度 | category="" | P0 |
| D-07 | 按分类过滤下载进度 | category="anime" | P1 |
| D-08 | 查询单个下载进度(不存在) | hash="nonexist" → 404 | P1 |
| D-09 | 暂停/恢复/删除操作 | 完整生命周期 | P0 |
| D-10 | 删除时 delete_files 参数 | delete_files=true | P1 |

### C. 元数据模块 (Metadata) — 7 个测试点

| ID | 测试点 | 边际条件 | 优先级 |
|----|-------|---------|-------|
| M-01 | Bangumi 中文搜索 | q="葬送的芙莉莲" | P0 |
| M-02 | Bangumi limit 参数 | limit=5 | P1 |
| M-03 | Bangumi limit 超范围 | limit=0 → 422, limit=100 → 422 | P1 |
| M-04 | 获取番剧详情 | subject_id=valid | P0 |
| M-05 | 获取不存在的番剧 | subject_id=999999999 → 404 | P1 |
| M-06 | 获取封面图片 | 返回 image content-type | P0 |
| M-07 | 获取不存在的封面 | subject_id=999999999 → 404 | P1 |

### D. 收藏模块 (Favorites) — 10 个测试点

| ID | 测试点 | 边际条件 | 优先级 |
|----|-------|---------|-------|
| F-01 | 空收藏列表 | 初始无数据 → [] | P0 |
| F-02 | 添加收藏 | bangumi_id + name_cn | P0 |
| F-03 | 重复添加同一 bangumi_id | INSERT OR REPLACE | P1 |
| F-04 | 获取收藏列表 | 返回数组 | P0 |
| F-05 | 按状态过滤收藏 | status="watching" | P0 |
| F-06 | 无效状态过滤 | status="invalid" → [] | P1 |
| F-07 | 更新收藏状态 | status="completed" | P0 |
| F-08 | 更新不存在的收藏 | bangumi_id=0 → 404 | P1 |
| F-09 | 删除收藏 | 返回 ok | P0 |
| F-10 | 删除不存在的收藏 | → 404 | P1 |

### E. 抓取模块 (Crawl) — 8 个测试点

| ID | 测试点 | 边际条件 | 优先级 |
|----|-------|---------|-------|
| C-01 | SSE 流 SubsPlease 抓取 | source=subsplease | P0 |
| C-02 | SSE 流 Nyaa 抓取 | source=nyaa | P0 |
| C-03 | SSE 流 DMHY 抓取 | source=dmhy | P0 |
| C-04 | SSE 流 Mikan 抓取 | source=mikan | P0 |
| C-05 | SSE 流 AnimeTosho 抓取 | source=animetosho | P0 |
| C-06 | 全部抓取 | source=all → 6个源 | P0 |
| C-07 | SSE 事件格式验证 | data: {...}\n\n + [DONE] | P0 |
| C-08 | 抓取历史查询 | limit=10 | P0 |

### F. 日历模块 (Schedule) — 2 个测试点

| ID | 测试点 | 边际条件 | 优先级 |
|----|-------|---------|-------|
| SC-01 | 获取每周放送表 | 返回 {周一:[...], ...} | P0 |
| SC-02 | 空数据时返回空对象 | {} | P1 |

### G. 图片代理模块 (Image) — 6 个测试点

| ID | 测试点 | 边际条件 | 优先级 |
|----|-------|---------|-------|
| I-01 | 代理有效图片 URL | 返回 image content-type | P0 |
| I-02 | 代理无效 URL | → 502 | P0 |
| I-03 | 缓存命中 (X-Cache: HIT) | 第二次请求 | P0 |
| I-04 | 空 URL 参数 | → 400 | P1 |
| I-05 | 批量预取 | urls="url1,url2" | P1 |
| I-06 | Bangumi CDN 图片反盗链 | User-Agent + Referer | P0 |

### H. 封面解析模块 (Covers) — 8 个测试点

| ID | 测试点 | 边际条件 | 优先级 |
|----|-------|---------|-------|
| CV-01 | 批量解析英文种子标题 | SubsPlease 格式 | P0 |
| CV-02 | 缓存命中 (第二次调用) | 返回速度 < 10ms | P0 |
| CV-03 | 罗马字标题 AniList 回退 | "Hidarikiki no Eren" | P0 |
| CV-04 | 空标题列表 | titles=[] → [] | P1 |
| CV-05 | 超过30条截断 | titles 含 35 条 | P1 |
| CV-06 | 结果包含中文名 | name_cn 非空 | P0 |
| CV-07 | 无封面但有中文名的记录 | cover_url="" 但 name_cn 有值 | P0 |
| CV-08 | 清洗标题正确性 | [SubsPlease] xxx - 01 → "xxx" | P0 |

### I. AniList 模块 — 5 个测试点

| ID | 测试点 | 边际条件 | 优先级 |
|----|-------|---------|-------|
| AL-01 | 英文搜索 | q="frieren" | P0 |
| AL-02 | 中文搜索(Bangumi fallback) | q="芙莉莲" | P0 |
| AL-03 | 当季热门 | trending endpoint | P0 |
| AL-04 | 放送时间表 | schedule endpoint | P0 |
| AL-05 | limit 参数约束 | limit=0 → 422 | P1 |

### J. 放映室模块 (WatchParty) — 12 个测试点

| ID | 测试点 | 边际条件 | 优先级 |
|----|-------|---------|-------|
| W-01 | 创建房间 | name="测试房" | P0 |
| W-02 | 列出房间 | → 数组 | P0 |
| W-03 | 获取房间详情 | room_id=valid | P0 |
| W-04 | 获取不存在的房间 | → 404 | P1 |
| W-05 | 删除房间 | → ok | P1 |
| W-06 | WebSocket 连接 | 收到 init 消息 | P0 |
| W-07 | 发送聊天消息 | type=chat → 广播 | P0 |
| W-08 | 视频切换同步 | type=video_change | P0 |
| W-09 | 播放/暂停/跳转同步 | play/pause/seek | P0 |
| W-10 | 主持人转移 | host 离开 → 新 host | P1 |
| W-11 | WebSocket 连接不存在的房间 | code=4004 | P1 |
| W-12 | 空房间自动清除 | 最后一人离开 | P1 |

### K. 系统级 — 3 个测试点

| ID | 测试点 | 边际条件 | 优先级 |
|----|-------|---------|-------|
| SYS-01 | 健康检查 | /health → {status:ok} | P0 |
| SYS-02 | 根路径重定向 | / → /docs | P0 |
| SYS-03 | 全局异常处理 | → 500 {detail, code} | P1 |

---

## 三、总计

| 模块 | 测试点数 |
|------|---------|
| Search | 18 |
| Download | 10 |
| Metadata | 7 |
| Favorites | 10 |
| Crawl | 8 |
| Schedule | 2 |
| Image | 6 |
| Covers | 8 |
| AniList | 5 |
| WatchParty | 12 |
| System | 3 |
| **总计** | **89** |

---

## 四、已知问题

1. `GET /api/favorites/{bangumi_id}` — 后端有接口，前端无调用
2. `DELETE /api/watchparty/rooms/{id}` — 后端有接口，前端无调用
3. `GET /api/search/all` — 前端有函数但未被任何页面使用
4. `GET /api/anilist/trending` / `GET /api/anilist/schedule` — 前端有函数但未被调用
5. `GET /api/image/batch_prefetch` — 前端有函数但未被调用
6. `GET /api/download/progress/{hash}` — 前端有函数但未被调用
7. CalendarPage 的 `batchResolveCovers` 仍然用 `if (c.cover_url)` 过滤，与 HomePage 修复不一致
