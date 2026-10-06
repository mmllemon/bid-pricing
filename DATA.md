# DATA.md — 数据一页纸

> 给非程序员维护者：出问题 / 要备份 / 要迁移时，先看这张表。
> 盘点基准：`6933c6e`（2026-10-06），依据代码建模（`src/bidpricing/*.py`、`api/*.py`、`workbench-server/src/db.ts`、`agent-service/server.mjs`、前端 localStorage 调用）。运行时文件均 gitignore，**只存在你 Windows 本机**。

## 文件存储（3 个库，各有主人）

| 数据 | 文件 | 归属进程 | 表 / 内容 | 备份 |
|---|---|---|---|---|
| 报价方案 | `outputs/projects/<user>/.sqlite/quote.db` | :8000 FastAPI | `plan`（方案）、`plan_group`（分组）、`plan_slot`（槽位）、`audit_log`（审计） | 拷整个 `outputs/projects/<user>/` |
| 项目经营 | `outputs/projects/<user>/projects.json` | :8000 FastAPI | 项目列表（Biz 页；与方案经 `overview_id` 关联） | 同上（同一目录） |
| 井库 | `outputs/projects/<user>/well-library.json` | :8000 FastAPI | 手动保存的井（含参数/单价/钢筋表快照）；旧浏览器数据首次访问自动迁移 | 同上（同一目录） |
| 工作台数据 | `outputs/workbench-data/workbench.db` | :3456 Express | `settings`、`todos`（`project_id` 可空→关联 Biz 项目）、`scan_reports`、`xhs_*`（小红书账号）、`hotspot_*`（热点雷达）、`productivity_*`（日程/AI分析） | 拷整个目录（WAL 模式：停服务后拷，或连 `-wal`/`-shm` 一起拷） |
| Agent 会话 | `agent-service/agent.sqlite` | :8010 agent-service | 会话/任务、提醒、审批决定（表由 Pi Durable 库管理） | 拷文件 |
| 模型配置 | `agent-service/agent-model-config.json` | :8010 | 自定义模型 baseUrl＋**API Key**（已 gitignore，别外传） | 同上 |

## 浏览器存储（localStorage，备份盲区⚠️）

| 键 | 内容 | 说明 |
|---|---|---|
| `bidpricing.tool-{cable,earth,duct,well}.v1` | 四工具参数自动保存 | 刷新恢复用；清缓存即丢 |
| `bidpricing.handoff.v1` | 工具间交接槽（duct→earth） | 24h 自动过期 |
| `gc_wb_nav_open`、`gc_user_name` | 导航展开态、用户名 | 丢了无所谓 |
| `agent_api_token`、`bidpricingApiToken` | 边车/:8000 的鉴权 token | 本机保存，重装需重填 |

## 三个必须知道的结论

1. **待办只有一套在用**：`todos`（workbench.db，React 待办页用，已加 `project_id` 可空字段挂项目）。`wb_todos`（quote.db 的闲置表）已于 2026-10-06 删除模块与路由（`api/wb_todos.py`，全仓库无前端调用；旧库中残留的空表不再建也不再访问）。项目↔待办关联已打通：待办详情抽屉可挂项目，Biz 项目卡片显示待办数、编辑弹窗聚合显示关联待办。
2. **浏览器里现在只剩**：四工具参数快照、交接槽（24h 过期）、UI 偏好、两个 token（`agent_api_token`/`bidpricingApiToken`，localhost 单用户场景下 localStorage 存 token 的实际风险可接受，保留免重复输入）——井库已落盘 `well-library.json`。
3. **备份口诀**：`outputs/` 整个拷走＋`agent-service/agent.sqlite` 拷走＝全部。

## 出问题先看哪

| 症状 | 看哪 |
|---|---|
| 报价方案/项目列表没了 | `outputs/projects/<user>/` 在不在，`quote.db`/`projects.json` 时间戳 |
| 井库没了 | `outputs/projects/<user>/well-library.json` 在不在；首次迁移失败时旧数据仍在浏览器 `gc_well_library_v1` |
| 工作台待办/热点没了 | `outputs/workbench-data/workbench.db`（及 -wal/-shm） |
| Agent 失忆/提醒没了 | `agent-service/agent.sqlite` |
| 工具页参数没恢复 | 浏览器 localStorage（F12→Application），键见上表 |
| 端口/启动问题 | `run.ps1` 头部注释＋各进程日志目录 |
