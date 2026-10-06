# agent-service（Pi Durable 边车）

把 [Pi Durable](https://earendil.com/posts/pi-durable/)（实验性）嵌入 bid-pricing 项目的 agent 服务。

- 持久化：会话/任务/工具调用全部落在 `agent.sqlite`，进程死了重启自动接上
- 工具：包装后端 FastAPI（8000）的查询与测算接口（list_projects / list_project_overviews / run_calculation）
- 接口：HTTP，默认 `:8010`

> 注意：Pi Durable 目前是 experimental，API 可能变化。本目录独立于 Python 主项目，可随时删除。

## 启动

```powershell
cd agent-service
npm install
node server.mjs
```

默认直接使用你 pi 正在用的模型（读 `~/.pi/agent/models.json`，跟随 `PI_PROVIDER`/`PI_MODEL`）。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `AGENT_PORT` | `8010` | 服务端口 |
| `BACKEND_URL` | `http://127.0.0.1:8000` | bid-pricing 后端地址 |
| `AGENT_PROVIDER` | `$PI_PROVIDER`（否则 `agnes`） | models.json 里的 provider 名 |
| `AGENT_MODEL` | `$PI_MODEL`（否则该 provider 第一个） | 模型 id |
| `PI_MODELS_JSON` | `~/.pi/agent/models.json` | provider 定义文件 |
| `AGENT_SQLITE` | `./agent.sqlite` | 存储文件 |

## 接口

```
POST /submit  { "content": "..." }           → { status, answer, submission_id }（阻塞到回答）
GET  /watch   SSE：snapshot（当前视图）+ frame（增量）+ approval_request / approval_decided
POST /approve  { "key": "<taskId>:<tool>", "allow": true }   审批副作用工具
GET  /usage                               → 按模型/工具统计 token 与费用
GET  /model-config                        → 当前/可用模型清单
POST /apply-model { provider, model, baseUrl?, apiKey?, test? } → 切换模型（自定义端点会持久化）
GET  /status/<submission_id>              → 提交是否存在
GET  /health                              → 运行状态
```

## 工具与审批门

| 工具 | 说明 |
|---|---|
| `list_projects` / `list_project_overviews` / `get_project_detail` | 只读查询（崩溃自动重跑，replay safe） |
| `recompute_plan` | 重算已存方案（**副作用，需批准**） |
| `run_calculation` | 两个 xlsx 新测算（**副作用，需批准**） |
| `set_reminder` / `list_reminders` | 持久提醒：后台任务+持久定时器，**重启存活**，到点自动作为 follow-up 投回会话 |

副作用工具被 `approval-gate` 扩展拦截：执行前挂起，决定写入 durable memo（崩溃重跑不重复问；15 分钟未批 = 拒绝）。SSE 会推 `approval_request` 事件，前端「AI 测算助手」页面上点批准/拒绝。

## 前端

网页端「AI 测算助手」模块（`frontend/agent.js`，http://127.0.0.1:8080/#agent）：
聊天 + 实时工作指示 + 审批卡片 + ⚙ 模型设置抽屉（内置/models.json 选模型，或自定义 OpenAI 兼容端点并自动测试连接）。

## 崩溃恢复

杀掉本服务后重新 `node server.mjs`：`harness.resume()` 会自动接上上次没跑完的任务；
工具 `list_*` 声明了 `replay:"safe"`（只读，崩溃后自动重跑），`run_calculation`
有副作用（会持久化方案），崩溃后不会自动重跑，模型会收到"被中断"提示并自行决定。

## 与 run.ps1 集成

`run.ps1` 会同时拉起本服务（8010），与后端 8000 / 前端 8080 并列，Ctrl+C 一起停：

- 端口可用 `$env:BIDPRICING_AGENT_PORT = '<端口>'` 覆盖（与另两个服务同一套机制）
- 后端地址自动跟随 `BIDPRICING_BACKEND_PORT`（写入 `BACKEND_URL` 环境变量）
- 首次运行时自动 `npm install`
- **它是增值组件**：没装 node / 依赖装失败 / 服务起不来时只告警跳过，不阻断主应用
- 如果 8010 已有在跑的 agent-service（比如你手动起的），run.ps1 会**复用而不是重启**，Ctrl+C 也不会停它
