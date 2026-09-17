# ADR-0022：约束编译器 —— 「无手写约束」做成可机械判定的事；三处口径修正

- 状态：已采纳（2026-09-17）
- 任务：T04-02B
- 制品：`config/lp_compiler_spec.json`
- 实现：`src/bidpricing/solver/compiler.py`、`cli compile-check`
- 相关：实施路线 v3.2.1 §8.1 T04-02B；ADR-0013（治理三档）、ADR-0004（未定态）、ADR-0007（沉默不是断言）、ADR-0021（LP 形式化落点）
- 前置：T04-02A（LP 形式化）—— 本任务依赖它产出可被比对的 `Formulation`
- **修正**：ADR-0021「决策一」中 `∂Z/∂p_i = q1_i · r_eff_i` 一句**是错的**，本 ADR 决策三予以推翻（正确为 `∂Z/∂p_i = q0_i · r_eff_i`）

## 背景

T04-02A 的产出是一份**受控声明**：模型长什么样（变量表 + 稀疏行 + 目标 + 挂账）。
T04-02B 的任务摘要只有一句话——「约束字典 → 求解器约束的机械转换，**无手写约束**」。

这句话难在**「无手写约束」不是一个功能，是一个可被证伪的性质**。若把编译并回形式化
（同一处既声明又实现），就没有第二份东西可比对，「实现与声明一致」永远无法判定。
故本任务的第一件事是把编译目标定成一个**与建模器/求解器都无关的规范形式**
（`CompiledModel`），让「声明侧」与「实现侧」成为两份可逐项对账的对象。

真做下去，本任务顺带暴露了 T04-02A 遗留的两处**真 bug** 与一处**必须裁定的形式问题**，
以及 T04-02A 自己写错的一条公式。三者都比「把模型建出来」更要紧，故一并记录。

## 决策

### 一、「无手写约束」做成 12 条可执行判据（CC-01..CC-12）

判据回答一句话：**编译出来的模型，确实是那份声明吗？** 因此全部是**跨来源对账**
（一侧 `Formulation`，一侧 `CompiledModel`，CC-07 再加一侧业务公式）：

| 判据 | 拦的东西 | 违反 |
|---|---|---|
| CC-01 | 单向检查抓不到的「编译器吞掉一条约束」 | FAIL |
| CC-02 | 凭空多出的行（=手写）/ 漏编译的行 | FAIL |
| CC-03 | 行引用未在变量表声明的符号（手写一列变量） | FAIL |
| CC-04 | 变量界/类型/目标系数被改写 | FAIL |
| CC-05 | 空系数行（`0 ≤ rhs`）或非有限右端；**含被激活却未编译的约束** | BLOCKED |
| CC-06 | 目标方向/常量项被「顺手优化」 | FAIL |
| CC-07 | 编译产物 vs 业务语义（`evaluate` 对 `check_solution`，**独立实现**） | FAIL |
| CC-08 | C7 双 M 的恒真条件（见决策二） | FAIL |
| CC-09 | PuLP 导出走样（sense 反向、常量符号） | FAIL / 无 PuLP ⇒ SKIP |
| CC-10 | C11 形式在两份制品间不一致或静默选定 | FAIL |
| CC-11 | 化简未登记（「少了三行」与「正确化简三行」不可分辨） | FAIL |
| CC-12 | 编译器源码里的裸字面量（手写系数的静态证据） | FAIL |

**CC-07 的独立性是刻意的**：它一侧走 `evaluate`（按行求和），一侧走
`check_solution`（按业务式重算）。两侧若同源，本判据退化为恒真式。正因如此
它们必须分别实现——它也是本轮抓到「目标系数」bug 的那条判据。

**CC-05 把「算不出」挡在建模之前**（ADR-0013）：`rhs is None` 的行一律不得进模型
（求解器会读成「无约束」或「0 ≥ rhs」，两种误读都不报错），登记 `NOT_COMPILED`
并判 **BLOCKED**。`NOT_COMPILED` 进台账解决的是**可追溯性**（查得到为什么没编译），
不是**正确性**——所以它仍然阻塞。

### 二、C7 的双向指示式需要**两个不同的 M**（实现 bug 1）

指示式（`z_i` = 「该项亏损」）：

```
z = 1 ⇔ p_i < c_i
p_i + M_lo·z_i ≥ c_i          （第二式：z=1 处须恒真）
p_i + M_hi·z_i ≤ c_i − eps + M_hi   （第三式：z=0 处须恒真）
```

两式的恒真条件**不同**：

- 第二式在 `z = 1` 处须恒真 ⇒ `M_lo ≥ c_i − lb_i`  —— 覆盖**下界**；
- 第三式在 `z = 0` 处须恒真 ⇒ `M_hi ≥ ub_i^eff − c_i + eps` —— 覆盖**上界**。

原实现两式共用 `M = c_i − lb_i`。当 `ub_i > 2c_i − eps − lb_i` 时，第三式在 `z = 0`
处把 `p_i` 压到 `c_i − eps + M`，**切掉 `[c_i, ub_i]` 的大部分区间**：业务侧判可行的解
被编译侧判违反，求解器随即误报 infeasible 或返回次优解，**且不报任何错误**。
实测两端（c=50, lb=45, ub=120, eps=0.01）：共用 M=5 把 z=0 的合法区间从
`[50,120]` 压到 `[50,54.99]`，切掉 65.01 元。CC-08 即为此设。

伴随两处退化必须显式处理（否则变成静默的政策选择）：

- `M_lo ≤ 0` ⇒ **恒不亏损** ⇒ `z_i` 固定 0，**不占** `N_max` 名额；
- `M_hi ≤ 0` ⇒ **恒亏损** ⇒ `z_i` 固定 1，**占**一个名额 ⇒ C7 汇总行的 RHS 须扣减
  `n_fixed_one`。漏掉扣减会把「亏损项数上限」放宽，且不触发任何检查。
- 退化项的 `z` **不删除**（删掉会让解向量不完整，解校验器无从复核该位），而是把
  界固定为 `[0,0]` / `[1,1]`：留着 `[0,1]` 的自由 `z` 目标系数为 0 又不受约束
  ⇒ MILP 多最优解，「亏损项数」的报告值随求解器心情变化。

不限价项（`U` 空）没有**有限**上界时，退到 C1 的隐式上界
`ub_i^eff = (B − Σ_{j≠i} lb_j q0_j)/q0_i`（任何可行解都满足它）。若它仍推不出有限值
（如 `q0` 缺失），`M_hi` 不存在 ⇒ 登记 `NOT_COMPILED`、判 **BLOCKED**，
**不得**退回 M_lo（那正是上面那个 bug）。

### 三、目标系数是 `q0_i · r_eff_i`，不是 `q1_i · r_eff_i`（口径修正，推翻 ADR-0021）

```
Z = Σ_{i∈X_opt} ( R_i(p_i) − c_i·q1_i ),   c_i·q1_i 与 p 无关
⇒ ∂Z/∂p_i = ∂R_i/∂p_i = q0_i · r_eff_i
```

ADR-0021 决策一写的是 `∂Z/∂p_i = q1_i · r_eff_i`，并说「目标系数由前者乘 `r_i` 导出」。
**这一句是错的**，且错法恰好是 T04-00 EC-2 警告过的失效模式：LP 的排序键是
`(目标系数)/(C1 系数)`，用 `q1·r_eff` 会得到

```
(q1·r_eff)/q0 = r_i · r_eff ≠ r_eff
```

即**把排序键又乘了一遍 `r_i`** ⇒ 解满足**全部约束**但**次优**，不触发任何可行性检查。
由 CC-07（编译侧 `evaluate` 对业务式 `check_solution`）实测抓到：编译侧 676000
vs 业务侧 420000，差 256000。已修，并加 `tests/test_lp_formulation.py`
`test_objective_marginal_equals_revenue_marginal` 做跨来源数值锁定。

> 教训：**自洽的错公式仍然自洽**。ADR-0021 内部 `∂R/∂p = q0·r_eff`（对）与
> `∂Z/∂p = q1·r_eff`（错）并列，居然长时间读起来没有矛盾——因为两者各自的
> 推导链都是闭合的。只有引入第三个数（结算收入的中心差分、业务侧的目标值）
> 才照得出来。

### 四、C11 移出 LP，改为求解后**离散判定**（DISCRETE_CHECK）

`σ(d)` 是凸二次/二阶锥约束。HiGHS 支持面是 LP/MILP/QP，**不含二阶锥**；schema 原建议的
MAD 替代由 `MAD_c ≤ σ_c`（Cauchy-Schwarz）可知是**放松**，最坏 √n 倍（本项目 n=115
时 10.72 倍），且原式 `(1/n)Σ|p_i − p̄|` 既不含 `base_i` 又未归一化 ⇒ **不是同一度量**。

故 C11 不建模，由判定层在求解后对 `p` 向量求值。两份制品
（`constraint_schema.C11.selected_form` 与 `lp_formulation_spec.C11.model_form`）
同时落 `DISCRETE_CHECK`，并由 **CC-10** 锁死：只要两侧不一致、或形式缺失、
或用 L1 替代 L2，即 FAIL。「未定」不静默处理（ADR-0004）。

### 五、CC-12 的规则是「数值必须具名」，不是「数值必须为 0/1」

首版按**值白名单**，结果把本模块自己的比较容差（`1e-6`/`1e-9`）与截断长度
（`60`/`5`）全部报成「手写系数」——**判据把正常实现报成违规**。于是白名单被越加越长，
判据慢慢失去意义。改判「**是否具名**」后：

- 比较容差写成 `SLACK_ATOL = 1e-9`（有名字、可 grep、可审计）⇒ 通过；
- 手写系数长成 `rhs = 0.85 * cap` 或 `M = 1e9`，必然出现在表达式里 ⇒ 被抓。

同日第二处同类误报：`term[2]` 的切片下标 `2`。制品 `literal_allowlist.rationale`
本就明写「切片下标、偏移」属**结构系数**，是实现的漏洞（未豁免 `Subscript` 索引位），
不是源码的问题。两次都指向同一条经验：

> **判据把正常实现报成违规，先改判据，不是改实现。**

### 六、编译目标与后端分离；探针必须给出求解层入参

编译目标定为建模器无关的 `CompiledModel`（变量表 + 稀疏行 + 目标 + 化简台账），
理由是环境实测**无 PuLP / numpy / HiGHS**（零第三方依赖是本仓硬约束）：若把目标直接
定成 PuLP 对象，核心路径在本机一行都跑不到，判据全部退化为 SKIP。PuLP 导出是
**可选层**（`to_pulp` 惰性，缺失 ⇒ CC-09 SKIP 而**不 FAIL**），结构对账走
`extract_pulp_structure`，依赖的 PuLP 接口面压到最小以便替身单测。编译器**不得调用
`solve()`**：混入求解会让 CC-07 的独立性丧失。

`theta`/`n_max`/`z_min`/`pi_target`/`tf_terms` 这些量**不是** `Phase1Instance` 的字段
（由调用方直接传给 `build_formulation`/`compile_model`）。探针实例的用途是「覆盖判据
全部分叉」，故必须一并给出（`formulation.PROBE_SOLVER_INPUTS`，合成值）：否则
C6/C7/C9/C10 的占位行 rhs 恒为 None ⇒ 恒 `NOT_COMPILED` ⇒ 探针**覆盖不到**这些行的
编译路径。2026-09-17 首跑 `compile-check` 时 MILP 变体 CC-05 恒为 BLOCKED，根因正是
CLI 没给 `n_max`。`--instance` 分支**不给默认值**：缺即 None ⇒ 对应占位行不编译
⇒ CC-05 BLOCKED（诚实），由 `--n-max/--theta/--d-max/--z-min/--pi-target/--tf-terms`
按需提供。

## 后果

- T04-02B 完成：`config/lp_compiler_spec.json` + `solver/compiler.py` + `cli compile-check`。
  CC 判据 12 条铺在 LP/MILP 两变体上共 24 条：**21 PASS / 3 SKIP / 0 待处理**
  （LP 变体 CC-08 与两变体的 CC-09 为 SKIP —— **SKIP ≠ PASS**，CC-09 须在 T04-02C 复跑）。
- 测试 555 → **587**（新增 `tests/test_lp_compiler.py` 32 项，含区分度层：把 12 条判据
  各自的错误实现注入回去逐条确认会 FAIL/BLOCKED；以及 `evaluate`、惰性导出、
  字面量审计三组单元测试）。
- 修两处 T04-02A 遗留真 bug（C7 双 M、目标系数）＋两处 CC-12 判据自身误报
  ＋一处 CLI 契约漂移（误读 `literal_allowlist.allowed`，正确键名
  `allowed_in_expressions`；读错会静默退回模块默认值，使「制品是白名单的真相来源」
  不成立）。
- T04-02A 的 `DeferredConstraint("C11", ...)` 由 `NONLINEAR_DEFERRED` 改为
  `DISCRETE_CHECK`；`lp_formulation_spec.json` 的 C11 段同步改写（含
  `rejected_alternatives`：MAD_FIXED_CENTER / MAD_FREE_CENTER_RAW / SOCP）。
- `formulation.NON_LP_FORMS` / `NON_LP_REASON_FIELD` 增补 `DISCRETE_CHECK`。

## 遗留

- **CC-09 在本机恒为 SKIP**（无 PuLP）。「导出层没走样」这件事**尚未被验证过**，
  须在 T04-02C 装好 PuLP 后复跑。这是本任务唯一未闭合的正确性缺口。
- C7 的 `M_hi` 通常显著大于 `M_lo`（不限价项的有效上界可远大于 `c_i`），对分支定界
  收敛速度的影响须由 T04-07 量化，必要时改用指示约束等价的紧形式。
- 「不限价 + C1 推不出有限上界」的分支（`M_hi` 不存在 ⇒ BLOCKED）目前只有单元测试
  覆盖，尚无真实项目触发。
- `compile-check --json` 的 payload 结构供 T04-02C 消费，其稳定性尚无制品锁
  （现由 `lp_compiler_spec.target_form` 描述）。
