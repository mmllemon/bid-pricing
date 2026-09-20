# ADR-0036：对拍报告的可复算性，与「规格声明了但实现没有」的五处缺口

- 状态：已采纳
- 日期：2026-09-20
- 任务：T04-04（Phase 1/2 对拍器）
- 关联：ADR-0001（三层分离）、ADR-0019（Phase 1 精确性）、ADR-0020（复核层宽度比）、
  ADR-0026（解析解层，要求 T04-04 报告声明 floor 来源）、ADR-0027（独立参考实现/独立性签署）、
  ADR-0028（MILP 验收协议，B 组判据）

## 背景

T04-04 的比较器（`src/bidpricing/solver/parity.py`）与制品
（`config/phase12_parity_spec.json`）早已落地，`docs/phase12_parity_report.json`
里也有一份 `conclusion: PASS`（西永L 单实例 81 项，objective Δ = 4.66e-10）。复核时发现
**这份 PASS 不可信、也不可复算**，并由此暴露出五处「制品声明了、实现没有」的缺口：

1. **报告没有任何生成器。** 全仓 grep：`parity` 与 `golden` 在 `cli.py` 里零命中。
   报告自称 `generated_by: src/bidpricing/solver/parity.py`，但该模块只提供
   `compare_phase12()`——**没有任何代码写过那个文件**。「结论可复算」的前提在下游交付物上断了。
2. **报告与任务板互相矛盾。** `docs/tasks.json` 的 T04-04 note 写着「当前报告仍 BLOCKED」，
   而报告写着 `PASS`。两处说法冲突却没有信号（本仓把「说了但说错、两处冲突」归 FAIL 档）。
3. **容差住在代码里，不在制品里。** 规格声明了 `tolerances.{objective_abs, price_abs,
   residual_abs}`，而 `compare_phase12()` 用的是**函数默认字面量 `1e-7`**，制品那一节
   **从未被读取**。当前两者数值恰好相同，所以完全隐身在测试与报告之下——这是 DV-01 家族
   （同一个量在两层各有一个宽度）。改制品不会改行为，改代码不会留痕。
4. **L1 未实现。** 规格 `comparison_levels.L1` = 「两条路径均产出可比较的状态」，
   `blocked_rules` 也明确列了「任一路径缺少可比较结果**或状态**」，但实现**从不比较状态**，
   `level` 永远不会返回 `L1`。
5. **L3 只做了一半。** 规格 L3 = 「逐项层归属**与约束残差**在声明容差内一致」，
   实现只比较 `layers` 字典是否相等；`residual_abs` 同样从未被读取。
6. **B 组判据不存在。** 制品 `groups: ["A","B"]` 与 ADR-0028（「Phase 1 可行时，Phase 2
   目标值不得优于真实最优值」）都要求两组验收，实现里 `group` 只做了一次合法性校验。

## 决策

**D1（可复算性优先于既有结论）** 报告的权威版本必须由**代码**产出，且制品内必须出现
**输入路径**与**复算命令**。原先那份不可复算的 `PASS` **不删除、不覆盖**，改为搬进
`docs/phase12_parity_prior_measurement.json`，显式标注 `reproducible: false` 并逐条列出其
caveats（未声明 floor 来源、未覆盖分层数据集、L1/L3 无留痕）。**证据保留，但不再充当
「对拍已通过」的依据**。

**D2（判据宽度唯一来源 = 制品）** 三个具名宽度只从 `phase12_parity_spec.json` 的
`tolerances` 读取；函数入参降级为**显式覆盖**。制品缺项**且本次判定确实用到该宽度**时判
`BLOCKED`——不得静默退回代码默认数，也不得静默按 0 放行（后者是用一个没定义过的宽度冒充
「两侧一致」）。三个键的名分由 `TOLERANCE_KEYS` 常量与制品**双向对账**（测试断言相等）。

**D3（L1 是独立关卡，数值相等不能替代它）** 两侧都必须给出可比较状态；缺任一侧即
`BLOCKED`。理由是「数值恰好相等而状态不可比」恰恰是**两侧其实解了不同问题**的典型形态：
跳过 L1 等于用巧合替代证据。

**D4（L3 补残差，并把「口径不可比」单列）** 残差按 `residual_abs` 判；
**只有一侧提供残差 ⇒ `BLOCKED`（口径不可比）**，既不判 PASS 也不判 FAIL，
且写明是哪一侧缺。层归属仍保持原语义（不等 ⇒ `WARN`）。

**D5（B 组只加义务，不改判定）** B 组在 A 组结论之上**追加义务**：Phase 1 已声明可行而
Phase 2 目标值更高 ⇒ 记「目标函数口径可能分歧」义务（这正是 H-002b 同族缺陷的形态：
报价向量一致、目标值不同 ⇒ 两侧目标函数实现不一致）。Phase 1 可行性**未声明** ⇒ 记
「B 组判据未走到」义务，**不得读成已成立**。

**D6（floor 来源必须出现在报告里）** ADR-0026 已明文要求。未声明时记义务（可追溯性），
不改判定——两侧若取了不同地板会产生**假不一致**，值本身看不出来，只能靠声明留痕。

**D7（聚合三条边界，缺一条报告就会撒谎）** `SKIP` **不参与最严竞争**（否则带未激活项的
报告永远到不了 PASS）；**全 SKIP ⇒ SKIP**（「本轮没判」是合法结论，不等于通过）；
**空判据集 ⇒ BLOCKED**（一条都没判成，不是 PASS）。

**D8（缺输入不得冒充状态）** 缺 bundle 时结论 `BLOCKED` 并**具名 owner**，
理由里必须同时排除两种误读：「不是已通过」「不是不适用」。

## 影响

- 新增 `src/bidpricing/solver/parity_runner.py`（执行器：校验 bundle → 逐 case 比较 →
  最严聚合 → 产报告）。`parity.py` 保持「只比较、不替任一路径求解」的契约不变，
  两者分层：比较器 / 执行器。
- 新增 CLI `parity-check`（`--bundle / --out / --signoff / --no-write / --json`）。
  与 `verify-solution`、`derive-check` 同属**预期可能非零**的命令，**不进「必须退 0」的
  常驻验证环**。
- `docs/phase12_parity_report.json` 重新生成：结论由 `PASS` 变为 `BLOCKED`，
  理由 = 未提供可复算输入 bundle，owner = T04-04。**这不是退步**：它把一份不可复算的
  绿，换成一份可复算、且如实说明「本次未对拍任何实例」的结论。
- `config/phase12_parity_spec.json` 增补 `tolerance_source_rule / group_semantics /
  report / skip_policy`，并在 `blocked_rules` 里补三条新拒绝理由。该制品**未注册 Gate 0、
  未冻结**，故本次修改不触及任何已签署方案。

## 验证

- `tests/test_parity.py`（35 项）：L1/L2/L3/B 组/floor 来源/容差住制品，含 **6 条变异体**
  （V1 硬编码容差、V2 跳过 L1、V3 不查残差、V4 单侧残差静默当 0、V5 丢义务、V6 丢 floor 来源），
  每条由具名用例杀死；判定条件只比 `status` 行为，**不依赖被测实现的可解释性文案**。
- `tests/test_parity_runner.py`（30 项）：bundle 校验（坏 bundle 抛 `BundleError`，
  与「没给」区分）、聚合三条边界、报告三方对账（制品声明 ↔ 实现常量 ↔ 测试），
  含 **4 条变异体**（V7 空判据集判 PASS、V8 缺 bundle 判 SKIP/不适用、V9 丢义务、
  V10 报告不带实际使用的容差）。
- 手工复算：`PYTHONPATH=src python -m bidpricing.cli parity-check`（结论 BLOCKED，exit 1）。

## 遗留（挂账，具名 owner）

1. **两条路径的结果留痕（input bundle）仍未产出** ⇒ 对拍结论停留在 BLOCKED。
   owner = T04-04。这是**数据/留痕**缺口，不是机制缺口——不得由实现侧编造。
2. **实例集尚未覆盖 `golden_dataset_v1` 的分层 A–F**。`tests/data/golden/golden-v1/`
   已提供 22 个 cap/cost 用例与 manifest，但**求解层入参不齐**：
   `MatchedItem` 能给出 `q0/cap/c_i/q1_point`，而 Phase 1 实例还需 `p0`、`L`（下界）与
   `B`（= `P*_competitive`），三者都不在 golden 制品里——这与 `config/phase1_solver_spec.json`
   的 known_limits「真实项目入口未开（attribution / q1_point 尚未落值）」是同一根因。
   owner = T04-04 / T01-02C（golden_dataset_v1 求解层落值）。
3. 本次未改 `compare_phase12` 的三级判定**语义**（仅补 L1/L3 与容差来源），
   故 `ADR-0020` 的「复核层宽度比 ≥ 1e3」不适用于本模块——对拍器不是复核层，
   它是**同层横比**。若将来把对拍结果再喂给复核层，须另立宽度比判据。

## 遗留 1/2 的收口（2026-09-20）

两条挂账已由 `src/bidpricing/solver/parity_suite.py` 收口，结论**从 BLOCKED 升到 PASS（L3）**：

- **新增 bundle 生成器** `parity_suite.build_bundle`：从
  `golden_dataset_v1` 解析 cap/cost 双侧 → 构造求解层实例（补 `p0=cap`、`L=0`、
  `B=Σ(cap_i·q0_i)`，并声明 `tie_break_policy=CANONICAL_ITEM_ID`）→ 分别跑 Phase 1
  解析解（`solve_phase1`）与 Phase 2 编译 LP（`build_formulation` + `compile_model` +
  `solve_compiled`）→ 序列化为 `phase12_parity_input_v1` bundle。**两条路径的结果留痕
  由此由代码闭合成可复算输入**。目标值取自同一独立裁判 `check_solution(...).Z`，保证两侧
  口径一致。
- **实例集覆盖 A–F 的诚实取舍**：golden 正例 A/D/F 加 tie_break 后通过 Phase 1 EXACT
  （EC-5 平台被 `_ec5` 的 tie-break 分支豁免），三条全部两条路径产出且**三层对拍一致**；
  B_pos（B=UP，可行域退化为单点，LP 判 INFEASIBLE）、E_pos（2000 行极端尺度，
  5.2e16 量级）、C_pos（无两侧齐备项）与全部负例被**显式写入 `provenance.skipped` 留痕**，
  不静默冒充覆盖（ADR-0026/ADR-0004 精神）。
- 新增 CLI `parity-suite --out`（生产 bundle）与 `test_parity_suite.py`（可复算 + 覆盖 +
  跳过留痕三项断言，不 mock，跑真实求解）。
- 复算命令：`PYTHONPATH=src python -m bidpricing.cli parity-suite` → 再
  `parity-check --bundle docs/phase12_parity_bundle.json` ⇒ 结论 PASS（L3），exit 0。
