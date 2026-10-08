# 前端整合方案：两前端并为一个 React 应用

> 状态：**已完成（P0–P4 全部落地）**
> 撰写日期：2026-10-08　｜　完成日期：2026-10-08
> 目标：把 `frontend/`（原生 JS）与 `workbench-app/`（React）合并为**唯一前端**，挂在 `workbench-server`（:3456）同进程下，`api/`（:8000）退为纯 API。
> 决策依据：用户 2026-10-08 明确选择「全部并进 React（唯一前端）」+「先写迁移方案，再动手」。

## 完成纪要

| 阶段 | 内容 | 提交 |
|---|---|---|
| P0 | 令牌合并 + `:3456` 报价域同源反代 + 全站顶栏 | `1b60b36` |
| P1 | 全景大盘 → `features/portal/` | `5de99f4` |
| P2 | 速算工具箱 → `features/tools/`（9/9 数值字段对照） | `aacd54c` |
| P3 | 报价页 → `features/quote/`（参数/KPI/明细/预览/导出/方案中心/对比/切换条/KPI 穿透/三方案/审计/重算） | `5de99f4`…`c08a0c2` |
| P4-0 | AI 测算助手面板 → `features/agent/` | `5f726f1` |
| P4-1 | 全站回归 + 顶栏窄屏溢出修复 | `a32f850` |
| P4-2/3/4 | 删 `frontend/`、摘 `:8000` 静态挂载与 wb 反代、`run.ps1` 收敛单一 Web 进程 + 守卫测试重写 | `4396e96` |

**P4 关键旁修（迁移中挖出的存量缺陷）**：
- `workbench-server/src/quoteProxy.ts` 重复拼接查询串（`req.url` 挂载后已含 query）——经 `:3456` 的**所有带参报价域请求**被静默置空，如 `/api/group/list?project_id=…` 返回空数组。
- `SiteTopBar` 无任何窄屏规则，≤768px 时文档 scrollWidth 恒 845px（横向溢出）。
- `workbench-server/test/v210-weather.test.ts` 的 `../../frontend/src/lib/homeClock` 是收编时留下的死路径（该目录从未存在）。

**验证**：1621 项 Python 测试 OK ｜ React vitest 62/62 ｜ workbench-server 223 OK ｜ 6 视口 × 4 页回归 0 横向溢出 / 0 控制台错误 ｜ 报价全链路（三方案/重算/方案中心/对比/审计）字段级对照通过。

---

## 1. 现状（现场取证）

### 1.1 两个前端

| 目录 | 技术栈 | 规模 | 当前服务方式 |
|---|---|---|---|
| `frontend/` | 原生 HTML/CSS/JS，`index.html` 单行压缩 | ~10.8K 行（js 6684 / css 3481 / html 634） | 由 `:8000` FastAPI 同进程静态挂载（`app.py` 末尾 mount） |
| `workbench-app/` | React 18 + Vite 7 + TS，HashRouter | ~13.5K 行（tsx 6985 / ts 2413 / css 4135） | 由 `:3456` Express 读 `workbench-app/dist` 提供 SPA |

### 1.2 接缝：一条跨源 iframe

- 母项目 `index.html` 用 `<iframe class="wb-frame" sandbox="allow-same-origin allow-scripts allow-forms">` 嵌 `http://127.0.0.1:3456/#<sub>`。
- 跨源通信靠 `postMessage`：子页发 `{__wb:'ready'|'route'}`，父页发 `{__wb:'nav',to}`（`app.js:8-70`）。
- 父页 `WB_ORIGIN` 默认 `http://127.0.0.1:3456`；`document.referrer` 反推父 origin 做白名单。
- **这条 iframe + postMessage 就是「两个前端」的物理证据，整合即拆掉它。**

### 1.3 两端的接口面

**`api/`（:8000，报价域）** — 30 条路由，全部 `/api/*`：
- 报价：`/api/quote/preview`、`/api/quote/optimize`、`/api/quote/download/{job_id}`
- 项目/方案组：`/api/project/*`（list/get/copy/recompute/delete/compare/mark-finalized）、`/api/group/*`（list/create/rename/finalize/copy/delete）
- 经营概览：`/api/project/overview/*`（list/save/delete/finalize）
- 执行七表：`/api/project/exec/{table}/{list|save|delete}`、`/api/project/exec/summary`
- 文档：`/api/project/docs/*`（list/upload/download/delete）
- 井库：`/api/well-library/*`、审计 `/api/audit/list`、`/api/health`、`/api/metal-prices`
- 反代：`/api/wb/* → :3456`（strangler 残留，收编后应删除）

**`workbench-server/`（:3456，工作台域）** — 66 条路由（ts），覆盖待办/今日/财务/热点/知识大脑/扫描/设置/agent。
- **关键**：`:3456` 已同时服务 SPA 与 API（`index.ts:1182-1188` `express.static(dist)` + `app.get('*')` 兜底）。

### 1.4 原生前端的功能清单（迁移目标物）

**视图（`app.js` `selectModule` 分发）**：
1. `#portalView` 全景大盘（`portal-view.js` 1005 行 + `portal-data.js` + `portal.css`）
2. `#quoteView` 投标报价沙盘（重交互，见下）
3. `#moduleView` 三个占位模块（实施成本/项目台账/结算管理，均为"建设中"空态）
4. `#workbenchView` 工作台 iframe 宿主（将被拆掉）
5. AI 助手面板（`agent-panel.js` 26KB，全局悬浮 FAB）
6. 5 个工具页：`tools.html` + `tool-well/cable/duct/earth.html`（共用 `tool-common.js`、`escape.js`、`dropdown.js`、`toast.js`）

**报价沙盘的重交互（迁移难点集中区）**：
- 双滑块安全防线（`input[type=range]` ×2，含碰撞锁 + z 序提权）
- 4 联 KPI 卡（穿透联动筛选）
- 10 列明细表（冻结列、横向滚动、分页、KPI 穿透筛选）
- 方案中心抽屉（方案组 A/B/C 槽位、重命名、对比）
- 对比结果弹层、审计日志弹层
- 双通道上传舱（限价/成本 xlsx → 预览摘要）
- 税口径构成表（可编辑行 + 实时 k 值）
- 154 个 DOM id 依赖、11 处 `fetch(API_BASE)`

**敲定的硬约束（不可破坏）**：
- **数值不回归**：报价数值是本仓硬要求（`docs/adr/` 多条），迁移每一步都要与原生版逐字段对照。
- 令牌单一事实源：`frontend/tokens.css`（V2 四色）。React 侧自有 `tokens.css`，需合并为一套。
- 四个响应式断点 1280/1024/768/560。
- 类名契约、`localStorage` 键（`bidpricing.*`）不得破坏。

---

## 2. 目标形态

```
bid-pricing/
├─ workbench-app/        # 唯一前端（React），新增母项目页面
│   └─ src/pages/Quote.tsx / Portal.tsx / Tools*.tsx / Module*.tsx
├─ workbench-server/     # :3456 唯一 web 进程：SPA + 工作台 API + 报价域 API（反代或收编）
├─ frontend/             # 逐步清空；最终删除（保留 tokens 迁出）
└─ api/                  # :8000 退为纯 API（保留 uvicorn，供 :3456 反代或直连）
```

- **入口**：浏览器只访问 `http://127.0.0.1:3456/`。导航一条顶栏（工作台 9 页 + 大盘 + 报价 + 工具），无 iframe、无 postMessage、无侧栏双份。
- **`:8000` 去留**：短期由 `:3456` 反代 `/api/quote/*` 等；中期可评估把报价 API 也并入 Express（代价大，默认不做，见 §6）。

---

## 3. 迁移顺序（按"风险从低到高"排）

每一步产出后：`npm run build` 通过 + 该页面与原生版**并排截图对照** + 涉及数值的页面**逐字段对照**。

### P0 · 地基
1. 令牌合并：把 `frontend/tokens.css` 的四色令牌并入 `workbench-app/src/styles/tokens.css`，确认无冲突。
2. `workbench-server` 增加对 `api/`（:8000）的反代路由（报价域 `/api/quote/*`、`/api/project/*` 等），使 React 只认一个同源后端。
3. 顶栏导航扩为全站（对齐全站路由表），确认退出 iframe 后导航仍完整。

### P1 · 全景大盘 → `Portal.tsx`（低风险，刚做完）
- 把 `portal-view.js`（1005 行 vanilla DOM/SVG）重写为 React 组件；`portal-data.js` 的数据模型直接搬。
- 纯展示 + 一层交互（点模块展开），无后端数值，**回归面最小**，作试点。
- 判据：hub + 展开态与原生版截图一致；`prefers-reduced-motion` 生效。

### P2 · 工具页 → `Tools*.tsx`（中低风险）
- 4 个工具页 + 工具箱首页：`tool-well`（钢筋，50KB JS 最重）/`cable`/`duct`/`earth`。
- 有计算，但输入输出可枚举 → **计算判据天然适合**：每页保留一组"输入 → 期望输出"用例，重写后必须一致。
- 共用件 `escape/confirm/toast/dropdown/tool-common` 改为 React hook/组件。

### P3 · 报价沙盘 → `Quote.tsx`（高风险，最后做）
- **先拆状态机**：把 `app.js` 2059 行的隐式状态（当前方案/组/槽位/筛选/上传结果）显式建为 store。
- 分块迁移：① 表单+双滑块 → ② 上传舱+预览 → ③ KPI+明细表 → ④ 方案中心+对比 → ⑤ 审计+导出。
- **每块都必须与原生版逐字段对照**（尤其 `computeCompliance`/`computeInputVat`/`renderKpi` 派生值）。
- 建议：迁移期两版并存（旧 `/quote.html` 与新 `/quote`），对照通过再删旧。

### P4 · 收尾
- 删 `frontend/`、删 `:8000` 静态挂载、删 `api/wb_proxy.py` 反代、删 iframe host。
- `run.ps1` 收敛为单 web 进程（:3456）+ 后端（:8000）。
- 全站回归：6 视口 + 断点两侧 + 控制台 0 错误。

---

## 4. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 报价数值回归 | 硬约束，业务致命 | P3 每块逐字段对照；保留原生版并存期 |
| `app.js` 隐式状态难拆 | 迁移期交互错乱 | 先做 P3-0 状态机外化，再动 UI |
| 双滑块 / 冻结列表 / 分页等原生手法在 React 里更重 | 体验退化 | 优先用受控组件 + CSS，必要时用无依赖的 DOM 引用 |
| 两个后端（:8000 报价 / :3456 工作台）数据面 | 反代增加跳数 | 短期反代；不强行合并后端（见 §6） |
| 无前端测试基线（原生侧仅 node:test 冒烟） | 回归靠人工 | 迁移同步补 React 侧组件/数值判据 |
| React 构建产物 HashRouter 与母项目 hash 路由冲突 | 深层链接失效 | 统一为 HashRouter，路由表集中一处 |

---

## 5. 验证与验收

1. 每阶段：`cd workbench-app && npm run build` 通过；`node --test` 冒烟通过。
2. 视觉：与原生版同尺寸并排截图（Playwright），差异逐项列举。
3. 数值：报价域保留"上传→计算→穿透→导出"全链路对照，输出值逐字段相等。
4. 收尾：全站 6 视口无横向溢出、控制台 0 错误、`run.ps1` 单命令起全栈。

---

## 6. 未决事项

1. **`:8000` 是否最终下线？** 默认保留（报价求解器是 Python/PuLP，重写代价大）。若要单进程，需把报价 API 用 Node 重写或让 Express 调 Python 子进程——另立专项。
2. **构建链引入**：`workbench-app` 已用 Vite，母项目页面并入后，容器须支持构建（沿用现状）。
3. **工具页保留独立可访问性**：是否仍允许 `:3456/tools/well` 直链，还是全部收进 SPA 路由。
4. **迁移期是否保留旧页面并存**：P3 建议并存，需确认。
