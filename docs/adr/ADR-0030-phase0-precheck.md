# ADR-0030: Phase 0 预检与可行性证书（T03-03）

- 状态：Accepted
- 日期：2026-09-18
- 关联：ADR-0025（计算/判定分离）、ADR-0026（merged_lower 单一实现）、ADR-0029（判定器结构）、T00-06B（compute_P_competitive 唯一提供者）、model_v0.3_R2 §6.1/§6.2/§6.3、impl_plan v3.2.1 §3 T03-03

## 背景

T03-03 交付 Phase 0 预检引擎：在进入求解器**之前**做纯算术可行性判定。
§6.1 的核心警告：缺此步骤时，结构性不可行会被误报为「求解失败」，排查方向
直接错；§6.2 的核心原则：P* 越界必须判 INFEASIBLE 且不进求解器——优化器的
职责是「在合规可行域内最优分配」，不是「让任何 P* 都变可行」。

## 决策

### D1. P*_var 的唯一提供者是 `total_price.compute_P_competitive`

路线原文写 `P*_var = P* − P_fixed`。含税总价结构下简单减法漏掉税金联动
（税基随可竞争部分变化），且 profit_bridge_spec 已登记
`compute_P_competitive` 为「C1 右端的唯一提供者，T03-03 直接调用，禁止重实现」。
预检的 P*_var 直接取其闭式输出——「同一约束跨层共用同一个名与同一个实现」
（规则⑨）在 P*_var 上的落点。闭式 `C = (P* + S·k)/(1+k) − A` 中
`∂C/∂A = −1`（固定项直接扣减、不除 1+k），测试钉住该敏感性。

### D2. P_min 必须用派生层的 L（merged_lower 多源取大）

ADR-0026 决策六已证：用普通 L 求和的边界证书会在条款下浮时虚低
（EC-7 可判 PASS 而真实可行域已空）。预检的 L_i/U_i/floor_i 全部取
T03-02 派生层单一实现，不重算。

### D3. P*_eff 三 term 任一不可算 ⇒ 整体 BLOCKED（不丢项取 max）

`P*_eff = max(模型下界之和, 成本线, 法定下浮底线)` 是**下界**——丢掉任何
一项取 max 都会让下界变弱 = 静默放宽可行性门槛，方向性违反
「宁可判死也不静默放宽」。缺失键必须具名报出（μ 未落值 OI-DQ-A、
π_target 未声明、α_cap 未声明、α_cap 已声明但存在空 cap 项）。
其中「α_cap 已声明而 cap 缺」是**声明与数据矛盾**，单独成 BLOCKED 理由。

### D4. 空 cap ⇒ P_max 不落值（≠0），上界检查 SKIP

cap 空 = 合法语义 `ALLOW_EMPTY_NO_CAP`，上界由 P* 自身兜底（C1 锁总价）。
把缺界记成 0 会把上界检查判成必然 FAIL——与「把沉默记成断言」同根因
（规则⑤）。PC-04/PC-07 在此场景判 SKIP，保留在报告里但不参与聚合。

### D5. SKIP 不参与最严竞争（与 ADR-0029 同款裁定，此处先写规格后踩坑）

初版聚合把 SKIP 计入 `_worst` ⇒ 带 PC-08 SKIP 的全 PASS 报告整体只到
SKIP，永远到不了 PASS。聚合修正为：只对非 SKIP 状态取最严；
全部 SKIP = 一个判据都没判成 ⇒ BLOCKED。T03-04 的教训在 T03-03 重演了
一次——该裁定现在是跨层不变量，后续任何聚合器直接沿用。

### D6. 甲供材/环保税未声明按 0 计 + WARN；税率缺失 BLOCKED

`supplied_material`/`env_tax` 取 0 是**收紧**方向（C 更小、门槛更高），
不会静默放宽，故允许缺省并显式记 note；`vat_rate`/`surtax_rate` 是税率
结构本身，取 0 会改变结构而非收紧，缺失 ⇒ BLOCKED（与
`compute_P_competitive` 自身「税率无默认值」的口径一致）。

### D7. 容差：复用 `eps_total` 名与公式，解析入口单一

边界比较（PC-03/04/06/07）用 `eps_total = max(eps_abs, eps_price·P*)`——
与 C1/判定层同一个名、同一条公式（规则⑨；§8.2「不得预检一套、判定一套」）。
解析复用 `constraint_judge.resolve_tolerances`；调用方显式传表只是**覆盖
个别名**，不绕过解析（首版实现「传了表就不合成 eps_total」导致全部边界
判据 BLOCKED，测试当场抓出）。

### D8. 计算与判定分离，判定器可注入验证

`build_certificate` 只算数（字段不落值 = 算不出，不得替换成 0）；
`judge_precheck` 只判（吃 inputs + 证书，不重算任何求和）。测试用
`dataclasses.replace` 伪造证书字段验证：注入 p*_var < P_min ⇒ PC-03 FAIL、
伪造 ΔP=0 掩不住缺口（PC-06 看 P* 与 P*_eff 本身）——判据能被错误的值否定。

## 测试

28 项（全量 979 → 1007，双环境绿）。手算钉值：simple 探针
P_min=1.3e6 / P_max=2.45e6 / terms=1.75e6·1.8375e6·2.205e6 /
P*_eff=2.205e6；P*_var=2.4e6/(1+0.09×1.03)=2,196,394.26（闭式含分位收敛
迭代，断言放至分位）；越界 1 元即 FAIL、贴边 PASS 双向钉容差。

## 遗留

- PC-02 角色域检查目前只查「role ∈ 域」；「清单级缺省角色 + 例外清单」的
  完全划分校验（competitiveness_classification.closure_requirement）在
  T00-06 分类表落值后接入。
- §6.3 放弃投标判据表的「建议动作」输出归 T03-06（不可行诊断，依赖本任务）。
- μ 未落值（OI-DQ-A）经 D3 传导为 PC-05 BLOCKED——挂账继续可见。
