# ADR-0028：MILP 独立验收协议 —— 最优性必须由一个可被否定的量证明

- 状态：已接受（2026-09-18）
- 任务：T04-07《MILP 独立验收协议》
- 制品：`config/milp_acceptance_spec.json`
- 实现：`src/bidpricing/solver/milp_acceptance.py`；适配层取数 `src/bidpricing/solver/backend.py::_pulp_diagnostics`
- 上游：ADR-0023（后端适配层，九值状态域）、ADR-0024（解校验器）、ADR-0027（独立参考实现）
- 下游：T04-04（对拍器 B 组）、T04-05（Phase 3 MILP 模式）、T05-00（Baseline 增益）

## 背景与问题

路线要求对拍器 B 组判据之一：「Phase 1 可行时，Phase 2 目标值**不得优于真实最优值**」。
实现这一条需要先回答：什么叫「真实最优值」？

最省事的答案是 `SolveResult.status.normalized == "OPTIMAL"`。但那是**求解器自己的
结论**，不是本项目的验收结论——二者混用会让该判据退化成恒真：它只能发现
「Phase 2 比求解器自报值更好」（不可能发生），发现不了两条路径共同的错误。

根因与本仓反复出现的失效同族：**把两种机器上本可区分的状态混成一种**
（这里是「求解器认为最优」与「本项目已验收为最优」）。

## 决策

### ① 最优性由三项可核的量证明，不由一个词证明

标 `OPTIMAL` 需同时满足：

1. 归一状态 = `OPTIMAL`（来自 T04-02C，不另立状态词表）；
2. `integer_feasible`：**逐变量**复算整数/二元变量到最近整数的距离 ≤ `eps_int`；
3. `best_bound` 已知（适配层能力探测，缺失即留空）；
4. `gap ≤ eps_gap_abs + eps_gap_rel·max(|Z|,|bound|)`。

缺任一 ⇒ 降级 `FEASIBLE`，`optimality_proven=False`。**降级是单向下坡**
（never_upgrade），绝无反向路径。

### ② 计算与判定分离（ADR-0025 同款）

`build_acceptance` 生产结论，`judge_milp` 只吃 `MilpFacts` + `MilpAcceptance`。
判据因此可以**被注入的错误结论否定**（如「FEASIBLE 状态却给 OPTIMAL」⇒ MA-02 FAIL）。
若两者合一，判据只能验证「自己的实现恰好对自己」。

### ③ 诊断量靠能力探测，不硬编码

`best_bound`/`mip_gap`/`integrality_violation` 只在适配层内取
（`prob.solverModel` + 逐项 `hasattr`），取不到就**不写该键**。空字典的含义是
「后端没给」，不是「间隙为 0」。

- HiGHS 用 ±inf 表示「该量无定义」（LP 形态下 `mip_gap=inf`）⇒ **非有限值一律不写键**，
  否则它看起来像一个数值（一个极大的间隙），而不是「没这个量」。
- ★ 实测（2026-09-18）：同一模型在 `pulp_highs` 上得 `OPTIMAL`（已证）；
  在 `pulp_cbc`（命令行后端，`solverModel=None`）上 diagnostics 为空 ⇒
  MA-05 WARN + MA-06 BLOCKED、`accepted=FEASIBLE`、未证。
  若当初写死「PuLP 一定有诊断量」，CBC 上会**静默宣称最优**。

### ④ 跨来源对账：自报间隙 × (Z − bound) 复算间隙（MA-06）

只有自报间隙时，「自报 0」与「自报 0」永远一致（规则⑥：判据不得自证）；
必须有第二个来源才构成对账。两侧不一致 ⇒ BLOCKED。

**这一条在接线首跑即抓到一处真实口径错误**：HiGHS 的 `mip_dual_bound`
**不含 `objective_constant`**。探针常量 −2,270,000，只做「min→max 取反」
得到 bound=2,730,000 对 Z=460,000 ⇒ 复算间隙 4.9 而自报 0.0。补回常量后
两侧一致（2,730,000 − 2,270,000 = 460,000）。

换算因此是**两步**：(1) 口径取反；(2) 补回常量。缺任一步都会得到一个
**看起来合理**的错界——正是这种错误不可能靠阅读代码发现。

### ⑤ 三态不得合并，且各自有明确去向

| 结论 | 含义 | 可出现于 |
|---|---|---|
| `OPTIMAL` | 最优性已证 | 最优结论栏、对拍 B 组参照 |
| `FEASIBLE` | 有解、最优性未证（含超时有 incumbent、缺 bound、整数违规） | 可行解栏，**永不在最优栏** |
| `UNSOLVED` | 超时且无 incumbent | 未决栏（≠ INFEASIBLE） |

`BLOCKED` 表示协议本身判不了（缺字段 / 缺容差 / 形态不符），与三者并列，
不得按默认值顶掉。LP 形态 ⇒ `SKIP`：不适用不是通过，也不是违反。

### ⑥ 禁用 KKT 证 MILP 最优性

MILP 可行域非凸，KKT 既非必要也非充分。用 KKT 证 MILP 是把 LP 的定理搬到
它不适用的地方（与 ADR-0021「C7 的二元 z_i 是 MILP 唯一来源」同源）。

## 后果

| 挂账项 | 处置 |
|---|---|
| T04-02C open_items「M_hi 对 B&B 收敛的影响待 T04-07 量化」 | 转为 OI-MA-A，仍挂账。本协议保证「最优性有没有被证明」可判，不保证收敛快慢 |
| T04-04 对拍 B 组「真实最优值」 | 有了唯一来源：`optimality_proven=True` 的结果；未证时该条判 **BLOCKED 而非 PASS** |
| `SolveResult` 字段面 | 新增 `diagnostics`（透传），并暴露 `best_bound_min` / `reported_gap` 只读属性 |

## 通用教训（可复用）

1. **「别人的结论」要经过换算才变成「我的结论」**，且换算的每一步都要有
   第二来源对账——最有把握的那一步（「min 取反」）错了，最有把握的那一步
   之外（「常量要不要补」）也错了，两处都是靠对账发现的，不是靠阅读。
2. **非有限值（inf/NaN）是「无定义」的信号，不是数值**。把 inf 当数存下去，
   下游会用它做算术并得到一个荒谬但「合理」的结果。
3. **能力探测 > 硬编码断言**：同一份代码在 A 后端能取证、在 B 后端不能，
   这是环境事实。写死「一定有」会让 B 上出现**静默的错误自信**。
