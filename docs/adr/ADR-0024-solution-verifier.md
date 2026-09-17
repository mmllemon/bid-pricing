# ADR-0024 解校验器的位置：复核层不得是内层判据的复制，且判据宽度必须具名

- 状态：已采纳
- 日期：2026-09-17
- 任务：T04-02D（解校验器）
- 相关：ADR-0006（就绪性判声明不判行数）、ADR-0013（治理三档）、ADR-0015（判据不得自证）、
  ADR-0019（Phase 1 精确性）、ADR-0020（等式容差模式 A → D1 宽度比）、ADR-0022（约束编译器）、
  ADR-0023（求解后端适配层）
- 制品：`config/solution_verifier_spec.json`（新）、`src/bidpricing/solver/verifier.py`（新）、
  `config/lp_compiler_spec.json`（改）、`config/solver_backend_spec.json`（改）
- 判据：`verify-solution`（SV-01..SV-13）

---

## 背景

实施路线给 T04-02D 的完成判据是一句话：**独立复核可行性、目标值、上下界、层归属**。
接口契约由三份上游制品**分别**交出（各自 `consumers` 里的 T04-02D 条目）：

| 来源 | 交出什么 |
|---|---|
| `lp_formulation_spec` | `diagnostic_metric` + `tolerance` |
| `lp_compiler_spec` | `CompiledModel.rows` + **各行的 tolerance** |
| `solver_backend_spec` | `SolveResult.x` + `CompiledModel.rows` + 各行的 tolerance；并特意写明 **「BB-07/BB-08 只判『链路走样没有』，不替代解校验报告的逐行判定」** |

第一条线索就在最后那句话里：BB-07/BB-08 已经把「自报 vs 复算」「编译侧 vs 业务侧」
都判过了，**如果 T04-02D 只是把它们的结论重述一遍，它就不该存在**。ADR-0020 的 D1
把这条说成了机械判据：外层复核判据的宽度必须 ≥ 1e3 倍于内层，否则「残差恰好落在
带内」的解会同时通过两关，复核层退化为内层判据的**复制**。

于是必须先回答一个具体问题：**内层到底是在什么宽度上判的？**

## 决策一：复核层与内层不同宽，且宽度必须是具名的数

内层 `compiler.evaluate` 的可行性判定原本是：

```python
@property
def ok(self) -> bool:
    return self.slack >= -ZERO_EPS          # ZERO_EPS = 1e-12，未具名
```

而行上携带的 `CompiledRow.tolerance` 是一个**名字**（`eps_solver` / `eps_price` /
`eps_total` / `0（整数）`），**从未被任何判据解析成数值**。后果是存在的两层容差
在源码上看起来都只是「一个很小的数」，实际相差 1e4～1e10 倍。

决策：容差名 → 数值的映射落成**单一来源**（`solution_verifier_spec.tolerance_name_resolution`），
由 `verifier.resolve_tolerances` 实现，解析器取值域是**封闭**的五个动词，制品为每个名字择一。
调用方（`evaluate` / `solve_compiled` / 复核层）都消费同一份解析结果。

配套两条：

- **`eps_price` 与 `eps_rel_price` 必须分开命名。** 同一个 `profile.eps_price` 字段有两种
  用法：行级容差要的是「×P* 的绝对量」，§4.1 的混合容差形式与 `compute_lb_c5` 要的是
  「无量纲相对量」。混用就是乘重一遍——实测把已 ×P\* 的值喂给 `compute_lb_c5`，
  `lb_C5` 由 0.01 元被放大成 9000 元，四项全判违反下界；ε_Z 也被放大 1.3e5 倍。
  对策是给两种读法两个名字：**名字不同，乘法写不下去**。
- **未被使用的名字解析不出不构成阻塞。** 否则一个为将来预留的名字（`eps_quantity`
  需要 Q_ref）会让整条校验恒 BLOCKED，而那与「本轮没检查」是两件事。故 `resolve_tolerances`
  按**名字**记账问题，由调用方按「用到的名字」过滤。

判据 SV-06 把 D1 机械化：`R2 = eps_abs / eps_solver`，要求 ≥ 1e3（本项目 = 1e6）。

## 决策二：复核层的独立性做成**接口级**，不是纪律声明

复核层的价值全在独立性。因此 `verify_solution` 的签名**只接受原始量**：

```
verify_solution(model, x, *, spec, profile, instance, reported_objective,
                floor_by_id, reference, verifier_source, resolution)
```

**刻意不提供 `SolveResult` 重载**——不接收即无从消费 `evaluation` / `solution_check` /
`recomputed_objective`。这是比运行时检查更强的保证：类型上就拿不到。

另加 SV-12 的静态面（AST，与 ADR-0023 的 BB-03 同手法）：本模块不得出现
`evaluate` / `check_solution` / `solve_compiled` 的**调用**，不得 import 求解器包；
按 AST 取调用与导入而**不取纯文本**——文档里提到这些名字不算违规（同 BB-05 的教训）。

第四族声称（层归属）与第三族（上下界）给出复核层**独有**的内容：

- 编译侧把 `C3/C4/C5` **合并成一行**（rhs = `max(L, floor, lb_C5)`，制品 detail 已写明
  「逐条诊断须用各自原始阈值复算」），合并后**是哪一条在起作用**在编译侧不可恢复；
  SV-07 从业务侧逐条重建四路阈值，并给出 `binding_lower`。
- 层归属（`BOUNDARY_LOW` / `INTERIOR` / `BOUNDARY_HIGH` / `INFEASIBLE`）编译侧完全没有
  这个概念；它只在**层间**可判，与残差是否为零无关。

## 决策三：目标值对账只要两侧，第三侧**刻意不做**

§5.3 的 S0 要求 `Z_ref` 由 T04-08 的独立实现给出。复核层**不**自算业务侧利润去顶替它：
`compiler.evaluate` 与 `check_solution` 的比对是 CC-07 的活，复核层再算一遍就是同一件事
做两次（同源规则⑥：判据不得自证）。故 SV-13 在缺少 `Z_ref` 时判 **BLOCKED**，
并把「禁止用本层自算的业务式顶替」写进判据原文与制品。

SV-05 的两侧是**跨来源**的：一侧是求解器自报值（外来），一侧是本层对模型系数的独立复算。
ε_Z 取 §4.1 的绝对+相对混合形式 `eps_abs + eps_rel_price·max(|a|,|b|)`（本项目 ≈ 0.0105 元），
替代 BB-07 的层内 ad-hoc 常量（`backend_spec.open_items` 已把它挂账为「需按后端分别声明」）。

## 决策四：**未走到**与**没查成**与**查出问题**是三种事，三种状态

| 状态 | 含义 | 处置 |
|---|---|---|
| `SKIP` | 本轮没检查（无解 / 缺实例） | 不阻塞，但**不得**读成通过 |
| `BLOCKED` | 这一环**没检查成**（缺已验证的输入） | 必须可见，不许静默降级 |
| `FAIL` | 查出问题 | 必须可见 |

其中两条边界是本决策的关键：

1. **SV-03：容差带必须被被测实例真的走到，否则判 WARN 并写明复跑条件。**
   探针的最优值可精确表示（C1 slack 恰为 0），故容差带**不被任何行走到**——此时
   声明容差的「载荷」在这一轮上是**未被验证**的。判 WARN 而不是 PASS，理由是把
   「这一轮没走到」与「已成立」分开（第 ⑧ 条同源规则：判据覆盖面不得取决于被测数据；
   若覆盖面确实取决于数据，就必须**显式声明**这个依赖）。
2. **SV-13：没有解 ⇒ SKIP；有解但没有 `Z_ref` ⇒ BLOCKED。** 二者不得合并——合并会让
   「参考实现未落地」被读成「本轮没跑」。

verdict 聚合为 `worst(...)`，优先级 `FAIL > BLOCKED > WARN > SKIP > PASS`；判据集为空
判 BLOCKED（无判据即无证据）。`FAIL` 与 `BLOCKED` **必须可分**：FAIL = 有结论的问题，
BLOCKED = 没结论的环节；把 BLOCKED 排在 FAIL 之下会让有结论的问题被没结论的环节盖住。

## 决策五（本条最重）：判决必须**具名**，不具名的数会把正常实现报成违规

T04-02D 一落地就实测到两处缺陷，都是「数在源码上看得见、含义却没人声明」：

### DV-01 行上声明的容差名从未被解析

在 C1 行注入 C1 残差 **5.0e-9**（在声明的内层容差 `eps_solver = 1e-8` **之内**）：

| 层 | 容差 | 判定 |
|---|---|---|
| `compiler.evaluate` | 未具名的 1e-12 | **不可行** |
| `instance.check_solution` | `eps_total` = 0.01 | 可行 |
| `backend` BB-08 | 取两侧与 | **FAIL**，理由写「求解器在**另一个模型**上求了最优解（导出层走样）」 |

导出层没问题（CC-09 已 PASS）。**真因是容差名未解析 ⇒ 两侧宽度差 1e10 ⇒ 内层的严格
算术判定被当成业务可行性结论。** 现实可达性：HiGHS 默认原始可行容差 1e-7，PuLP 报告前
还会就地舍入，故任何真实规模项目（q0 非整十、n 大）的 C1 残差都会落在 `[1e-12, 1e-8]` 带内——
这是必然触发，不是偶发。

修法：`evaluate` 增 `tolerances` 参数；`RowEval` 把两个判定**分开命名**——`ok_exact`
（严格算术，旧口径，CC-07 的数值对账用得上的那个）与 `ok`（可行性，按声明容差）；
另加 `in_tolerance_band` 把「落在带内」这一事实暴露出来。不传 `tolerances` ⇒ 行为不变，
故 CC-07 不受影响（它比的是 `lhs` 值，不是 `ok` 标志）。BB-08 的**归因**同时加了口径自述：
未传容差表时不再断言「导出层走样」，而是说明该判定走的是严格算术口径、不足以断言不可行。

### DV-02 同一 profile 字段的两种量纲读法被混用（乘重一遍）

见决策一。这一条与历史上 `∂Z/∂p` 误写 `q1·r_eff` **同族**：都是把一个量乘了两遍，
结果不违反任何语法约束、不报错，只是判据静默失效或误杀。

两处的共同教训写成规则：**凡判决里出现的宽度，必须具名，且一个名字只对应一种量纲。**
它同时是 CC-12「数值必须具名」的第二个受益面——CC-12 原本只被当作防手写系数的手段，
现在看它防的同一类事：未具名的常数在源码上等价于「一个很小的数」，而它可能是 1e-12，
也可能是 1e-8，也可能是 9000。

## 决策六：`verify-solution` 的退出码在未定态下是 1，这是设计而非故障

当前 `verify-solution` 在装有求解器的环境里退出码为 1，verdict 为 `BLOCKED`，原因是
两条**本任务之外**的未定态：

| 判据 | 未定态 | owner | 复跑条件 |
|---|---|---|---|
| SV-07（`floor` 一路） | T03-02 的 `floor_i` 未接入 | T03-02 | `floor_by_id` 可传入时该路转为可判 |
| SV-13（参考对照） | T04-08 的独立参考实现未落地 | T04-08 | 传入 `Z_ref` 且其独立性验收 PASS |

这与 `phase1-check` 的口径一致（非 EXACT 即返回 1），也与「BLOCKED 不得被 override」
一致。**它与 `extract_tasks --check` 那种常红信号的区别在于**：这里的成因是两个**具名
owner + 明确复跑条件**的未定态，逐条印在报告里；那一种的成因连检查脚本自己都表达不出来
（见另一条挂账）。

因此 `verify-solution` **不**进入「必须退出 0」的常驻校验环集合；它的预期状态被声明为
「BLOCKED，两个具名 owner」，而不是「绿」。

## 后果

- T04-02D 完成判据满足：四族声称各有机械判据，且每族都能说出「内层没有做什么」。
- `evaluate` 新增可选 `tolerances`（不传则行为不变）；`SolveResult` 新增 `tolerances_applied`
  字段，使报告能自述这次判定用的是哪个口径。
- `solver_backend_spec` 的 BB-08 归因改为口径自述；`lp_compiler_spec` 的 `RowEval` 契约扩展
  为 `ok` / `ok_exact` / `in_tolerance_band` / `tolerance_name` / `tolerance_value`。
- 测试 659 → 719（`tests/test_solution_verifier.py` 60 项；每条 SV 判据配错误注入的区分度层，
  另加 DV-01/DV-02 的回归用例）。
- 未推翻任何既有决策。ADR-0020 的 D1 与 §8.2 的「两层 ε」在本任务里第一次**真的被实现**。

## 遗留

- SV-07 的 `floor` 一路、SV-13 的参考对照两族 BLOCKED（见决策六，均有具名 owner）。
- `eps_price` 解析为「×P\*」的口径对单价量级很小的项目偏松（P\* = 1e6 时约 1e-3 元，
  相当于 0.01 元/单位的 10%）。该口径由 `precision_profile` 明示、`compute_lb_c5` 亦已采用，
  本层**不擅自改读法**，只在制品 `open_items` 登记；若要改，须三处同步改（否则判据自证）。
- ρ_layer 的阈值**刻意不设**：§4.2 已把它定为描述性指标，设阈值等于把它升格成证伪判据。
- 多最优解与平台效应（`r_eff` 相等项）的 canonical tie-break 属 T04-06B，本层只标
  「落在容差带内」的 AMBIGUOUS，不负责选解。

---

## 补记（2026-09-17，同一任务收尾时追加；不改上文任何决策）

**补记一：DV-01 的修复当时**只做了一半**，第二半在收尾复核时才发现——这本身是教训。**

决策五把 DV-01 的修法写成了「`evaluate` 增 `tolerances` 参数」。按那个修法做完，
编译侧确实按声明容差了，但**业务侧的 `instance.check_solution` 仍在用严格比较判盒式
约束**（`L`/`U`），只有 C1 用 `eps_total`。于是同一个解：

| 侧 | 判定 `p = U + 5e-12` | 口径 |
|---|---|---|
| 编译侧 `compiler.evaluate`（已传容差表） | 可行 | 声明行容差 `eps_price` = 0.003 |
| 业务侧 `instance.check_solution`（旧） | **不可行** | 严格（0 容差） |

**只修一半比不修更隐蔽**：修完编译侧后，它看起来已经「按声明容差判」了；两侧不一致
只有在把**两侧结论摆在一起**时（即 BB-08 的双侧可行性）才看得出来。原来的 BB-08 恰好
就是看两侧的那个判据——可它当时正被 DV-01 的**错误归因**牵着走，读不出这是口径问题。

第二半修法：`check_solution` 增 `tolerances` 参数，盒式约束改用**声明名** `eps_price`
的宽度判；`SolutionCheck` 增 `tolerance_name` / `tolerance_value` / `tolerance_resolved`
**自述口径**；传了表却缺该名 ⇒ **不静默按 0**，由 BB-08 判 **BLOCKED**（「口径不可比」
既不是 PASS 也不是 FAIL）。

由此在决策五的规则上再加一句：**「具名」还必须是同一个约束的两侧共用同一个名。**
推论：凡「同一约束在不同层各判一次」，须有一处**跨层对账**（此处即 BB-08）来暴露口径
不一致；没有跨层对账，两侧各自自洽地错着，永远不会被发现。

区分度层（两方向都进测试）：`p` 越上界 5e-12 ⇒ 不传表判不可行 / 传 `eps_price=0.003`
判可行；真越界 0.5 ⇒ 仍判不可行；表在但缺 `eps_price` ⇒ `tolerance_resolved=False`
且 BB-08 判 BLOCKED。

**补记二：决策六与后果里的数字更正。**

- 后果一条写「测试 659 → **719**」，当时 T04-02D 的用例尚未全部落地；收尾实测为
  **659 → 735**（`tests/test_solution_verifier.py` 60 项 + `TestDeclaredTolerance` 6 项
  + `TestBB08ToleranceCaliber` 6 项 + 业务侧容差 4 项）。零依赖环境 **735 OK / 9 SKIP**，
  装 PuLP 环境 **735 OK / 0 SKIP**。
- 决策六的表格与结论不变，但收尾时实测到：补齐 `floor`（T03-02）与 `Z_ref`（T04-08）
  两个入参后，`verify-solution` 的 verdict 由 `BLOCKED` 升为 **`WARN`**，余下唯一 WARN
  即 **SV-03**（探针的 C1 slack 恰为 0 ⇒ 容差带没被本实例走到）。这正验证了决策四第三态
  的设计意图：两个 BLOCKED 是**输入未给**，不是实现缺陷——给了就真的能判。

**补记三：新增一条挂账（属过渡态，不是缺陷）。**

`solve_compiled` 现在同时有 `eps_total`（旧：裸浮点，只喂 C1）与 `tolerances`（新：
声明名→数值表，喂各行 + 业务侧盒式边界）。**二者可以不一致**：若调用方只传 `eps_total`
而漏传 `tolerances`，C1 按 `eps_total` 判、盒式仍走严格口径，BB-08 就落回 DV-01 的错配。
当前 CLI 两条路径都传表、测试亦覆盖，但这是**过渡态**，应由后续任务收敛为 `tolerances`
单一入参（届时 `eps_total` 从 `solve_compiled` 与 `check_solution` 一并移除）。
已登记进 `config/solver_backend_spec.json` 的 `open_items`。

**补记四：上游制品的交接条目已同步。**`lp_compiler_spec.consumers[T04-02D]` 与
`solver_backend_spec.consumers[T04-02D]` 由「待办」措辞改为「已完成 + 本轮改了什么口径」，
并按项目规则全仓 grep 过旧表述（`evaluate` 的旧严格口径、BB-08 的旧归因文案）。
`docs/tasks.json` 的 T04-02D 已标 `done`，evidence 指向本 ADR。
