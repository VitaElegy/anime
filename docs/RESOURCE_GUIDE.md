# 动漫资源站点指南 & 本地媒体库搭建手册

> 最后验证日期：2026-04-07
> 测试环境：中国大陆网络（无代理）

---

## 一、站点验证结果总览

| 站点 | 域名 | 状态 | 需代理 | RSS支持 | 资源类型 |
|------|------|------|--------|---------|---------|
| Nyaa.land | nyaa.land | ✅ 可用 | 否 | ✅ | BT全量 |
| SubsPlease | subsplease.org | ✅ 可用 | 否 | ✅ | 新番同步 |
| Anime Tosho | animetosho.org | ✅ 可用(⚠️2026年5月关站) | 否 | ✅ | BD高品质聚合 |
| Nyaa.si | nyaa.si | ❌ SSL失败 | 是 | ✅ | BT全量(主站) |
| 蜜柑计划 | mikanani.me / mikanime.tv | ❌ SSL失败 | 是 | ✅ | 中文追番 |
| 动漫花园 | dmhy.org | ❌ 502/证书错误 | 是 | ✅ | 中文字幕组BT |
| ACG.RIP | acg.rip | ❌ SSL失败 | 是 | ✅ | 中文字幕组 |
| 萌番组 | bangumi.moe | ❌ SSL失败 | 是 | ✅ | 中文字幕组 |
| 爱恋动漫 | kisssub.org | ⚠️ CAPTCHA拦截 | 否 | 可能 | 中文老牌站 |
| 末日动漫 | share.acgnx.se | ❌ SSL失败 | 是 | ✅ | 中文资源库 |
| AnimePahe | animepahe.com/org | ❌ 403 | 是 | 否 | MP4直连 |
| Tokyo Toshokan | tokyotosho.info | ❌ 连接失败 | 是 | ✅ | 日本原版 |
| Shana Project | shanaproject.com | ❌ SSL失败 | 是 | ✅ | RSS自动 |

---

## 二、Tier 1 站点详情（无代理可用）

### 2.1 Nyaa.land（Nyaa.si 镜像）

- **首页**: https://nyaa.land
- **动画分类**: https://nyaa.land/?c=1_0
- **搜索**: https://nyaa.land/?f=0&c=1_0&q=关键词
- **特点**:
  - 全球最大动漫BT索引站 Nyaa.si 的可直接访问镜像
  - 中/英/日字幕组资源齐全（LoliHouse、豌豆字幕组、SubsPlease 等）
  - 新番、旧番、BD/DVD Rip、合集批量下载全覆盖
  - 支持磁力链接和种子文件下载
- **RSS**: 页面底部有 RSS 链接，但被 Cloudflare 保护，可能需要浏览器 cookie
- **2026-04-07 资源样例**:
  - [LoliHouse] GHOST CONCERT: 失落之歌 - 01 [1080p HEVC] — 818.6 MiB
  - Medalist S02E08 [DSNP WEB-DL DUAL] — 835.0 MiB
  - [豌豆&LoliHouse] 转生史莱姆 第四季 - 01(73) [1080p HEVC] — 455.9 MiB
  - [LoliHouse] 天使变成废柴 第二季 - 01 [1080p HEVC] — 380.5 MiB
  - [LoliHouse] 魔法姊妹露露特莉莉 - 01 [1080p HEVC] — 634.8 MiB
  - LUPIN THE IIIRD Movie [1080p BD] — 26.5 GiB
  - [AI-Raws] 十二国记 4K MKV — 大型合集
  - [AI-Raws] 樱花大战 Movie+OVA BDRip 1080p — 合集
  - [TSDM字幕组] 厄里斯的圣杯 01-12 [1080p HEVC] — 合集
  - Kunon the Sorcerer S01 1080p CR WEB-DL — 整季打包

### 2.2 SubsPlease

- **首页**: https://subsplease.org
- **节目列表**: https://subsplease.org/shows/（800+番剧）
- **时间表**: https://subsplease.org/schedule/
- **RSS 1080p**: https://subsplease.org/rss/?r=1080 ✅ 已验证可用
- **RSS 720p**: https://subsplease.org/rss/?r=720
- **RSS 480p**: https://subsplease.org/rss/?r=480
- **特点**:
  - 当季新番同步字幕发布，速度最快
  - 固定命名格式：[SubsPlease] 番名 - 集数 (分辨率) [CRC].mkv
  - 支持批量(Batch)下载整季
  - RSS 格式标准，完美支持 qBittorrent / AutoBangumi 自动下载
  - IRC: irc://irc.rizon.net/subsplease
  - Discord 社区活跃
- **2026-04-07 资源样例**:
  - [SubsPlease] Release that Witch - 06v2 (1080p)
  - [SubsPlease] LIAR GAME - 01 (1080p)
  - [SubsPlease] Tongari Boushi no Atelier - 02 (1080p) — 尖帽子的魔法工房
  - [SubsPlease] Isekai Nonbiri Nouka S2 - 01 (1080p) — 异世界悠闲农家S2
  - [SubsPlease] One Piece - 1156 (1080p) — 海贼王
  - [SubsPlease] Ghost Concert - missing Songs - 01 (1080p)
  - [SubsPlease] NEEDY GIRL OVERDOSE - 01 (1080p)
  - [SubsPlease] Digimon Beatbreak - 25 (1080p)
  - [SubsPlease] Meitantei Precure! - 10 (1080p)
  - [SubsPlease] Ace of Diamond Act II S2 - 01 (1080p)
  - 批量打包: Odayaka Kizoku (01-12), Arne no Jikenbo (01-12), Isekai no Sata (01-12)

### 2.3 Anime Tosho

- **首页**: https://animetosho.org
- **⚠️ 重要**: 网站公告将于 2026年5月永久关闭
- **特点**:
  - BD/DVD Rip 高品质资源聚合
  - 同一资源提供多种下载方式：Torrent / NZB / DDL（直连下载）
  - 双音轨(Dual Audio)资源丰富
  - 多语言字幕
- **2026-04-07 资源样例**:
  - Medalist S02E08 — 835.0 MB — 129 seeders
  - LUPIN THE IIIRD Movie [BD] — 26.54 GB — 15 seeders
  - One Piece 1156 — 1.369 GB — 446 seeders
  - Frieren S2E05-E09 — 366-485 MB/集 — 200+ seeders
  - Release that Witch S01E06 — 302.0 MB — 191 seeders
  - Witch Hat Atelier S01E01-02 — 1.39 GB/集
  - Kunon the Sorcerer S01 — 18.14 GB — 整季
  - Oedo Fire Slayer S01 — 16.70 GB — 整季
  - So I'm a Spider S01 — 36.74 GB — 整季

---

## 三、Tier 2 站点详情（需代理访问）

### 3.1 蜜柑计划 (Mikan Project)

- **主域名**: https://mikanani.me（mikanime.tv 会 302 重定向到此）
- **特点**:
  - 中文圈最佳新番追踪站
  - 按字幕组分类，界面友好
  - 新番时间表一目了然
  - RSS 订阅是中文自动追番的首选数据源
  - 深度对接 AutoBangumi
- **RSS格式**: https://mikanani.me/RSS/Bangumi?bangumiId=XXX
- **使用建议**: 配合代理 + AutoBangumi 实现全自动中文字幕追番

### 3.2 动漫花园 (DMHY)

- **主域名**: https://dmhy.org（当前 502/证书异常）
- **特点**:
  - 中文圈历史最悠久的动漫BT站
  - 几乎所有中文字幕组在此发布
  - 支持 RSS 订阅和高级搜索
  - 资源涵盖动画、漫画、音乐、游戏
- **使用建议**: 等域名恢复，或通过代理访问

### 3.3 ACG.RIP

- **主域名**: https://acg.rip
- **特点**:
  - 更新快，资源质量高
  - 界面简洁
  - 支持 RSS
- **使用建议**: 需代理

### 3.4 萌番组 (Bangumi.moe)

- **主域名**: https://bangumi.moe
- **API**: https://bangumi.moe/api/torrent/page/1
- **特点**:
  - 支持标签高级搜索
  - 按字幕组分类清晰
  - 有公开 API，适合开发自定义工具
- **使用建议**: 需代理

---

## 四、本地媒体库搭建方案

### 4.1 架构概览

```
资源发现(RSS) → 自动下载(qBittorrent) → 整理重命名 → 媒体服务器(Jellyfin) → 多端播放
```

### 4.2 核心组件

| 组件 | 推荐工具 | 用途 | 端口 |
|------|---------|------|------|
| 媒体服务器 | Jellyfin | 本地流媒体播放、刮削元数据 | 8096 |
| BT下载器 | qBittorrent | 种子/磁力下载、RSS自动订阅 | 8080(WebUI), 6881(BT) |
| 自动追番 | AutoBangumi | 对接蜜柑计划RSS自动追番 | 7892 |
| 番剧管理 | Sonarr + Prowlarr | 自动搜索、下载、重命名(国际站) | 8989, 9696 |
| 元数据刮削 | Bangumi插件(Jellyfin) | 中文番剧信息、封面、评分 | - |
| 反代(可选) | Nginx Proxy Manager | 统一入口、HTTPS | 81 |

### 4.3 Docker Compose 部署文件

```yaml
version: "3.8"

services:
  # ====== 媒体服务器 ======
  jellyfin:
    image: jellyfin/jellyfin:latest
    container_name: jellyfin
    ports:
      - 8096:8096
    volumes:
      - ./jellyfin/config:/config
      - ./jellyfin/cache:/cache
      - ./media/anime:/media/anime        # 动漫库
      - ./media/movies:/media/movies      # 电影库
    environment:
      - TZ=Asia/Shanghai
    restart: unless-stopped

  # ====== BT下载器 ======
  qbittorrent:
    image: linuxserver/qbittorrent:latest
    container_name: qbittorrent
    ports:
      - 8080:8080     # WebUI
      - 6881:6881     # BT端口
      - 6881:6881/udp
    volumes:
      - ./qbittorrent/config:/config
      - ./media/downloads:/downloads      # 下载目录
      - ./media/anime:/anime              # 完成后移动目标
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Asia/Shanghai
      - WEBUI_PORT=8080
    restart: unless-stopped

  # ====== 自动追番(中文) ======
  autobangumi:
    image: estrellaxd/auto_bangumi:latest
    container_name: autobangumi
    ports:
      - 7892:7892
    volumes:
      - ./autobangumi/config:/app/config
      - ./autobangumi/data:/app/data
    environment:
      - TZ=Asia/Shanghai
      - AB_DOWNLOADER_HOST=qbittorrent
      - AB_DOWNLOADER_PORT=8080
    depends_on:
      - qbittorrent
    restart: unless-stopped

  # ====== 番剧管理(国际) ======
  sonarr:
    image: linuxserver/sonarr:latest
    container_name: sonarr
    ports:
      - 8989:8989
    volumes:
      - ./sonarr/config:/config
      - ./media/anime:/tv
      - ./media/downloads:/downloads
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Asia/Shanghai
    restart: unless-stopped

  # ====== 索引器管理 ======
  prowlarr:
    image: linuxserver/prowlarr:latest
    container_name: prowlarr
    ports:
      - 9696:9696
    volumes:
      - ./prowlarr/config:/config
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Asia/Shanghai
    restart: unless-stopped
```

### 4.4 目录结构

```
/media/
├── downloads/          # qBittorrent 下载临时目录
├── anime/              # Jellyfin 动漫媒体库
│   ├── 转生变成史莱姆/
│   │   ├── Season 01/
│   │   ├── Season 02/
│   │   ├── Season 03/
│   │   └── Season 04/
│   ├── 葬送的芙莉莲/
│   │   ├── Season 01/
│   │   └── Season 02/
│   ├── One Piece/
│   │   └── Season 01/
│   └── ...
└── movies/             # 剧场版电影
```

### 4.5 qBittorrent RSS 自动下载配置

#### SubsPlease 全量 1080p 订阅
```
RSS URL: https://subsplease.org/rss/?r=1080
自动下载规则:
  - 规则名: "追番-海贼王"
    匹配: "One Piece"
    保存到: /anime/One Piece/Season 01/
  - 规则名: "追番-芙莉莲S2"
    匹配: "Frieren"
    保存到: /anime/Frieren/Season 02/
  - 规则名: "追番-全部新番"
    匹配: "*"
    保存到: /downloads/anime-new/
```

#### Nyaa.land 字幕组订阅（如可获取RSS）
```
搜索关键词示例:
  - "LoliHouse 1080p" — LoliHouse 字幕组全部发布
  - "豌豆字幕组" — 豌豆出品
  - "TSDM" — TSDM字幕组
```

### 4.6 Jellyfin 推荐插件

| 插件 | 用途 |
|------|------|
| Bangumi | 从 bangumi.tv 获取中文元数据(标题/简介/评分/封面) |
| Open Subtitles | 自动下载字幕 |
| AniDB / AniList | 补充动漫元数据 |
| Intro Skipper | 自动跳过 OP/ED |

---

## 五、快速上手步骤

1. **安装 Docker & Docker Compose**
2. **创建目录**: `mkdir -p media/{downloads,anime,movies}`
3. **保存上方 docker-compose.yml** 到项目目录
4. **启动服务**: `docker compose up -d`
5. **配置 qBittorrent**:
   - 访问 `http://localhost:8080`
   - 添加 SubsPlease RSS: `https://subsplease.org/rss/?r=1080`
   - 配置自动下载规则
6. **配置 Jellyfin**:
   - 访问 `http://localhost:8096`
   - 添加媒体库 → 类型选"节目(Shows)" → 路径 `/media/anime`
   - 安装 Bangumi 插件获取中文元数据
7. **配置 AutoBangumi**(如有代理访问蜜柑计划):
   - 访问 `http://localhost:7892`
   - 设置蜜柑计划 RSS 源
   - 选择追踪的番剧

---

## 六、常用搜索技巧

### Nyaa.land 搜索语法
```
# 搜索特定番剧的1080p HEVC资源
https://nyaa.land/?f=0&c=1_0&q=史莱姆+1080p+HEVC

# 只看可信上传者
https://nyaa.land/?f=2&c=1_0&q=关键词

# 按大小排序(找BD合集)
https://nyaa.land/?f=0&c=1_0&q=关键词&s=size&o=desc
```

### 常见字幕组标识
| 字幕组 | 标识 | 特点 |
|--------|------|------|
| LoliHouse | [LoliHouse] | 简繁内封，HEVC 10bit，体积小画质好 |
| 豌豆字幕组 | [豌豆字幕组] | 中文翻译质量高 |
| TSDM字幕组 | 【TSDM字幕组】 | 日番中字 |
| AI-Raws | [AI-Raws] | 无字幕原盘/4K |
| SubsPlease | [SubsPlease] | 英字，速度最快 |
| Chika | [Chika] | WEB-DL，多字幕 |
| VARYG | -VARYG | CR WEB-DL，双音轨，多字幕 |

---

## 七、备注

- Anime Tosho 将于 2026年5月关站，如需其资源请尽快备份
- 中文站点(蜜柑/DMHY/ACG.RIP/萌番组)均需代理访问，但资源质量最高
- SubsPlease RSS 是无代理环境下自动追番的最佳方案
- Nyaa.land 是无代理环境下搜索全量资源的最佳选择
- 建议定期检查站点可用性，动漫资源站域名变动频繁
