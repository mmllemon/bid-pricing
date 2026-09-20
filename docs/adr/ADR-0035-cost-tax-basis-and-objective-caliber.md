# ADR-0035：成本税口径与目标口径一致性——含税成本换算、阻断接线与跨层对账（H-002 / H-002b）

日期：2026-09-20　状态：已接受　任务：H-002（成本税口径）、H-002b（目标口径跨层对账）
前置：ADR-0013（三档治理）、ADR-0011（跨来源证据）、ADR-0021/0022（目标系数与 C5 下界）、
ADR-0033（结算规则引擎）、ADR-0020（判据覆盖面不得取决于被测数据）

## 背景

### B1 缺陷一：含税成本与不含税报价在同一算式里相减

`config/basis_declarations.json` 已声明 `cap_tax_scope = cost_tax_scope = EXCL_VAT`
（依据 GB/T 50500-2024 2.0.8：综合单价不包括增值税）。但**成本清单**的综合单价
是承包人采购口径的**含税成本单价**（`cost_input_incl_vat`）。两份清单单价口径不同，
直接相减无意义。

现状盘点（缺陷确认）：

* `src/bidpricing/quote_resolve.py` 旧实现：`margin = revenue − q1 · c_i`，
  其中 `revenue = settlement_revenue_adjusted(...)` 是**不含税**结算收入，`c_i`
  是**含税**成本 ⇒ 毛利被系统性低估（低估额 = q1 上不可抵扣部分的进项税）。
* CT-01…CT-05 判据（`validation.cost_basis.check_cost_input_tax`）**早已存在**并全绿，
  但**两条报价入口一个都没消费它们**——判据齐全而无人使用，与 C13 未接线同族。
* 同一缺陷的第二个面向：`solver/settlement_milp.py` 的目标函数把结算收入乘
  `(1 + vat_rate)` 折算为含税，成本侧却保持含税 —— 这在 H-002 之前是「两侧同为含税」
  的自洽口径（但违反声明，见 D2），在 H-002 把成本换算为不含税之后变成**混合口径**。

### B2 判定依据（ADR-0013 三档）

进项税率 / 抵扣模式缺失，会让**利润算式算错**（含税成本与不含税收入相减），
而不是「说不清出处」 ⇒ 配 **BLOCKED**，阻断「最优利润」结论。
这正是 `docs/CODE_REVIEW_AND_REQUIREMENTS.md` 对 H-002 的验收标准原文：
**无抵扣声明时禁止输出最优利润结论**。

### B3 缺陷二：目标函数口径违反已冻结的声明（H-002b）

`config/profit_bridge_spec.json`（已冻结，2026-09-17）声明：

* `tax_caliber_of_objective = "EXCL_VAT"`；
* `objective.definition = "Σ_i [ 结算收入_i − 成本_i ]"`；
* binding 原文：「报价 p 与成本 c 两侧同为**不含增值税**口径……**故目标函数本身不含增值税**」。

而 `solver/settlement_milp.py` 的 `gross_factor = 1.0 + vat_rate` 把收入折算为含税，
**违反同一声明**。PB-04 只校验「声明 ↔ basis_declarations 自洽」，不校验实现，
因此该错层长期存活且**结果复核发现不了**。

## 决策

### D1——含税成本 → 不含税有效成本，唯一换算入口 + 声明缺失即阻断

换算式（唯一实现：`validation.cost_basis.effective_cost_multiplier`）：

```
k = 1 − vat_rate × credit_ratio / (1 + vat_rate)      # vat_rate 为**进项**税率
FULL    → credit_ratio = 1   ⇒ k = 1/(1+vat_rate)      # 进项税全额抵扣
NONE    → k = 1                                        # 不可抵扣，含税即有效成本
PARTIAL → credit_ratio 必须显式声明 (0,1)
UNKNOWN → 返回 None，不可计算 ⇒ 阻断
```

**PARTIAL 与「分项精算」严格等价**：设含税成本 `c`、货物占比 `ρ`、货物进项税率 `r`，
则 `c_eff = c(1−ρ)/(1) + c·ρ/(1+r) = c·(1 − rρ/(1+r))` —— 与上式逐字相同
（实测差 1.4e-14）。故「一部分是货物、一部分是人工」这类成本结构**不需要新机制**。

### D1.1——分项多税率精算（cost_composition）落地：把「两段等价」升级为任意段精确

ADR-0035 当初论证 PARTIAL 与两段分项精算严格等价，但也指出「三段及以上构成只在加权意义下近似」。
现按该扩展落库（2026-09-20 续作）：

* 新增 `cost_composition` 输入（字段规范见 `cost_input_tax_spec.json`）：把含税成本按科目
  （材料/设备/分包/人工/措施）拆段，每段带 `proportion`（含税成本占比）与 `input_vat_rate`
  （该段进项税率），换算式升级为精确式 `k = 1 − Σ_j p_j·r_j/(1+r_j)`，对任意段数/税率严格精确
  （不再像旧单税率 PARTIAL 那样只在加权意义下近似）。
* **优先级**：`build_effective_costs` 先判 `cost_composition` 是否存在且合法
  （`validate_cost_composition`：Σp=1、各段 0≤p,rate≤1）；存在则用精确式，否则回退旧单税率路径
  （向后兼容 CLI/旧配置）。
* **人工 r=0 自然不抵扣**：分段后无需另外标记「人工不可抵」，r=0 在公式里不贡献抵扣。
* **FULL/PARTIAL 同 k**：构成路径下 FULL 与 PARTIAL 产生相同 k（构成已含各段真实税率），
  模式仅作声明语义；NONE 恒 k=1 且忽略构成。
* **前端自定义**：网页平台新增「成本税口径（成本构成）」面板，逐项目填写占比与进项税率，
  实时校验 Σ占比=100% 并展示派生可抵扣占比与 k；提交时以 JSON 字符串注入 `cost_composition`，
  经 `api._build_tax_override` 解析后覆盖 `config/project_quote_policy.json` 默认
  （PROJECT_INPUT，不进冻结；改 JSON 即生效，无需 `bidpricing freeze`）。

治理：

* 模式缺失 / UNKNOWN / 词表外 / 需要税率而税率缺失或越界 / PARTIAL 比例缺失或越界
  / 系数不可计算 ⇒ **BLOCKED**，理由须点名缺哪一项以及缺了会让哪个数字失真；
* 词表**住制品**（`config/cost_input_tax_spec.json`），代码保留实现侧副本，
  由 **CT-06 双向对账**钉住（单向比对会漏掉「实现多判一个模式而制品没声明」）。

### D2——目标函数收入侧不再做含税折算；口径由跨层判据对账（H-002b）

删除 `(1 + vat_rate)` 折算，令 `objective_revenue_factor(vat_rate) ≡ 1.0`，
并把它做成**唯一提供者**函数（构建目标系数与独立复算共用），
在 `Formulation` 上新增具名量 `objective_caliber`。

**关键论证：该修正不改变推荐报价。** 目标函数中 `p` 的依赖项全部落在收入侧、
被同一正常数因子缩放；`Σ c_i·q1_i` 是 `objective_constant`，与 `p` 无关。
故 `gross_factor` 只影响**报告值**，不影响最优解。实证（两个可优化项，B=30000）：

| 口径 | 最优解 p | 目标值 Z |
|---|---|---|
| 含税折算（旧） | A=150, B=150 | 9605.00 |
| 不折算（新） | A=150, B=150 | 6500.00 |

差额 `9605 − 6500 = 3105 = 0.09 × Σ结算收入`，即**应交增值税**——
换句话说：旧口径把「应交增值税」计成了利润。

新增判据 **PB-07**（`validation.profit_bridge`）：把**报告层声明**与**求解层实现**
拉到一起对账 —— 声明口径 vs `settlement_milp.OBJECTIVE_CALIBER`，
且声明 `EXCL_VAT` 时收入侧系数必须恒为 1.0（与税率无关）。
若实现侧不可探测 ⇒ BLOCKED；声明缺失 ⇒ SKIP（由 PB-04 阻断，同一缺失不报两次）。

### D3——二次换算防护靠**写在数据里的标记**，不靠调用顺序的君子协定

`cost_tax_scope` 是写在每一项数据上的显式标记：

* 全标 `EXCL_VAT` ⇒ 调用方已完成换算，入口**跳过**换算（幂等）；
* 全未标 ⇒ 入口按项目声明换算；
* **混合** ⇒ BLOCKED（一半换算一半没换算的清单必然算错，拒绝猜以哪侧为准）。

`build_effective_costs` 另有 CT-07：若发现待换算项**已标** `EXCL_VAT` 且带成本，
直接 BLOCKED——这一步挡的是「有人把已换算的输出再喂回换算」（k 乘两遍 ⇒
成本静默偏小、毛利静默偏大且不报错，DV-02 同族）。

★ 为什么不用「传不传方案对象」做契约：那只挡住「调用方忘了传」，
**挡不住**「把已换算的输出再喂回换算」。标记写在数据里，两个方向都能机械拦住。
`c_i is None` 的人工报价项没有可换算的口径，不参与口径一致性判定（否则误报 BLOCKED）。

## 影响与验证

* 两条报价入口同时接线：`quote_pipeline.resolve_cost_plan`（CLI/分析侧，
  被 `run_quote_pipeline` 与 `run_settlement_adjusted_quote_pipeline` 共用）与
  `quote_resolve.run_resolve`（网页平台侧）。**两层共用同名同语义函数**，
  避免「同一约束两层各判一次、结论相反」的 DV-01 形态。
* 换算发生在**产出任何毛利数字之前**；阻断时 payload 不含 `items`，
  即不留下任何毛利/成本合价字段（阻断必须真的发生在出数前）。
* 留痕：`QuotePipelineResult.cost_multiplier` / `cost_adjustment_trace`；
  payload 的 `cost_input_tax`（声明内容 + 系数 + 逐项痕迹，可据此复算任一行 c_eff）。
* 展示层（七处同步）：`api/app.py`（阻断文案透传）、`frontend/app.js`（三列成本 +
  口径提示 + 阻断原因与行动建议）、`frontend/index.html`、`build_web_result.mjs`
  （Excel 由 16 列扩到 18 列：含税成本单价 / 成本税口径 / 有效成本单价，
  **成本合价与单项毛利改按有效成本单价计算**，否则导出表会退回旧口径）、
  文档两处。

验证（双环境）：

* `tests/test_cost_basis_wiring.py`：41 项，含 4 条**变体注入**（换算恒等 /
  入口不阻断 / 入口不换算 / 毛利用含税成本）逐个被具名用例杀死，存活 ⇒ FAIL。
* 数值钉死用**手算**：`c=113, r=13%, ρ=60% ⇒ c_eff = 105.2`（= 60.0 + 45.2 分项精算）；
  `113/(1+0.13) = 100.0`；PARTIAL 等价性逐位比对。
* 旧结果在新口径下重算的恒等式：`ΔZ = Σ q1_i·(c_incl_i − c_eff_i)`（实测残差 1.16e-10）。
* PB-07：对 ADR-0035 的真实缺陷（常量标 EXCL_VAT 但收入侧仍乘 1+v）有区分度，
  实测报 FAIL。

## 遗留与后续

1. **项目取值已落 + 分项构成已支持前端自定义**（2026-09-20 续作已解决）：
   `config/project_quote_policy.json` 的 `cost_input_tax_policy` 已声明为
   `PARTIAL` 并给出默认 `cost_composition`（材料 40%/13%、设备 22%/13%、分包 10%/9%、
   人工 23%/0%、措施费 5%/9%，可抵扣占比≈0.77，k≈0.9163）；网页平台新增成本构成面板，
   可逐项目自定义覆盖。
   **仍遗留**：`cost_composition` 是**项目级单一分解**——若同一项目内不同清单的
   货物/人工占比差异极大，项目级分解仍会产生项间近似；按清单逐项覆盖 composition 属后续扩展，
   本 ADR 换算式天然支持逐项 ρ，机制层已预留。
2. **前端预告已部分解决**：默认口径已声明，计算前不再触发「未声明」阻断；
   构成面板的实时 Σ占比校验 + 派生 k 展示，已把「税口径是否正确」前置到提交前可见。
3. **未决疑虑**：真实样本 `真实案件示例/中标限价/*.xlsx` 于 2026-09-20 被更新
   （sha256 由 `c32b4b709c2d…` 变为 `e45f691c294e…`），
   导致 `tests/test_io_boq.RealFileSmokeTest` 两例失败（83→84 行、15→16 项补充项）。
   该失败在**改动前的 HEAD 上同样复现**，与 H-002 无关，属独立的数据漂移事项，
   须按 H-001 纪律从新样本重新推导固化期望，不得手改数字。

## 与既有决策的关系

* 不推翻 ADR-0021/0022：目标系数 `∂Z/∂p = q0·r_eff` 的推导不涉及税折算，
  D2 只去掉一个对全部收入项等比的常数因子，系数结构不变。
* 补全 ADR-0011 的「含税/不含税口径」交叉满足：此前只在**声明层**满足，
  现在**实现层**也满足并被 PB-07 钉住。
* ADR-0013 三档治理在本 ADR 上再验一次：缺失让算式算错 ⇒ BLOCKED；
  说了但说错（模式/税率越界）⇒ FAIL；只是没接线 ⇒ 本 ADR 直接判为缺陷并修复，
  因为「判据存在但无消费者」在治理上等价于判据不存在。
