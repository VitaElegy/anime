# NicoTracker / anime

一个前后端分离的番剧资源管理项目：

- 前端：React + TypeScript + Vite
- 后端：FastAPI
- 数据：SQLite
- 下载：通过 qBittorrent WebUI API 下发任务
- 外部数据源：Nyaa、SubsPlease、Bangumi、AniList

## 项目结构

```text
anime/
├── app/                  # FastAPI 后端
│   ├── main.py           # 应用入口
│   ├── config.py         # 环境变量与配置
│   ├── models.py         # Pydantic 模型
│   ├── routers/          # API 路由
│   └── services/         # 外部服务与 SQLite 封装
├── frontend/             # React + Vite 前端
├── data/                 # 运行期数据（SQLite、封面缓存、下载目录）
├── deploy/               # 服务器部署示例
├── requirements.txt      # 后端依赖
└── .env.example          # 环境变量示例
```

## 本地开发

### 后端

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

后端健康检查：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/health
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

开发时前端默认跑在 `3000`，并把 `/api` 代理到 `8000`。

## 环境变量

优先复制 `.env.example` 再修改：

- `ANIME_QB_HOST` / `ANIME_QB_PORT` / `ANIME_QB_USERNAME` / `ANIME_QB_PASSWORD`
- `ANIME_DOWNLOAD_DIR`
- `ANIME_COVER_CACHE_DIR`
- `ANIME_HTTP_PROXY`

说明：

- `ANIME_DOWNLOAD_DIR` 会被后端作为默认下载目录传给 qBittorrent。
- 这个路径必须对 qBittorrent 所在机器有效。
- 最稳妥的方式是把 NicoTracker 后端和 qBittorrent 部署在同一台 Linux 机器上。

## 生产部署

建议阅读：

- [deploy/DEPLOY_SERVER.md](deploy/DEPLOY_SERVER.md)
- [deploy/systemd/anime-backend.service](deploy/systemd/anime-backend.service)
- [deploy/nginx/anime.conf](deploy/nginx/anime.conf)
