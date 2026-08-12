# 搜索功能重构报告

> 报告日期：2026-04-18
> 作者：Codebuddy 协同会话
> 涉及服务：`app.routers.search`, `app.services.{anime_garden,mikan,bangumi}`, `frontend/src/pages/SearchPage.tsx`, `frontend/src/api/index.ts`

---

## 一、背景 & 症状

用户报告：

1. 搜索页面逻辑繁杂、存在点击死循环（番剧卡片被劫持为英文种子搜索，无法进入详情页）。
2. 中文搜索时种子栏「完全搜索不到内容」。例如搜 `葬送` 后种子列表始终为空。
3. 前端中文输入会被后端"翻译"为英文关键词去查源站，语义被改写。

---

## 二、根因定位

调查路径：

| 步骤 | 证据 | 结论 |
|---|---|---|
| 1. 实测 AnimeGarden 公开 API：`GET /resources?search=葬送` | 返回 20 条《葬送的芙莉莲》资源 | **数据源本身中文原生可用** |
| 2. 查看后端 `app/services/anime_garden.py` | `params = {"search": keyword}` 原文透传 | **后端代码没问题** |
| 3. 拉取运行中后端的 `/openapi.json` | search 路由仅剩 `nyaa/subsplease/all/metadata/anilist` | **运行中的后端是旧版本** |
| 4. 对比源码与运行进程 | `/api/search/unified`、`/api/search/mikan`、`/api/search/anime_garden` 都 404 | **源码新、进程旧，从未重启** |

**真正根因**：`D:\Project\anime\anime\app\services\` 里 Mikan/AnimeGarden 适配器已完成，但运行中的 Python 进程（PID 52616）从早期版本启动以来**从未重启**，因此新路由从未被挂载，中文种子请求全部掉进 Nyaa（Nyaa 对中文关键词几乎零命中）→ 表格空空。

**次要问题**：

- 旧版前端 SearchPage 使用 AniList 做番剧检索（AniList 英文主导，对中文差），这是"中文被翻译为英文"现象的来源。
- 新版 SearchPage 调用 `/search/unified` 时按 `{torrents,anime}` 字段读取，但旧后端返回 `{items,total,source}`，字段不匹配 → 即使数据返回也渲染为空。

---

## 三、实施的修复

### 3.1 后端 — 新增两个前端友好路由

文件：`app/routers/search.py`

```python
@router.get("/anime")         # Bangumi 中文百科，参数原文透传
@router.get("/torrents")      # 多源聚合(Mikan+AnimeGarden+Nyaa+SubsPlease)
```

响应结构与前端 `SearchPage.tsx` 的 `SimpleAnimeHit` / `SimpleTorrentHit` 完全对齐，无需再做字段重映射。

### 3.2 前端 API 层 — 新增封装

文件：`frontend/src/api/index.ts`

```ts
export async function searchAnimeNew(q: string, limit = 12): Promise<SimpleAnimeHit[]>
export async function searchTorrentsNew(q: string, limit = 100): Promise<SimpleTorrentHit[]>
```

关键点：**不再做任何关键词改写**，中文/日文/罗马音 1:1 透传到后端。

### 3.3 前端搜索页 — 完全重写

文件：`frontend/src/pages/SearchPage.tsx`

| 旧版 | 新版 |
|---|---|
| AniList 做番剧检索（英文主导） | Bangumi v0（中文原生） |
| 番剧卡片点击触发英文种子搜索 | 番剧卡片点击直接 `/anime/:id` |
| Tab 互斥切换，重复发起请求 | 一次搜索 双结果并发，切 Tab 仅切显示 |
| 字段名不对齐，数据丢失 | 字段 1:1 对齐后端响应 |
| 单一风格 | 加入骨架屏、空态引导、错误分栏、玻璃拟态 |

核心交互：

- 默认进入 **番剧** 模式，卡片点击整张 → 详情页
- Tab 切 **种子** → 同一中文关键词聚合的种子表格（字幕组/大小/热度/来源/下载 5 列）
- 下载按钮直通 qBittorrent（调用现有 `addDownload`）

### 3.4 运维 — 重启并验证

```powershell
Stop-Process -Id 52616 -Force      # 杀旧进程
cd D:\Project\anime\anime
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# 新进程 PID: 47856, 日志: .run/uvicorn.log
```

---

## 四、验证结果（实测）

### 4.1 路由挂载

重启前后 `search` 路由对比：

| 路由 | 重启前 | 重启后 |
|---|:---:|:---:|
| `/api/search/nyaa` | ✅ | ✅ |
| `/api/search/subsplease` | ✅ | ✅ |
| `/api/search/all` | ✅ | ✅ |
| `/api/search/mikan` | ❌ | ✅ |
| `/api/search/anime_garden` | ❌ | ✅ |
| `/api/search/unified` | ❌ | ✅ |
| `/api/search/anime` | — | ✅ 新增 |
| `/api/search/torrents` | — | ✅ 新增 |

### 4.2 中文关键词 "葬送" 实测

**番剧** `GET /api/search/anime?q=葬送`：

| id | 标题 | 评分 |
|---|---|---|
| 400602 | 葬送的芙莉莲 | 8.5 |
| 515759 | 葬送的芙莉莲 第二季 | 7.5 |
| 638133 | 葬送的芙莉莲 第三季 黄金乡篇 | 7.6 |
| 459283 | 葬送的芙莉莲 ～●●的魔法～ | 6.8 |
| 549563 | 葬送的芙莉莲 ～●●的魔法～2期 | 6.7 |

**种子** `GET /api/search/torrents?q=葬送`：
- 总数 8 条，全部来自 AnimeGarden
- 字幕组命中：**拨雪寻春、爱恋&漫猫字幕社、云光字幕组**
- 文件大小 200MB–642MB，覆盖第二季全集与合集

---

## 五、上线后的长效注意事项

1. **避免代码改完不重启**
   生产建议使用 `uvicorn --reload` 或部署为服务托管（systemd / NSSM），杜绝"源码很新、运行很旧"的静默 drift。

2. **别再让 `/search/unified` 成为前端单点**
   前端已迁移到语义化的 `/search/anime` + `/search/torrents`，数据结构向前端对齐，任意新增源都只需后端扩展，前端不用动。

3. **关键词原文是铁律**
   任何未来新增数据源（Nyaa-like、ACG.rip、萌番组等）的适配器，都必须把用户原文作为 `q` 的首选 search term；只有当源站**明确拒收非 ASCII** 时才按 `_translate_keyword` 启用别名回退，且这是降级、不是默认。

4. **qBittorrent 未连接**
   `/health` 当前返回 `qb_connected: false`。若上线前需要真实下载，请确认 `config.py` 的 qBittorrent 凭据 & WebUI 是否启用。

---

## 六、变更文件清单

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `app/routers/search.py` | 新增端点 | `/anime`, `/torrents` 两个前端友好路由 |
| `frontend/src/api/index.ts` | 新增封装 | `searchAnimeNew`, `searchTorrentsNew` |
| `frontend/src/pages/SearchPage.tsx` | 完全重写 | 去除 AniList，重构交互 |
| `docs/SEARCH_API.md` | 新增 | 对外 API 文档 |
| `SEARCH_REDESIGN_REPORT.md` | 新增 | 本报告 |
| `scripts/test_watch_flow.py` | 新增 | 端到端冒烟：搜索 → 选资源 → 同看大厅生命周期 |

---

## 七、端到端冒烟测试（2026-04-18）

脚本：`scripts/test_watch_flow.py`。在重启后的新进程上完整跑通"搜索 → 选种子 → 创建同看房间 → 同步播放状态"。

> qBittorrent 未接入（`qb_connected: false`），因此本次未执行真实 BT 下载；房间创建跳过 `media_id` 绑定，改由前端在选片弹窗里后接。

### 执行结果

| 步骤 | 结果 |
|---|---|
| 1. Backend health | `status=ok` |
| 2. 种子搜索「葬送」 | 5 条，全部 AnimeGarden 真实资源。字幕组：北宇治、爱恋&漫猫、爱恋字幕社 |
| 3. 番剧搜索「葬送」 | 3 条（本篇 8.5 / 前传 6.8 / 第二季 7.5） |
| 4. 选定资源 | `[北宇治字幕组] 葬送的芙莉蓮 36 · 642 MB`，info_hash = `75OPYG6IOZG4BGQHIKSWX6Z3TJT6YYU2` |
| 5. 创建同看房间 | `room_id = a42e70442d` |
| 6. 大厅列表 | 房间可见，名称「【测试】葬送的芙莉莲同看」 |
| 7. 更新播放状态 | `paused=false`, `position_seconds=42.0`, `updated_by=tester` |
| 8. 重取确认持久化 | 状态完整落库 |
| 9. 聊天消息列表 | 空（未认证用户仅读，符合预期） |
| 10. 房间保留供前端连接 | `GET /api/watch/rooms/a42e70442d` 仍可达 |

### 发现的约束（非回归，属产品设计）

- `watch_room.create_room` 对 `media_id` 做了强校验：只接受存在于本地 `media_library` 的 asset。在无下载的空库上建房时必须**不传** `media_id`，由前端在房间创建后调用 `/rooms/{id}/state` 绑定。
- 发送聊天消息需要 JWT（`get_current_user` 依赖）。匿名仅可读。

### 待真实 BT 测试的前置条件

1. 启动 qBittorrent Desktop 或 qbittorrent-nox，并在 WebUI 启用 API（默认端口 8080）。
2. 覆写 `.env` 里的 `ANIME_QB_USERNAME` / `ANIME_QB_PASSWORD`（默认 `adminadmin` 不安全，生产会被 `assert_runtime_safety` 拦截）。
3. 重启 FastAPI 后端，`/health` 应返回 `qb_connected: true`。
4. 在搜索页点击下载按钮 → 监控 qB WebUI 完成 → `media_library` 扫描到新 asset → 回到房间绑定 media_id 即可。
