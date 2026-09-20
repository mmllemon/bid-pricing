# 投标报价优化项目：接手维护手册（v0.1.0）

版本：`v0.1.0`（2026-09-20，以当前工作区代码为准）  
适用对象：新接手的开发者、测试人员、造价/商务人员，以及后续执行任务的 Agent

## 0. 先看结论

这是一个「给定总报价，联合求解分部分项综合单价」的报价优化项目。当前已形成 **计算内核 + 网页报价平台 + 个人工作台** 三层完整闭环，全量测试 **1393 项通过**（`python -m unittest discover -s tests -t .`），并已版本化、可推送到私有仓库。

接手时必须记住四件事：

1. **代码已纳入版本管理。** 运行时产物不入库：`outputs/`（用户方案数据、日志、下载文件）、`docs/parsed/`（真实清单解析中间产物）、`node_modules/` 均被 `.gitignore` 排除。删除任何东西前先确认是否被证据/测试引用。
2. **`docs/STATE.md` 是自动生成的快照**（`python -m bidpricing.cli status --write`），不是即时事实源。事实源是代码、配置与现场复算；改完代码必须重新生成快照再对账。
3. **低价确认 ≠ 废标判定。** 报价比率低于阈值时系统只做确认留痕（记录用户/时间/条款依据），不替用户作法律判断；所有结果恒附「是否废标以招标文件为准」。
4. **成本税口径已闭环，取值待责任人声明（H-002 / ADR-0035）。** 成本清单综合单价按「含税成本单价」入账，系统在**产出任何毛利数字之前**按已声明的抵扣方式换算为不含税有效成本；未声明抵扣方式时**阻断**「最优利润」结论（`config/project_quote_policy.json` 的 `cost_input_tax_policy.mode` 当前为 `UNKNOWN`，故网页与 CLI 均按阻断行为运行——这是设计行为，不是故障）。模型利润的口径与单价、限价一致（均不含增值税），但**仍不是最终财务利润**：项目固定成本与隐性成本链路未闭环。

## 1. 项目要解决什么问题

用户提供：固定格式的限价清单 Excel（综合单价列为不含税最高限价，空表示无最高限价）、成本清单 Excel（含税成本单价）、目标总报价、固定税前金额、增值税率/附加税率、招标文件的不平衡报价条款与报价区间。

系统在总报价固定、限价不超限、报价区间等约束下联合决定各清单综合单价，使结算调整后利润最大，并输出可复核的 Excel。

### 已确认的业务口径

| 事项 | 当前口径 |
|---|---|
| 限价综合单价 | 不含税最高限价 `cap_excl_vat` |
| 成本综合单价 | 成本清单原始含税成本 `cost_input_incl_vat`；入口按声明换算为不含税有效成本 `cost_effective`（H-002 / ADR-0035），声明缺失即阻断 |
| 单项报价是否必须高于成本 | 不必须；允许单项毛利为负，成本参与利润目标 |
| 措施项目费、规费 | 按当前固定税前金额处理 |
| 隐形成本 | 暂按项目固定成本理解；不默认单项成本 0，不重复分摊 |
| C13 基准 / 低价阈值 | 最高限价；报价比率 <50% 需严重低价/废标风险确认（留痕） |
| C13 工程量阈值 | 相对限价工程量偏差超 ±15% 触发结算调整 |
| 空白限价 | `no_cap=true`，识别并提示，结果转人工报价 |
| 清单顺序 | 保留原限价清单顺序；成本侧独有项按成本输入顺序插入 |
| 项目凭证 | `project_id` 只存经营概览真实项目 UUID（唯一凭证）；`project_name` 承载展示名/目录名 |
| 输出语言 / UI 风格 | 中文；简洁浅色 Apple 风格，业务清晰度优先 |

## 2. 当前实现状态

### 2.1 已实现并已核对

- **计算内核**：固定格式/变体 Excel 读取与清洗、复合主键匹配（`(project_id, unit_work, item_id)`，重复键阻断不合并）、Phase 1 普通优化、Phase 2 C13 结算调整 MILP（McCormick 线性化 + 独立复算）、Phase 0 预检/可行性证书、不可行诊断、结算规则引擎（2013/2024 规则集）、数值稳定性/退化检测/奇偶校验。
- **网页报价平台**（FastAPI 8000 + 原生 JS 8080）：上传导入预览（行数/字段/匹配覆盖/异常/文件哈希）、计算、方案保存/打开/复制/重算/定稿回写、多方案对比（限同项目变体）、低价确认留痕、Excel 导出（`build_web_result.mjs`，缺文件自愈重建）。
- **个人工作台**：项目经营概览看板（投标/中标在建/完工/结算/售后 + 未中标归档）、项目档案（简称便利贴、堆叠卡片、搜索、按列排序、阶段流转）、方案库、今日计划/习惯打卡等个人模块。
- **多用户目录隔离**（H-012）：`outputs/<projects|web-results>/<用户>/`，默认目录调用时解析（`deployment.py`）。
- **前端体验**：MiSans VF 可变字体本地化子集（56 woff2 切片按需加载）、窄屏抽屉式侧栏、毛玻璃自定义下拉、`font-synthesis:none`、响应式断点。
- **质量设施**：配置制品（`config/`）、ADR 决策记录（34 项）、状态快照、审计日志、68 项任务机械状态（`docs/tasks.json`）。

### 2.2 部分实现 / 已知缺口

- **成本税口径**：输入语义是「含税成本单价」，**换算链路已闭环**（含税 → 不含税有效成本，唯一换算入口 `validation/cost_basis.py`，声明缺失即阻断；目标函数口径由 PB-07 跨层对账钉住）。剩余缺口是**项目固定成本与隐性成本**的录入/分摊链路——模型利润仍不等于最终财务利润。
- **成本税口径取值未落**：`project_quote_policy.cost_input_tax_policy.mode` 为 `UNKNOWN` ⇒ 全链路按阻断行为运行，须责任人声明抵扣方式（及税率/可抵扣占比）后方可出利润结论。若各清单的货物/人工构成比例差异较大，需扩展为逐项可抵扣占比（见 ADR-0035 遗留 1）。
- **无最高限价项 / 隐形成本**：识别与提示存在；不能自动优化、无完整录入分摊服务。
- **多方案对比**：支持同项目方案变体对比；跨项目对比被 400 阻断（产品决策，非缺口）。
- **状态快照**：自动生成机制存在，数字由 `collect()` 实时派生；必须以 `status --write` 生成交付，不手写数字。

## 3. 仓库地图

```text
bid-pricing/
├─ api/app.py                         FastAPI 生产入口（预览/优化/方案/概览/对比）
├─ frontend/                          网页源码：index.html + app.js + styles.css + workbench.js/css
│  └─ assets/fonts/misans/            MiSans VF 本地化子集（56 切片）
├─ app/streamlit_app.py               早期 Streamlit 入口，非当前主 UI
├─ build_t06_01.mjs / build_t07_quote.mjs / build_web_result.mjs  结果构建脚本
├─ run.ps1                            Windows 一键启动（后端 8000 + 前端 8080）
├─ config/                            规则、字段、约束、精度、报告、项目报价策略等 JSON 制品
├─ src/bidpricing/
│  ├─ io/                              Excel 读取、清洗、匹配、导入登记
│  ├─ validation/                      缺失值、成本、利润、C13、不平衡、低价确认、隐形成本
│  ├─ solver/                          Phase 0/1/2、编译器、后端、复核、诊断、退化、稳定性
│  ├─ contracts/                       2013/2024 规则集与规则选择
│  ├─ quote_pipeline.py                报价主业务流程
│  ├─ settlement.py                    结算规则引擎
│  ├─ project_store.py                 方案持久化（<报价金额>_<id>.json 命名）
│  ├─ project_overview.py              项目经营概览存储
│  ├─ plan_compare.py                  方案对比（同项目门禁）
│  ├─ deployment.py                    用户隔离与访问日志
│  └─ status.py / cli.py               状态快照与命令行入口
├─ tests/                              单元、契约、金样、真实项目、状态证据测试
│  └─ data/                            样例数据（golden、xiyong_l_district、t06-01 报价表证据）
├─ docs/adr/                           设计决策记录（ADR-0001..0034）
├─ docs/STATE.md                       自动生成状态快照（status --write 派生）
├─ docs/tasks.json                     68 项路线任务机器可读状态
├─ docs/PROJECT_HANDOFF.md             本文件（接手入口）
└─ outputs/                            本地运行数据（gitignore，不入库）
```

## 4. 系统架构与数据流

```text
限价 Excel ─┐
            ├─ parse_listing → clean → match_canonical_rows（复合键、并集、异常）
成本 Excel ─┘
                 ↓
        preview（导入预览：行数/字段/覆盖/异常/哈希）
                 ↓
        quote_resolve（Phase 0 预检 → Phase 1 → Phase 2 结算 MILP）
                 ↓
        独立复算（settlement_revenue_adjusted / 总价核对）
                 ↓
        JSON 结果 ──┬─ 前端结果表 + Excel 下载（build_web_result.mjs）
                    └─ 方案持久化 project_store（按用户目录隔离）
```

界面不直接操作 `Phase1Instance` 或 MILP 内部对象；`api/app.py` 是薄入口，业务逻辑在 `src/bidpricing` 纯 Python 模块（可单测）。

## 5. 技术栈与运行方式

### 5.1 技术栈

- Python 3.11+（标准库为主；FastAPI/Uvicorn/python-multipart 提供网页 API）。
- PuLP / HiGHS：Phase 2 MILP 后端，由 `config/solver_backend_spec.json` 选择。
- 原生 HTML/CSS/JavaScript：前端无框架。
- Node.js + `@oai/artifact-tool`：生成/格式化 Excel（`node_modules` 为本地依赖，不入库）。
- JSON 配置制品 + `unittest` 测试。

### 5.2 启动（Windows 一键）

```powershell
.\run.ps1
```

脚本定位 Python、首次自动补装 `requirements-web.txt`，启动后端 8000 + 前端 8080。缺 node 时 Excel 导出降级（JSON 结果仍可下载）。浏览器打开 <http://localhost:8080>；健康检查 <http://localhost:8000/api/health>。

手动启动：后端 `$env:PYTHONPATH="src"; python -m uvicorn api.app:app --host 127.0.0.1 --port 8000`；前端 `python -m http.server 8080 --directory frontend`。

### 5.3 API 一览

| 端点 | 说明 |
|---|---|
| `GET /api/health` | 健康检查 |
| `POST /api/quote/preview` | 导入预览（限价/成本双文件 + `project_id` + `project_name`） |
| `POST /api/quote/optimize` | 计算（文件 + 参数 + 低价确认 + `overview_id`） |
| `GET /api/quote/download/{job_id}` | 下载 Excel（`<项目名称>-<报价金额>.xlsx`，缺失自愈重建） |
| `GET /api/project/list` | 方案按项目分组（分组名 = `project_name`） |
| `GET /api/project/get?id=` | 打开方案（含 `project_name`、`params`、`result`） |
| `POST /api/project/copy` / `recompute` / `mark-finalized` / `delete` | 方案复制/重算/定稿（含回写）/删除 |
| `POST /api/project/overview/save\|list\|delete\|finalize` | 项目经营概览 CRUD 与定稿 |
| `POST /api/project/compare` | 方案对比（仅同项目，跨项目 400） |

字段约定：`project_id` = 经营概览真实项目 UUID；`project_name` = 展示名；`overview_id` = 定稿回写目标项目 id。

## 6. 输出契约

网页 JSON 主要字段：`status / solver_status / target_total / competitive_budget / objective / p_by_id / line_amounts / items / manual_item_count / matched_count / anomalies / ratio_min / ratio_max / low_ratio_confirmed / low_ratio_review_required / unbalanced_clause / excel_download_url / project_id / project_name`。

Excel 由 `build_web_result.mjs` 生成，明细表含报价比率公式、汇总、规则与说明、数据来源；报价比率列用百分比格式、金额列 `#,##0.00`。扩展列必须同步 `api/app.py`、`frontend/app.js`、`build_web_result.mjs`、测试与本文档。

## 7. 测试与验证

```powershell
# 全量测试（当前 1393 项通过）
$env:PYTHONPATH="src"; python -m unittest discover -s tests -t . -q

# 契约/状态
$env:PYTHONPATH="src"; python -m bidpricing.cli contract-check
$env:PYTHONPATH="src"; python -m bidpricing.cli status --write
```

注意：`tests/test_status.py` 会校验任务证据文件真实存在（T06-01 证据现指向 `tests/data/t06-01/报价表.xlsx`），删除任何被证据引用的文件会直接测试失败。

## 8. 待办与路线

68 项模型路线任务见 `docs/tasks.json`（机器可读）；当前遗留 9 项，下一步建议：T04-04（Phase1/2 奇偶校验）、T07-03（精度监控）、T07-04（参数校准）。

产品向主要缺口：

1. ~~**成本税口径闭环**（P0）~~ **已实现（H-002 / ADR-0035，2026-09-20）**：抵扣方式声明 + 含税→有效成本换算（唯一入口）+ 声明缺失时在出数前阻断利润结论；两条报价入口共用同一判据，并新增 PB-07 跨层口径对账。**遗留**：项目取值（`project_quote_policy.cost_input_tax_policy.mode`）须责任人声明，当前仍为 `UNKNOWN`。
2. **固定/隐形成本模型**（P1）：直接归属、分摊、项目固定费用分列可追溯。
3. **模板适配层**（P1）：模板版本、列位置映射、友好错误。
4. **实施成本 / 项目台账 / 结算管理模块**（P2）：目前是工作台占位/部分功能。

## 9. 用户偏好与沟通约定

- 使用中文说明和中文 UI；先给结论，再说明依据。
- 不把阶段名、英文状态、内部任务号直接当用户可理解的结果，必要时附中文解释。
- 用户重视 Excel 结果的丰富程度；保留清单原始顺序，任何重排视为回归。
- 接受单项低于成本，但不接受低于 50% 报价比率时无确认直接给结果。
- 界面有审美（Apple 风格浅色），业务清晰度优先于装饰。
- 未开发模块进独立子页面，不在原页面弹「正在规划」。

## 10. 重要踩坑与设计纪律

1. **状态快照会过期。** 生成物不是事实源；事实源是代码、配置和现场复算。
2. **成本含税/报价不含税不可直接相减。** 必须声明税率与抵扣方式。
3. **空限价不是零限价。** 空值 = 无最高限价，零值 = 明确零价，二者分开。
4. **低价确认 ≠ 废标判定。** `NEEDS_CONFIRMATION` 是产品安全闸门；留痕字段（`confirmed_by`/`confirmed_at`/`clause_basis`）一旦生成即冻结，结果恒附「是否废标以招标文件为准」。
5. **`p_by_id` 假设 item_id 唯一。** 匹配主键含 `unit_work`；重复键必须显式阻断（冲突编码），不能静默覆盖。
6. **MILP 目标值不是最终可信利润。** 必须独立复算结算收入并核对总价。
7. **方案 JSON 命名 `<报价金额>_<id>.json`、Excel 命名 `<项目名称>-<报价金额>.xlsx`。** 文件名即契约，改命名必须同步 `project_store.py` 与 `_excel_filename`。
8. **`project_id` 是唯一凭证。** 只存真实 UUID；展示/目录用 `project_name`；旧方案（project_id=名称）打开时按 name→id 归一化，重算后升级为 UUID。
9. **默认目录调用时解析。** `project_store.PROJECTS_DIR` 等路径不得在模块定义时绑定，否则用户隔离失效。
10. **规则配置与代码常量重复会漂移。** 新增阈值必须加配置—实现—测试三方一致性检查。
11. **用户输入必须转义。** 前端所有来自 Excel/用户的字符串进 `innerHTML` 前过 `esc()`，防注入。
12. **前端缓存。** 修改 `app.js`/`styles.css`/`workbench.js` 后必须递增版本查询串（如 `wb31`），否则浏览器 HTML 缓存会加载旧脚本（曾导致「下拉显示旧值」假象）。

## 11. 接手者操作手册

### 第一次接手

1. 阅读本文件、`README.md`、`docs/STATE.md`、`docs/USER_PRODUCT_SPEC.md`、`docs/PRODUCT_ROADMAP_AND_TASK_PLAN.md`。
2. `git status --short` 了解工作区；`outputs/` 等为本地数据，不清理他人改动。
3. 运行全量测试 + `contract-check` + `status --write`。
4. 读 `docs/adr/` 中与报价规则、C13、结算规则、低价确认相关的 ADR。
5. `.\run.ps1` 启动，确认 `/api/health` 与页面；做一次默认 50% 计算和一次「低于 50% 未确认」测试。

### 修改任何模型代码后

- 先补/改最小单元测试，再改主流程；求解器结果必须独立复算。
- 任何字段新增同步配置、API、前端、Excel、测试和文档。
- 条款解释写入配置/ADR，不留在聊天记录。
- 不把空限价转 0、不静默补缺成本、不改用户清单顺序。

### 交付前

```powershell
git status --short
python -m unittest discover -s tests -t . -q
python -m bidpricing.cli contract-check
python -m bidpricing.cli status --write
git tag v0.1.0   # 语义化版本号，里程碑需同步 CHANGELOG
```

将测试实际数字、失败列表、未完成事项写入交付说明；全量测试若失败必须写明原因与相关性，不能只说「已测试」。
