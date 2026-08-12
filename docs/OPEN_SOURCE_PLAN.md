# NicoTracker / anime — 开源化整改规划

> 状态：进行中（本文件既是「不规范项盘点」，也是整改跟踪清单）
> 最后更新：2026-08-13

## 一、项目现状基线

| 维度 | 现状 |
|---|---|
| 技术栈 | FastAPI + SQLite / React 19 + Vite + TS + Tailwind |
| 功能 | 搜索（中文化、4 源聚合）、qBittorrent 下载、HLS ABR 转码、同看（SSE + 好友/私信/邀请）、账号体系、日历/收藏/爬取 |
| 后端测试 | 77 passed（临时 venv 实测） |
| 前端测试 | 1/9 passed（EventSource 未 mock、测试与重构后 UI 脱节） |
| Git | 本地 75 个未提交变更（37 M + 38 ??），本地领先远程 3 提交 |
| 远程分支 | `master` + `feature/watch-party`（12 提交未合入，与本地实现重复） |
| 仓库可见性 | PRIVATE |

## 二、不规范项清单（按优先级）

### P0 — 阻断「开源」的硬伤

| # | 问题 | 证据 | 整改方案 |
|---|---|---|---|
| 1 | 75 个变更未提交、未推送，包含大量调试残留 | `git status` 37M+38?? | 清理杂物 → 按逻辑拆 commit → 推送 |
| 2 | `reference-projects/` 内含第三方仓库 `.git`（14MB） | `reference-projects/watchparty/.git` 存在 | 移出仓库（保留在 ~/work/Project/_reference） |
| 3 | `.playwright-cli/`、`.run/`、`*.log`、`after-fix.png`、`tab*.txt` 等调试产物未忽略 | 未跟踪文件列表 | 删除 + 补 .gitignore |
| 4 | 无 LICENSE / CONTRIBUTING / SECURITY / CODE_OF_CONDUCT / CHANGELOG | 根目录无这些文件 | 补全开源元数据 |
| 5 | 无 CI | `.github/workflows/` 不存在 | 新增 GitHub Actions（后端 pytest + 前端 test/build） |
| 6 | 前端测试红（8/9 失败） | `vitest run` 实测 | 修 EventSource mock、同步测试与新版 UI |
| 7 | `.venv` 是 Windows 复制产物 | `pyvenv.cfg` 指向 `C:\Users\elegywang` | 删除并 gitignore，改文档引导用户自建 |

### P1 — 工程化缺失

| # | 问题 | 整改方案 |
|---|---|---|
| 8 | 无 `pyproject.toml`（无 ruff/pytest 配置、无包元数据） | 新增 pyproject.toml + ruff 规则 + pytest 配置 |
| 9 | requirements.txt 无版本锁定 | 保留范围约束 + 生成 `requirements-dev.txt` |
| 10 | 无 Makefile / 统一命令入口 | 新增 Makefile（dev/test/lint/build） |
| 11 | 无容器化 | 新增 docker-compose.yml（backend + frontend + qbittorrent） |
| 12 | README 单薄（3.7KB，无徽章/快速开始/架构图/贡献指引） | 重写 README |
| 13 | 测试脚本散落根目录（test_*.py 在根，tests/ 在子目录） | 归并到 tests/ 并统一 pytest |

### P2 — 代码与功能待完善

| # | 问题 | 证据 | 整改方案 |
|---|---|---|---|
| 14 | 远程 `feature/watch-party` 12 提交未合入，与本地实现重复 | `git log master..origin/feature/watch-party` | 明确决策：以本地实现为准，记录到 ROADMAP；评估 cherry-pick aria2/语音 |
| 15 | WatchParty 邀请功能：后端 + 处理器齐全，但重构后 UI 缺失 | `incoming_room_invitations` 无渲染 | 补回「收到的邀请」UI，同步测试 |
| 16 | 同步协议 v1 预留字段未启用 | docs/WATCH_SYNC_PROTOCOL.md §8 | 列入 ROADMAP（captions/audio_track/buffering/presence） |
| 17 | 同看权限/心跳/RTT 补偿未做 | MULTIVIEWER_SYNC_REPORT.md §8 | 列入 ROADMAP |
| 18 | 转码为整片 VOD 模式、GPU 并行受限 | HIGH_RESOLUTION_PLAYBACK_REPORT.md §6 | 列入 ROADMAP（on-demand/直通检测/并行） |
| 19 | 资源站集成：Comicat/DMHY/AnimeTosho 只在远程分支有 | RESOURCE_DIRECTORY.md §9 | 评估移植到本地 4 源聚合 |
| 20 | 文档与实际不一致（AnimeGarden 已实现但文档仍写「下一步」） | docs/RESOURCE_DIRECTORY.md §9 | 更新文档 |

### P3 — 安全与合规

| # | 问题 | 整改方案 |
|---|---|---|
| 21 | 未扫描仓库内密钥 | `git grep` token/password；.env 已忽略但需确认无硬编码 |
| 22 | 无 SECURITY.md 漏洞报告渠道 | 新增 |
| 23 | 生产配置守卫已存在但未文档化 | 在 README/DEPLOY 明确 |

## 三、整改路线（执行顺序）

1. **P0 全清**：仓库卫生 → 开源元数据 → CI → 前端测试 → venv 清理
2. **P1 工程化**：pyproject/Makefile/docker-compose/README
3. **P2 功能补全**：邀请 UI、文档同步、ROADMAP 记录决策
4. **P3 安全**：密钥扫描、SECURITY.md
5. **收尾**：逻辑提交 + 推送 + 全量验证

## 四、验收标准

- [ ] `git status` 干净，远程 master 与本地一致
- [ ] 后端 `pytest` 全绿；前端 `vitest` 全绿；`npm run build` 通过
- [ ] ruff check 通过（零错误）
- [ ] 根目录具备 LICENSE/README/CONTRIBUTING/SECURITY/CODE_OF_CONDUCT/CHANGELOG/ROADMAP
- [ ] `.github/workflows/ci.yml` 存在且语法有效（actionslint 或 yamllint 校验）
- [ ] 无调试残留/第三方 .git/日志/截图进入仓库
- [ ] 新贡献者可凭 README + docker-compose 5 分钟内跑起来
