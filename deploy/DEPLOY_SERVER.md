# 服务器部署说明

## 适合的部署目标

这个项目不是纯静态站，后端依赖：

- Python 运行环境
- 可写的 SQLite / 封面缓存目录
- 能访问互联网的 HTTP 出口
- 可访问的 qBittorrent WebUI API
- 一个对 qBittorrent 有效的下载目录

所以最推荐的方式是：

1. 在一台新的 Ubuntu CT / VM 上部署后端和前端。
2. qBittorrent 也部署在同一台机器，或者至少保证下载目录路径一致。
3. 用 Nginx 提供前端静态文件并反代 `/api` 到 FastAPI。

## 不建议直接落到的现有机器

如果你的当前服务器状态没有变化，下面这些目标都不理想：

- `192.168.1.3 (elegy / VM 101)`：系统盘几乎满了，根分区可用空间非常少。
- `192.168.1.102 (MC-main / CT 105)`：根分区使用率很高，而且正在跑 MC 服务。
- 公网云主机 `47.109.100.118`：目前没有 qBittorrent，也没有现成的下载存储位。

## 推荐部署目录

```text
/srv/anime
├── app/                  # git clone 下来的项目根目录
├── .venv/                # Python 虚拟环境
├── data/
│   ├── covers/
│   └── downloads/
└── frontend-dist/        # 也可以直接用 app/frontend/dist
```

下文假设项目根目录为 `/srv/anime/app`。

## 1. 安装系统依赖

```bash
apt update
apt install -y python3 python3-venv python3-pip nginx nodejs npm git
```

如果你打算在服务器本机跑 qBittorrent，也顺手安装：

```bash
apt install -y qbittorrent-nox
```

## 2. 拉代码

```bash
mkdir -p /srv/anime
cd /srv/anime
git clone https://github.com/VitaElegy/anime.git app
cd app
cp .env.example .env
```

## 3. 配置环境变量

编辑 `/srv/anime/app/.env`：

```env
ANIME_QB_HOST=127.0.0.1
ANIME_QB_PORT=8080
ANIME_QB_USERNAME=admin
ANIME_QB_PASSWORD=你的密码
ANIME_DOWNLOAD_DIR=/srv/anime/data/downloads
ANIME_COVER_CACHE_DIR=/srv/anime/data/covers
ANIME_HTTP_PROXY=http://127.0.0.1:7890
```

说明：

- 如果服务器本身不能直连 `nyaa.land`，需要配置 `ANIME_HTTP_PROXY`。
- 如果 qBittorrent 不在本机，`ANIME_DOWNLOAD_DIR` 仍然必须是 qBittorrent 机器能识别的路径。

## 4. 创建目录与 Python 环境

```bash
mkdir -p /srv/anime/data/covers /srv/anime/data/downloads
cd /srv/anime/app
python3 -m venv /srv/anime/.venv
/srv/anime/.venv/bin/pip install -U pip
/srv/anime/.venv/bin/pip install -r requirements.txt
```

## 5. 构建前端

```bash
cd /srv/anime/app/frontend
npm install
npm run build
```

构建产物默认在：

```text
/srv/anime/app/frontend/dist
```

## 6. 先手动启动后端验证

```bash
cd /srv/anime/app
/srv/anime/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

验证：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/health
```

如果 qB 还没配置好，也可以先看到这种降级状态：

```json
{"status":"ok","qb_connected":false}
```

## 7. 配置 systemd

把仓库里的示例复制到系统目录：

```bash
cp /srv/anime/app/deploy/systemd/anime-backend.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now anime-backend
systemctl status anime-backend
```

## 8. 配置 Nginx

把示例复制进去：

```bash
cp /srv/anime/app/deploy/nginx/anime.conf /etc/nginx/sites-available/anime.conf
ln -sf /etc/nginx/sites-available/anime.conf /etc/nginx/sites-enabled/anime.conf
nginx -t
systemctl reload nginx
```

## 9. 反代与访问逻辑

Nginx 负责：

- `/` -> 前端静态文件
- `/api/` -> `127.0.0.1:8000`
- `/health` -> `127.0.0.1:8000`

这样前端里基于相对路径的 `/api/...` 请求不用改。

## 10. 建议的最终架构

最稳的方案：

1. 新建一台专门的 Ubuntu CT / VM。
2. 这台机器同时部署 `anime + qBittorrent + Nginx`。
3. 如果需要公网访问，再通过 Nginx 域名或 FRP 暴露。

## 当前代码层面的已知注意点

- 前端使用 `/api` 作为 API 前缀。
- 后端现在同时提供 `/health` 和 `/api/health`，方便前端和运维探活都能用。
- 下载功能是否可用，核心取决于 qBittorrent 是否连通。
- 该项目非常依赖出网质量；如果在大陆机房，通常需要给后端配置代理才能稳定访问 Nyaa。
