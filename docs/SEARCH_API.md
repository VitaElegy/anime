# Search API 参考

> 最后更新：2026-04-18
> 适用版本：后端 `app.routers.search` @ 重构版

本服务暴露了两组搜索相关的 HTTP 端点：

1. **面向前端的语义化端点**（推荐）：`/api/search/anime`、`/api/search/torrents`
2. **单源 / 聚合端点**（后向兼容）：`/api/search/nyaa` 等

所有端点**接受原文关键词**（中文 / 日文 / 罗马音 / 英文），**不做自动翻译**。

---

## 1. `GET /api/search/anime`

基于 **Bangumi v0** 的中文动漫元数据检索。返回结构已对齐前端 `SearchPage.tsx`。

### Query 参数

| 名称 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `q` | string | — | 必填。关键词原文，直接透传 Bangumi。 |
| `limit` | int | 12 | 返回数量上限（1–30）。 |

### 响应

```json
{
  "anime": [
    {
      "id": "400602",
      "title": "葬送的芙莉莲",
      "titleOriginal": "葬送のフリーレン",
      "coverImage": "https://lain.bgm.tv/pic/cover/l/....jpg",
      "description": "在魔王被击败之后 ...",
      "year": "",
      "score": 8.5,
      "source": "Bangumi"
    }
  ],
  "total": 5
}
```

**调用样例（cURL）**

```bash
curl "http://localhost:8000/api/search/anime?q=葬送&limit=5"
```

---

## 2. `GET /api/search/torrents`

聚合多源的种子检索，结果已**去重 + 排序**：

- **去重**：`info_hash` 为主键，不存在时退化到归一化标题匹配。
- **排序**：`seeders` DESC → 中文字幕组加权 → 发布日期 DESC。

### Query 参数

| 名称 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `q` | string | — | 必填。关键词原文。中文/日文会自动触发 `prefer_chinese` 加权。 |
| `limit` | int | 80 | 返回数量上限（1–200）。 |

### 响应

```json
{
  "torrents": [
    {
      "info_hash": "abcdef0123456789....",
      "title": "[拨雪寻春] 葬送的芙莉莲 第二季 - 38 ...",
      "size": "642.00 MB",
      "seeders": 42,
      "source": "AnimeGarden",
      "fansub": "拨雪寻春",
      "link": "magnet:?xt=urn:btih:...",
      "pubDate": "2026-04-17 22:29:00"
    }
  ],
  "total": 8
}
```

**来源字段取值**：`Mikan` | `AnimeGarden` | `Nyaa` | `SubsPlease` | …

---

## 3. 单源与后向兼容端点

保留给内部调试、批处理脚本、少量老客户端使用。**不建议新前端使用**。

| 路径 | 说明 |
|---|---|
| `GET /api/search/nyaa?q=&page=&filter=&category=` | Nyaa 单源 |
| `GET /api/search/subsplease?q=&quality=` | SubsPlease |
| `GET /api/search/mikan?q=` | 蜜柑计划 HTML |
| `GET /api/search/anime_garden?q=&page=&page_size=` | 动漫花园聚合 API |
| `GET /api/search/all?q=` | 返回 `list[SearchResult]` — 原始四源未合并 |
| `GET /api/search/unified?q=&limit=` | 返回 `SearchResult` — 合并去重排序（字段与 `/torrents` 不同） |

> **重要**：`/search/unified` 返回 `{items, total, source}` 结构，与 `/search/torrents` 的 `{torrents, total}` 不兼容。前端已全面迁移到 `/search/torrents`。

---

## 4. 数据源能力矩阵

| 源 | 中文支持 | 字幕组信息 | BT info_hash | 稳定性 |
|---|:---:|:---:|:---:|:---:|
| Bangumi v0（元数据） | ★★★★★ | — | — | 高 |
| AnimeGarden | ★★★★★ | ✅ | ✅ | 高 |
| Mikan | ★★★★☆ | ✅ | ✅ | 中（偶尔 SSL） |
| Nyaa | ★★☆☆☆ | ❌ | ✅ | 中 |
| SubsPlease | ★☆☆☆☆ | ❌（固定 SubsPlease） | ✅ | 高 |

---

## 5. 常见问题

### Q: 搜中文有结果但点击详情页空白？
A: 前端 `SearchPage.tsx` 已使用 Bangumi 的 `subject_id` 跳转 `/anime/:id`，详情页需确认 `AnimeDetailPage` 能用 Bangumi ID 直接加载。

### Q: `/api/search/torrents` 返回为空？
A: 参考调试清单：
1. 确认后端进程是**最新**代码启动的（对比 `/openapi.json` 是否含 `/anime`、`/torrents`）。
2. 打开 `.run/uvicorn.log` 查看 `AnimeGarden search failed` 等警告。
3. 验证 `settings.HTTP_PROXY`（如需要代理访问 AnimeGarden 的话）。

### Q: 如何新增数据源？
A:
1. 在 `app/services/<new_source>.py` 实现 `async def search(keyword, ...) -> SearchResult`，**关键词原文直接透传**。
2. 在 `app/routers/search.py` 的 `search_all` 里新增一个并发任务。
3. 在 `search_torrents_for_frontend` 的 `source_label` 里加中文标签。
4. 无需改前端。
