# ADR-0029：约束判定器 —— 六元组把「合不合规」与「对不对」分开

- 状态：已接受（2026-09-18）
- 任务：T03-04《约束判定器》（Gate 2 判定层）
- 制品：`config/constraint_judge_spec.json`（CJ-01..CJ-13 + 具名容差注册表）
- 实现：`src/bidpricing/solver/constraint_judge.py`；CLI `constraint-check`
- 上游：ADR-0021/0022（C1–C13 形式化）、ADR-0025（派生量层，floor 唯一来源）、ADR-0020（模式 A，容差宽度比 R2≥1e3）
- 下游：T04-04（对拍器可复用六元组做逐约束对照）、T03-03（Phase 0 预检复用激活语义）、T03-06（不可行诊断）

## 背景与问题

路线要求每约束返回六元组 `constraint_id/status/actual/limit/slack/severity`，
且 status **不得只有 PASS/FAIL**。若判定器与解校验器（T04-02D）共用判据或
共用实现，会出现两类已付过学费的失效：

1. **复核层是内层判据的复制**（ADR-0020 D1 的根因）——两层永远同绿同红，
   复核丧失独立否定能力；
2. **判据覆盖面取决于被测数据**（规则⑧）——未激活的约束被静默跳过且
   不留痕，「没判」被读成「通过」。

## 决策

### ① 判「合不合规」，不判「对不对」

`verify-solution`（T04-02D）回答解是否忠实于模型；本判定器回答候选报价
是否满足全部投标约束（C1–C13）。二者入参**互不重叠**：本层只吃原始量
（`JudgeInputs`：实例 + p 向量 + 可选 z/Z/floor 表/前载系数表/外生限值），
刻意不收 `SolveResult`/`Formulation`/`DerivedReport`——接口级独立性
（ADR-0024 SV-12 同款），使判据可被注入的错误结论否定。

### ② 五态而不是四态：SKIP 必须与 PASS 可区分

任务摘要的四态指**判定结论**必须四态可区分。本层额外保留 SKIP 表
「未判定」（未激活/不限价子项/c_i=0 退化项），因为把「没判」折叠进 PASS
正是规则⑧禁止的失效。聚合序 FAIL > BLOCKED > WARN > SKIP > PASS；
空判据集 ⇒ BLOCKED。**SKIP 不参与最严竞争**：全部判过且通过的报告必须
是 PASS，否则任何带未激活项的实例永远到不了 PASS——「有约束未激活」
不是缺陷。

### ③ 容差具名 + DV-02 显式隔离

全部容差在制品注册表具名，判据只引用名字，解析不出 ⇒ BLOCKED（DV-01）。
C12 的被测量 R_pc 是**无量纲比值**，与 eps_price 的「相对值 ×P*」读法是
同一物理量的两种量纲——按 DV-02 必须**两个名字**：独立具名 `eps_ratio`
（比值上的绝对量 1e-9），并**禁止** C12 引用 eps_price。否则容差被放大
P* ≈ 10⁶ 倍，判据静默失效。测试以「缺口 1e-6 的比值」钉住两种读法的分叉。

### ④ 激活语义：沉默不是断言，缺席也不是数据

* C6/C7/C8/C9 由 `active_soft_constraints` 声明激活；C10 由付款条款
  （front_rho）声明；C11 由 sigma_max/kappa_max 声明；C12 由 R_min 声明。
  未声明 ⇒ SKIP，**不是**「用户声明为无」（规则⑤）。
* 激活但缺输入 ⇒ BLOCKED（theta/N_max/Z/N_max 缺失等）。
* **C11 仅给 kappa_max ⇒ BLOCKED**：MAD 形式已被 lp_formulation_spec 否决
  （同中心 Cauchy-Schwarz ⇒ MAD ≤ σ，方向性错误），不得静默替换判据。
* C13 恒 SKIP：结算期条件修正，投标期不可知（ADR-0007 同类失效）。
* 空 cap ≠ 0：C2 的 N_free 项 SKIP 行留痕；C11 的无基准项从 d 统计剔除留痕。

### ⑤ C7 双向 z 一致性；无 z 降 WARN

实际亏损项数（p_i < c_i）为唯一事实。提供 z 向量时**双向**核查：
z=1 但 p > c_i−eps_res ⇒ 虚报；z=0 但 p < c_i ⇒ 漏报（PS-06 同族——
单向核查分不清「亏损项数 ≤ N_max」与「自称亏损项数 ≤ N_max」）。
未提供 z 且计数未超限 ⇒ **WARN**（自称口径未核），不是 PASS。

### ⑥ C12 的 FAIL 语义是「P* 不可接受」

R_pc 在 C1 可行域上是常量（ADR-0021），写成 LP 约束恒真恒假且掩盖真问题。
本层把它实现为前置可接受性判据：分子用候选 p（X_opt）+ 外生固定价
（非 X_opt），分母 Σc·q0。FAIL ⇒ 「这个 P* 不可接受」，不是 infeasible。

## 后果

- C1–C5 与 Phase 1 解析解在两探针上交叉验证全绿；C4 因 μ 未落值
  （OI-DQ-A）如实 BLOCKED——挂账在判定层可见化，不再静默。
- 64 条区分性测试（注入错误值 FAIL / 缺输入 BLOCKED / 未激活 SKIP /
  q0-q1 量纲分叉 / z 双向 / eps_ratio-eps_price 读法分叉），全量
  915 → 979，双环境（零依赖 + PuLP/HiGHS）全绿。
- P1（C11/C12）的 FAIL 不阻塞 P0 主干（`verdict()` 只聚合 P0），
  但 `verdict_all()` 与明细必须可见。
