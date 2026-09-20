# 变更日志

本文件记录**里程碑级**变更。逐次提交请用 `git log`；本文件回答的是
「相比上一次里程碑，项目发生了什么变化」。

**格式约定**：每个里程碑对应一个 git tag，tag 名形如 `<主题>-v<N>`。
条目分类：`新增` / `变更` / `修正` / `移除` / `安全`。

---

## [未发布]

### run.ps1 一键启动器加固（解释器能力探测 + 停止路径 + 编码）

**修正**

- **解释器判定由「存在性」改为「能力探测」**。`%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe` 是 0 字节的应用执行别名占位符，`Test-Path`/`Get-Command` 都会命中，执行时只打印 `Python was not found ... Microsoft Store` 并返回非 0——旧脚本据此判定「已找到 Python」，继续装依赖、启动服务，最后**假报成功**。现改为逐个候选真跑 `import ssl,venv`，跳过 `*\WindowsApps\*` 与 0 字节文件。
- **探测的能力换成真正需要的能力**。只验 `--version` 会漏掉 `_ssl` DLL 加载失败的残缺安装：它打印得出版本号，pip 却走不了 HTTPS（本机 `python` 首个候选即为此种）。
- **`Wait-Process -Id $a -Id $b` 参数绑定失败**。`-Id` 只能出现一次，多进程须传数组；旧写法使 `Ctrl+C` 停止路径直接抛错（用户实际遇到的报错）。
- **原生命令 stderr 被 `$ErrorActionPreference="Stop"` 升级为终止错误**。pip 的 `Disabling truststore ...` 警告会让脚本在装依赖中途暴毙；新增 `Invoke-Native` 统一包装。
- **脚本编码**：本文件含中文，必须保存为 UTF-8 **with BOM**。PowerShell 5.1 对无 BOM 的 `.ps1` 按系统 ANSI（GBK）解码，丢 BOM 会解码错乱、吃掉引号与大括号，报出一批离奇语法错误（实测同一份文件：有 BOM 解析 0 错、剥掉 BOM 解析出 6 个错）。

**变更**

- 依赖改在仓库内 `.venv` 隔离安装（不污染系统解释器）；`.venv` 存在但探测失败时**改名保留**为 `.venv.broken-<时间戳>` 后重建，不静默复用。
- 新增解释器钉死方式：仓库根 `.python-path`（单行绝对路径，不入库）或环境变量 `BIDPRICING_PYTHON`；候选还覆盖 `%LOCALAPPDATA%\Programs\Python\Python3*` 等常见安装位置（本机即由此自动找到 3.14.6）。
- 最低 Python 版本改从 `pyproject.toml` 的 `requires-python` 读取，不在脚本里重复硬编码。
- **启动后必须探到 HTTP 200 才打印成功**（后端 `/api/health` 60s、前端首页 20s）；失败时报出子进程 `ExitCode` 与日志路径并非零退出。
- 两个服务的 stdout/stderr 重定向到 `outputs/logs/*.log`（原先创建了 `outputs\logs` 却从未使用）。
- README / PROJECT_HANDOFF 同步新口径；`.gitignore` 增 `.venv.broken-*/`、`.python-path`。

**新增**

- `tests/test_run_script.py`（15 项静态判据）：编码（含非 ASCII 必须带 BOM）、`-Id` 不得重复、能力探测须含 `ssl`、须剔除 `WindowsApps` 占位符、成功横幅须在探活之后、pip 须走容错包装、文档口径一致性。判据已做**变异检验**（把 `-Id` 改回重复写法 / 剥掉 BOM → 各自被杀）。

### T04-04 收口：对拍报告可复算 + 补齐五处「规格声明了但实现没有」（ADR-0036）

**新增**

- `solver/parity_runner.py`：对拍**执行器**（校验 input bundle → 逐 case 比较 → 最严聚合 → 产报告）。与 `parity.py`（比较器，只吃两条路径已产出的结果）分层——本模块**不替任一路径求解**。
- CLI `parity-check`（`--bundle / --out / --signoff / --no-write / --json`），报告自带 `reproduce_command`。与 `verify-solution`、`derive-check` 同属**预期可能非零**的命令，**不进常驻验证环**。
- `docs/phase12_parity_prior_measurement.json`：把原先那份**不可复算**的 `PASS` 证据留档（`reproducible: false` + 三条 caveats），不再冒充「对拍已通过」。
- `docs/adr/ADR-0036-parity-reproducibility.md`。
- 测试 `tests/test_parity_runner.py`（含 4 条变异体）；`tests/test_parity.py` 由 5 项扩到 35 项（含 6 条变异体）。

**修正**

- **报告此前没有生成器**：全仓 `parity`/`golden` 在 `cli.py` 零命中，`docs/phase12_parity_report.json` 自称 `generated_by: parity.py` 却无任何代码写它。现由 `parity-check` 产出并写入输入路径与复算命令。
- **判据宽度由代码字面量改为制品唯一提供**（DV-01 家族）：`tolerances.{objective_abs, price_abs, residual_abs}` 原先是函数默认值 `1e-7`，制品那节**从未被读取**；现改为从制品读、入参仅作显式覆盖，缺项且本次用到即 `BLOCKED`（不静默退回默认数）。三个键由 `TOLERANCE_KEYS` 与制品**双向对账**。
- **补齐 L1**（原先从不比较状态）：两侧都必须给出可比较状态，缺任一侧即 `BLOCKED`——「数值恰好相等」不得替代状态可比。
- **补齐 L3 残差**（原先只比 `layers`，`residual_abs` 从未被读）：残差按 `residual_abs` 判；**只有一侧提供 ⇒ `BLOCKED`（口径不可比）**，不判 PASS 也不判 FAIL。
- **补 B 组义务**（原先 `group` 只做合法性校验）：Phase 1 已声明可行而 Phase 2 目标值更高 ⇒ 记「目标函数口径可能分歧」义务；可行性未声明 ⇒ 记「B 组判据未走到」义务。**只加义务，不改判定**。
- **补 floor 来源声明**（ADR-0026 明文要求）：未声明记义务。
- 聚合澄清三条边界：`SKIP` 不参与最严竞争；全 `SKIP` ⇒ `SKIP`；空判据集 ⇒ `BLOCKED`。
- `config/phase12_parity_spec.json` 增补 `tolerance_source_rule / group_semantics / report / skip_policy`，`blocked_rules` 补三条新拒绝理由（该制品未注册 Gate 0、未冻结）。
- 缺 input bundle 时结论 `BLOCKED` 并**具名 owner**，理由同时排除两种误读（非「已通过」、非「不适用」）。

**变更**

- `docs/phase12_parity_report.json` 结论由 `PASS` → `BLOCKED`，**与任务板 `docs/tasks.json` 原先的「仍 BLOCKED」说法对齐**（此前两处冲突）。这不是退步：一份不可复算的绿换成可复算且如实说明「本次未对拍任何实例」的结论。
- `docs/tasks.json` T04-04 证据由 4 条扩到 8 条；`tools/extract_tasks.py` 的 `EVIDENCE` 字典**补登 `T04-04` 键**（此前该键不在字典里而 tasks.json 已有证据 ⇒ `--check` 一旦恢复可跑即报漂移）。

### H-002 完成：成本税口径闭环 + 目标口径跨层对账（ADR-0035）

**新增**

- `config/cost_input_tax_spec.json`：成本税口径**机制**制品（已入 Gate 0b 登记并冻结）——抵扣模式词表 `FULL/PARTIAL/NONE/UNKNOWN`、唯一换算式 `k = 1 − rate×ratio/(1+rate)`、判据 `CT-01..CT-07`、字段名与阻断语义。
- `validation/cost_basis.py::build_effective_costs`：含税成本 → 不含税有效成本的**唯一换算入口**（`policy_section` 可注入，供测试；返回逐项 `CostAdjustment` 痕迹与 `EffectiveCostPlan`）。新增 `check_cost_input_tax` 的 **CT-06**：制品词表 ↔ 实现常量**双向**对账。
- `quote_pipeline.resolve_cost_plan`：口径契约由**写在数据里的** `cost_tax_scope` 标记驱动——全标 `EXCL_VAT` ⇒ 幂等跳过；全未标 ⇒ 本层换算；**混合 ⇒ BLOCKED**（拒绝猜以哪侧为准）。
- 判据 **PB-07**（`validation/profit_bridge.py`）：把**报告层声明** `tax_caliber_of_objective` 与**求解层实现** `settlement_milp.OBJECTIVE_CALIBER` + `objective_revenue_factor()` 跨层对账。
- `Formulation.objective_caliber` 具名量（求解器无关形式化结果新增字段）。

**变更**

- 两条报价入口同时接线：`run_quote_pipeline` / `run_settlement_adjusted_quote_pipeline` / `quote_resolve.run_resolve` 均在**产出任何毛利数字之前**取得换算方案；不可计算即阻断（网页侧 400）。`QuotePipelineResult` 新增 `cost_multiplier` 与 `cost_adjustment_trace`；payload 新增 `cost_input_tax`（声明 + 系数 + 逐项痕迹）。
- 网页结果表由 13 列扩到 15 列（新增「成本税口径」「有效成本单价」）；Excel 导出由 16 列扩到 18 列，**成本合价与单项毛利改按有效成本单价计算**；利润文案口径由「含税口径」更正为「不含增值税」。
- `settlement_milp`：删除收入侧 `(1+vat_rate)` 折算（`objective_revenue_factor` 恒 1.0，口径 EXCL_VAT）。**推荐报价不变**（p 依赖项被同一常数缩放、`Σc_i·q1` 与 p 无关），仅报告值更正。

**修正**

- **成本税口径缺陷（H-002）**：成本清单综合单价为含税，而限价与报价不含税，旧实现 `margin = 不含税收入 − 含税成本` **系统性低估毛利**；CT-01..CT-05 判据虽已存在却**无任何入口消费**（与 C13 未接线同族）。现换算链路闭环，声明未定时阻断利润结论。
- **目标口径缺陷（H-002b）**：`settlement_milp` 曾把结算收入乘 `(1+vat_rate)` 折算为含税，违反已冻结的 `profit_bridge_spec.tax_caliber_of_objective = EXCL_VAT` 声明，使报告利润**虚增「应交增值税」**（实测 9605 vs 6500，差额 3105 = 0.09×Σ结算收入）。因**最优解不变**，该错层无法被结果复核发现，故补 PB-07 机械拦截。
- `run_quote_pipeline` 签名回归修复：`unbalanced_clause` 形参在改写中丢失，由 `tests.test_quote_pipeline.test_probe_instance_runs_end_to_end` 抓出（此前被 cost plan 阻断掩盖）。
- 测试纪律：`test_field_regression` / `test_project_store` / `test_quote_pipeline` 夹具补 `cost_tax_scope="EXCL_VAT"`——测试针对管道机制，不耦合项目实时税口径。

**测试**

- 新增 `tests/test_cost_basis_wiring.py`（41 项）：内核数值手算钉死（`113 → 100.0`；`PARTIAL` 与分项精算逐位等价）、七类阻断矩阵、口径契约、两条入口接线、**4 条变体注入**（换算恒等 / 入口不阻断 / 入口不换算 / 毛利用含税成本，逐条被具名用例杀死）。
- `tests/test_settlement_milp.py` 新增 `ObjectiveCaliberTest`（p 列系数须恰为 `q1`、复算手算可算、换税率目标不变）；`tests/test_profit_bridge.py` 新增 `ObjectiveCaliberCrossLayerTest`。
- 全量 1393 → **1434** 项，双环境通过（3.13.12 零依赖 / solver 环境 PuLP 3.3.2 + HiGHS）。唯二失败为**独立数据漂移**：真实样本限价清单于 2026-09-20 被更新（83→84 行、15→16 项补充项），在改动前的 HEAD 上同样复现，与本次改动无关。

## v0.1.0 (2026-09-20)

首个对外发布里程碑：报价优化计算内核 + 网页平台 + 个人工作台完成闭环，全量测试 1393 项通过。

**新增**

- 网页报价平台（FastAPI 后端 8000 + 原生 JS 前端 8080，`run.ps1` 一键启动）：上传导入预览（H-006 行数/字段/匹配覆盖/异常/哈希）、方案保存/打开/复制/重算/定稿回写、多方案对比、低价确认留痕（用户/时间/条款依据）、Excel 导出缺失自愈重建。
- 项目经营概览工作台：投标/中标在建/完工/结算/售后看板、堆叠卡片 + 简称便利贴、搜索与按列排序、阶段流转、定稿方案回写投标报价金额。
- 多用户目录隔离（H-012）：`outputs/<projects|web-results>/<用户>/`，默认目录调用时解析。
- 前端细节：MiSans VF 可变字体本地化子集（56 切片按需加载）、窄屏抽屉式侧栏、`font-synthesis:none` 渲染优化、自定义毛玻璃下拉。

**变更**

- 项目凭证字段统一：`project_id` 只存经营概览真实项目 UUID（唯一凭证），新增 `project_name` 承载展示名；方案 JSON 命名 `<报价金额>_<id>.json`、Excel 命名 `<项目名称>-<报价金额>.xlsx`；旧方案打开时按 name→id 归一化兼容。
- `_summary` 补充 `project_name`，方案列表分组显示项目名而非 UUID。

**修正**

- 副本方案（名称带「（副本）」）打开时自动关联经营项目，匹配优先级 overview_id → project_id → name → 去后缀 name。
- 低价格式、定稿锁定、空限价、缺成本等既有校验保持，结果恒附「是否废标以招标文件为准」。

### T03-01 完成：结算规则引擎（ADR-0033）

- `src/bidpricing/settlement.py`：`SettlementRule.evaluate(Q0, Q1, P0, ContractContext)` → `settlement_amount / effective_price / rule_id / rule_branch`；`rule_set_id` 严格分发（未注册 ⇒ BLOCKED 且不回填）；`p1_source` 随版本分发（2013=REDETERMINE / 2024=ADJUST_ON_CONTRACT_PRICE）；SR-01..SR-09 判据（含三类坏引擎否定用例）。
- **分层互锁修正**：规则卡互锁只约束 Standard 层（声明值 = 实现常量），合同/招标/地方层覆盖标准阈值**允许偏离并留痕**——旧实现会把「合同约定按 10% 调价」判违规。
- `RuleSet.classify_branch / settlement_amount / effective_revenue_multiple` 增加阈值可注入参数（默认取规范常量，既有调用零行为变更）。
- `config/settlement_rule_spec.json`：注册表 + 固定探针网格 + 具名容差（eps_ratio 与 eps_total 分列，DV-02）。
- CLI `settlement-check`（含 `--judge`）；测试 +37，全量 1046 → 1083 双环境绿。

### T04-02E 完成：不可行诊断的预言机接线（ADR-0032）

- `solver/diagnose.py` 新增 `milp_oracle`（build_formulation→compile_model→solve_compiled 归一映射：INFEASIBLE⇒INFEASIBLE、OPTIMAL/FEASIBLE⇒FEASIBLE、其余含 UNAVAILABLE/UNSUPPORTED⇒UNKNOWN——没跑成 ≠ 不可行）与 `chained_oracle`（首个非 UNKNOWN 胜出，整链 UNKNOWN⇒UNKNOWN）；backend 注入点透传（BB-06 同源）。
- 规格 `lp_reserved` 替换为 `milp_builtin`（已接线语义）；CLI `diagnose --oracle phase1|milp|chain`（默认 phase1 行为不变）。
- 零依赖环境用替身后端全链路测试；求解器环境低 B 实例由 HiGHS 实证 INFEASIBLE。测试 +9，全量 1037→1046 双环境绿。

### T03-06 完成：不可行诊断（ADR-0031）

- `config/infeasibility_diagnosis_spec.json`：DG-01..DG-08 + 旋钮表（toggleable=C6..C13）+ §6.3 建议动作目录。
- `solver/diagnose.py`：两遍设计——Pass A 结构冲突（总价层 P_min/P_max vs B + 逐项箱，带数额）+ Pass B 删除过滤器（单关/成对关，IIS 近似，最小性抑制超集）。
- oracle 三态注入（FEASIBLE/INFEASIBLE/UNKNOWN）+ **EC-7 精化**：EC-7 FAIL=已证空域⇒INFEASIBLE；EC-7 BLOCKED（B 缺失）⇒UNKNOWN——「没给 B」不是「B 定得太低」。
- 建议动作唯一来源 §6.3 判据表；金额从原始量重算，不抄预言机文案。
- CLI `diagnose`；tests 30 项，全量 1007→1037 双环境绿。

### T03-03 完成：Phase 0 预检与可行性证书（ADR-0030）

**新增**

- `config/phase0_precheck_spec.json`：PC-01..PC-08 判据 + 证书字段语义 +
  具名容差注册表（复用 `eps_total` 名与公式，解析入口单一）。
- `src/bidpricing/solver/precheck.py`：`build_certificate`（P_min/P_max/
  P*_var/P*_eff/ΔP）+ `judge_precheck`（计算/判定分离，判定器可注入验证）；
  CLI `precheck`（`--instance` / `--probe` / `--json`）。
- `tests/test_precheck.py`：28 项（全量 979 → **1007**，双环境全绿）。

**关键裁定**

- P*_var 唯一提供者 = `total_price.compute_P_competitive`（T00-06B ④）；
  闭式 `∂C/∂A = −1`（固定项直接扣减）由测试钉住。
- P_min 用派生层 L（merged_lower 多源取大，ADR-0026 决策六）——普通 L
  求和会在条款下浮时虚低。
- P*_eff 三 term **任一不可算 ⇒ 整体 BLOCKED**，不丢项取 max（丢项=静默
  放宽下界）；「α_cap 已声明但存在空 cap 项」单列为声明与数据矛盾。
- 空 cap ⇒ P_max 不落值（≠0），PC-04/PC-07 SKIP；SKIP 不参与最严竞争
  （ADR-0029 裁定跨层沿用，全 SKIP ⇒ BLOCKED）。

### T03-04 完成：约束判定器（C1–C13 六元组，ADR-0029）

**新增**

- `config/constraint_judge_spec.json`：CJ-01..CJ-13 判据 + 六元组语义
  （constraint_id / status / actual / limit / slack / severity）+ **具名容差
  注册表**（`eps_c1_abs` / `eps_res` / `eps_total` / `eps_ratio` /
  `eps_price` / `resolution`）+ 逐约束激活语义表。
- `src/bidpricing/solver/constraint_judge.py`：`JudgeInputs` 只吃原始量
  （接口级独立性，不收 SolveResult/Formulation/DerivedReport）；
  `judge_constraints` 聚合序 FAIL > BLOCKED > WARN > SKIP > PASS，
  空判据集 ⇒ BLOCKED；P1（C11/C12）FAIL 不阻塞 P0 主干。
- CLI `constraint-check`（`--instance` / `--probe` / `--floor-json` / `--json`）。
- `tests/test_constraint_judge.py`：64 项（全量 915 → **979**，双环境全绿）。

**关键裁定**

- ★ **SKIP 不参与最严竞争**：全部判过且通过 ⇒ PASS；「有约束未激活」不是
  缺陷，但「没判」必须留痕（规则⑧）。
- ★ **DV-02 显式隔离**：C12 的 R_pc 是无量纲比值，容差独立具名 `eps_ratio`
  （1e-9 绝对），**禁止**引用 eps_price×P*（会被放大 ~10⁶ 倍静默失效）；
  测试以「缺口 1e-6 比值」钉住两种读法的分叉。
- ★ C7 双向 z 一致性：虚报（z=1 但 p>c−eps_res）与漏报（z=0 但 p<c）
  都抓；无 z 向量且计数未超限 ⇒ WARN（自称口径未核），不是 PASS。
- ★ C11 仅给 kappa_max ⇒ BLOCKED：MAD 已被否决（同中心 MAD ≤ σ），
  不得静默替换判据。C13 恒 SKIP（结算期事实投标期不可知）。
- C4 floor 缺失 ⇒ BLOCKED：μ 未落值挂账（OI-DQ-A）在判定层可见化。
- 两探针交叉验证：Phase 1 解析解在 C1/C2/C3/C5 全 PASS。

### T04-07 完成：MILP 独立验收协议（ADR-0028）

**新增**

- `config/milp_acceptance_spec.json`：六字段（status / integer_feasible /
  objective_gap / best_bound / time_limit / incumbent）+ MA-01..MA-10 判据 +
  三个具名容差（`eps_gap_abs` / `eps_gap_rel` / `eps_int`）。
- `src/bidpricing/solver/milp_acceptance.py`：`build_acceptance`（生产结论）与
  `judge_milp`（判定）分离，判据只吃 `MilpFacts` 原始量，可被注入的错误结论否定。
- CLI `milp-check`（`--form LP|MILP|both` / `--time-limit` / `--json`）。
- `tests/test_milp_acceptance.py`：38 项（全量 877 → **915**，双环境全绿）。

**变更**

- `SolveResult` 新增 `diagnostics`（对偶界 / 自报间隙 / 整数性违规 / 节点数），
  并暴露 `best_bound_min` / `reported_gap` 只读属性；取数在适配层内以
  `hasattr` **能力探测**完成（`backend._pulp_diagnostics`），取不到即留空。

**修正**

- ★ HiGHS 的 `mip_dual_bound` **不含 `objective_constant`**：只做 min→max 取反
  会得到 bound=2,730,000 对 Z=460,000（复算间隙 4.9 而自报 0.0），由 MA-06
  跨来源对账抓出。换算改为两步（取反 + 补常量）。
- HiGHS 用 ±inf 表示「该量无定义」（LP 形态的 `mip_gap`）⇒ 非有限值一律不写键。

**实测**

- `pulp_highs` ⇒ `OPTIMAL`（最优性已证，全判据 PASS）；
  `pulp_cbc`（命令行后端，`solverModel=None`）⇒ diagnostics 为空 ⇒ MA-05 WARN
  + MA-06 BLOCKED ⇒ 降级 `FEASIBLE`、未证。这是「能力必须探测、不得硬编码」的
  价值证据：写死「一定有诊断量」会让 CBC 上静默宣称最优。

### T04-08 完成：独立参考实现（第二条计算路径 + 三层隔离证明，ADR-0027）

**新增**
- `config/reference_impl_spec.json`：重算范围、公式来源、ε_Z 组成与具名、
  三层隔离证明规则、RI-01..RI-11 判据、branch_domain 基准。
- `src/bidpricing/refimpl/{reference,isolation}.py`：**不 import 任何生产模块**
  （连数据结构也不 import，靠冻结快照取属性）⇒「源码文件不重叠」是可审计的事实。
  公式由路线 §5.3 S0 + `profit_bridge_spec` + `pricing_rule_card` 推导。
- `tests/test_reference_impl.py`：39 项，含**手算钉死**六分支组合、
  注入错 Z / 篡改逐项必 FAIL、制品少声明分支必 BLOCKED、审计抓
  `settlement_revenue`、ISO-2 运行时复读探针。
- CLI `ref-check`（--probe/--instance/--p-json/--z-solver/--json）。
- `docs/reference_review_signoff.json`：ISO-3 签署记录占位（`signed=false`）。

**变更**
- `Z_total`（全量，§5.3 S0）与 `Z_competitive`（目标层，X_opt）**两个名字**
  + `constant_part`（与 DV-02 同族：混用即静默偏掉一个常数）。
- `verify-solution` 未给 `--reference` 时默认向参考层索取 `Z_ref` 并自述来源
  ⇒ **SV-13 挂账闭合**：LP/MILP 两变体均 PASS（Δ=0 ≤ ε_Z≈0.0105）。

**修正**
- ★ 接线首跑即抓到真 bug：C7 的二值 `z_i` 与 `p_i` **共用 `item_id`**，按
  `item_id` 建 p 向量映射时 0/1 把单价覆盖掉（不报错，只让 `Z_ref` 静默偏小）。
  按变量族 `family == "p"` 过滤修复。★ 这条正是跨来源对照的价值实证——
  若参考层只是生产层的复制，该错误不会被任何判据发现。
- ★ 隔离③（作者分离）**不伪造**：机械判据无法证明「作者不是同一人」，
  故只读签署记录；未签 ⇒ BLOCKED，owner = 用户。未签前 T04-04 对拍结论强制 BLOCKED。

### extract_tasks --check 长期红修复（非破坏性，9 项漂移清零）

**修正**
- ★ **A 类（evidence 回灌）**：方向是「tasks.json 的富 evidence → 脚本 `EVIDENCE`
  字典」（存盘值更全），不是反向重写。修正了字典把 T00-06B 写成 `identity.py`
  的错误路径（实为 `total_price.py`+`money.py`），并补齐 T00-01/03/04/06/12 的
  缺失条目（T00-06 补 `project_classification_table` 两项）。
- ★ **B 类（人字段）**：`status_note`/`updated_at` 不在脚本 schema 内，原
  `build()` 不保留 ⇒ 重跑**静默删除**，且不在 `--check` 排除元组 ⇒ 一存在即恒判
  漂移。修复：`build()` 存在即原样保留（dry-run 验证零丢失）+ `--check` 排除
  元组扩为四个维护字段。
- `extract_tasks --check` 首次转绿（68 项一致）；全量 838 测试不受影响。

### T04-01 完成：Phase 1 解析解（排序+二分+贪心定容，ADR-0026）

**新增**
- `config/phase1_solver_spec.json`：算法步骤、λ 定义与种类、层域
  （BOUNDARY_LOW/INTERIOR/BOUNDARY_HIGH/FIXED/INFEASIBLE）、tie-break 支持集、
  PS-01..PS-11 判据（含区分度双向验证）。
- `src/bidpricing/solver/phase1.py`：`solve_phase1`（**只在 T04-00 已证明的
  适用子集内求解**；空 cap 临界项分支；平台 tie-break）+ `judge_phase1`
  （只吃实例与 p 向量，不读求解中间量）+ `phase1_report`（判据聚合，外层
  `check_solution` 做可行性裁判）+ 两个内置探针（free-cap / simple）。
- `tests/test_phase1_solver.py`：48 项，每条判据双向验证（注入错解必 FAIL、
  正确解必 PASS）。
- CLI `phase1-solve`（`--probe` / `--instance` / `--json`）。
- `docs/adr/ADR-0026-phase1-analytic-solver.md`。

**变更**
- `formulation._merged_lower` 提升为公开名 `merged_lower`（唯一实现不变，
  phase1 复用，不重实现下界与 R_i）。
- `solver/__init__.py` 导出 phase1 命名族；`verify-solution` 的 floor 来源
  解析抽为 `_resolve_floor_by_id` 共用实现。
- `docs/tasks.json`：T04-01 → `done`；`EVIDENCE` 同步（漂移集合保持 9 项）。

**修正**
- ★ **PS-06 首版只做单向交换探针**——只试「i↓j↑」，漏掉「先增后减」那一半；
  注入「把顶格项增价、临界项减价」的次优解逃过了检测。补齐双向后抓到。
- ★ **判据先于实现纠错的一次实证**：PS-11 在冒烟阶段抓到制品把
  eps_abs/eps_price/resolution 三个入参写成一条（实现读的是三个）——修制品，
  不是放宽判据。

### T03-02 完成：派生量计算（L/U/floor/r_eff 的唯一实现，闭合 SV-07 挂账）

**新增**
- `config/derived_quantities_spec.json`：四个派生量的唯一实现口径 + DQ-01..DQ-11
  判据 + 就绪性分层 + 三档治理落地 + 与 T03-03/03-04/04-01/04-02A/B/D/04-04 的交接表。
- `src/bidpricing/derived.py`：`compute_derived`（取大/取小/委派）+ `judge_derived`
  （**只吃 DerivedItem**，故判据可注入验证）+ `audit_derived_source`（AST 审计）
  + `inputs_from_project`（只读已落值位置，绝不代填）。
- `tests/test_derived.py`：55 项，每条判据**双向**验证。
- CLI `derive-check`（`--mu` / `--loss-acceptance` / `--unbalanced-json` /
  `--no-unbalanced-clause` / `--json`）。
- `docs/adr/ADR-0025-derived-quantities.md`。

**变更**
- `formulation.build_formulation` 的 `floor_by_id` 有了**唯一生产者**；
  `verify-solution` 默认由派生量层现场产出 floor（`--floor-json` 仍可覆盖）。
- `docs/tasks.json`：T03-02 → `done`；`tools/extract_tasks.py` 的 `EVIDENCE` 同步
  （漂移集合保持原样 9 项，均属待裁定的历史遗留）。

**修正**
- ★ **空 cap 的钳制**：`loss_acceptance=ACCEPT` 时 `floor_i := min(floor_i, cap_i)`
  **只在 cap 非空时生效**。空 cap 的合法语义是「不限价」而非 0——把它当 0 参与
  `min` 会把地板**静默压到 0**（地板失效且不报错）。
- ★ **L_i 多来源取大**：`max(实例下界, L_i^tender, 0)`，不是覆盖。条款启用但
  `tol_lo` 缺失 ⇒ BLOCKED（不编造阈值）；条款以 CAP 为基准而该项 cap 为空 ⇒
  **WARN**（可解释性档，不 BLOCKED、也不取 0 冒充）。
- **判据过紧的一处自纠**：DQ-10（声明—实现对账）原在「上游全 BLOCKED、无样本」
  时判 FAIL——把「没走到」当成了「已违反」。改为 SKIP，并保留另一条 DQ-09 守住
  真正的默认值泄漏。

**结果**
- `verify-solution` 的 **SV-07 由恒 BLOCKED 转为可判**：不给 floor ⇒ BLOCKED
  （4 条）；给 floor ⇒ **PASS**（BLOCKED 降至 2，余下即 SV-13 `Z_ref`，owner T04-08）。
- 测试 735 → **790**。`derive-check` 在真实项目上返回 1 是**设计**
  （μ 与 `unbalanced_clause` 尚无落值位置），故与 `verify-solution` 同列，
  **不进常驻验证环**。

### T04-02D 完成：解校验器（落地时实测出两处真缺陷 DV-01 / DV-02）

- `config/solution_verifier_spec.json`（新）：两层容差定义（内层 `eps_solver` /
  外层 `eps_abs`）+ **容差名 → 数值** 的解析表（封闭动词集 PROFILE_VALUE /
  PROFILE_TIMES_P_REF / PROFILE_TIMES_Q_REF / MAX_ABS_PRICE_P / CONST_ZERO，
  未列名字 ⇒ BLOCKED）+ 四族声明（可行性 / 目标值 / 上下界 / 层归属）+ 五类层归属
  （BOUNDARY_LOW / INTERIOR / BOUNDARY_HIGH / INFEASIBLE / AMBIGUOUS）+
  **SV-01..SV-13** + 判定聚合序 + 独立性（接口级 + 静态级）+ 参考值策略 + DV-01/DV-02 实录。
- `src/bidpricing/solver/verifier.py`（新，约 600 行）：外层复核层。`verify_solution(model, x, ...)`
  的入参**只有原始量**，**刻意不过载 `SolveResult`** —— 接口层面就够不着内层结论；再叠一层
  AST 静态审计（禁调 `evaluate` / `check_solution` / `solve_compiled`，禁 import 任何求解器包）。
- CLI `verify-solution`（LP/MILP 两变体各 13 条；`--instance` / `--reference` / `--floor-json` / `--json`）。
- `docs/adr/ADR-0024-solution-verifier.md`（新，6 条决策）。
- `tests/test_solution_verifier.py`（新，60 项）+ `tests/test_lp_compiler.py` 增
  `TestDeclaredTolerance`（6 项）+ `tests/test_solver_backend.py` 增 `TestBB08ToleranceCaliber`（6 项）
  + `tests/test_phase1_exactness.py` 增业务侧容差 4 项。

**修正（DV-01）：行上声明的容差名字从未被解析成数值 —— 内层用未具名的 1e-12**
`compiler.evaluate` 用硬编码 `ZERO_EPS = 1e-12` 判 `ok`，而各行声明的是容差**名**
（`eps_solver = 1e-8` 等），名字从未解析成数。后果：把 C1 残差注入 5.0e-9（**在声明
内层容差之内**的合法回传）即被判不可行，且 **BB-08 给出错误归因**「求解器在另一个模型上
求了最优解（导出层走样）」——而导出层是好的（CC-09 已 PASS）。探针看不见它（最优值可精确
表示，C1 slack 恰为 0）；真实规模项目上这是**必然触发**（HiGHS 原始可行容差 1e-7，
PuLP 报告前还就地舍入）。两半修复：
① **编译侧** `evaluate` 增 `tolerances` 入参（唯一来源 `verifier.resolve_tolerances`），
`RowEval` 拆 `ok_exact`（严格，旧口径）/ `ok`（按声明容差）/ `in_tolerance_band`；
② **业务侧** `check_solution` 增 `tolerances` 入参，盒式约束（`L`/`U`）改用**声明名**
`eps_price` 的宽度判（此前对 `L`/`U` 是严格比较、只有 C1 用 `eps_total` ⇒ 同一个
`p = U + 5e-12` 编译侧判可行、业务侧判不可行）——**只修一半比不修更隐蔽**：编译侧看起来
已按声明容差判了，只有把两侧结果摆到一起才看得出来。故 `SolutionCheck` 新增
`tolerance_name` / `tolerance_value` / `tolerance_resolved` **自述口径**，传了表却缺该名
⇒ `BB-08` 判 **BLOCKED**（不得静默按 0 冒充「两侧可比」）。
③ BB-08 归因随之改为按「是否传入声明容差表」自述：未传入时不得再说「导出层走样」。

**修正（DV-02）：`eps_price` 的两种读法被混成一个名字（「乘重一遍」同族）**
`eps_price` 既是**绝对**量（`profile.eps_price.value × P*`，行级容差宽度），又与
`compute_lb_c5` 的入参 / ε_Z 的相对项是**相对**量（无量纲因子）。把已 ×P* 的 `0.003`
再喂给 `compute_lb_c5` ⇒ `lb_C5` 由 0.01 元被放大成 9000 元，于是所有项被判越下界；
ε_Z 的相对项同时被放大 1.3e5 倍。这与历史上目标系数误写 `q1·r_eff`（应为 `q0·r_eff`）
同族：**同一个量被乘了第二遍**。修法：二者在制品里是**两个名字**——`eps_price`（绝对）
与 `eps_rel_price`（相对，同源同一个 profile 字段），各自的 `used_by` 显式登记。

**判据覆盖面与自省（不收紧容差，而是补/区分）**
- SV-03：容差带必须**被本实例走到**。探针的 C1 slack 恰为 0 ⇒ 带没被走到 ⇒ 判 **WARN**
  而非 PASS（「这一轮没走到」不得读成「已成立」）。
- SV-12：复核层不得消费内层结论 —— 用「入参无 `SolveResult`」做**接口级**保证 + AST 静态审计。
- SV-06：两层容差宽度比 `R2 = eps_abs / eps_solver = 1e6 ≥ 1e3`（ADR-0020 D1），否则复核层
  退化为内层判据的复制。
- SV-13：在 T04-08 落地前恒 **BLOCKED**；禁止用本层自算的业务式顶替（那与 CC-07 同源，
  构成恒真式）。
- 状态域：SKIP（本轮没查）/ BLOCKED（这一环没查成）/ FAIL（查出问题）三者不得合并；
  空判据集 ⇒ BLOCKED；聚合序 `FAIL > BLOCKED > WARN > SKIP > PASS`。

**仓外验证与双环境**
装 PuLP 环境：`backend-check` **18 PASS / 0 SKIP**（BB-09 的 CC-09 挂账闭合、BB-08 双侧含
新口径均 PASS）；`verify-solution` 在补齐 floor（T03-02）与 Z_ref（T04-08）后升到 **WARN**，
余下唯一 WARN 即 SV-03（探针走不到容差带）。测试 659 → **735**；零依赖环境 735 OK / 9 SKIP，
装 PuLP 环境 735 OK / 0 SKIP。

**未结（显式挂账，非缺陷）**：SV-07 的 floor 一路（owner T03-02）、SV-13 的 Z_ref
（owner T04-08），以及 `solve_compiled` 的 `eps_total` / `tolerances` 双入参**过渡态**
（已登记进 `solver_backend_spec.open_items`，应收敛为 `tolerances` 单一入参）。

### T04-02C 完成：求解后端适配层 + CC-09 复跑（挂账闭合，并修出两处静默走样）

- `config/solver_backend_spec.json`（新）：分层（业务层 / 适配层）+ 能力域
  （LP/MILP/QP/SOCP）+ 后端注册表（4 条目：pulp_highs / pulp_cbc /
  highspy_direct〔已声明未实现〕/ none〔零依赖占位〕）+ 选择策略
  （active / fallback_chain / **never_downgrade_capability**）+ 归一状态域
  （九值，class 与 judge 两张映射分开）+ 序列化约定 + **BB-01..BB-09** +
  静态审计基准（求解器包名单、import 白名单、solve 调用白名单、分支禁令）+
  环境观测与证据指针。**换后端 = 只改本制品的 `selection.active`。**
- `src/bidpricing/solver/backend.py`（新）：**唯一**允许接触求解器包的模块。
  `solve_compiled(CompiledModel) -> SolveResult` 是业务侧唯一入口；复用 T04-02B
  的导出层而不自建模型（自建等于绕过 CC-09）；惰性 import + 制品驱动的
  `solver_factory` getattr（代码里没有任何按后端名的分支）；解按 `pulp_name_map`
  回读；9 条 BB 判据（含 AST 静态审计与运行时全表遍历两类取证手段）。
- CLI `backend-check`（LP/MILP 两变体各 9 条；`--prefer` 用于替换性检验）。
- `docs/adr/ADR-0023-solver-backend-adapter.md`（新，9 条决策）。
- `tests/test_solver_backend.py`（新，62 项）：每条 BB 判据都配错误注入的区分度层；
  CC-09 六种走样注入；符号编码回归；上游常量实测回归。

**修正一：导出层把变量名交给建模器净化（静默改写模型语义）**
PuLP 在构造 `LpVariable` 时把 `+ - / > [ ]` 与空格一律换成 `_`。后果两条都不报错：
① 符号回读对不上（`p_P-DEC` 导出成 `p_P_DEC`）⇒ 解被判「全部变量缺失」；
② 两个不同符号净化后同名 ⇒ **两个决策变量静默合并成一个**（实测 `a-b` 与 `a_b`）。
修法：导出层自持**可逆编码**（白名单 `[A-Za-z0-9_]` 原样，其余编码为 `~%04x`），
CC-09 增判「编码在真实符号集上单射」与「往返一致」。穷举实测 PuLP 3.3.2 只改动
七个字符（`+ - / > [ ]` 与空格），清单记在 `MODELER_MANGLED_CHARS` 并由单测断言不相交。

**修正二：优化方向反向映射对反（`extract_pulp_structure`）**
按直觉写成 `{-1: MINIMIZE, 1: MAXIMIZE}`，实测 PuLP 是 `LpMinimize = 1` /
`LpMaximize = -1`（与直觉相反）——把最大化读成最小化。修正常量表并加实测回归
（PuLP 可导入时直接对 `pulp.LpMinimize` / `pulp.LpMaximize` 断言）。

**修正三：CC-09 覆盖面不足（属补全覆盖面，不是收紧容差）**
原实现只比变量集、行数、逐行 sense、逐行 rhs 与目标系数。而导出层最常见的三种
走样恰好落在未覆盖区间：系数漏乘/错位、目标常量丢符号、最大化↔最小化反向——三者
都满足「变量集相同、行数相同、sense 相同、rhs 相同、目标系数相同」。补齐逐行系数
多重集 + 目标方向 + 目标常量，并把行比对由「按下标」改为「按指纹多重集配对」
（与 CC-02 同构；原按下标隐含假设了「模型行序 == 约束插入序」，该假设从未声明）。

**修正四：判据不得在它该拦的输入上崩**
`to_pulp` 原先在符号闭包缺口时让 `lpSum` 抛 `KeyError`，把整条校验以异常形态炸掉
（而不是报一条 FAIL）。改为构造前自查并抛 `CompilerError` ⇒ CC-09 归一 **BLOCKED**，
且与「本机没装 PuLP ⇒ SKIP」分成不同出口，不再互相顶替。

**修正五：输出文案里的环境断言不得硬编码（与决策二同一条根因）**
`compile-check` / `backend-check` 的「N 条 SKIP」提示原先写死「本机无 PuLP ⇒ CC-09 恒为
SKIP」——在装上 PuLP 的机器上这是假话（CC-09 已实跑并 PASS，剩下的 SKIP 是 LP 变体
CC-08 那类结构性豁免）。改为读具名探针 `compiler.pulp_available()`（探测方式与 `to_pulp`
逐字相同）决定文案；探针住 `compiler.py` 而非 CLI（BB-03 只许声明过的模块 import 求解器包），
并加单测断言探针与导出层**答案恒等**。测试侧同类问题一并纠正：`TestCheckLayerGreen`
原先断言 `CC-09 == "SKIP"`（只在零依赖机器成立），改为按 `import pulp` 探测取值——
**缺能力时假 PASS 与有能力时假 SKIP 同属回归**。

**状态分域（本里程碑的核心设计）**
求解器的答案（有没有解、最优值多少）与判据的答案（这一环走样没有）分属两个枚举。
四条关键裁定：① `AMBIGUOUS` 独立存在——HiGHS 的 `kUnboundedOrInfeasible` 与 PuLP 的
`Undefined` 都自带歧义，折进 INFEASIBLE 是无据断言、折进 ERROR 是无据归因；
② 「超时」不含结论——`kTimeLimit` 等按有无 incumbent 分叉（有 ⇒ FEASIBLE 未证最优，
无 ⇒ UNSOLVED）；③ `UNAVAILABLE`（环境缺失 ⇒ SKIP + 复跑条件）与 `UNSUPPORTED`
（机制缺失/能力不足 ⇒ BLOCKED）分属不同档；④ 原生别名表整张住制品，适配层源码不得
出现任何别名串（BB-05 静态子判据）。

**替换性实证**：`active` 由 `pulp_highs` 改为 `pulp_cbc`（或 `--prefer`），**源码零改动**，
HiGHS 与 CBC 给出同一最优值 460000.0、业务侧 C1 残差 0（0.004 s vs 0.057 s）。
BB-06 在只有一个候选时判 **FAIL 而非 PASS**（无第二候选即无证据）。

**验证环境**：为闭合 CC-09 在**仓外**建隔离 venv（PuLP 3.3.2 + HiGHS 1.15.1），
仓内维持零第三方依赖——无 PuLP 时 BB-07/BB-08/BB-09 与 CC-09 判 SKIP
（**SKIP ≠ PASS**），BB-01..BB-06 仍全部可判。`backend-check`：零依赖环境
12 PASS / 6 SKIP / 0 待处理；装 PuLP 环境 **18 PASS / 0 SKIP / 0 待处理**。
`compile-check`：零依赖 21 PASS / 3 SKIP；装 PuLP **23 PASS / 1 SKIP**（余下 SKIP 为
LP 变体 CC-08 的结构性豁免）。

**上游漂移（实测并挂账）**：`PULP_CBC_CMD` 已弃用（4.0 移除）⇒ `pulp_cbc` 是随版本
失效的第二候选，升级须同步改制品，否则 BB-06 会（真地）退化为「只有一个候选」；
`LpVariable(name, ...)` 直接构造与 `prob.constraints` 字典用法 4.0 将变（影响面在
T04-02B 的导出层，CC-09 的接口面已刻意压到最小以便枚举影响）。

**CC-12 在适配层新写的代码上当场生效**：`int(..., 16)` 的裸进制被自己抓出，提成
`SYMBOL_ESCAPE_RADIX`。判据不是事后合规检查，它参与实现。

测试 587 → **659**（零依赖环境 659 OK / 9 SKIP；装 PuLP环境 659 OK / 0 SKIP，
其中 `test_solver_backend` 62 项、`test_lp_compiler` 新增探针一致性 1 项）。

### T04-02B 完成：约束编译器 + 三处口径修正（含推翻 ADR-0021 一条公式）

- `config/lp_compiler_spec.json`（新）：目标形式（与建模器/求解器无关的
  `CompiledModel`——零第三方依赖环境下的硬约束）+ 展开规则（C9 从目标系数复制、
  C10 从 T_front 三元组）+ 化简规则（DEGENERATE_DOMINATED / DEGENERATE_FIXED /
  NOT_COMPILED）+ 后端（PuLP 缺失 ⇒ CC-09 SKIP）+ 字面量白名单 + **CC-01..CC-12**。
- `src/bidpricing/solver/compiler.py`（新）：`Formulation` → `CompiledModel` 的机械
  翻译（系数逐项复制、不改写）；零依赖求值器 `evaluate`（CC-07 的编译侧独立实现）；
  惰性 PuLP 导出 `to_pulp` + `extract_pulp_structure`；12 条 CC 判据。
- CLI `compile-check`：LP/MILP 两变体各 12 条判据（**21 PASS / 3 SKIP / 0 待处理**）；
  `--json` 输出完整模型供 T04-02C 消费；新增 `--n-max/--theta/--d-max/--z-min/
  --pi-target/--tf-terms`（占位行展开所需的求解层入参，缺省即 BLOCKED 而非静默）。
- `tests/test_lp_compiler.py`（新，32 项）：含**区分度层**——把 12 条判据各自的错误
  实现注入回去逐条确认会 FAIL/BLOCKED；另加 `evaluate`、惰性导出、字面量审计三组。
- **修正 1（真 bug）**：C7 双向指示式原两式共用 `M = c_i − lb_i`，而两式恒真条件
  不同（下式覆盖下界、上式覆盖上界）⇒ 第三式在 `z=0` 处切掉 `[c_i, ub_eff]` 的大部分
  区间（实测 c=50/lb=45/ub=120/eps=0.01：共用 M=5 把合法区间从 `[50,120]` 压到
  `[50,54.99]`）⇒ 业务侧判可行、编译侧判违反，误报 infeasible 且不报错。已拆
  `M_lo`/`M_hi` + 有效上界 `ub_i^eff` + 退化固定（z 固定界而非删除、C7 汇总 RHS
  扣减 `n_fixed_one`）。CC-08 锁死。
- **修正 2（真 bug）**：目标系数原写 `q1_i·r_eff_i`，正确为 `q0_i·r_eff_i`
  （`= ∂R_i/∂p_i`，因 `c_i·q1_i` 与 p 无关）——写成 q1 等于把 LP 排序键
  `(目标系数)/(C1 系数)` 又乘一遍 `r_i` ⇒ 解满足全部约束但**次优**且不触发任何
  可行性检查（T04-00 EC-2 的失效模式）。由 CC-07 跨来源代回实测抓到（编译侧
  676000 vs 业务侧 420000）。已修 + 数值差分回归测试。
- **修正 3（口径，推翻 ADR-0021 决策一）**：ADR-0021 写「`∂Z/∂p_i = q1_i·r_eff_i`」
  是错的，由 ADR-0022 决策三推翻。旧表述已全仓 grep 并同步修正
  （`lp_formulation_spec.relation_to_objective`、`formulation.objective_expr`、
  `lp_compiler_spec.coefficient_rule`、compiler 文档串）；ADR-0021 不可变，保留原文
  由 ADR-0022 记录推翻关系。
- **裁定**：C11 移出 LP 改 `DISCRETE_CHECK`（σ 是二阶锥、HiGHS 无 SOCP；MAD 替代由
  Cauchy-Schwarz 是放松，最坏 √n＝本项目 10.72 倍；原式 `(1/n)Σ|p−p̄|` 不含 `base_i`
  未归一化）。两份制品同落 `DISCRETE_CHECK`，由 CC-10 锁死。
- **判据自身两处误报**：CC-12 首版按**值**白名单，把模块自身容差（1e-6/1e-9）与
  切片下标（`term[2]`）报成「手写系数」——**判据把正常实现报成违规**。改判
  「**数值必须具名**」：`SLACK_ATOL = 1e-9` 通过、`0.85*cap` 被抓。
- **CLI 契约漂移**：误读 `literal_allowlist.allowed`（正确键 `allowed_in_expressions`），
  读错会静默退回模块默认值 ⇒ 「制品是白名单的真相来源」不成立。已修。
- `formulation.PROBE_SOLVER_INPUTS`（新）：探针的求解层入参（合成值）。否则
  C6/C7/C9/C10 占位行 rhs 恒为 None ⇒ 恒 `NOT_COMPILED` ⇒ 探针覆盖不到编译路径
  （首跑 MILP 变体 CC-05 恒 BLOCKED 的根因）。
- ADR-0022（新）。测试 555 → **587**。contract-check 17/17；Gate 0a/0b/Phase 0
  输入门全 PASS；WP4 构建 ALLOWED；phase1-check 10/10；ruleset-selftest PASS；
  freeze 14 项。

### T00-04 / T00-03 / T00-06 结清 + T04-02A 完成：LP 模型形式化

- `config/precision_profile.json`：`equality_tolerance_mode.current = "A"`
  （内部严格等式 + 输出层独立舍入调和）。三条机械判据：D1（决定性，与 benchmark
  无关）模式 B 使内外层判据同宽 ⇒ 复核层退化为内层判据的复制；D2 容差带
  R1 = eps_solver/HiGHS 默认容差 = 0.1 < 1 ⇒ 无任何放宽收益；D3 benchmark_status
  = NOT_RUN ⇒ 未证收益不得交换已证语义性质。含 `reopen_condition`（D1 不可交易）。
  冻结 hash → `sha256:146e8e6ffbc4`。
- **T00-03 / T00-04 / T00-06 三个前置任务结清**（制品早已就绪，状态漂移系任务板
  未跟进），T04-02A 依赖解封。
- `config/lp_formulation_spec.json`：变量/非变量/参数/索引集/目标/C1–C13 逐条
  映射/箱型预处理/求解器形态/F 判据 11 条/消费者/挂账。**核心结论**：目标对 `p`
  严格线性（`r_eff` 全外生 ⇒ P1 分支建模期已知）⇒ LP 成立，MILP 唯一来源是 C7
  的二元变量；`∂R/∂p = q0·r_eff`（目标系数**同此**——2026-09-17 修正：本行原文写
  「`∂Z/∂p = q1·r_eff` 是两个不同的量」是**错的**，正确为 `∂Z/∂p = ∂R/∂p = q0·r_eff`，
  见 ADR-0022 决策三）。
- `src/bidpricing/solver/formulation.py`：把实例编译为求解器无关的 LP 词汇
  （**只形式化、不建模**——建模是 T04-02B，后端是 T04-02C）。新增本地状态域
  **SKIP**：缺实例时「没检查」必须与「检查过且通过」可区分。
- **三条约束改变位置**：C5 的 LP 下界抬到报价分辨率（否则 P*=1e6 时解为 1e-3 元，
  舍入成 0.00 ⇒ 提交的报价违反 C5）；C12 在可行域上是常量 ⇒ 作 `P*` 的前置
  可接受性判据而非 LP 约束；C11 的 MAD/σ 替换方向相反 ⇒ 挂账给 T04-02B。
- CLI `formulate-check`：LP 与 MILP 两变体各 11 条判据，**22/22 PASS**。

#### 修正

- `settlement_revenue` 的区间内分支漏了作用域判断：`SEGMENT ∧ alpha≠0` 时它返回
  含 `(1+alpha)` 的收入，而 `compute_r_eff` 返回 `r` ⇒ 相差 `(1+alpha)` 倍。按
  §5.3.1（alpha 只作用于 FULL）后者为错。`alpha = 0` 时完全不可见。
- `status.check_evidence` 第三处缺口：phase_0 的项目级输入
  （`project_classification_table`）本就不做版本冻结，按「hash 已冻结」判会永远
  不成立 ⇒ 改用「文件存在」，与 Phase 0 输入门的「声明式就绪」同向。
- 判据自身的一处反向风险：F-02 首版借道 `instance.r_eff`，被实例 `Phase1Params`
  覆盖了传入的 scope，**自己制造出假 FAIL**。据此确立原则：**判据的覆盖面不得
  取决于被测数据**（F-02 自扫 FULL/SEGMENT，不沿用实例 scope）。

### T04-00 完成：Phase 1 精确性条件与反例集（WP4 求解层第一块）

- `config/phase1_exactness_spec.json`：九条条件 `EC-1..EC-9` + 九个反例
  `CE-01..CE-09` + 一个正例 `PE-01`。每条条件含形式化命题、机械判据、
  违反后果与对应反例；每个反例含「误用解 vs 正确解」的数值见证。
- `src/bidpricing/solver/`：`instance`（Phase 1 论域与解校验）、
  `exactness`（EC 判定器）、`cases`（反例集机械复算器）。
- CLI `phase1-check`：跑制品里的全部实例，把 `expected` 与 `witness.assertions`
  逐条喂给实现——**制品与实现的双向锁定**。
- **证明路径**：定理 T1（阈值分割）用**交换论证**证明，不走 KKT。
  KKT 是 T04-02A/D 的实现路线，两者共用会让证明与实现按同一个误解同时成立，
  T04-08 的独立性验收即失去对象。
- **条件分两组**：A 组（EC-1..EC-7）违反 ⇒ 阈值分割解不是 P_A 最优解；
  B 组（EC-8 舍入可调和 / EC-9 上界有限）违反 ⇒ 只加实现性义务。
  `verdict` **只看 A 组**——首版把 EC-8 归 A 组的结果是任何实例都判不出
  `EXACT`（舍入上界 `0.005·Σq0` 几乎总超 `eps_total`）。
- **本项目真实结论**：EC-9 对西永L样本判 WARN（存在不限价项
  `031301017001`），故 Phase 1 算法**必须内建「空 cap 项固定为临界项」分支**，
  不得依赖「所有项都有 cap」这一假前提。
- 修正 `compute_r_eff` 的 SEGMENT 分支：`increase_threshold` 本身已是
  `(1 + θ_dev)`，原式再加 `1.0` 使越界段 `r_eff` 被系统性高估
  （例 2R 的 r=1.6 处算成 2.04 而非 1.24）。附录 B 例 2R 的期望值用例抓到。
- 新增 `compute_r_eff` / `settlement_revenue` 于 `contracts/pricing_card.py`
  作为**唯一实现**，测试用 `compute_p1` 逐值交叉锁定，防止出现第二事实源。
- 测试 477 → **527** 项；`phase1-check` 10/10 一致；contract-check 17/17；闸门全 PASS。
- **发现（既存，未修）**：`tools/extract_tasks.py --check` 长期报「任务板已过期」——
  `tasks.json` 中多个任务的 `evidence` 多于脚本内 `EVIDENCE` 字典（历史上手改过
  派生物）。本轮已把 T04-00 的证据写进 `EVIDENCE` 单一来源，其余任务的对齐
  需重跑 `extract_tasks.py`（会重写结构字段，属破坏性操作，待确认）。

## [boq-parser-v1] — 2026-09-16

### T01-00B 完成：清单解析器（WP1 第一块落地）

- `src/bidpricing/io/xlsx.py`：零依赖 xlsx 读取器（zip + XML，stdlib only）。
- `src/bidpricing/io/boq.py`：解析器。表号 → 角色识别；「逻辑字段 → 别名集合」
  双键列识别（命中 0 或 ≥2 即失败，**不猜**）；双行表头合并（综合单价/合价/
  暂估价在子表头行）；分节标题行四信号合取判据（编码列放分节名 C/B.3/一 +
  工程量/单价/单位/特征全空）；空值口径（空值 ≠ 缺行）；复合主键
  (project_id, unit_work, item_id)；code_kind 三分类、位数不判合法性。
- CLI `parse-boq`：三项产出（解析日志 JSON / 字段映射报告 md / 失败样本 csv）
  落盘 `docs/parsed/<文件名>/`。
- 真实配对样本实测：82 行、0 失败、键集合两侧一致；加权下浮 **8.0084%** 与
  已固化 pair.json **独立复算一致**（交叉印证）；确认已知数据缺口
  `031301017001 脚手架搭拆`（限价侧综合单价为空、报价侧 1370.75）。
- 新增 contract-check 第 11 项判据 `io.column_aliases_mirror`：代码侧别名表
  与契约 `listing_structure.column_aliases` **逐字一致**——两处独立存在即有
  漂移风险，解析器实际按代码侧工作。
- 测试 192 → **211**（+19）；Gate 0a 仍 PASS。

---

## [bound-clauses-v1] — 2026-09-16

### 单项下界的两类真实依据；输入 A 结构按真实文件固化

**背景**：用户指出两件事，都成立——

1. 用户实际提供的限价清单**就是**那份真实文件的结构（只是清单项与数据会不同）。
   此前所有输入口径都是照 3 份**示例模板**推的，而那些示例是**结算期**的表格。
2. 记录者把用户「只会限制①各项单价②整个项目总价」外推成了
   「用户明确：**没有给出单价下限**」。用户否认：原意是**有最高限价**，
   且**单项报价不能为 0**，且**有时有不平衡报价条款（如 ±50%）**。

#### 修正（本里程碑最重要的一条）
- `input_protocol_schema.open_issues[OI-04]` 重写，并**永久保留纠正留痕**：
  `correction.what_was_wrong` / `user_actual_words` / `failure_mode`。
  撤销的旧结论不删除——它解释了为什么 C3 曾经按 `δ⁻` 单来源设计。
- 新增 `docs/adr/ADR-0007-沉默不是断言.md`：把「用户未提及」记成「用户已声明为无」
  是一类结构性失效，与 ADR-0004（未定态 = key 完全缺失）同源——
  那条管机器，本条管人。

#### 变更 — 输入 A 结构固化
- `input_protocol_schema.listing_structure`（新增）：按真实文件固化
  6 张表（表-04 / 表-09 分部分项 / 表-09 技术措施 / 表-10 组织措施 / 表-11 其他 / 表-12 规费税金）、
  双行表头、**列名别名表**、分节标题行、单位工程维度、空值口径、总价限价位置。
  **关键修正**：真实限价清单单价列名是「**综合单价**」，而示例模板是「**最高限价**」
  → **禁止硬编码列名**，必须走「表号 + 别名集合」双键识别。
- 新增口径 **空值 ≠ 缺列/缺行**：限价侧普遍「列在、行在、值空」
  （合价列存在但为空、合计行存在但为空）。与 ADR-0006 同源。

#### 变更 — 约束层
- `constraint_schema.C3` **重定义**：由 `p_i >= base_i(1-δ⁻)` 单一来源
  改为**多来源取大**。δ⁻ 只在招标文件明示幅度时参与，否则不得编造；
  δ⁻ 取 0 会把报价钉死在限价上，是荒谬解。
- `constraint_schema.C5` **由 P1 升为 P0 且不可关**：语义由「非负性（求解器保险）」
  改为「**单项报价不得为零**」——用户明确这是招标条款，`p_i = 0` 算术上满足
  `p_i >= 0` 却直接违反招标文件。
- `constraint_schema.C13`（**新增**）：不平衡报价幅度约束（条件性）。
  声明 **4 条机制分支**（`BID_VALIDITY` / `SETTLEMENT_ADJUSTMENT` / `SCORING` / `NONE`）——
  前者是 `X_opt` 硬约束，中者是 `R_i(·)` 的改造而**不约束** `X_opt`，二者落点完全不同。
  机制进 Gate 0a（两分支都要实装），取值属 Phase 0。
- `constraint_schema.C4` 注释更新：显式声明它引用的是**重定义后**的 C3。

#### 新增 — 字段
- `field_schema` 新增 5 字段：`zero_price_prohibited`、`unbalanced_clause`（整块声明）、
  `unbalanced_reference`、`unbalanced_tolerance`、`unbalanced_mechanism`。
  全部 `missing_policy=BLOCK` 且**无默认值**。

#### 新增 — 第四条验证环 `contract-check`
- `src/bidpricing/contracts/consistency.py` — **跨制品一致性判据**（10 项）。
  与 `gate-check` 正交：后者判「制品是否被改动」，本判据判「制品彼此是否自洽」。
  一份**未被改动**的制品集照样可以自相矛盾——本项目已实测两次，两次都靠人眼发现：
  ① `field_schema` 写「13/15 位体系」而 `input_protocol_schema` 写「位数不参与判定」；
  ② `code_system.range` 与 `rule_set_id.range` 两个**本应相等**的枚举两种写法。
- 核心判据 `constraint_schema.inputs_declared`：约束引用的每个输入必须已在
  字段字典中声明（拦截「新增约束忘了加字段」）。
- 判据 `field_schema.enum_agreement` **必须比对原始字符串，不得先归一化**——
  归一化会把事故里的两种写法折叠成同一个值，等于判据自我取消。
- **反向断言**：`test_historical_code_system_spelling_bug_blocks` 精确复现事故写法，
  锁住该判据不得退化为归一化比对。
- `bidpricing contract-check` 子命令；`README` / `GOVERNANCE` 同步（三环 → 四环）。

#### 清理
- `tools/xlsx_dump.py` / `tools/xlsx_compact.py` — 零依赖 xlsx 读取器
  （本机无 openpyxl / pandas；xlsx 即 zip + XML，直接解析即可）。
- `cli.py` gate-check 的提示文案改为**只针对实际阻塞项**输出——
  原先 `adjustment_scope` 已落值却仍打印「选择项取值未定」，指向一个不存在的动作
  （与 `d3f358e` 修的是同一类毛病）。

#### 制品重新冻结
| 制品 | 旧 hash | 新 hash |
|---|---|---|
| `field_schema_version` | `sha256:7837eac655a6` | `sha256:26b940c21e0b` |
| `constraint_schema_version` | `sha256:9…` | `sha256:ebed21c439e8` |
| `input_protocol_schema` | `sha256:d6a26c25f5aa` | `sha256:41dc4f1bbd6e` |
| `rule_set_selector_spec` | `sha256:0dd335b5a8ae` | 不变 |
| `precision_profile_version` | `sha256:6ce483e8d221` | 不变 |
| `architecture_decision_version` | `sha256:3601adeed46c` | 不变 |
| `competitiveness_classification` | `sha256:2913378715d5` | 不变 |

#### 测试
- 165 → **192** 项（新增 `tests/test_contract_consistency.py` 25 项 + `test_status.py` 2 项）。
- `src/bidpricing/status.py` 采集并渲染跨制品一致性——**状态数字一律不手写**，
  快照里的「10/10」是复算出来的，不是抄的。
- Gate 0a 仍 **PASS 8/8**；`contract-check` **PASS 10/10**；
  Phase 0 输入门仍 BLOCKED（仅 `project_classification_table`）。

#### 待用户裁定（新增 OI-05）
- 「±50%」的**基准**是什么（cap / 控制价 / 评标基准价 / 成本占比）？
  若基准 = cap，则上浮侧与 C2 矛盾，条款实际只约束下浮侧。
- 超幅的**后果**是投标有效性问题，还是结算调整条款？
- 该条款在什么条件下出现（逐项目 / 金额门槛 / 计价方式）？

#### 同时发现的待确认项
- **总价限价不在限价清单文件内**：实测该文件表-04「投标报价合计 8,623.74」
  只等于措施 7,834.06 + 税金 789.68（分部分项为空），而单项就有 176,068.11 的变压器
  ——它绝不可能是总价限价。`P*_max` 须由用户**另行提供**，不得外推。

---

### 真实样本接入：总价恒等式获得外部锚点（2026-09-16）

**背景**：拿到第一份**同一项目**的「招标限价 + 投标报价」配对样本
（西永L分区公立学校一期工程等项目配电工程，电气设备安装工程，81 条明细）。
此前只有分属不同项目的示例模板，跨项目恒等式不闭合（实测差 3.21 倍），
中心不变量始终没有真实样本背书。

#### 新增
- `tests/data/xiyong_l_district/pair.json` + `PROVENANCE.md` — 首份真实配对样本。
  含限价/报价两侧逐项 81 条（编码、名称、单位、工程量、限价单价、报价单价、合价）、
  措施表、其他项目表、规费税金表、表-04 汇总值，并逐列记录提取口径。
- `src/bidpricing/identity.py` — **总价恒等式的可执行判据**。
  `Totals` / `TaxDecomposition` / `decompose()` / `check_identity()` /
  `check_component_sum()`；容差取自 `precision_profile.json` 的
  `eps_total = max(eps_abs, eps_price × P*)`，**求解层与复核层共用同一函数**。
- `bidpricing identity-check` 子命令 — 对样本执行数值判据，支持 `--side bid|cap`。
- `tests/test_identity.py` — 33 项用例。
- `docs/adr/ADR-0005-恒等式闭合不等于数据完整.md`。

#### 修正
- `src/bidpricing/status.py` — `check_evidence` 新增 `file` 证据类型
  （数据类制品存在即成立），与 `module` 判定方式相同、语义不同。
- `tools/extract_tasks.py` — 登记 T00-06B 的模块证据、T01-02C 的样本证据。

#### 实测结论
- **报价侧恒等式精确闭合**：残差 **0.0000**。
  增值税 115,790.94 / 附加税 13,894.91 / 税金 129,685.85 / 总价 1,416,251.85，
  与源工作簿逐项相符。
- **限价侧也闭合（残差 0）但数据不完整**：其表-04「分部分项工程费」为空，
  逐项单价合计实为 1,374,238.77 元。据此确立 **ADR-0005：闭合 ≠ 完整**，
  完整性由独立的「输入保真」判据承担。
- **实证 D3 建模口径**：安全文明施工费在限价与报价中**同为 7,834.06 元**，
  投标人未改动 → 外生固定常量，进总价、不进 `X_opt`。
- **报价结构不是单一系数下浮**：加权总下浮 8.008%（0.919916），
  逐项下浮比呈明显分簇——0.810（标识牌 12 条）/ 0.833（补充编码绝缘工器具 10 条）/
  0.918（变压器与低压柜 13 条）/ 0.981–0.984（调试类几乎不下浮）。
  这一组聚类即模型要回答"是否最优"的对象。
- 编码实测：12 位 67 条 + 6 位 14 条，无 13/15 位；序号在分节内各自从 1 重算
  （安装工程 52 条 / 准备运行费 29 条），实证"不得用序号作主键"。

---

### 工程治理（2026-09-16）

#### 新增
- `docs/STATE.md` — **状态快照，自动生成**。含版本锚点、三闸门状态、制品冻结表、
  现场测试结果、任务进度、自动派生的下一步、遗留项汇总。
  由 `bidpricing status --write` 生成，头部标注"勿手改"。
- `docs/tasks.json` — 机器可读任务板，68 项任务。结构字段从路线文档派生，
  状态字段人工维护，二者互不污染。
- `docs/adr/` — 架构决策记录目录。新增 ADR-0002（判定时点与机制数据分层）、
  ADR-0003（状态快照自动派生）、ADR-0004（未定态必须是机器可判状态）。
- `tools/extract_tasks.py` — 路线文档 → 任务板的单向派生器，含 `--check` 校验模式。
- `bidpricing status` 子命令 — 支持 `--write` / `--json` / `--print-md`。
- 本文件 `CHANGELOG.md` 与 `docs/GOVERNANCE.md`。

#### 变更
- `docs/ADR-0001-three-layer-separation.md` → `docs/adr/` 目录（用 `git mv` 保留历史）。

#### 修正
- **消除三处文档漂移**（详见 ADR-0003）：`README.md` 的「Gate 0a 6/8」、
  `DEVELOPMENT.md` 的「89 项测试」、以及已被推翻的「真实清单=开工前置」表述。
  改为统一指向自动生成的 `STATE.md`。

---

## [classification-declaration-v1] — 2026-09-16

### 分类改为「声明 + 例外」；判据由《行数》改为《声明式就绪》

**背景**：用户 2026-09-16 提出两点，均成立——

1. 「如果没有特殊说明，分部分项清单里面的应都是可竞争项，所以为什么要做这个分类？」
   → 分部分项清单内**缺省即可竞争**，例外（`其中:暂估价` 列 / 甲供材）在清单里
   **是列**、机械可读，不需要人工逐行填表。原设计属**过度设计**。
2. 用户同时说明**实际可提供的资料**只有两份：招标限价清单（逐项只有单价、
   不超限价；另给一个项目总价限价金额）+ 成本清单（编码/名称/特征/单位一致，
   工程量不同、单价为成本价）。此前所有输入契约都是照**示例模板**推的，不是
   照用户实际能提供的资料推的——这是本轮 3 项 OI 的根因。

#### 变更
- `config/competitiveness_classification.json`（规则书）：新增
  `assignment_scope.defaults_and_exceptions`——逐张清单的**缺省角色**与
  **例外信号**（`role_defaults_by_list`）；`assignment_scope.answer` 改为区分
  「优化对象的主体」与「总价的完全划分」两件事；`assignment_protocol` 改为
  声明式（`artifact_shape` / `readiness_criterion` / `exception_row_fields` /
  `coverage_check_location`）。
- `config/project_classification_table.json`（项目级）：结构由 `rows[]`
  改为 `project_id` / `code_system` / `covered_lists` / `external_constants` /
  `exceptions` / `search_basis` + `field_semantics` 逐字段说明。
- `config/gate0_registry.json`：`phase_0` 规格改为
  `required_scalar_fields` / `required_list_fields` / `required_covered_list_fields` /
  `required_exception_row_fields` / `required_external_constant_fields`。
- `src/bidpricing/gates/gate0.py::_check_project_input`：**重写**为三层声明式判据。
  必需 key 缺失 → BLOCKED；**列表字段取 `[]` → PASS**（已核查、结论为空）；
  逐条校验缺省角色、例外行字段与角色、外部常量取值与依据。
- `docs/adr/ADR-0006-声明式就绪而非行数.md`。
- 文档同步：`README.md`、`DEVELOPMENT.md`、`src/bidpricing/paths.py`、
  `gate0.py` 模块说明、`cli.py` 的 gate-check 提示文案。

#### 修正
- `config/field_schema.json` → `item_id.note` 仍写「13/15 位编码体系由
  code_system 区分」——该口径早在 D1 裁定中删除，输入协议已明写「位数不参与
  合法性判定」。**同一份字段字典与输入协议对同一条规则说法相反**，已修正。
  （教训：删除一条口径时必须全仓搜索旧表述。）
- `config/field_schema.json` → `code_system.range` 原写 `GBT50500-2024`（无斜杠），
  而同一文件的 `rule_set_id.range` 写 `GB/T50500-2024`，且该字段的注释要求
  「与 rule_set_id 一致性校验」。**两个应当相等的枚举用了两种写法**，已统一。

#### 新增（待决问题登记）
- `config/input_protocol_schema.json` → `open_issues`：
  - `OI-01` 成本清单工程量与招标清单不一致 → **RESOLVED**：该量即预估结算量
    `q1`，输入 B 由输入 C 兼任；须补 `attribution` 归属标签。
  - `OI-02` 限价清单单价是 cap 还是 base → **RESOLVED**：仅最高限价，
    `base_i := cap_i`；连带 **δ⁺ 失效**（`U_i ≡ cap_i`）。
  - `OI-03` P* 由谁定 → **RESOLVED**：用户定总价，模型给最优单价结构，不扩范围。
  - `OI-04` **新增**：`C3` 合规下界 `L_i` 缺招标依据（招标文件不设单价下限），
    `δ⁻` 取值来源未定 → PENDING_USER_DECISION。

#### 制品重新冻结
| 制品 | 旧 hash | 新 hash |
|---|---|---|
| `field_schema_version` | `sha256:858b0c997f85` | `sha256:7837eac655a6` |
| `competitiveness_classification` | `sha256:5610c8d879dd` | `sha256:2913378715d5` |
| `input_protocol_schema` | `sha256:92c3edea3d46` | `sha256:d6a26c25f5aa` |

#### 测试
- 155 → **165** 项（`ProjectInputArtifactTest` 由 6 项重写为 15 项，含
  `test_missing_exceptions_key_blocks_while_empty_list_passes` 这一**反向断言**：
  同一 payload，`[]` → PASS，删 key → BLOCKED）。
- Gate 0a 仍 **PASS 8/8**；Phase 0 输入门仍 BLOCKED（现为「声明未就位」而不再是「表为空」）。

> 里程碑索引见文末。

---

## [classification-split-v1] — 2026-09-16

> 修正 commit `a17e07c`：`fix(t00-06): 分类表拆为机制层/数据层 —— 真实清单不再是开工前置`

### 修正
- **T00-06 拆分**（用户质疑"为什么需要真实清单"）：
  - `config/competitiveness_classification.json` 收敛为**规则书**（角色集合 + 启发式 + 覆盖范围
    + 外生常量），删除 `classification_table` 与 `freeze_blocker`；
  - 新增 `config/project_classification_table.json` 作为**项目级落值表**（数据侧）；
  - 注册表新增 `phase_0` 段；`gate0.check_project_input_artifacts` 校验文件存在 → 行非空
    → 逐行字段与 `pricing_role` 合法；**注册表未声明时判 BLOCKED，不允许空真通过**。
- 分类表覆盖范围明确为**分部分项 + 表-09 + 表-10 + 表-11 四类清单**
  （非"选一套做基准"）：只取分部分项会丢失表-09 的可竞价空间与表-10 的唯一
  `NON_COMPETITIVE` 实例。

### 结果
- **Gate 0a = PASS（8/8）**，放行 WP1 / WP2 / WP3。
- Phase 0 输入门 = BLOCKED（`adjustment_scope`、`project_classification_table`）。
- 测试 98 项全通过。

---

## [options-phase-split-v1] — 2026-09-16

> 修正 commit `315f53d`：`fix(gate): 选择项判定时点后移 —— 机制就绪与取值已定拆为两个时点`

### 修正
- **`adjustment_scope` 判定时点后移**（用户质疑"为何一定要现在确定"）：
  `check_selectable_option` 增加 `phase` 参数，拆开两类判定：
  - `phase="gate_0a"` → 只判**机制就绪**，取值未定 **PASS**；
  - `phase="phase_0"` → 判**取值**，未定 **BLOCKED**。
- 新增 `check_phase0_inputs` —— §7.1.1 断言 2「Phase 0 直接 BLOCKED」的正确落点
  （早前误挂在 `check_gate_0a` 上）。
- 配置冲突（2013 落 `FULL`）在**两个时点下都 BLOCKED**，不因时点放行。

### 变更（回应实测偏差 D1/D2/D3）
- `input_protocol_schema.json`：**删除「13 位 / 15 位」编码位数对应关系**，
  改为 `code_identity_policy` —— 位数不参与合法性判定，唯一键含 `unit_work`。
- `competitiveness_classification.json`：新增 `external_constants` ——
  安全文明施工费 = 投标期**外生常量**（删除结算期「人工费 + 机械费」基数口径）；
  规费 / 税金 = 外生输入，模型不复算。

### 结果
- Gate 0a 从 `BLOCKED 6/8` → `BLOCKED 7/8`（仅剩分类表）。
- 测试 90 项全通过。

---

## [options-adjustment-scope-v1] — 2026-09-16

> 实现 commit `5b35aa3`：`feat(wp0): adjustment_scope 升级为项目级选择项`

### 新增
- `src/bidpricing/selection_options.py` — 选择项机制：`default` 恒为 `None`，
  取值集合**按规则集而变**，落值带 `source/actor/selected_at/rationale` 依据快照。
- `src/bidpricing/contracts/scope_impact.py` — `scope-impact` 命令，
  量化 `FULL`/`SEGMENT` 在**规则层**的结算分叉。
- `config/project_selection.json` — 落值通道（未选择 = 不写 `value` 字段）。

### 变更
- `adjustment_scope` 从「一次性裁决常量」升级为「项目级选择项」。

### 已知限制（实测发现）
- **选择 `SEGMENT` 会使 T00-07/08 数值指纹退化**：此时 2024 与 2013 的跳变量同为 `≈0`
  （实测 `1.99e-9`），指纹失去鉴别力。区分依据退回条款覆盖 + 代码路径独立实现。
  已登记为遗留项，由 `ruleset-selftest` 显式输出。

---

## [contracts-wp0-v1] — 2026-09-16

> 实现 commits：`833003e`（契约冻结与闸门）、`c0a82c7`（状态板去 emoji）

### 新增
- 建立 `bid-pricing/` 代码仓库，**零第三方依赖**（JSON 配置 + stdlib `unittest`）。
- `src/bidpricing/artifact.py` — §7.1.1 断言 4 制品元数据机制（`_version`/`_hash`/
  `_frozen_at` + 占位符黑名单 + `freeze_blocker` 拒绝冻结）。
- `src/bidpricing/states.py` — §5 全局四态状态机 `PASS/WARN/FAIL/BLOCKED`。
- `src/bidpricing/contracts/` — 规则集抽象接口 + 2013/2024 两版**独立实现** + 选择器 + 指纹自检。
- `src/bidpricing/gates/gate0.py` — §7.1.1 六条死锁断言的**可执行实现**。
- `src/bidpricing/cli.py` — `gate-check` / `ruleset-select` / `ruleset-selftest` / `freeze`。
- `config/` — 7 项 Gate 0a 受控制品 + 注册表。

### 结果
- Gate 0a = BLOCKED 6/8；Gate 0b = BLOCKED。测试 55 项全通过。

---

## 里程碑索引

| tag | 日期 | 一句话 |
|---|---|---|
| `contracts-wp0-v1` | 2026-09-16 | WP0 契约冻结 + Gate 0 机械门禁落地 |
| `options-adjustment-scope-v1` | 2026-09-16 | `adjustment_scope` 升级为项目级选择项 |
| `options-phase-split-v1` | 2026-09-16 | 选择项判定时点后移（机制 / 取值分离） |
| `classification-split-v1` | 2026-09-16 | 分类表拆为规则书 / 项目落值表 |
| `project-governance-v1` | 2026-09-16 | 状态快照自动派生 + 任务板 + ADR 目录 |
| `classification-declaration-v1` | 2026-09-16 | 分类改为「声明 + 例外」；判据由行数改为声明式就绪 |
| `bound-clauses-v1` | 2026-09-16 | 单项下界的两类真实依据（不得为零 / 不平衡条款）；输入 A 结构按真实文件固化；新增 `contract-check` 第四环 |
