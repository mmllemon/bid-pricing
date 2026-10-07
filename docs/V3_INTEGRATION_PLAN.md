# V3 集成计划：导航单一事实源 · AI 助手全局悬浮 · 工作台融合

> 状态：**待批准（Draft）**
> 创建日期：2026-10-06
> 注（2026-10-07）：`lshu-workbench-v0.1.0/` 只读参照已删除（git rm，3.3M/208 文件），本文中提及它的段落为历史记录，不再有效。
> 适用仓库：`d:\Lee-proj\TRAE\bid-pricing-build\bid-pricing`
> 参照规范：`c:\Users\leema\.trae-cn\skills\lshu-workbench\app\DESIGN.md`、`docs/UI_REFACTOR_V2_PLAN.md`
> 备份基线：git tag `pre-wb-merge-20261006`（指向 `ba554d4`）；`outputs\projects\leema\.sqlite\quote.db.bak-prewbmerge-20261006-140331`

本计划覆盖三条请求：① 导航维护两份的结构改造；② AI 测算助手改全局悬浮；③ lshu-workbench 与本项目融合。其中 ③ 是主体，① ② 是 ③ 的必要前置（融合后导航项会变多、页面会变多，两份导航必然失控）。

---

## 0. 背景

本项目现状：`frontend/` 为纯 HTML/CSS/原生 JS 单页应用（`index.html` + `app.js` 做视图切换，另 5 个工具页），后端为 FastAPI（`api/` + `src/`，:8000），静态前端由 `python -m http.server --directory frontend` 服务在 :8080，AI 助手由 Node 边车 `agent-service`（:8010）提供。

lshu-workbench 现状：Express + TypeScript 后端（:3456）+ Vite/React 前端（8 路由）+ better-sqlite3。视觉规范为「黑白极简 + 橙/黄双专色 + 像素秩序」，与本项目 V2 设计系统高度同源。

目标：把 lshu 的**功能与工作流**并入本项目，形成单一导航、单一设计系统、单一数据面的个人工作台。

---

## 1. 已核实的事实

### 1.1 三处需要纠正的认知（与最初设想不符）

1. **工作目录里的 `lshu-workbench-v0.1.0/` 是上游 macOS 发布版，不是 skill 目录里那份 Windows 适配版。**
   - 证据：项目内副本缺少 `Install.ps1` / `Start.ps1` / `Stop.ps1` / `doctor.ps1`，只有 `Install.command` / `Start.command` / `scripts/*.sh`；且 `backend/package.json` 里 `better-sqlite3` 为 `^11.5.0`。
   - 而 `c:\Users\leema\.trae-cn\skills\lshu-workbench\app` 里的是 `^13.0.3` + 4 个 PowerShell 脚本。
   - 影响：**项目内副本直接 `npm ci` 会在 Node 24 上因缺少 win-x64 预编译包而回退 node-gyp、要求 VS C++ 工具链并失败**（skill 自己的 SKILL.md 已记录这一点）。

2. **lshu 后端远比预想的大。** 不是「一个 1200 行的 index.ts」，而是 `index.ts` + 约 70 个 `src/**` 模块（含 `services/`、`connectors/`、`finance/`、4 代 schema 迁移 `productivitySchemaV3/V31/V4`）+ 约 25 个测试文件。功能已迭代到 v3.3（AI 日程规划、DeepSeek 客户端、天气/反地理编码、家计同步、热点、知识大脑）。
   - 影响：这不是「搬几个页面」，而是**收编一个中型应用**。计划必须分阶段且允许在 P5 缩范围。

3. **FastAPI 侧是单文件单 app，没有 APIRouter 分层。** `api/app.py` 直接 `app = FastAPI(...)` 并挂中间件；没有任何 `include_router`。
   - 影响：新增 `/api/wb/*` 反代应**先建独立模块**（如 `api/wb_proxy.py`）再挂载，不要把代理逻辑塞进已 2000+ 行的 `app.py`。

### 1.2 已确认的其余事实

| 事实 | 证据 |
| --- | --- |
| lshu 的 CORS 白名单仅 `localhost:5173/5180/3456`，**不含 8080** | `backend/src/http/localCors.ts` |
| 本项目 CORS 放行本机任意端口 | `api/app.py` L256-258 `allow_origin_regex` |
| 本项目前端调用后端用绝对地址 `http://localhost:8000` | `app.js:109`、`workbench.js:15` `const API_BASE = window.__API_BASE__ \|\| 'http://localhost:8000'` |
| 静态前端是 `python -m http.server`，**无反代能力** | `run.ps1` L295-299 |
| 导航确实有两份：`index.html` 静态侧栏（7 项，`<button data-module>`）与 `frontend/js/sidebar.js` 模板字符串（7 项，`<a href="#...">`） | `index.html` L37-81 / `js/sidebar.js` L24-71 |
| `sidebar.js` 同时被 `index.html` 引入（L601），但在 index 上因取不到 `#sidebarSlot` 而只做抽屉与用户名逻辑、不渲染结构 | `js/sidebar.js` L3-4 |
| `app.js` 在**脚本解析期**就绑定了 `.nav-item` 的 click | `app.js` L52-54 |
| AI 助手是整页 section，非悬浮层 | `index.html` L466-529 `#agentView` |
| 悬浮操作坞固定在右下角 | `quote-dashboard.css` L233-234 `bottom:24px; right:32px` |
| `run.ps1` 已为 agent-service 建立了「增值组件：故障只告警不阻断」的启动范式 | `run.ps1` L301-347 |
| 项目内 lshu 副本未被 git 跟踪 | `git status` → `?? lshu-workbench-v0.1.0/` |

---

## 2. 架构决策

### D-1 前端：移植进现有原生 JS 体系（用户已选）

不引入 Vite/React 构建链。lshu 的 React 源码作为**行为与视觉的只读参照**，逐页用原生 JS 重写进 `workbench.js` 所在体系。

理由：两套设计系统（本项目 V2 / lshu DESIGN.md）本就是同一套「黑白 + 橙黄 + 像素」审美，融合阻力小；而引入第二条构建链会带来两套导航、两套状态管理、两套样式令牌，与「完美融合」直接冲突。

### D-2 后端：FastAPI 先反代保通，再逐模块 Python 收编（用户已选）

- **过渡期**：FastAPI 新增 `api/wb_proxy.py`，把 `/api/wb/*` 反代到 `http://127.0.0.1:3456/api/*`。前端只认 8000 一个后端。
- **收编期**：每个模块用 Python 重写等价接口，前端契约不变（`/api/wb/todos` 从「被代理」变成「本地实现」），逐个摘除。
- **终态**：所有被采用的模块均已 Python 化，Node 与 Express 下线。

理由：可在任意时点停下而不留半成品；每次收编都可与 Express 的返回做逐字段对照，降低「重写引入数值/语义偏差」的风险（本项目对数值不回归有硬要求）。

### D-3 过渡期 Express 实例用 skill 目录那份，不修改项目内副本

- 跑：`c:\Users\leema\.trae-cn\skills\lshu-workbench\app`（已装依赖、已 Windows 适配）。
- 读：项目内 `lshu-workbench-v0.1.0/`（上游源码，进 git，供检索与对照）。
- **不修改 vendored 副本**，避免维护一个与上游分叉的 fork；Windows 适配差异不影响「读代码做移植」。

风险与缓解：skill 目录不在本项目版本控制内，skill 升级可能覆盖。缓解——过渡期是临时的，且 D-2 的收编目标就是让它消失；若过渡期预期拉长，则改为把 Windows 适配补丁以独立 patch 文件形式落在本项目（见 §6 未决 1）。

### D-4 数据：不迁移，从空开始（用户已选）

lshu 侧数据留在 `workbench.db`，不导入 `quote.db`。收编后的新表直接建在收编目标库里。**注意**：不迁移数据 ≠ 不迁移数据结构；表结构（字段、约束、语义）仍须逐项对齐，否则前端 DTO 对不上。

### D-5 首页：以 lshu「今日」页为基底（用户已选，与我原推荐不同）

保留现有个人工作台的**容器与导航地位**（`data-module="workbench"`），把其内部渲染改为以 lshu 今日页（`features/home/HomeDashboard.tsx` + `pages/Home.tsx`）为骨架，再把本项目现有的「项目经营概览」作为其中一张卡片并入。

代价需明确：lshu 今日页依赖**时钟（系统时区）、天气（需 Geolocation 授权）、位置反解（Nominatim 外部请求）**。`DESIGN.md` L207 对这三者的隐私边界有硬规定（经纬度只取两位小数、不写库、不回传、不记日志；反解失败显示「电脑当前位置」而非上海）。移植时必须逐条遵从，不得简化。

### D-6 导航：`js/sidebar.js` 成为唯一事实源

- 导航项数据（分组、编号、标题、图标 path、目标）抽为 `sidebar.js` 内的单一数组。
- `index.html` 的整块 `<aside class="sidebar">` 替换为 `<div id="sidebarSlot"></div>`，由 `sidebar.js` 渲染。
- 渲染模式由「当前是否 index」决定：index 用 `<button data-module>`（同页切视图），工具页用 `<a href="./index.html#mod">`（跨页）。
- **连带必改**：`app.js` L52-54 在解析期绑定 `.nav-item`。改为由 `sidebar.js` 渲染完成后派发事件或暴露 `__navReady` 钩子，`app.js` 在钩子内绑定；`sidebar.js` 已先于 `app.js` 加载（`index.html` L601 → L606），天然满足时序。
- 激活态由 `pathname + hash` 推导，不再硬编码 `active` 类。

### D-7 AI 助手：全站可唤起的悬浮面板（用户已选）

- 抽出 `frontend/agent-panel.js`：**自包含**，运行时注入面板 DOM（现 `#agentView` 的内容 + 模型设置抽屉）并完成既有全部交互（`/submit`、SSE `/watch`、审批卡片、`/health`、`/model-config`、`/apply-model`）。
- 入口统一为右下角悬浮按钮（48×48，橙底黑框），**改用 `#agentView` 整页 section 的方案作废**——页面级 section 无法在工具页共存。
- 与 `.floating-dock` 的位置冲突：FAB 固定 `bottom:24px; right:32px`，`.floating-dock` 的 `right` 由 `32px` 改为 `92px`（FAB 宽 48 + 间距 12）。工具页无 dock，FAB 独立存在。
- 6 个页面（`index.html` + `tools.html` + 4 个 `tool-*.html`）统一引入 `agent.css` + `agent-panel.js`。
- 导航中的 `A-03 AI 测算助手` 保留为入口（点击打开悬浮面板），不再作为 `#agentView` 视图切换项——**这会移除 app.js 的 `agent` 分支**，需同步改 `selectModule` / `showModule` / `hashchange` 兜底白名单。

---

## 3. 红线

以下为本次改造中不可逾越的约束，任一条被触碰即须停止并上报：

1. **不修改 `lshu-workbench-v0.1.0/` 内的任何文件。** 它是只读参照。
2. **不修改 `config/**` 下的任何 spec / schema 文件。**（沿用本项目既有红线）
3. **不改 lshu 的 `frontend/src/**`。** 移植是「照着重写」，不是「改它来适配」。
4. **不引入前端构建链**（Vite / webpack / React 运行时 / Tailwind）。
5. **不改动 `quote.db` 的既有表结构与既有数据**；新表用新前缀（如 `wb_`），不侵入 `projects` / `quotes` 等既有表。
6. **AI 助手的 `agent-service`（:8010）本轮不动**，仍按 `run.ps1` L301-347 的「增值组件、故障不阻断」范式运行。
7. **`localStorage` 键 `gc-workbench-v2` 的既有结构不得破坏**；如需新键，另起新键并写迁移分支。
8. 响应式断点仍严格为 1280/1024/768/560 四档，不新增。
9. 视觉遵守 `DESIGN.md` §3.1 颜色预算（白 78-84% / 黑 12-18% / 橙 ≤4% / 黄 ≤2%）与 §3.2 禁止项。

---

## 4. 阶段划分

每阶段产出后按固定格式汇报：**改了什么 / 实测证据 / 主动决策与例外（含理由）**。实测一律用 Playwright（`.trae\*.mjs`，**用完删除**）。

### P0 · 门禁与准备

**目标**：把「能不能做」验证清楚，避免后续阶段产出空壳。

| # | 事项 | 判据 |
| --- | --- | --- |
| 0.1 | 凭证实地核实：`DEEPSEEK_API_KEY`、`CIMIDATA_APP_ID/SECRET`、`OPENCLI_BIN`、`LARK_CLI_BIN`、`KNOWLEDGE_BASE_URL`、`MONEYCATS_DB_PATH` | 逐项给出「存在 / 不存在 / 存在但不可用」，**不采信配置文件里的占位值** |
| 0.2 | skill 目录的 lshu 实例跑通 | `http://127.0.0.1:3456/api/health` 返回 200 |
| 0.3 | 备份复核 | `pre-wb-merge-20261006` 指向 `ba554d4`；`quote.db` 副本字节数与当前一致 |
| 0.4 | 明确 `lshu-workbench-v0.1.0/` 的 git 归属 | 见 §6 未决 2 |

**出口条件**：0.1 的结论直接决定 P5 的范围。**若某模块凭证不可用，该模块不进 P5**，并在计划中标注「因凭证缺失暂缓」，不产出占位 UI。

#### P0 实测结果（2026-10-06）

探测方式：读取 `backend\.env.local` 的键值存在性（不输出真实值）+ `Get-Command` 验可执行文件 + HTTP 探活。

| 项目 | 实测 | 判定 |
| --- | --- | --- |
| lshu 实例 :3456 | `200 {"ok":true,...}` | **可用**（P1.3 反代目标就绪） |
| Node | `v24.18.0` | 可用 |
| 后端 :8000 | DOWN | P1 测试时需拉起 |
| 前端 :8080 | `200` | 可用 |
| 本项目 agent-service :8010 | `200 {"ok":true,"provider":"agnes","model":"agnes-3.0-flash","model_available":true}` | **可用**，且已有真实模型接入 |
| `DEEPSEEK_API_KEY` | EMPTY | **不可用** |
| `CIMIDATA_APP_ID` / `CIMIDATA_APP_SECRET` | 均 EMPTY | **不可用** |
| `MONEYCATS_DB_PATH` | 键不存在 | **不可用** |
| `OPENCLI_BIN` = `opencli` | `Get-Command opencli` → NOT FOUND | **不可用** |
| `KNOWLEDGE_BASE_URL` = `http://127.0.0.1:8765` | 连接被积极拒绝 | **不可用** |
| `LARK_CLI_BIN` = `lark-cli` | FOUND（`plugins\trae-remote-official\lark\1.0.5\bin\lark-cli.exe`） | 存在，但属 TRAE 插件自带 CLI，非用户自备 |

**结论：P5 的五组外部依赖模块中，四组凭证/服务不可用，一组（飞书）只有插件自带 CLI。**

因此范围调整如下（不改 P1–P4，它们本就不依赖外部凭证）：

- **P5-a 财务分析、内容表现、热点雷达、知识大脑 → 全部暂缓**，不写占位 UI、不写假数据，等凭证可用再排期。
- **P5-b AI 行动分析 / 今日规划 → 改道**：不走 lshu 的 `DEEPSEEK_API_KEY` 直连，改为复用**本项目已跑通的 agent-service（:8010）**。该服务 `model_available: true`，且本项目 AI 助手已在使用它。改造点是把 lshu 的 `services/deepseekClient.ts` 契约映射到 agent-service 的 `/submit`，而非移植 DeepSeek SDK 调用。
- **P5-c 飞书 → 待定**：`lark-cli` 存在于 TRAE 插件目录，路径随插件版本变化（当前 `1.0.5`），把它写死进配置会让工作台依赖插件升级节奏。倾向不采用，除非你明确要求。

### P1 · 壳层基础设施（对应请求 ①②）

| # | 事项 | 主要改动文件 |
| --- | --- | --- |
| 1.1 | 导航单一事实源（D-6） | `frontend/js/sidebar.js`、`frontend/index.html`、`frontend/app.js`、6 个 HTML 版本号 |
| 1.2 | AI 助手全局悬浮（D-7） | 新增 `frontend/agent-panel.js`；`frontend/agent.js` 合并/退役；`frontend/index.html`（删 `#agentView` section）、5 个工具页 HTML、`frontend/agent.css`、`frontend/quote-dashboard.css`（dock `right` 让位） |
| 1.3 | FastAPI 反代层 | 新增 `api/wb_proxy.py`；`api/app.py` 挂载 |
| 1.4 | `run.ps1` 接入 lshu 实例 | `run.ps1`（按 agent-service 的「增值组件」范式新增第 4 个服务，失败只告警不阻断） |

**验收标准**
- 6 个页面侧栏逐项一致（分组、编号、文案、图标、顺序）；修改 `sidebar.js` 一处即全站生效。
- index 内 6 个视图 + 5 个工具页**均可唤起** AI 面板；面板在 index 与工具页的交互（发送、SSE、审批、设置抽屉）行为一致。
- FAB 与 `.floating-dock` 在任何断点下不重叠、不遮挡。
- `curl http://127.0.0.1:8000/api/wb/health` 返回 Express 的健康响应。
- `run.ps1` 在 3456 被占用/Node 不可用时仍能正常拉起主应用并给出告警。
- JS 错误 0 条。

#### P1 实测结果（2026-10-06）

| 项目 | 实测 | 判定 |
| --- | --- | --- |
| 6 页侧栏清单 | 均为 `W-00 个人工作台 / Q-01 投标报价 / C-02 实施成本 / A-03 AI 测算助手 / L-04 项目台账 / S-05 结算管理 / T-06 速算工具箱`，逐字相同 | **PASS** |
| index 5 个 `data-module` 项切换 | workbench/quote/cost/ledger/settlement → hash 依次落 `#workbench/#quote/#cost/#ledger/#settlement` | **PASS** |
| A-03 侧栏项唤起面板 | `data-agent-open` 计数 1；点击后 `#agentPanel` 可见 | **PASS** |
| FAB + 面板（6 页 @1440px） | FAB 与面板均 `visible` | **PASS** |
| JS 错误 | 6 页 + 窄屏 2 页：console error / pageerror 全 0 | **PASS** |
| FAB ↔ 操作坞重叠 | 1440/1024/768/375 四档 `overlap=false`；375px 坞居中（x=75,w=225 → 右缘 300 ≤ 375） | **PASS** |
| 横向溢出 | 各档 `scrollWidth - clientWidth = 0` | **PASS** |
| 反代 `/api/wb/health` | `200`，响应体为 lshu 原文 `{"ok":true,...}`，content-type 原文透传 | **PASS** |
| 反代 `/api/wb/settings` | `200`，返回真实设置 JSON（非空壳） | **PASS** |
| run.ps1：3456 被占用 | 本拉起的 node 退出 → 探活 3456 由在跑实例应答 → 告警「复用在跑的实例」→ `$workbench=$null`；主应用正常拉起，成功横幅**不**输出 workbench 行 | **PASS** |
| run.ps1：happy path（改用空闲的 3470） | workbench 起来，`/api/health` 200 且 `sourceFingerprint=v0.1.0`；经 8100 反代 `/api/wb/health` 亦 200 | **PASS** |
| `tests/test_run_script.py` | 19 项全过；`Parser::ParseFile` 0 错；UTF-8 BOM 保留 | **PASS** |

**P1.4 过程中发现并修正的一处真实缺陷（原设计有误）**
原实现按 `backend/package.json` 的 `npm start`（即 `node dist/index.js`）启动工作台，实测**必然失败**：
`backend/tsconfig.json` 用 `"moduleResolution": "bundler"`，tsc 产出的 `dist/` 里全是无扩展名的相对导入
（`import './bootstrapEnv'`），普通 node 按 ESM 规则解析报
`ERR_MODULE_NOT_FOUND: .../backend/dist/bootstrapEnv` —— 该 skill 的 `npm start` 本身就是坏的
（它自带的 `Start.ps1` 用的是 `node --import tsx src/index.ts`）。
已改为与 `Start.ps1` 一致：`node --import tsx src/index.ts`，并预检 `backend/node_modules/tsx`；
另按 `Start.ps1` 补设 `WORKBENCH_SOURCE_FINGERPRINT`（取自 `VERSION`），否则健康响应里是 `dev-untracked`。

### P2 · 首页重构（对应请求 ③ 的第一屏）

以 lshu 今日页为基底重写 `workbench.js` 的首页渲染，并入本项目「项目经营概览」卡片。

**验收标准**
- 时钟用系统时区（`Intl.DateTimeFormat().resolvedOptions().timeZone`），不默认 Asia/Shanghai。
- 天气与位置反解严格遵 `DESIGN.md` L207 隐私边界；未授权时不请求、不显示假数据。
- 颜色预算实测：橙 ≤4%、黄 ≤2%。
- 既有 `gc-workbench-v2` 数据无损；`biz` 模块仍能读到后端 `api/project/overview/list`。

#### P2 实测结果（2026-10-06）

首页骨架：`ui-status-head`（H-01 · TODAY + 问候/每日一句 + date-chip）→ `home-context-row`（CLK 时钟 + WX 天气）→ M-01 项目经营概览（4 指标卡 + 最近 5 项目）→ 今日待办 + 快速记录 → 习惯打卡 → 番茄钟 + 本周趋势。

| 项目 | 实测 | 判定 |
| --- | --- | --- |
| 首页可达 & 不误跳 | `#workbenchView` 可见；`#wbNav .navi.active` = 「首页」（非「项目经营概览」）；`#bizMask` 不存在 | **PASS** |
| 时钟系统时区 | `14:56 / 星期二`；`workbench.js` 全文件无硬编码 `Asia/Shanghai`，取 `Intl.DateTimeFormat().resolvedOptions().timeZone`（遵 `DESIGN.md` L207） | **PASS** |
| 天气隐私边界 | 未授权态文案「使用电脑位置获取天气 / 允许定位」；此时**不发** weather 请求、不显示假数据；授权后坐标仅两位小数 `{latitude:39.9, longitude:116.41}` | **PASS** |
| 天气署名 | `.home-weather-credit a[href*="openstreetmap.org"]` 存在（Open-Meteo + OpenStreetMap） | **PASS** |
| 项目经营概览 | `.home-biz-row` = 4 行、`.home-biz-metric` = 4 张卡；数据来自 `api/project/overview/list`（200） | **PASS** |
| 经营行交互 | 点击 `/ 聚焦后按 Enter` 均跳 `biz`，active nav 变为「项目经营概览」（键盘可达） | **PASS** |
| 快速记录入口 | `[data-quick]` = 3 | **PASS** |
| 既有数据无损 | `gc-workbench-v2` 字节级无损（163B→163B） | **PASS** |
| 颜色预算 | 橙 0.71%（≤4%）、黄 0.70%（≤2%）、白 83.87%、黑 12.80%（白/黑均在 78–84% / 12–18% 区间） | **PASS** |
| 横向溢出 | 1440/1024/768/375 四档 `scrollWidth - clientWidth` 均为 0 | **PASS** |
| JS 错误 | console error / pageerror 全 0；实载 `workbench.js?v=2026-10-06-wb25` | **PASS** |

**P2 过程中发现并修正的一处真实缺陷（P1 遗留，仅 curl 验证导致漏检）**
`api/wb_proxy.py` 把浏览器的 `Origin` 头透传给 lshu，而 lshu 的 `localCors` 只放行 5173/5180/3456，导致所有**从浏览器发起**的 `/api/wb/*` 请求被上游以 `CORS origin denied` 拒绝（500）——天气功能因此完全不可用。P1 当时只用 `curl` 验反代（curl 不发 `Origin`），故未暴露。已新增 `_BROWSER_CONTEXT = frozenset({"origin","referer"})` 并在转发时剥离；带 `Origin: http://localhost:8080` POST `/api/wb/weather/today` 实测 **200**，返回真实 DTO。**教训：跨源验证必须带 `Origin` 头，curl 默认行为与浏览器不等价。**

**P2 过程中发生的一次自查回归（已修复）**
首页 `[data-quick]` 绑定在编辑时丢失 `el.onclick=()=>{` 包裹，导致 forEach 体在绑定期被立即执行——每次渲染首页都立刻 `go("biz")` 并弹出 `#bizMask`，首页无法显示。修复后 `wireHome()` 恢复正确包裹，版本号 wb23 → wb25。

### P3 · 核心本地模块移植

按 lshu 路由顺序移植**不依赖外部凭证**的部分：设置、扫描、待办（今日待办 / 待办中心 / 优先级 / 收件箱动作）、记录（灵感/收藏/备忘）、项目概览。

**验收标准**
- 逐接口与 Express 返回做逐字段对照，差异逐条说明（允许的差异须写明理由）。
- 收编完成一个接口即摘除 `wb_proxy` 中对应路径。
- 空状态、错误状态、loading 状态齐全，不使用 emoji。

#### P3 侦察结论与范围修正（2026-10-06，动手前）

**修正一：本节原列 5 个模块，其中 2 个在 lshu 侧不存在。**
逐端点枚举 `backend/src/index.ts`（36 个）+ `productivityRoutes.ts`（41 个）+ `financeRoutes.ts`（3 个）后确认：lshu **没有「记录（灵感/收藏/备忘）」模块**，也**没有「项目概览」**。前端 8 个页面为 `Home / Todos / Scan / Settings / Performance / Hotspots / Knowledge / Finance`，其中「收藏」仅是小红书笔记指标（`collects`），属 Performance 模块，受 OpenCLI 凭证门禁约束。而「项目概览」是本项目自有模块（`/api/project/overview/list`），P2 已接通，不属 lshu。

**修正二：lshu 侧真正的无凭证模块只有 3 个** —— Settings、Scan、Todos。其余 5 个模块（Performance/Hotspots/Knowledge/Finance/Home 的 AI 与日程部分）全部依赖 P0.1 已判定不可用的外部凭证。

**修正三：母项目前端目前只消费 lshu 的 1 个接口。** 全仓检索 `/api/wb/` 仅命中 `frontend/workbench.js:347` 的 `POST /api/wb/weather/today`（另一处为注释）。即：**唯一阻碍 Express 下线的是 `weather/today` 与 `health` 两个端点**，其余 34+41+3 个端点当前无任何消费者。

**修正四：lshu 库内没有值得迁移的用户数据。** 只读盘点 `backend/data/workbench.db`（28 张表，WAL 1.43MB）：非空表仅 6 张 —— `todos` 7 行、`todo_source_evidence` 7 行、`settings` **3 行且全部是迁移记账键**（`productivitySchemaVersion` / `productivityV3MigratedAt` / `productivityV31MigratedAt`）、`hotspot_sources` 2 行（`ensureHotspotSources()` 的默认值）、`productivity_migration_audit` 3 行、`sqlite_sequence`。
7 条 todos 全部为**测试夹具**：标题 `推进丝路` / `整理桌面文件`×6，`cluster` 均为 `项目A`，证据 `external_id` 为 `th-unique-a`、`cluster:proj-a-<ts>`，创建时间集中在 2026-10-05T17:20–17:31Z（北京时间 10-06 01:20–01:31，11 分钟窗口，与 db 文件创建时间 01:37 吻合）。`scan_reports`、全部 `xhs_*`、`hotspot_articles`、`hotspot_fetch_runs`、`knowledge*` 均为空。
→ **结论：不需要数据迁移**，原计划担心的「两种数据落点如何合并」不成立（该风险随之作废）。

**修正五：lshu 数据落点在 skill 安装目录内，本身是风险。**
`db.ts:19-20` 默认 `DATA_DIR = <app>/backend/data`，`run.ps1` 只设 `WORKBENCH_UPSTREAM` / `WORKBENCH_SOURCE_FINGERPRINT`，**未设 `WORKBENCH_DATA_DIR`**，故实例把库写在 `~/.trae-cn/skills/lshu-workbench/app/backend/data/`。该路径不在本项目仓库内、且不是 git 仓库（`rev-parse` 报 not a git repository），skill 升级/重装即可能被覆盖。收编后自有数据必须落到本项目 `outputs/projects/<user>/.sqlite/quote.db`。

**据此重排 P3 执行顺序**（按「每步都有真实消费者」原则，不再为无消费者的端点做纯搬运）：
- **P3-a（先做）**：把 `weather/today` + `health` 用 Python 重写。这是唯一有消费者的路径，做完即可摘除 `wb_proxy` 的两条路径；顺带消掉 P2 修的 Origin 剥离 hack 的必要性。
- **P3-b**：把 lshu「待办」页移植为母项目原生 JS 页面，存储由 Python 收编到 `quote.db`；替换 P2 遗留的 localStorage `data.todo` 占位接缝。这是请求 ③「结合」的实质交付物。
- **P3-c**：设置页。注意 lshu 的 `settings` 表当前**零用户行**，`GET /api/settings` 实际等价于返回 `DEFAULT_SETTINGS`（`db.ts:277-323`）；移植时只保留母项目真正会用到的键。
- **P3-d（降级为可选，需显式同意）**：扫描页。它会真实遍历用户 Windows 桌面（`scanRoot` 默认 `~/Desktop`），且 `POST /api/scan/run` 会经 `commitDesktopScan()` 写待办库，并有 DLP 过滤（`publicScanFiles` / `desktopDlp.ts`）。隐私面大于已定的位置信息边界，**未经用户显式同意不实施**。

#### P3-a 实测结果（2026-10-06）

**改了什么**

| 文件 | 改动 |
| --- | --- |
| `api/wb_local.py`（新增） | 工作台域的 Python 实现，收编 `GET /api/wb/health`、`POST /api/wb/weather/today`；逐条对齐 `weatherService.ts`（DTO、条件码表、15min 新鲜/6h 快照降级、in-flight 合并、上游严格校验）与 `locationLabelService.ts`（城市级标签、24h 缓存、1.1s 最小间隔、失败回落「电脑当前位置」） |
| `api/app.py` | 新增 `from api.wb_local import router as wb_local_router`，并在 `app.include_router(wb_router)` **之前** `include_router`。FastAPI 按注册顺序匹配，故已收编的 `/api/wb/<path>` 被本地实现短路，未收编的路径继续落到原反代 |
| `requirements-web.txt` | 新增 `tzdata>=2024.1` |

**为什么要引入 `tzdata`（本轮唯一新增依赖）**
实测 `.venv` 的 `zoneinfo.available_timezones()` **返回 0 个**——Windows 无系统 IANA 时区库。缺它则两件事都会失真：① `isValidTimeZone` 无法真的校验时区，只能退回正则；② `localDateInZone` 无法推出「当地日期」，而 `parseUpstream` 本来要用它校验 `daily.time[0]` 是否与请求时区一致（口径错位检测会失效）。装上后 `available_timezones()` 为 598 个，`localDate` 与 Express 一致（`2026-10-06`）。`tzdata` 是纯数据包。

**字段对照（同一请求体 `{latitude:39.9042, longitude:116.4074, timezone:"Asia/Shanghai"}`，带 `Origin: http://localhost:8080`）**

| 字段 | Express `/api/weather/today` | 本地 `/api/wb/weather/today` | 判定 |
| --- | --- | --- | --- |
| HTTP | 200 | 200 | PASS |
| `status` | `cache`（命中其 06:52 的缓存） | `live`（本地冷缓存） | 预期差异（缓存状态不同，非语义差异） |
| `locationLabel` | `电脑当前位置` | `电脑当前位置` | PASS（两侧都回落默认值，原因见下） |
| `timezone` / `localDate` | `Asia/Shanghai` / `2026-10-06` | 同左 | PASS |
| `fetchedAt` | `2026-10-06T06:52:45.983Z` | `2026-10-06T07:03:51.639Z` | 格式**同形**（3 位毫秒 + `Z`）；时间不同因两次取数时刻不同 |
| `current.conditionCode` / `conditionLabel` | `clear` / `晴` | `clear` / `晴` | PASS |
| `current.temperatureC` | 25.4 | 25.5 | 上游在两次调用间自身变动（差异 ≤0.1℃） |
| `current.apparentTemperatureC` / `windKph` | 21.8 / 5.9 | 22.0 / 5.5 | 上游变动；且两侧都**不**做取整（与 TS 一致） |
| `today.minC` / `maxC` / `precipitationProbabilityPct` | 13.7 / 25.5 / 0 | 13.7 / 25.5 / 0 | PASS |

**分支覆盖（模块级，直调 `_get_today`，非 HTTP）**

| 场景 | 实测 | 判定 |
| --- | --- | --- |
| `WEATHER_ENABLED=false` | `unavailable` + `WEATHER_DISABLED`，`localDate` 仍正确，上游请求数 **0** | PASS |
| 冷缓存首次取数 | `live`；`25.44→25.4`、`13.66→13.7`、`25.46→25.5`（半数进位与 JS `Math.round` 一致）；`apparentTemperatureC`/`windKph` 保持原值不取整 | PASS |
| 二次取数 | `cache`，新增上游调用 **0** | PASS |
| 并发 3 次（同一 key） | 三个都拿到结果，上游天气调用 **1 次**（in-flight 合并生效） | PASS |
| 降级：2 小时前快照 | `stale` | PASS |
| 降级：7 小时前快照 | `unavailable` + 原错误码，`current=null` | PASS |
| 上游 HTTP 500 | `unavailable` + `WEATHER_UPSTREAM_UNAVAILABLE` | PASS |
| 上游日期与当地日期错位 | `unavailable` + `WEATHER_RESPONSE_INVALID` | PASS |
| 非法时区 `Not/AZone` | HTTP 200 + `WEATHER_RESPONSE_INVALID`，`timezone`/`localDate` 均为 `""` | PASS |
| 非 JSON 请求体 | 同上（HTTP 200） | PASS |
| 反解限速：3 个不同坐标 | 耗时 2.20s（1.1s × 2 个间隔） | PASS |
| 未收编路径 `/api/wb/settings` | HTTP 200，响应体与 Express 直连 `/api/settings` 逐字相同 → 反代未被破坏 | PASS |

**一处环境事实（不是缺陷，但会长期影响观感）**
`nominatim.openstreetmap.org` 从本机**不可达**（直连 10s 超时）。因此城市级标签恒回落「电脑当前位置」——Express 侧同样是默认值，两侧表现一致。即：本机环境下天气卡片永远不会显示城市名，这是网络可达性问题，不是移植缺陷；若将来网络可达，本地实现会自动开始显示城市标签。

**主动决策与例外**

1. **`/api/wb/health` 的响应形态有意偏离 Express**。lshu 的 `appVersion`/`buildId`/`promptVersion`/`schemaVersion`/`hubVersion`/`sourceFingerprint` 是它的构建指纹，收编后如实填写只能是编造；而唯一消费者（`run.ps1` 的 `Wait-HttpOk`）只判 HTTP 200、不解析任何字段。故改为只报真实可核的事实：`{ok, time, domain:"workbench", impl:"python", version:"v3-p3a"}`。已在 `wb_local.py` 的 docstring 中写明理由。
2. **`tzdata` 作为新增依赖**：见上。它是 `localDate` 与真实时区校验的前提，不装则验收项无法成立。
3. **`_as_number` 收紧了两处 JS 宽松转换**：JS 的 `Number(null)` / `Number("")` 均为 `0`，会把 `{latitude:null}` 静默当成 (0,0) 这个真实坐标去查询。这里对 `None`/`""`/`bool` 一律判非法。浏览器端只送数字，收紧不影响任何真实调用。
4. **反解限速改为「先占坑再等待」**：TS 是「先 `await` 再写 `nextRequestAt`」，并发调用会同时穿透限速。改为在等待前先占位，单请求行为完全相同，并发下才真正生效（实测 3 个不同坐标耗时 2.20s）。
5. **Nominatim 的默认 User-Agent 改为 `BidPricing-Workbench/1.0 (local personal dashboard)`**（TS 侧是 `LShuWorkbench/...`）。Nominatim 使用条款要求可识别的 UA，沿用 lshu 的名字会让这一层以一个已下线的服务自称。可用 `LOCATION_REVERSE_USER_AGENT` 覆盖。
6. **反解任务在提前失败时被取消**：TS 侧天气失败时反解 promise 会成为悬挂 promise（JS 不告警）；Python 不取消会打印 `Task was destroyed but it is pending`。故在 `finally` 中显式取消。
7. **未删除 `api/wb_proxy.py`，也未改动 `run.ps1`**。理由：`weather/today` 是母项目前端**唯一**的 `/api/wb/*` 消费者，收编后 Express 对前端已无实际作用；但 P3-b/c 尚未开始，反代对未收编路径（如 `/api/wb/settings`）仍可用作参照，且 `run.ps1` 的 lshu 边车段与 `tests/test_run_script.py`（19 项）绑定，物理下线属 P6 的既定范围。**风险提示**：在 P6 完成前，`run.ps1` 仍会尝试拉起 Express 实例；若 3456 无人应答，`/api/wb/<未收编路径>` 会返回 502——当前前端不调用这些路径，故不影响页面。

#### P3-b 实测结果（2026-10-06）

**改了什么**

| 文件 | 改动 |
| --- | --- |
| `api/wb_todos.py`（新增） | 待办域的 Python 实现：`wb_todos` 表 + 6 个端点（`GET/POST /api/wb/todos`、`POST /api/wb/todos/import`、`PATCH/DELETE /api/wb/todos/{id}`）。错误形态对齐 Express：`{"code":"INVALID_REQUEST"\|"NOT_FOUND","message":...}`，400/404 语义逐项对齐 |
| `api/app.py` | 新增 `from api.wb_todos import router as wb_todos_router` 并**注册在 `wb_local_router` 之前**。FastAPI 按注册顺序匹配，故 `/api/wb/todos*` 被本地实现短路，未收编路径（如 `/api/wb/settings`）继续落到反代 |
| `frontend/workbench.js` | 待办读写改走后端：新增 `todoApi` / `todoFromDto` / `todoPayload` / `todoBootstrap` / `todoWrite` / `todoCreate` / `todoDelete` 同步层；`wireHome`、`wireModule`、`openEditor` 保存分支、`confirmDelete` 四处 todo 分支改走同步层；初始化追加 `todoBootstrap()` |
| `frontend/index.html` | `workbench.js?v=2026-10-06-wb27`（由 `wb25` 起迭代破缓存） |

**为什么只搬「待办本体」，不搬 lshu 待办页的全部功能**
lshu 的待办域除 CRUD 外还有 evidence（证据）/ plan（AI 排程）/ complete / reopen 等端点，逐条核对后确认它们**全部**依赖外部连接器与本地扫描：Things 导入、飞书任务、Apple 日历、桌面文件扫描、DeepSeek。这些在 P0.1 已判定不可用，照搬只能是空壳——与 P0 出口条件「凭证不可用的模块不产出占位 UI」冲突。故只移植**语义可自洽、无需外部输入**的待办本体（标题/备注/优先级/完成/置顶），其余不移植。

**存储与迁移设计（实测覆盖）**

| 设计点 | 做法 | 理由 |
| --- | --- | --- |
| 表落点 | `outputs/projects/<user>/.sqlite/quote.db` 的 `wb_todos` 表（`wb_` 前缀） | 红线 5：不侵入 `plan`/`plan_group`/`plan_slot`/`audit_log` |
| 权威来源 | 后端为权威；`data.todo` 仅作渲染镜像；localStorage 降级为缓存 | 渲染链路零改动；后端不可用时页面仍可读 |
| 迁移标记 | 独立键 `gc-workbench-v2.todoMigrated` | 红线 7：`gc-workbench-v2` 结构不得破坏，故不往里加字段 |
| 迁移前提 | ① 本次会话读到过非种子的原始串 ② 后端列表为空 ③ 标记键不存在——三者缺一不可 | 防止把 `CONFIG.modules[].seed` 的演示数据写成真实数据 |
| 顺序保真 | 列表按 `id DESC`，迁移时**倒序**导入 | 复现 localStorage `unshift` 的先后顺序 |
| 幂等 | 导入失败**不置**标记，下次加载自动重试 | 失败可自愈，不需要用户干预 |

**后端分支实测（PowerShell 探针，直打 `:8000`，确认走本地实现而非 Express）**

| 场景 | 实测 | 判定 |
| --- | --- | --- |
| `GET /api/wb/todos`（空库） | `200 []` | PASS |
| 创建 | `200 {"id":1,"title":"后端往返测试",...}` | PASS |
| 空标题 / 无 `title` 键 / 非对象体 | 400「待办标题不能为空」/ 400 / 400「请求体必须是 JSON 对象」 | PASS |
| `done:"yes"`（非布尔） | 400「done 必须是布尔值」 | PASS |
| 空 patch | 400「没有可更新的字段」 | PASS |
| `PATCH`/`DELETE` 不存在 id | 404「待办不存在」 | PASS |
| `import`：`items` 非数组 / 501 条 / 混合非法条目 | 400 / 400「单次最多导入 500 条」/ 仅落合法条目 | PASS |
| `import` 顺序 | 输入 `[C,B,A]` → ids 2,3,4 → 列表返回 `A,B,C` | PASS（印证前端须倒序导入） |
| 既有表未受影响 | `tables` 含 `wb_todos` 及原四表；`plan` 13 行、`plan_group` 11 行、`plan_slot` 33 行、`audit_log` 4 行均不变 | PASS |

**前端验收（Playwright，`.trae/p3b-verify.mjs`，20 项）**

```
PASS A1 全新浏览器不迁移 seed  db=0          PASS C1 勾选落到库  done=1
PASS A2 页面无 JS 错误                        PASS C2 新建落到库且在首位  priority=P0
PASS A3 迁移标记已写入                        PASS C3 服务端 id 已回填前端
PASS A4 gc-workbench-v2 结构未破坏            PASS C4 编辑落到库  priority=P2
PASS B1 迁移条数正确  db=3                    PASS C5 删除落到库  db=3
PASS B2 迁移后顺序与 localStorage 一致        PASS C6 清空 localStorage 后仍能从后端恢复  渲染=3
PASS B3 字段逐项落地                          PASS C7 全程无 JS 错误
PASS B4 checkin 等其它键未受影响              PASS D1 后端不可用时用缓存渲染  渲染=1
PASS B5 页面渲染出 3 条待办  渲染=3           PASS D2 后端不可用时无 JS 错误
PASS B6 无 JS 错误                            PASS D3 迁移标记未被误置

== 20/20 PASS ==
```

**P3-b 过程中发现并修复的一处真实缺陷（本轮自己引入）**
首次全量跑时 C5 超时：删除确认框 `#c-ok` 永不出现，且库里多出标题为「未命名」的幽灵行。加 `page.on('request')` 抓荷载后定位到「编辑」步骤实际发出了 **POST（新建）** 而非 PATCH。
根因：新建时前端先用本地占位 id（`Date.now()`）渲染，DOM 上的 `data-id` / `data-edit` 也跟着占位值；`todoCreate` 拿到服务端 id 后只 `store.save()`（存但不重绘），于是后续任何按 `data-*` 反查（勾选、编辑、删除）都**查不到而静默失效**——编辑退化成新建，删除直接 return。
修复：`todoCreate` 成功回调改用 `persist()`（save + render）。**教训：任何按 `data-*` 反查的 DOM 绑定，在 id 变化后必须重绘；「保持对象同一性以免重绘」这类优化在此处是错的。**

**主动决策与例外**

1. **「收编一个接口即摘除 `wb_proxy` 对应路径」这条 P3 验收标准在结构上无法逐条执行。** `wb_proxy` 是 `/api/wb/{path:path}` 的**单条兜底**路由，不是逐路径注册，故不存在「摘除某一条」的动作。等价效果由**注册顺序短路**实现（`wb_todos` → `wb_local` → `wb_proxy`），前端契约不变。物理删除该模块属 P6 范围（与 P3-a 决策 7 同）。
2. **一处可见行为变化：全新浏览器（无 `localStorage`、空库）不再显示 3 条内置演示待办。** 因为「不把 seed 写成真实数据」是迁移的硬前提，`data.todo` 被后端权威值（空）覆盖。该路径**不是白屏**——渲染出的是既有的设计空状态 `今天暂无待推进事项`（[workbench.js:617](file:///d:/Lee-proj/TRAE/bid-pricing-build/bid-pricing/frontend/workbench.js#L617)）。副作用是 `todo` 成为首页唯一不显示种子的模块（`checkin` / `record` 仍显示种子）。**判断：保留空列表更诚实**（演示数据冒充真实数据是更坏的体验）；若你希望首启有样例数据，请明示，届时应在库为空时显式落种子，而不是放宽迁移前提。
3. **本轮未改任何 CSS，也未改 DOM 结构**，故颜色预算与 1280/1024/768/560 四档无横向溢出**沿用 P2/P3-a 的取证结论，未重复测试**——这不是遗漏，而是存储层改动在视觉上不可能产生差异。若你要独立复验，我可以补跑。
4. **`todoWrite` 落库成功后不重绘**（与 `todoCreate` 相反）：PATCH 不改变 id，DOM 上的 `data-*` 仍有效，重绘反而会打断输入焦点。失败时回滚并 `alert` 说明「请确认后端服务（:8000）是否正常」。
5. **后端没有 `--reload`**（`run.ps1`/本次启动命令均未加），故改 `api/wb_todos.py` 后必须重启 `:8000` 才生效。本轮已重启并验证。
6. **清理了两类本轮自建产物**：`.trae/p3b-verify.mjs`、`.trae/p3b-dbg.mjs`（约定用完必删）；以及 `outputs/projects/.sqlite/quote.db`——它是我用独立 Python 进程直调 `wb_todos._connect()` 时，因未按用户重定向 `PROJECTS_DIR` 而在默认路径建出的空壳（仅含 `wb_todos` 表、0 行）。经核对 `api/app.py:58` 的 `user_scope()` 恒把库定向到 `outputs/projects/<user>/`，该文件永不被应用使用，故删除该文件与其空目录。
7. **`wb_todos` 自增序列未重置**：删行后 `sqlite_sequence` 仍停在 21，新建 id 从 22 起。id 只作标识、不承载语义（排序按 `id DESC`，与时间递增一致），故不重置——重置反而需写 `sqlite_sequence`，多一次不可逆操作。

### P4 · 跨域联动（本轮最高价值项）

这是「完美融合」与「两个应用并排」的分界线，也是双后端方案物理上做不到的部分。

| # | 联动 | 说明 |
| --- | --- | --- |
| 4.1 | 待办 ↔ 报价项目 | 待办可挂到项目上（真外键），项目卡片显示关联待办 |
| 4.2 | 项目概览 ↔ 经营数据 | 今日页的经营数字与报价/结算数据同源 |
| 4.3 | AI 助手 ↔ 双域数据 | AI 同时可读工程域（项目/报价）与个人域（待办/记录） |

**前置**：4.1 要求待办表与项目表在同一 SQLite 内，或至少在同一进程可事务访问。若按 D-2 收编到本项目库则天然满足。

### P5 · 外部依赖模块（受 P0.1 门禁约束）

- AI 行动分析 / 今日规划（DeepSeek）
- 财务分析（MoneyCats 备份库）
- 内容表现（小红书 OpenCLI）
- 热点雷达（次幂数据）
- 知识大脑（外部服务）

**规则**：P0.1 核实不可用的模块直接跳过，不写占位 UI、不写假数据。

### P6 · 收尾

- 全部采用的模块已 Python 化 → 从 `run.ps1` 移除 lshu 实例启动段，从 `api/wb_proxy.py` 移除死路由，随后删除该模块。
- 清理临时脚本、临时备份。
- 全站回归：6 视图 + 5 工具页 + 新工作台，多断点无横向溢出，JS 错误 0 条。
- 更新 `docs/STATE.md`。

---

## 5. 风险登记

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| lshu 体量远超预期（§1.1-2） | P3–P5 可能长期占用 | 阶段化 + P5 门禁；P2/P3 完成即已有可用价值，可随时叫停 |
| skill 目录不在版本控制内 | 过渡期 Express 实例被 skill 升级破坏 | 过渡期短期化；必要时降级为 patch 文件（§6 未决 1） |
| 重写引入语义偏差 | 本项目对数值不回归有硬要求 | 每个收编接口与 Express 逐字段对照 |
| 天气/位置反解的隐私条款被简化 | 违反 `DESIGN.md` L207 | P2 验收标准单列该项 |
| `app.js` 视图路由改动面广 | 可能回归「刷新掉页」类缺陷 | P1 完成后重跑既有的 hash / 刷新回归用例 |
| 4 份 HTML 版本号需要同步 | 缓存中间态 | 同批改动合并为一次提交（沿用既有约定） |

---

## 6. 未决事项

1. **过渡期若拉长，是否把 Windows 适配以 patch 文件形式落入本项目？** 当前决策是不动 vendored 副本、用 skill 实例。
2. **`lshu-workbench-v0.1.0/` 是否提交进 git？** 当前未跟踪。建议提交（去掉 `node_modules`），使其成为稳定、可检索的参照；代价是仓库体积增加（含 2 个 woff2 字体）。
3. **是否在 P6 把静态前端从 `http.server:8080` 收敛到 FastAPI 单端口？** 收益是同源、少一个进程；代价是牵动 `run.ps1` 与前端 `API_BASE`。当前倾向：P6 再评估，P1 不动。
4. **历史遗留待裁决项**（本轮不动）：`workbench.js:243` 的 `−`(U+2212) 是否改 ASCII `-`；`--text-h1`（30px）零引用是否清理；F-19 的 327 处网格偏离是否正式关闭；`quote.db.bak-p7-preAuditClean-*` 是否删除；`run.ps1` 中历史未提交改动。

---

## 7. 阶段授权

用户已明确：**不接受阶段授权询问，禁止再问「是否继续」**。本计划在用户批准后，将按 P0 → P6 连续推进，每阶段结束以文本汇报（改了什么 / 实测证据 / 主动决策与例外），不中断等待确认。仅在遇到以下情况时暂停并提问：红线冲突、需要不可逆操作、P0 门禁判定模块不可用导致范围变化。

---

# 8. V3.1 修订：个人工作台改为「完全照搬 lshu」

> 修订日期：2026-10-06
> 触发：用户指示「个人工作台这块，我想把 lshu 的完全照搬进我的项目，把我以前的基本废除，除了项目经营留下」。
> 两个前提由用户二选一确认：**前端＝引入 lshu 原版 React 前端**；**凭证＝全部照搬，缺就缺**。
> 本节**覆盖** §2 的 D-1 / D-3 / D-5、§3 的红线 3 与 4、§4 的 P3-c / P3-d / P5 门禁 / P6 终态目标。未被本节点名的部分（D-2 过渡机制、D-4、D-6、D-7，红线 1/2/5/6/7/8/9）**继续有效**。
> 备份基线：`outputs/backups/`（`frontend-preV31-20261006-152839.zip`、`api-preV31-20261006-152839.zip`、计划文档副本）+ git tag `pre-wb-merge-20261006`。

## 8.1 决策覆盖表

| 旧决策 | 新决策 | 理由 |
| --- | --- | --- |
| D-1 不引入构建链，lshu 页面用原生 JS 重写 | **作废**。vendored lshu 原版 React 前端 + Vite 构建 | 用户明确选「引入原版 React」；8 页含图表/热点/知识大脑，原生重写做不到「照搬」 |
| D-3 项目内 lshu 副本只读、不修改 | **收窄**。skill 目录仍为只读参照；**vendored 进本项目的副本归本项目所有、可改** | 要在其中新增「项目经营」页、隐藏重复导航，必须可改 |
| D-5 首页＝lshu 今日页骨架 + 母项目 `workbench.js` 重写 | **作废**。首页＝lshu 原版 Home 页（React） | 同上 |
| 红线 3「不改 lshu `frontend/src/**`」 | **改为**：不改 skill 目录的 lshu；vendored 副本可改 | 同上 |
| 红线 4「不引入前端构建链」 | **删除** | 用户已选 React + Vite |
| P3-c 设置页（原按「只留有用的键」缩范围） | **改为**直接用 lshu 原版 Settings 页，照搬 29 键 | 用户已选「完全照搬」 |
| P3-d 扫描页（原降级为「需显式同意」） | **改为照搬** | 用户已选「全部照搬」，该同意即视为已给出（见 §8.4-4 的隐私提示） |
| P5 五模块「因凭证缺失暂缓，不产出占位 UI」 | **作废**。全部照搬，缺凭证的模块上线即空态/错误态 | 用户已选「缺就缺」 |
| P6「所有模块 Python 化 → Express 下线」 | **作废**。Express 长期保留 | 连接器/扫描/AI 规划只存在于 TypeScript 侧 |

## 8.2 动手前已核实的事实

| 事实 | 证据 |
| --- | --- |
| lshu 前端是 React 应用，不是静态页 | `frontend/package.json`：React 18.3 + react-router-dom 7.18 + recharts 2.12 + pixelarticons 2.4 + Vite 8.2 + TypeScript 5.6 |
| 源码规模 | `frontend/src` 共 **64** 个文件，合计约 **1.78 MB**（含字体） |
| 路由表（8 条） | `App.tsx`：`/`（Home）/ `/todos` / `/performance` / `/hotspots` / `/knowledge` / `/scan` / `/finance` / `/settings` |
| 路由模式＝**HashRouter** | `main.tsx:3,9`。故构建产物在任意子路径/独立端口都能跑，**无需服务端重写规则** |
| API 地址＝相对 `/api` | `api/client.ts:40` `const BASE = '/api'` |
| dev 代理目标 | `vite.config.ts`：`/api` → `http://localhost:3456`（可由 `VITE_API_PROXY` 覆盖） |
| 构建产物目录 | `vite.config.ts` `build.outDir = 'dist'`，未设 `base`（默认 `/`） |
| **Express 单进程已同时提供 SPA 与 API** | `backend/src/index.ts:1207-1216`：`express.static(frontend/dist)` + `app.get('*')` SPA 回退（`/api/` 前缀除外） |
| skill 目录已就绪 | `frontend/node_modules`、`frontend/dist` **均已存在**（可直接构建/直用） |
| 启动方式 | 必须 `node --import tsx src/index.ts`；`npm start`（`node dist/index.js`）**是坏的**（P1.4 已实测） |
| 工作区现状 | 大量未提交改动（P1+P2+P3-a+P3-b）；`lshu-workbench-v0.1.0/` 未跟踪 |

## 8.3 目标形态

```
bid-pricing/
├── workbench-app/            # vendored：lshu frontend（React+TS，归本项目所有、可改）
│   ├── src/pages/Biz.tsx     #   新增：项目经营（调用本项目 FastAPI）
│   └── vite.config.ts        #   改：base 与 API 代理目标
├── workbench-server/         # vendored：lshu backend（Express+TS，不含 node_modules）
├── frontend/                 # 母项目原生 JS 壳（保留 5 页：报价/成本/台账/结算/工具）
└── api/                      # FastAPI :8000（保留：报价域 + 项目经营数据源）
```

- **进程**：`workbench-server` 单进程（:3456）同时提供 React SPA 与工作台 API。
- **母项目入口**：侧栏 `W-00 个人工作台` → React 工作台（`index.html` 的 `workbench` 分支不再渲染旧工作台）。
- **项目经营**：在 React 应用内新增 `/biz` 路由，数据来自本项目 FastAPI `/api/project/overview/list`（本项目 CORS 已放行本机任意端口）。
- **废除**：`frontend/workbench.js` 中除「项目经营概览」外的全部功能（todo / checkin / record / 阅读 / 锻炼 / 支出 / 番茄钟 / 趋势 / 快速记录 / owner / slogan / quotes / overview / quickAdd / trend）。

## 8.4 用户已知悉并接受的代价（逐条列明，避免日后误判为缺陷）

1. **引入前端构建链**。首次落地需联网 `npm install`（依赖树数百包）；改一行前端需重构建。`run.ps1` 必须新增安装/构建/降级逻辑。
2. **Express 长期在线**，D-2 的「逐模块 Python 收编 → Express 下线」终态放弃。P3-a（天气）与 P3-b（待办）已 Python 化的成果，其去留见 §8.6。
3. **五个模块长期处于空态或错误态**（Performance 小红书 / Hotspots 次幂数据 / Knowledge 外部服务 / Finance MoneyCats / AI 规划 DeepSeek）。按用户选择「缺就缺」照装上架；**不得伪造数据**，错误态须显示真实原因。
4. **扫描页会真实遍历 Windows 桌面**（`scanRoot` 默认 `~/Desktop`），并有 `POST /api/scan/run → commitDesktopScan()` 写待办库、`desktopDlp` 过滤。用户选择「全部照搬」即视为已给出此前计划要求的显式同意。**若你希望保留「需再次确认」的保护，请在动手前否决此项。**
5. **两套导航并存**：母项目侧栏（外层）+ lshu `AppShell` 侧栏（工作台内层）。是否隐藏内层侧栏见 §8.6-3。
6. **旧工作台功能区失效**（习惯打卡/记录/番茄钟等）。安全默认：`localStorage` 键 `gc-workbench-v2` 与其数据**保留不动、仅无 UI**（遵红线 7，可逆）。

## 8.5 新阶段划分（P-W1 … P-W7）

每阶段仍按固定格式汇报：**改了什么 / 实测证据 / 主动决策与例外**。实测一律 Playwright（`.trae\*.mjs`，**用完删除**）。

| 阶段 | 事项 | 验收标准 |
| --- | --- | --- |
| **P-W1** | 备份与基线固化 | `outputs/backups/` 三件套存在且可解压；git tag 与工作区状态记录在案 |
| **P-W2** | vendored `workbench-app/` + `workbench-server/`（不含 `node_modules`）；`npm install` + `npm run build` 跑通 | `http://127.0.0.1:3456/api/health` 200；`http://127.0.0.1:3456/#/` 渲染出 Home；8 条路由逐条可达；控制台错误 0 |
| **P-W3** | React 侧新增 `/biz` 项目经营页（复用母项目 `workbench.js` 的 biz 渲染逻辑与 FastAPI 数据源）；`AppShell` 导航加入该入口 | `/biz` 渲染 4 指标卡 + 项目列表；数值与母项目旧工作台**逐项一致**（同源同数据比对） |
| **P-W4** | 母项目 `frontend/` 侧废除旧工作台：`workbench.js` 裁到只剩 biz（或整体改为跳转 React）；`index.html` 的 `workbench` 视图改为跳转/内嵌 | 母项目侧栏 6 项仍全通；`W-00` 进入 React 工作台；报价/成本/台账/结算/工具 5 页无 JS 错误 |
| **P-W5** | 全局 AI 悬浮面板在 React 工作台内的可达性（D-7 成果不得因换前端而丢失）；母项目与工作台的导航关系定稿 | React 工作台内可唤起 AI 面板，行为与母项目一致；两端入口不冲突 |
| **P-W6** | `run.ps1` 编排：新增「工作台依赖安装/构建/启动」段，沿用「增值组件、故障只告警不阻断」范式 | 3456 被占用 / Node 不可用 / 构建失败 三种场景下主应用仍能拉起并给出告警；`tests/test_run_script.py` 全过 |
| **P-W7** | 全站回归与文档 | 6 视图 + 5 工具页 + React 工作台 8+1 页；四档断点无横向溢出；JS 错误 0；更新 `docs/STATE.md` |

**依赖次序**：P-W1 → P-W2 是硬前置；P-W3 与 P-W4 可并行；P-W6 依赖 P-W2 的构建产物路径确定；P-W7 最后。

## 8.6 待裁决（有推荐默认，未否决即按默认执行）

1. **待办存储归谁**：React 工作台用 lshu `todos` 表（Express 侧，含 evidence/plan 语义），而 P3-b 已把待办 Python 化到 `quote.db.wb_todos` 并通过 20/20 验收。
   *推荐默认*：**以 lshu `todos` 表为准**（因为要用 lshu Todos 页的全部功能）；`wb_todos` 与其 6 个端点**保留不删**，但 UI 不再使用；若你希望保留已收编链路，则需把 React Todos 页的数据源改指向 `/api/wb/todos`（改动在 vendored 副本内，成本中等）。
2. **天气归谁**：P3-a 已 Python 化 `weather/today`，而 React Home 页要调 Express 版。
   *推荐默认*：**React 侧直连 Express**；Python 实现保留（不删、不接入），作为已收编成果与回归参照。
3. **嵌入方式**：新标签跳转 / 同页 iframe / iframe + 隐藏内层 `AppShell` 侧栏。
   *推荐默认*：**同页 iframe + 隐藏内层侧栏**（维持「单一外层导航」，与 D-6 的单一事实源目标一致；代价是要改 vendored 的 `AppShell.tsx`）。
4. **lshu 数据落点**：当前实例把库写在 skill 安装目录内（`db.ts:19-20`，`run.ps1` 未设 `WORKBENCH_DATA_DIR`），skill 升级即可能被覆盖。
   *推荐默认*：**必须改到本项目**（如 `outputs/projects/<user>/.workbench/workbench.db`），通过 `WORKBENCH_DATA_DIR` 注入，不改源码。
5. **`lshu-workbench-v0.1.0/`（项目内上游副本）的 git 归属**：vendored 后是否存在两份副本、是否只留一份。

## 8.7 风险登记（本轮新增）

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| `npm install` 依赖 Node 版本 / 网络 | P-W2 可能直接卡住 | 已有 skill 目录 `node_modules` 可先复制；失败则降级为「直用 skill 目录实例」并告警 |
| vendored 副本与上游 lshu 分叉 | 上游升级无法合并 | vendored 后以本项目为准；升级靠人工比对 |
| 两个前端体系并存（React + 原生 JS） | 样式/令牌漂移、回归面变大 | P-W7 全站回归纳入两侧；`DESIGN.md` 颜色预算在两侧分别实测 |
| 旧工作台数据「有数据无 UI」 | 用户以为数据丢了 | UI 上明示迁移状态；`gc-workbench-v2` 保留可回滚 |
| 扫描页隐私面 | 真实遍历桌面并写库 | 见 §8.4-4；可随时否决该项 |

## 8.8 P-W2 实测结果（2026-10-06）

落地形态：`workbench-app/`（= lshu `frontend`）+ `workbench-server/`（= lshu `backend`），两者为**同级目录**，故 Express 的 SPA 目录解析仅需 1 处 patch。

| # | 事项 | 实测 | 判定 |
| --- | --- | --- | --- |
| 1 | vendored 复制 | `workbench-app` 75 文件 / 1.78MB（+ `node_modules` 96.6MB）；`workbench-server` 114 文件 / 935KB（+ `node_modules` 103.6MB）；均从 skill 目录 robocopy 复用依赖，**未联网 npm install** | **PASS** |
| 2 | 路径适配 | `workbench-server/src/index.ts:1210` 的 `frontendDist` 由 `../../frontend/dist` 改为 `../../workbench-app/dist`（唯一代码 patch） | **PASS** |
| 3 | 构建 | `npm run build`（`tsc -b && vite build`）成功：1099 modules，`dist/index.html` 0.43kB + `index-BuSlCPyq.js` 368.81kB + `index-DjyO_J6W.css` 70.31kB，耗时 276ms | **PASS** |
| 4 | 启动 | `node --import tsx src/index.ts` + `WORKBENCH_DATA_DIR=<项目>/outputs/workbench-data`；日志 `✅ L叔工作台后端已启动: http://127.0.0.1:3456` | **PASS** |
| 5 | 数据落点 | 新库建于 `outputs/workbench-data/workbench.db`（151KB，含 V3/V31 迁移备份）；skill 目录 `backend/data/` 未被写入（mtime 未变） | **PASS** |
| 6 | `/api/health` | 200 `{"ok":true,...,"sourceFingerprint":"dev-untracked"}` | **PASS** |
| 7 | `#/` 渲染 Home | `.shell` 存在、8 条内层导航、激活项 `今日H-01`、正文 337 字符 | **PASS** |
| 8 | 8 条路由逐条可达 | `/`、`/todos`、`/finance`、`/performance`、`/hotspots`、`/knowledge`、`/scan`、`/settings` 全部 `.shell` 渲染 + 激活项正确 | **PASS** |
| 9 | 控制台错误 | `pageerror` **0**、非网络类 `console.error` **0**；仅 4 条资源 503（finance 1 / knowledge 2 / settings 1），来源为 MoneyCats / Knowledge Base / DeepSeek 状态接口——即 §8.4-3 已声明的「缺凭证模块显示真实错误态」 | **PASS** |
| 10 | SPA 回退 | 无 hash 请求 `/` 返回 200 且含 `<div id="root">` | **PASS** |

**主动决策与例外**
1. 目录形态沿用 §8.3 的 `workbench-app/` + `workbench-server/`（而非改名成 `workbench/frontend|backend`）。代价是必须 patch 一行 `frontendDist`；收益是文档命名与结构清晰一致。已在本节登记该 patch。
2. `vite.config.ts` **未改**：`base` 默认 `/` 在「Express 同源服务根路径 + HashRouter」下本就正确；dev 代理默认目标 `http://localhost:3456` 也正是本项目后端。为遵守最小改动，不做无收益修改。
3. `workbench-server/dist/`（skill 侧预编译产物）**未复制**——`npm start` 已知是坏的（P1.4），改走 `tsx` 直跑源码；`workbench-server/data/`（skill 侧旧库）**未复制**，遵 D-4「数据从空开始」。
4. `.gitignore` 新增 `workbench-server/.env.local`、`workbench-server/data/`（凭证与运行期库不入库）。`node_modules/`、`dist/` 已被既有全局规则覆盖。
5. skill 目录原 :3456 实例（PID 40276）已停止，改用 vendored 实例；skill 目录文件与数据未改动。

## 8.9 P-W3 实测结果（2026-10-06）

落地形态：React 工作台新增 `/biz` 页，数据源为本项目 FastAPI（`:8000`）的 `/api/project/overview/list`。

**改动文件**（均在 vendored `workbench-app/` 内，母项目侧未动）
| 文件 | 改动 |
| --- | --- |
| `src/pages/Biz.tsx` | 新增（约 145 行）：4 指标卡 + 全量项目列表 |
| `src/App.tsx` | 新增 `/biz` 路由 |
| `src/components/AppShell.tsx` | 导航新增 `项目经营 M-01`（置于「今日」之后） |
| `src/components/icons.tsx` | 新增 `IconBriefcase`（与既有线性单色图标同规格） |
| `src/styles/global.css` | 新增 `.biz-row*` 样式块（复用 `.ui-row` / `.home-metric-grid` / `.home-core-metric` 既有基元，未引入新令牌） |

**口径对齐**：`yf()`（千分位 + 2 位小数、空值「—」）、`toNum()`、4 卡片（项目总数 / 投标中 / 在建中 / 总毛利合计，null 按 0 计入合计）、列表行（名称 + 阶段徽章 + `报价 <金额>` + 右对齐总毛利，负值着色）均逐条照搬母项目 `frontend/workbench.js` 的 `homeBizMetricsHTML` / `homeBizListHTML`。列表取全量（母项目 Home 模块只取前 5，前 5 行必然一致）。

**实测**（Playwright，`.trae/pw3-biz.mjs`，跑完已删除）：同一次运行内同时打开 React `:3456/#/biz` 与母项目 `:8080/index.html#workbench`，同一份 API 数据三方比对。

| # | 事项 | 实测 | 判定 |
| --- | --- | --- | --- |
| 1 | 页面标题 | `h1` = 项目经营 | **PASS** |
| 2 | 4 指标卡 | 项目总数 4 / 投标中 2 / 在建中 1 / 总毛利合计 0.00，与 API 现算值一致 | **PASS** |
| 3 | 项目列表 | 4 行（重启旅游学校配电项目·投标 / 金融城5号配电工程·中标在建 / 石船安置房项目·未中标 / 西永L公立学校项目·投标·报价 1,450,000.00） | **PASS** |
| 4 | 与母项目同源同数据比对 | 指标数组、列表数组与母项目 `#homeBizMetrics` / `#homeBizList` **逐项全等**（`JSON.stringify` 相等） | **PASS** |
| 5 | 导航与激活态 | 导航 9 项，含 `项目经营M-01`，激活项唯一且正确 | **PASS** |
| 6 | 错误面 | 无 `.ui-alert`、`pageerror` 0、非网络 `console.error` 0（跨源 `:3456 → :8000` 调用未被 CORS 拦截） | **PASS** |
| 7 | 构建 | `tsc -b && vite build` 通过（1100 modules，`index-DTTlYA_w.js` 372.38kB / `index-Bx4eO4WB.css` 70.73kB） | **PASS** |

**主动决策与例外**
1. **列表取全量而非前 5**：母项目 Home 的 M-01 模块只展示前 5 行，`/biz` 作为其「查看全部」的落点，展示全部项目。前 5 行与母项目逐项一致（实测第 4 项已覆盖）。
2. **本阶段为只读**：母项目 `workbench.js` 的 biz 还含「新建/编辑弹窗 + 五列看板」，P-W3 按计划只做「4 指标卡 + 项目列表」。**这构成 P-W4 的前置约束**——P-W4 若直接废除旧工作台，新建/编辑能力会一并消失。处理方式见 P-W4（继续保留母项目 biz 页可达，或在 React 侧补齐编辑能力），不在本阶段擅自扩大。
3. **图标去重**：`内容表现 C-03` 已占用 `IconChart`，新增 `IconBriefcase` 给 `项目经营 M-01`，避免侧栏出现两个同形图标。
4. **未重启 :3456**：Express 用 `express.static(frontendDist)` 在请求期读盘，`dist` 重建后无需重启（实测第 1–7 项即在新产物上取得）。

## 8.10 P-W4 实测结果（2026-10-06）

落地形态：母项目 `#workbenchView` 由「原生 JS 渲染的旧工作台」改为「同页 iframe 宿主」，指向 React 版工作台（`http://127.0.0.1:3456/`）；旧工作台唯一被保留的功能区（项目经营）已在 React `/biz` 完整重建，故 `frontend/workbench.js` 与 `frontend/workbench.css` 整体退役。

### 决策：§8.9 例外 2 的二选一取 **(b) 在 React 侧补齐编辑能力**

| 方案 | 取舍 | 结论 |
| --- | --- | --- |
| (a) 母项目 biz 页保留可达 | 需在已废除的旧壳里留一条活路径 → 两份工作台长期并存；`workbench.js` 无法退役 | **否决** |
| (b) React `/biz` 补齐 | 一次性把「4 指标卡 + 项目列表」升级为「4 指标卡 + 五列看板 + 搜索 + 每列排序 + 新建/编辑/删除弹窗」 | **采用** |

采用 (b) 的依据：用户指令为「把我以前的基本废除，**除了项目经营留下**」——「留下」指功能存续而非旧实现存续；且 (a) 与 D-6「单一外层导航」目标直接冲突。

### 改动文件

**React 侧（vendored `workbench-app/`）**

| 文件 | 改动 |
| --- | --- |
| `src/pages/Biz.tsx` | 重写：新增五列看板（投标/中标在建/已竣工/已结算/售后）+「未中标」折叠归档、搜索、每列排序、卡片堆叠、新建/编辑弹窗（11 字段 + 3 派生实时预览 + 删除） |
| `src/components/icons.tsx` | 新增 `IconPlus` / `IconSearch`（与既有线性单色图标同规格） |
| `src/styles/global.css` | 新增 `.biz-cols` / `.biz-card` / `.biz-tab` / `.biz-modal` / `.biz-fld` / `.biz-derived` 等约 400 行；断点 1280（5→3 列）、768（→1 列 + 弹窗单列）、560（工具条换行） |

**母项目侧（`frontend/`）**

| 文件 | 改动 |
| --- | --- |
| `index.html` | `#workbenchView` 改为 iframe 宿主；移除 `workbench.css` 与 `workbench.js` 引用；`styles.css` 版本号 `v2h→v2i`、`app.js` `ag7→ag8` |
| `styles.css` | `.workbench-view .wb-frame` 高度与 ≤560 档位 |
| `app.js` | 新增 `WB_ORIGIN` / `mountWorkbenchFrame()`（首次显示才设 iframe src，避免打开报价页即拉起工作台服务）；删除已失效的 `window.__wbResurface()` 调用 |
| `workbench.js`、`workbench.css` | **删除**（整份退役；备份见 §8.1） |
| `workbench.html` | 仅更新过期注释（行为不变，仍 `location.replace('index.html#workbench')`） |
| `tools.css` | 仅修正注释中已不存在的 `workbench.css` 引用 |

### 实测（Playwright，`.trae/pw4-verify.mjs` + `.trae/pw4-responsive.mjs`，跑完已删除）

| # | 事项 | 实测 | 判定 |
| --- | --- | --- | --- |
| 1 | `W-00` 进入 React 工作台 | `#workbenchView` 显示后 iframe `src=http://127.0.0.1:3456/`；iframe 内 `h1=今日状态`、内层导航 9 项 | **PASS** |
| 2 | iframe 只挂载一次 | 切到 cost 再切回 workbench，`src` 前后相同 | **PASS** |
| 3 | 母项目侧栏仍全通 | `quote/cost/ledger/settlement` 逐项点击 → hash 落 `#quote/#cost/#ledger/#settlement`，且 `#quoteView`/`#moduleView`/`#workbenchView` 显示互斥正确 | **PASS** |
| 4 | 5 个工具页 | `tools/tool-well/tool-earth/tool-duct/tool-cable` 侧栏均 7 项、JS 错误 0 | **PASS** |
| 5 | 母项目 JS 错误 | `pageerror` 0、非网络 `console.error` 0 | **PASS** |
| 6 | `/biz` 指标卡 | 项目总数 4 / 投标中 2 / 在建中 1 / 总毛利合计 0.00（与 API 现算一致） | **PASS** |
| 7 | `/biz` 五列看板 | 列 = 投标/中标在建/已竣工/已结算/售后；列内卡片 3；归档 = 未中标归档（1） | **PASS** |
| 8 | 搜索 | 输入「西永」后可见卡片 1（搜索前首列 2） | **PASS** |
| 9 | 每列排序 | 首列切「报价金额」→ 标签序 `[旅游学校, 西永L]`（无金额按 0 排前，符合升序） | **PASS** |
| 10 | 编辑弹窗 | 点卡片 → 标题「编辑项目」、名称预填「重启旅游学校配电项目」、派生三项初始「—」 | **PASS** |
| 11 | 派生实时重算 | 改「投标报价金额 1,000,000 / 投标成本测算 800,000」→ 派生变 `200,000.00 / 20.00% / —`（与 `deriveProj` 公式一致） | **PASS** |
| 12 | 弹窗关闭 | Escape → 弹窗消失；再次打开无残留 | **PASS** |
| 13 | 新建弹窗 | 标题「新建项目」且**无**删除按钮；取消后弹窗消失 | **PASS** |
| 14 | `/biz` JS 错误 | `pageerror` 0、非网络 `console.error` 0 | **PASS** |
| 15 | 四档断点无横向溢出 | 1440/1280/1024/768/560 下，`mother#workbench` 与 `react#/biz` 的 `scrollWidth-clientWidth` 全为 0；看板列数 5→3（≤1280）→1（≤768）符合预期 | **PASS** |
| 16 | 构建 | `tsc -b && vite build` 通过（1100 modules，`index-D3ZHW-rQ.js` 382.31kB / `index-BCG56zlh.css` 76.33kB） | **PASS** |

### 主动决策与例外

1. **导航本轮仍不合并（沿用 P-W4 既定例外）**：母项目外层侧栏（7 项）与 React `AppShell` 内层侧栏（9 项）在 iframe 下同时可见。§8.6-3「隐藏内层侧栏」**继续推迟到 P-W5**——外层 7 项不含 lshu 的 8 个页面，此刻隐藏内层即功能不可达。
2. **嵌入方式取「同页 iframe」，本轮不隐藏内层侧栏**：之所以不用整页跳转，是为了保住「母项目侧栏全通」——跳转会让母项目导航整体消失。
3. **不移植的两处视觉细节（已在此显式登记，非静默丢弃）**：
   - 阶段色点由「实心 + 灰阶」改为「实心 + 描边」——lshu 设计系统只有四色（`global.css` 内 `border-radius` 全为 0、无任何灰阶令牌），引入灰阶会破坏颜色预算；
   - 阶段色点由圆形改为方形（`8×8`），与「全域直角」一致。
   两者均不损失信息：列头始终紧邻阶段名文字，卡片标签也带阶段文字。
4. **`workbench.js` / `workbench.css` 整体删除**：删除前已 grep 确认除 `index.html` 外无任何引用（`.js` 侧仅 `app.js` 的 `window.__wbResurface` 一处，已同步移除）；`gc-workbench-v2` 既未读取也未改动，符合红线 7。
5. **`workbench.html` 保留**：它是无导航引用的历史入口，行为等价于 `index.html#workbench`，删除只会让旧书签 404。
6. **iframe 不做存活探测**：`:3456` 的 CORS 白名单不含 `:8080`，从母项目发 `fetch` 健康检查即便服务在线也会被拦；iframe 加载本身不受 CORS 限制，故直接设 `src`，不引入不可靠的「错误页检测」。
7. **本阶段未做真实写库验证**：新建/编辑/删除的实测仅到「弹窗打开、字段预填、派生重算、关闭」，**未提交任何 POST**，以免污染 `quote.db` 中的业务数据。写入路径（`/api/project/overview/save|delete`）本身未改动，母项目原实现即调用同一对端点。

## 8.11 P-W5 实测结果（2026-10-06）

**本阶段零代码改动**，只做取证与裁决；临时脚本 `.trae/pw5-verify.mjs`、`.trae/pw5-probe2.mjs` 跑完即删。

### 一、D-7 全局 AI 悬浮面板在 iframe 工作台之上是否仍可达 → **可达**

先查证后动手：`frontend/agent-panel.js` 在运行时把 FAB/面板/设置抽屉注入 `<body>`；`.agent-fab` 为 `position:fixed; z-index:var(--z-floating)`＝50，`.agent-panel` 为 51，而 `.wb-frame` 无 `z-index`、祖先亦无 `transform/filter/isolation`（`.main-content` 的 `overflow` 实测为 `visible`），故二者同处根层叠上下文，面板必然压在 iframe 之上。实测复核（视口 1440×900）：

| 元素 | 父页坐标 | 说明 |
| --- | --- | --- |
| `.wb-frame` | x 280–1408，y 24–820 | `height:calc(100vh - 104px)`＝796 |
| `#agentFab` | x 1360–1408，y 828–876 | 落在 iframe 下沿之外的页脚留白，**不与 iframe 重叠** |
| `#agentPanel` | x 1008–1408，y 196–816 | **完全落在 iframe 矩形之内** |

父页上下文执行 `document.elementFromPoint` 命中测试：

| 取样点 | 期望 | 实测 | 判定 |
| --- | --- | --- | --- |
| (500,500)（iframe 内、无面板覆盖）| iframe | `div>main>#workbenchView>iframe` | 控制组成立 |
| FAB 中心 | FAB | `#agentPanelRoot>#agentFab>svg` | **PASS** |
| 面板内（中心 x，顶 +30）| 面板 | `#agentPanelRoot>#agentPanel>header>#agentStatusPill>#agentModelText` | **PASS：面板盖在 iframe 上** |

其余实测（共 17 项，除上表 3 项外）：`W-00` 进入工作台且 iframe 内 `h1=今日状态`；FAB 固定定位 `z=50`；点击 FAB 面板可见；面板内 `textarea` 可聚焦、可输入、回读值一致；Esc 收起；外层侧栏 `AI 测算助手`（`data-agent-open`）可唤起面板；面板开合不影响外层导航切视图（实测落到 `#quote`）；报价视图对照组 FAB 可见且命中 FAB；外层导航 7 项、内层导航 9 项；母项目 `pageerror` 0、非网络 `console.error` 0。

**结论**：D-7 成果未因换前端而丢失。React 工作台内**不新增第二个 AI 入口**——面板是父页的全局浮层，已浮在工作台视图之上（外层侧栏项与 FAB 两个入口均已实测可达），再加深一层入口即为重复实现。

### 二、两端导航关系定稿：**不合并，各自守单一事实源**

| | 外层（母项目壳） | 内层（React 工作台） |
| --- | --- | --- |
| 事实源 | `frontend/js/sidebar.js` 的 `NAV_GROUPS` | `workbench-app/src/components/AppShell.tsx` 的 `navItems` |
| 项数 | 7：个人工作台 / 投标报价 / 实施成本 / AI 测算助手 / 项目台账 / 结算管理 / 速算工具箱 | 9：今日 / 项目经营 / 待办 / 财务分析 / 内容表现 / 热点雷达 / 知识大脑 / 扫描报告 / 设置 |
| 覆盖面 | 母项目 4 视图 + 5 工具页 + 全局 AI 入口 | lshu 自己的 9 页 |
| 渲染位置 | 静态列 x 0–248 | iframe 内 x 280–504（父页坐标） |

**裁决：维持双导航并排；§8.6-3「隐藏内层侧栏」正式关闭。** 三条依据：

1. **隐藏内层 ⇒ lshu 的 8 页不可达**：外层 7 项不含今日/待办/财务分析/内容表现/热点雷达/知识大脑/扫描报告/设置。
2. **把 8 页搬进外层 ⇒ 重新制造「导航两份」**：外层若枚举 lshu 页，React 的 `AppShell` 依然必须保留（它是 lshu 的应用壳），同一批导航立刻出现两份事实源——正是用户第 1 条诉求要修的缺陷。要让外层侧栏真正取代内层，前提是把母项目 4 视图也搬进 React，属 D-5 已否决的大范围改造。
3. **隐藏外层 ⇒ 母项目不可达**：报价/成本/台账/结算/工具/全局 AI 全在 iframe 之外。

边界规则定稿：**外层侧栏＝母项目壳的唯一导航；内层 `AppShell`＝工作台（lshu）的唯一导航；两者互不引用、互不复刻。**

本裁决同时**关闭用户原始诉求第 1 条**（母项目侧栏曾被维护两份）：早前 `index.html` 内联静态侧栏与 `js/sidebar.js` 各存一份，已在 commit `ba554d4` 收敛为 `sidebar.js` 单一事实源；本轮复核 6 个页面（`index.html` + `tools.html` + 4 个 `tool-*.html`）均为空 `#sidebarSlot` 占位并统一引用 `sidebar.js?v=2026-10-06-nav2`，无第二份拷贝。

### 三、已登记后果（非缺陷）

1. **iframe 宽度即 React 的 `100vw`**：React 内部断点按 **iframe 宽**（1440 视口下 1128px）而非浏览器宽触发——1280 视口下 iframe≈968px，React 的 1024 档会提前生效。P-W4 第 15 项已在 1440/1280/1024/768/560 五档实测无横向溢出。
2. **双导航并排占用横向空间**：外层 248px + 内层 224px＝472px，工作台视图的内容可用宽比全屏少约 33%。

### 主动决策与例外

1. **不改造、只取证**：P-W5 的①在动手前先做了层级与 `elementFromPoint` 查证，结论是「本来就成立」，因此未修改 `agent-panel.js` / `agent.css` / `app.js` 任何一行。
2. **未对外层 `W-00` 与内层 `H-01` 的语义重叠做处理**：两者都指向工作台首页（外层标签「个人工作台」、内层标签「今日」）。是否把外层 `W-00` 改名为「工作台首页」以消歧，登记为待裁决。
3. **未新增回归测试文件**：双导航的「单一事实源」约束本轮以复核取证（grep 全站 6 页 + 运行时计数 7/9）落实，未引入断言脚本；待 P-W7 全站回归时一并复核。

## 8.12 P-W6 实测结果（2026-10-06）

落地形态：`run.ps1` 的工作台段从「读 skill 安装目录」改为「读仓库内 vendored 目录」，并补齐**依赖安装 → 前端构建 → 启动**三步；全部按增值组件处理（只告警、不阻断主应用）。

### 改动文件（唯一文件：`run.ps1`）

| 位置 | 改动 |
| --- | --- |
| 头部注释 | 第 2–4 行与设计要点新增第 10 条：说明代码为仓库内 vendored、本段三段职责、`dist` 由 Express 请求期读盘故重建无需重启 |
| 变量段 | `$WbAppDir` 由 `BIDPRICING_WORKBENCH_DIR`／skill 路径改为 `$Root\workbench-app`；`$WbBackendDir` 改为 `$Root\workbench-server`（不再有 `backend` 子目录）；新增 `$WbDist`、`$WbDataDir` |
| 启动段 | 新增 `Invoke-WbNpm` 包装；前后端依赖缺失时各自 `npm install`；`dist` 缺失时 `npm run build`；`$wbOk` 逐级短路 |
| 环境变量 | 启动前新增 `$env:WORKBENCH_DATA_DIR = outputs\workbench-data`（此前只设 `WORKBENCH_UPSTREAM`，库会落到包内 `data/`）；`PORT` 与 `WORKBENCH_DATA_DIR` 用后立即 Remove |
| 删除 | 读 `VERSION` 设 `WORKBENCH_SOURCE_FINGERPRINT` 的死分支（vendored 目录无 `VERSION`，条件恒假） |
| 成功横幅 | 文案由「前端经 `/api/wb` 反代」改为「母项目 `#workbench` 以 iframe 嵌入本地址」（与 P-W4 实际实现一致） |

### 三场景实测

用真实 `run.ps1` 运行（主应用端口换到 18xxx，避免撞上正在运行的服务），跑完即杀进程并复核端口无残留：

| # | 场景 | 制造方式 | 实测输出 | 判定 |
| --- | --- | --- | --- | --- |
| 1 | 3456 被占用 | 直接运行（3456 有在跑实例） | `[WARN] :3456/api/health 已有人应答，但本拉起的工作台进程已退出——复用在跑的实例（Ctrl+C 时不会停它）`；成功横幅照常打印 frontend/backend 两行 | **PASS** |
| 2 | Node 不可用 | 从 `PATH` 摘掉 node 安装目录 | `[WARN] node 不可用，跳过个人工作台（不影响主应用）`；成功横幅照常 | **PASS** |
| 3 | 构建失败 | 临时移走 `workbench-app/dist` + PATH 前置一个 `exit /b 1` 的假 `npm.cmd` | `==> workbench: 构建前端产物（npm run build）...` → `[WARN] 工作台前端构建 失败，跳过个人工作台（不影响主应用）` → `[WARN] 工作台前端产物不可用（…\workbench-app\dist），跳过个人工作台`；无工作台启动，成功横幅照常 | **PASS** |

三场景共同点：主应用（backend/frontend）都是在**真实探活 200** 之后才打印成功横幅——不是「假成功」。

### 静态判据

`powershell` 的 `Parser::ParseFile` → 0 错（3174 tokens）；`python -m pytest tests/test_run_script.py -q` → **19 passed, 5 subtests passed**。

### 主动决策与例外

1. **构建仅在 `dist` 缺失时触发**：vite 全量构建慢，且 Express 请求期读盘、重建无需重启，故不做「每次启动都重建」；改过 `workbench-app/src` 后需自行 `npm run build`（已写进注释）。
2. **依赖装不上／缺 `tsx`／构建失败 ⇒ 跳过整个工作台**，而不是启动「只有 API 的半个实例」：与 agent-service 的「故障只告警跳过」范式一致——半个实例只会让 iframe 显示 404，比明确跳过更难排查。
3. **删除 `BIDPRICING_WORKBENCH_DIR` 覆盖口**：它原先用于指向 skill 安装目录；vendored 后目录是仓库内固定路径，留着它等于留一个能指回 skill 的后门，与「收编」目标相悖。端口覆盖口 `BIDPRICING_WORKBENCH_PORT` 保留。
4. **未新增测试用例**：既有 19 条静态判据全过，但本轮未为工作台段补新判据（例如「该段不得出现 `exit 1`」）；登记为可选加固项，不擅自扩大范围。
5. **临时物已清理并复核**：假 `npm.cmd` 与 `.trae\fakenpm\` 已删；`workbench-app/dist` 已改名复位（`dist\index.html` 存在、`:3456/` 实测 200）；测试端口 18000/18010/18020/18080/18081/18090 均无监听残留。

## 8.13 P-W7 实测结果（2026-10-06）

**改了什么**：源码零改动。唯一产出是重新生成 `docs/STATE.md`（该文件是 `status --write` 的生成物，禁止手写）：

```
PYTHONPATH=src python -m bidpricing.cli status --write
→ 提交 ba554d4 ｜ 测试 1612 项，未通过 ｜ 闸门 Gate 0a=PASS Gate 0b=BLOCKED ｜ 工作区 30 处未提交改动
```

### 覆盖矩阵与结果

19 个页面 × 5 档宽度（1440 基准 + 1280/1024/768/560 四档断点）= **95 次加载**，Playwright 无痕上下文逐次新建：

| 组 | 页面 | goto 失败 | pageerror | 横向溢出（5 档全为 0） |
| --- | --- | --- | --- | --- |
| 母项目视图 | `index.html#workbench` `#quote` `#cost` `#ledger` `#settlement` | 0 | **0** | 0 |
| 母项目工具 | `tools.html` `tool-well` `tool-earth` `tool-duct` `tool-cable` | 0 | **0** | 0 |
| React 工作台 | `:3456/#/` `#/biz` `#/todos` `#/finance` `#/performance` `#/hotspots` `#/knowledge` `#/scan` `#/settings` | 0 | **0** | 0 |

**横向溢出判据**：`max(documentElement.scrollWidth, body.scrollWidth) − max(clientWidth)`，19×5 = 95 组**全部为 0**（非「小于阈值」，是严格 0）。无任何元素 `getBoundingClientRect().right > innerWidth`。

### 内容回填健全性（防「空白页也无错误」的假 PASS）

| 判据 | 实测 |
| --- | --- |
| 外层导航项数 | 母项目页 **7**（`NAV_GROUPS` 7 项）；React 页 **9**（`AppShell` 9 项）——与 §8.11 定稿一致 |
| 视图可见性随 hash 正确切换 | `#workbench`→`workbenchView`；`#quote`→`quoteView`；`#cost/ledger/settlement`→`moduleView`（其余 hidden） |
| iframe 宿主存在 | index 各视图 `iframe` 数 = **1** |
| 正文非空 | 各页 `innerText` 去空白后 138–2102 字符，无 0 字符页 |

### 4 条资源加载失败的定性（全部非缺陷）

| 页面 | 失败 | 定性 |
| --- | --- | --- |
| `#/finance` | `HTTP503 /api/finance/overview` | **设计内降级**：`financeService.ts:338` → `FINANCE_DATA_UNAVAILABLE`「财务数据尚不可用，请先更新账本」（MoneyCats 未配置，用户已裁决「凭证照搬，缺就缺」） |
| `#/knowledge` | `HTTP503 /api/knowledge/status`、`/documents` | **设计内降级**：`knowledgeClient.ts` → `KNOWLEDGE_SERVICE_OFFLINE`（本地知识库 `:8765` 未启动）；页面仍渲染 412 字符 |
| `#/settings` | `HTTP503 /api/knowledge/status` | 同上 |
| `#quote` | `net::ERR_NO_BUFFER_SPACE` | **不可复现**：定向重跑 10/10 无命中，且 `requestfailed` 从未触发该 URL；判定为 headless Chromium 缓存写入瞬时失败，与页面无关 |

### 单元测试的 4 项未通过（与本次集成无交集，未修）

`src/` 与 `tests/` 下 Python 文件在本轮（P-W1…P-W7）**均无改动**（`git status` 可证），故这 4 项不是本次引入：

| 项 | 测试 | 根因 |
| --- | --- | --- |
| ERROR ×1 | `test_solver_backend.TestRegistryAndCapability.test_bb01_blocks_when_active_not_declared` | `pulp` 写 `%TEMP%` 被拒：`PermissionError: [Errno 13] Permission denied: 'C:\Users\leema\AppData\Local\Temp\<uuid>-pulp.mps'` |
| FAIL ×3 | `test_io_boq.RealFileSmokeTest.test_code_kind_distribution` / `test_row_count_and_key_agreement`、`test_io_clean.CleanListingTest.test_real_file_smoke` | 依赖「真实案件示例」xlsx 的冒烟测试；与 2026-09-24 快照记录的 `failures=3` 同族 |

**环境缺陷（本轮发现，登记在案、未修，也不在本轮范围内）**：`python.exe` 无法写入 `C:\Users\leema\AppData\Local\Temp`（PowerShell 可写，直连绝对路径写入即 `PermissionError`）。其连带效应有两个，都已取证：

1. `tempfile.gettempdir()` 候选目录全部被拒后**回落到 cwd**，于是依赖临时文件的代码把产物写进了仓库根——实测出现 `tmp4bt3ui33`、`tmpqv5sk8m8`、`tmpr7s8ohw2`（各 6 字节，内容 `report`），**已删除**；
2. `pulp` 因 `create_tmp_files` 写 `%TEMP%` 失败而抛 ERROR。

### 主动决策与例外

1. **`docs/STATE.md` 用 CLI 重新生成，未手写一行**：该文件头自带「请勿手工编辑」声明，手改必然在下次改动后过期。
2. **不修 4 项单元测试失败**：它们落在求解层与真实文件冒烟上，超出「工作台集成」范围；且其中 1 项根因是机器级 `%TEMP%` 权限，改代码无法解决。按用户规则登记风险而非静默带过。
3. **不把 `%TEMP%` 权限问题当成本轮缺陷**：先做了「PowerShell 可写 / python 直连写入被拒」的对照实验，再判定为环境问题；未擅自改机器 ACL 或安全软件设置。
4. **临时脚本已删**：`.trae\pw7-regress.mjs`、`pw7-probe2.mjs`、`pw7-retry.mjs` 及两份中间 JSON 已删除，`.trae\` 只剩 `documents\`。
5. **未新增回归脚本到仓库**：P-W7 的验收方式是「一次性取证」，与 §8.5「实测一律 Playwright（`.trae\*.mjs`，用完删除）」一致；若日后要长期守护，建议另行立项做成 `tests/` 下的常驻用例，不在本轮擅自扩大范围。

---

# 9. P-W8 导航单栏化（用户裁决于 2026-10-06，取代 §8.11 的双导航定稿）

## 9.1 用户原始反馈与裁决

> 「两个导航栏也太奇怪了吧」

复核确认这不是审美偏好，而是**结构缺陷**：§8.11 定稿的双导航是**两条全高竖向导航并排**，各带自己的品牌块（`工程智算` / `L叔的工作台`）与页脚，横向合计 **248 + 224 = 472px**，视觉上读作「两个并列的一级导航」，而非「一级 + 二级」。§8.11 当时否决「隐藏内层」的理由（「lshu 8 页不可达」）只针对「直接隐藏」，未考虑**换成另一种形态**。

**用户裁决**：选「侧栏单栏化：9 页并入外层作二级折叠」。

## 9.2 目标形态

```
┌──────────────┬─────────────────────────────────────────┐
│ 工程智算      │                                          │
│              │   ┌──────────────────────────────────┐   │
│ 工作台        │   │  iframe :3456（AppShell 不再渲染  │   │
│  ▾ 个人工作台 │   │   侧栏，只渲染 <main>）           │   │
│     今日 H-01 │   │                                  │   │
│     项目经营  │   │                                  │   │
│     待办      │   │                                  │   │
│     …共 9 项  │   │                                  │   │
│ 核心功能      │   │                                  │   │
│  投标报价     │   └──────────────────────────────────┘   │
│  …           │                                          │
└──────────────┴─────────────────────────────────────────┘
   一条竖栏（一级模块 + 工作台二级折叠）＝ 单一导航
```

## 9.3 关键设计（先定这三条，否则必然返工）

### 9.3-1 事实源归属（直接对应你第 1 条要求「导航不要维护两份」）

| 内容 | 唯一事实源 | 说明 |
| --- | --- | --- |
| 工作台 9 页的 `label / code / icon / to` | **`frontend/js/workbench-nav.js`**（新增） | 无构建、纯静态，`sidebar.js` 直接消费；`AppShell` 内嵌时**不渲染任何导航**，故零清单 |
| 工作台 9 页的**路由存在性** | `workbench-app/src/App.tsx` 的 `<Route>` | 这是「页面存在」的事实源，与清单的 `to` 必须集合相等 |
| 母项目 6 模块 | `frontend/js/sidebar.js` 的 `NAV_GROUPS`（维持现状） | 已收敛，不动 |

**防漂移守卫**：新增 `tests/test_workbench_nav.py`，静态比对 `frontend/js/workbench-nav.js` 的 `to` 集合与 `App.tsx` 的 `<Route path>` 集合**相等**（不比对文案/图标）。这样「两份清单」中重复的只是文案与图标，**路径层面的漂移被机器挡住**。

**独立访问 `:3456/#/todos` 的兜底**：`AppShell` 在**未内嵌**（`window.self === window.top`）时仍渲染自带侧栏，作为开发兜底；该清单在注释与文档中显式标注「**非事实源，仅独立访问使用**」。登记残留风险：文案/图标可能与外层漂移（路径由守卫测试兜住）。

### 9.3-2 跨源通信协议（iframe 跨源，父 :8080 / 子 :3456）

| 方向 | 消息 | 触发 | 安全要求 |
| --- | --- | --- | --- |
| 子 → 父 | `{__wb:'ready'}` | React 挂载完成 | 父须 `event.origin === WB_ORIGIN` 且 `event.source === frame.contentWindow` |
| 子 → 父 | `{__wb:'route', to:'/todos'}` | 每次路由变化（含首次） | 同上；`to` 由父按白名单过滤后才用于高亮 |
| 父 → 子 | `{__wb:'nav', to:'/todos'}` | 点击二级项 | `targetOrigin` 必须是 `WB_ORIGIN`，**禁止用 `'*'`**；子侧校验 `event.source === window.parent` 且 `to` 在白名单内 |

**竞态处理**：父侧维护 `pendingWbNav`。iframe 未 `ready` 前的导航请求入队，收到 `ready` 后 flush。无此握手会表现为「刷新后停在首页」——这是本方案最容易出的 bug。

### 9.3-3 父 URL 语义扩展

- `#workbench` → 工作台（子页为 `/`）；`#workbench/todos` → 工作台 + 待办子页。
- **必须同改两处**：`app.js` 的 `hashchange` 处理器与 `initDashboard` 的 hash 解析。此前已因「两处兜底值不一致」踩过坑（§8.5 记录），本次强制同改。
- 兜底值仍为 `'workbench'`（与 `sidebar.js` 的 `currentModule` 一致），不新增第三处常量。

## 9.4 分阶段与验收标准

| 阶段 | 事项 | 验收标准 |
| --- | --- | --- |
| **P-W8-1** | 备份（`outputs/backups/pw8-<ts>/` 含 5 个待改文件 + 还原说明）+ 新建 `frontend/js/workbench-nav.js` + 漂移守卫测试 | 备份可还原；`pytest tests/test_workbench_nav.py` 通过 |
| **P-W8-2** | 外层侧栏二级折叠 UI（`sidebar.js`）+ 展开态 `localStorage` + 父 hash 语义扩展（`app.js` 两处 + `index.html` 版本号） | 侧栏 7→16 项且层级可辨；点二级项父 hash 变 `#workbench/<sub>`；四档断点无横向溢出 |
| **P-W8-3** | React 侧内嵌模式：`AppShell` 隐藏自带侧栏 + `useLocation` 路由上报 + `nav` 消息监听；`vite build` | 内嵌时 iframe 内 `aside.sidebar` 数量 **0**；双向高亮跟随；9 条路由逐条可达 |
| **P-W8-4** | 全站回归取证 + 计划落账 §9.5 | 见下方「反作弊判据」 |

**反作弊判据（P-W8-4 必须逐条过，不许只测首页）**：
1. 页面竖栏总数 **= 1**（iframe 内 `aside.sidebar` 为 0）；
2. 外层 9 个二级项**逐项**点击 → iframe 路由、外层高亮、父 hash 三者同时正确（9/9）；
3. 刷新 `#workbench/todos` 仍停在待办（验证 ready 握手队列有效）；
4. 反向通道：在 iframe 内改路由 → 外层高亮跟随；
5. 五档宽度（1440/1280/1024/768/560）横向溢出 = 0；`pageerror` = 0；
6. `:3456/#/todos` 独立访问仍可用。

## 9.5 P-W8 实测结果

取证方式：Playwright 一次性脚本（`.trae\pw8-4-regress.mjs`），跑完即删；`:8080` 静态前端、`:3456` 工作台、`vite build` 产物均由同一 Express/静态进程按请求读盘提供。

**六条反作弊判据（逐条）**

| # | 判据 | 实测 | 结论 |
| --- | --- | --- | --- |
| 1 | 页面竖栏总数 = 1 | 外层 `.sidebar` 1 + iframe 内 `aside.sidebar` 0 | PASS |
| 2 | 9 个二级项逐项点击，iframe 路由 / 外层高亮 / 父 hash 三者同时正确 | **9 / 9**（`/`→`#workbench`、`/biz`→`#workbench/biz`、…、`/settings`→`#workbench/settings`） | PASS |
| 3 | 刷新 `#workbench/todos` 仍停在待办 | 深链刷新后 iframe 停在 `#/todos` | PASS |
| 4 | 反向通道：iframe 内改路由 → 外层高亮跟随 | iframe 内改到 `#/scan` → 外层 hash `#workbench/scan` 且高亮 `/scan` | PASS |
| 5 | 五档宽度（1440/1280/1024/768/560）横向溢出 = 0；`pageerror` = 0 | 母项目 **90 次加载**（9 页 × 5 档 + 9 条二级路由 × 5 档）溢出全 0、错误全 0；工作台独立页 **45 次加载**（9 页 × 5 档）溢出全 0、错误全 0 | PASS |
| 6 | `:3456/#/todos` 独立访问仍可用 | 自带侧栏 1 个 / 9 项，点第 6 项跳 `#/hotspots`，无错误 | PASS |

**补充取证**

- 工具页二级项跨页跳转：`tools.html` 点「热点雷达」→ `index.html#workbench/hotspots`，无错误。
- 折叠态持久化：折叠父行后 `localStorage.gc_wb_nav_open='0'`，刷新（`#quote`）仍收起。
- 漂移守卫：`pytest tests/test_workbench_nav.py -q` → 4 passed；解析出 nav 9 条 / `App.tsx` 路由 9 条、集合相等。**反向对照**（从 `App.tsx` 文本删掉 `/scan` 路由）判据能被击落 → 有区分力。
- 回归：`pytest tests/test_workbench_nav.py tests/test_run_script.py tests/test_deployment.py -q` → 33 passed + 5 subtests。

**主动决策与例外（4 条）**

1. **阶段边界调整**：父侧 `postMessage` 通信（`ready` 握手 + `pendingWbNav` 队列 + 双向校验）与 P-W8-2 一并实施（它本就住在 `app.js`），使 P-W8-2 结束时不是「点了二级项 iframe 不动」的破态；P-W8-3 因此只剩 React 侧。
2. **父行不承担跳转**：点「个人工作台」只展开/收起，跳转交给二级项——一个控件不承担两个动作。代价：「个人工作台」根页需两步（展开 → 今日）；若日后认为代价偏高，可改为「父行同时负责跳根页 + 独立 chevron 控件负责折叠」，但不建议再引入第二控件。
3. **子页不上报初始路由**：内嵌时首帧不上报 `route`，否则会把初始 `/` 报给父侧、抢跑掉父侧深链意图。父侧对「意外的初始上报」有自愈能力（最终仍会收敛到子页真实路由），此条属减少无谓抖动，不是正确性必需。
4. **侧栏纵向滚动新增 226px**：1440×900 下 `nav-scroll` 内容比可视区高 226px（原 7 项时不溢出）。已把二级行压紧（`padding 7px`、`margin-bottom 4px`）部分抵消；残余按 §9.6 风险 6 由既有 `nav-scroll` 承担，未擅自动 `.nav-group` 间距等全局样式。

**残留（已登记，未处理）**：二级项文案/图标与 React 兜底清单仍可能漂移（路径由测试守）；`workbench-standalone.css` 为孤儿样式——**已于 2026-10-06 删除**（见 CHANGELOG；§9.7-2 的这一条据此关闭）。

## 9.6 风险登记（本轮新增）

| # | 风险 | 后果 | 缓解 |
| --- | --- | --- | --- |
| 1 | postMessage 竞态（未 ready 先导航） | 刷新后停在首页，且**偶发**难以复现 | ready 握手 + 父侧 pending 队列；判据 3 专门测它 |
| 2 | `targetOrigin` 用 `'*'` 或父侧不校验 `origin` | 任意同浏览器页面可驱动工作台路由（安全缺陷） | 双向都校验；`'*'` 列为禁令 |
| 3 | 父 hash 两处解析不一致 | 「首次加载」与「运行中改 hash」落到不同页面 | 强制同改；判据 3 覆盖 |
| 4 | 二级项文案/图标与 React 兜底清单漂移 | 轻微不一致 | `to` 集合由测试守；文案登记为已知残留 |
| 5 | 改的是 vendored `AppShell.tsx` | 日后重新 vendored 上游会覆盖 | 登记进「上游同步需重做」清单 |
| 6 | 侧栏 16 项在 560 宽度超一屏 | 需滚动/遮挡 | 复用既有 `nav-scroll`；窄屏二级默认收起 |

## 9.7 需在实施中先确认的事实（勿凭记忆）

1. 侧栏样式主体落在 `frontend/styles.css`（`tools.css`、`workbench-standalone.css` 也命中 `.nav-item`/`.sidebar`，需确认各自适用范围，避免改错文件）。
   **已确认（P-W8 实施中）**：6 个 HTML 全部加载 `styles.css`，侧栏样式主体确在 `frontend/styles.css`（`.sidebar` 30 行、`.nav-item` 56 行、≤768px 抽屉式 406–428 行、像素字体区块 499 行起）。`tools.css` 仅有一处 `@media print` 内的 `.sidebar{display:none!important}`（不影响屏幕）。故 P-W8 的侧栏改动只落在 `styles.css`。
2. `frontend/workbench-standalone.css` 在原 `workbench.html` 的 JS（`workbench.js`）被删除后是否已成孤儿样式——若是，本轮**不顺手删**，另行登记。
   **已确认（P-W8 实施中）**：无任何 HTML 引用该文件，且其命中的是旧 `workbench.html` 的 DOM（`.sidebar .brand .ava img`、`.sidebar .nav`、`.sidebar.open`），与现侧栏 DOM 不匹配 ⇒ **孤儿样式**。按本条约定未删，登记为待清理项。


