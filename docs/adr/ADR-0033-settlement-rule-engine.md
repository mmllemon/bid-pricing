# ADR-0033：结算规则引擎与分层互锁修正（T03-01）

日期：2026-09-18　状态：已接受　任务：T03-01　前置：ADR-0025（派生量唯一实现）、ADR-0029（判定器聚合纪律）

## 背景

T03-01 要求交付 `SettlementRule.evaluate(Q0, Q1, P0, ContractContext)`，返回
`settlement_amount / effective_price / rule_id / rule_branch`，并满足四条完成判据：
三段覆盖 + 边界归属正确、**规则阈值与 P1 来源按 rule_set_id 分发**、
**支持合同规则覆盖标准阈值**。

盘点发现三处缺口：

1. 既有 `compute_p1` 只服务**单一**规则卡（`card['rule_set_id']` 写死），
   没有按 id 分发的入口；而 T00-07 已备两套独立 RuleSet。
2. 规则集方法把阈值写成**模块常量**（`INCREASE_THRESHOLD * q0`），
   没有注入通道——合同覆盖阈值时「参数被覆盖、判定仍走常量」。
3. `resolve_parameters` 的互锁（声明值 vs 实现常量）在**覆盖之后**执行，
   于是**任何**阈值覆盖都被判违规（既有测试
   `test_threshold_override_conflicting_with_constant_is_blocked` 正是如此断言）
   ——与「支持合同规则覆盖标准阈值」直接冲突。

## 决策

**D1——引擎是壳，公式唯一实现在 rule_sets。**
`settlement.py` 只做「分发规则集 + 施加覆盖链 + 归一输出」，**不自建任何调价公式**。
理由：一旦此处出现第二份公式，漂移会以「Phase 1 与 Phase 2 结果对不上」的形式
在 T04-04 对拍时才暴露；同一规则两处说法是本项目最主要的返工源（用户已两次踩到
「改口径漏改老表述」）。

**D2——`rule_set_id` 严格分发，未注册 ⇒ BLOCKED。**
`selector.py` 的 `_ruleset_for` 用 `else` 兜底到 2024 版本——那是**选择器层**的兜底，
由其状态机与 Gate 0a 把关；本层**不复制**该兜底（复制即两处说法）。
未注册 id 一律 BLOCKED，且 `rule_id` **原样回传**，不得回填成默认值
（回填即伪造分发证据）。

**D3——阈值可注入（新增可选参数，默认取规范常量）。**
`RuleSet.classify_branch / settlement_amount / effective_revenue_multiple` 增加
`decrease_threshold` / `increase_threshold` 关键字参数，`None` ⇒ 规范常量。
既有调用点（phase1 / derived / scope_impact / fingerprint）不传即保持原行为，
零行为变更。★ 阈值注入是**能力的下限条件**：`ρ=0` 时金额对阈值不敏感，
故 SR-05 的见证必须带 `ρ>0`——否则「覆盖不生效」的坏引擎会被金额相等掩盖。

**D4——互锁分层（本 ADR 的核心修正）。**
优先级链 `Contract > Tender > Regional > Standard`（规则卡 `precedence_chain`）
是两层不同的东西，旧互锁把两层混为一谈：

| 层 | 约束 |
|---|---|
| Standard（规则卡自身声明） | 阈值**必须**等于实现常量；不等 ⇒ `PricingCardError`（两处说法） |
| Contract / Tender / Regional（覆盖） | 阈值**允许**偏离，并记入 `sources`（留痕） |

判别依据是 `source_label`：Standard 层标签（`standard` / `pricing_rule_card`）
下的覆盖仍按违规处理（有人声称规范与实现分叉）。这既满足 T03-01 的
「合同规则覆盖标准阈值」，又保留旧互锁真正想守的东西——规范层不得自相矛盾。

**D5——三个量分列，不得混用（SR-08）。**
`settlement_amount`（元）、`effective_price = S/Q1`（加权平均单价）、
`adjusted_unit_price = P1`（调整后单价本身）在 **SEGMENT 增量段不相等**
（阈值内部分仍按 P0 结算）。把三者当同一个量是 DV-02 同族的量纲混用，
会静默错；判据双向钉住：SEGMENT 增量段**必须不等**，其余段**必须相等**。

**D6——`p1_source` 随规则集分发，三处一致。**
2013 = `REDETERMINE`（§9.6.2「重新确定」，与 P0 脱钩）；
2024 = `ADJUST_ON_CONTRACT_PRICE`（§8.9.2「上调/下调其合同单价」）。
登记三处：制品注册表、RuleSet 类属性、引擎出口——SR-04 跨来源核对，
并要求两版取值**必须不同**（相同等于把两种生成方式混为一谈）。

**D7——判据覆盖面固定在制品（`probe_grid`）。**
SR-01/SR-02/SR-09 在制品声明的固定网格上跑，不得由被测数据决定覆盖面（规则⑧）。
判据可注入（`engine_factory`）：测试构造三类坏引擎（边界写反 / 覆盖不生效 /
未注册 id 默认 2024），验证判据确实 FAIL。

## 后果

- 结算入口统一：T03-05（规则优先级测试）、T04-04（对拍器）、T06-06（利润桥接）
  都从 `SettlementRule.evaluate` 取数。
- 规则卡互锁语义变更已同步测试（`test_pricing_card.py` 三用例替换旧的一例），
  旧断言的「任何阈值覆盖都 BLOCKED」不再成立——这是**有意放宽**，理由见 D4。
- 测试 +37（新增 `tests/test_settlement.py` 35 项 + 规则卡 3 项替换 1 项），
  全量 1046 → 1083 双环境绿。
- 遗留：`selector._ruleset_for` 的 `else` 兜底仍是单点风险，建议后续把选择器
  改为严格注册表查表（本任务已记入 T03-01 状态注记，未擅自改 T00-08 范围）。
