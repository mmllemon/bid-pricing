# ADR-0025 派生量的唯一来源：地板必须在**一个**地方算，且空 cap 不是 0

- 状态：已采纳
- 日期：2026-09-17
- 任务：T03-02（派生量计算）
- 相关：ADR-0004（未定态不得降级为默认值）、ADR-0006（就绪性判声明不判行数）、
  ADR-0007（沉默不是断言）、ADR-0009（loss_acceptance 的地板钳制）、
  ADR-0013（治理三档）、ADR-0015（判据不得自证）、ADR-0019（Phase 1 精确性）、
  ADR-0022（约束编译器）、ADR-0024（解校验器）
- 制品：`config/derived_quantities_spec.json`（新）、`src/bidpricing/derived.py`（新）、
  `tests/test_derived.py`（新）、`config/lp_formulation_spec.json`（改）、
  `config/solution_verifier_spec.json`（改）
- 判据：`derive-check`（DQ-01..DQ-11）

---

## 背景

`L_i / U_i / floor_i / r_eff_i` 四个派生量的**规格**早已写全，但**实现**一直缺席：

| 派生量 | 规格在哪里 | 落地状态（本 ADR 之前） |
|---|---|---|
| `U_i = cap_i` | `constraint_schema.C2` | 编译层直接用 `Phase1Item.U` |
| `L_i = max(L_i^tender, 0)` | `constraint_schema.C3`（2026-09-16 重定义） | 编译层直接用 `Phase1Item.L` |
| `floor_i = max(L_i, c_i(1−μ_i))` | `constraint_schema.C4` + ADR-0009 | **完全没有**——只能靠 `compile(floor_by_id=...)` 手工传 |
| `r_eff_i` | `pricing_card.compute_r_eff` | 已实现（`Phase1Instance.r_eff` 委派） |

于是 `formulation._merged_lower` 的原注释留下了一句话：

> `floor_i` 是 T03-02 的派生量……**不在** `Phase1Item` 上——T04-02A 先于 T03-02
> 落地时它缺席。故由调用方通过 `floor_by_id` 传入；缺省表示「尚未接入」，
> 此时**不得**用 `c_i` 或 `L_i` 冒充地板。

这个占位在设计上是诚实的，但它的**后果**是结构性的：地板没有实现，可它又必须
在编译层（C4 的行）与判定层（T03-04 的逐条复算）各被用到一次。两处各自硬编码
C3/C4 的阈值 ⇒ **同一个地板出现两个真相来源**，两侧会各自自洽地错着、永远撞不上
（规则⑨ 的同根因：同一约束在不同层各判一次，缺一处跨层对账）。

直接证据：T04-02D 的 **SV-07（上下界四路复算）** 因 `floor` 缺席而**恒判 BLOCKED**
——它没法知道「起作用的下界是 L 还是 floor」。

---

## 决策

### 一、派生量收拢到**一层**，其余位置只引用不重算

`src/bidpricing/derived.py::compute_derived` 是四个派生量的**唯一实现**。
它只做三件事：**取大 / 取小 / 委派**——不做优化、不做判定、不做诊断。

`formulation._merged_lower` 的 `floor_by_id` 由此而来（CLI 已接线，见决策六）。
下游（T03-03 预检 / T03-04 判定 / T04-01 解析解 / T04-02A/B 建模 / T04-04 对拍）
一律**引用**本层输出，不得自行复算阈值。

**为什么不是「就近实现」**：地板一旦在两边各写一次，C4 的语义就分叉了。而且
分叉不会报错——两侧都「自己算自己的一致性」，直到有人把两侧结论摆到一起
（正如 T04-02D 的 DV-01 暴露出的：编译侧按 `eps_price` 判可行、业务侧按严格
口径判不可行，只在 BB-08 的双侧对照下才看得见）。

### 二、`loss_acceptance=ACCEPT` 的钳制**只在 cap 非空时生效**

ADR-0009 裁定 `floor_i := min(floor_i, cap_i)`。本层明确了它的**定义域**：

```
cap 非空 ⇒ floor_i = min(max(L_i, c_i(1−μ_i)), cap_i)
cap 为空 ⇒ floor_i = max(L_i, c_i(1−μ_i))        ← 不钳
```

★ **这是本层最容易静默出错的一处。** 空 `cap` 的合法语义是「不限价」
（`ALLOW_EMPTY_NO_CAP`），不是 0。若把空 cap 当 0 参与 `min`，地板会被
**静默压到 0**——地板失效、C4 形同虚设，却**不报任何错**。规格里为此单列
一条（`floor_i.clamp_rule`）、实现里单列一条分支、测试里单列一条用例
（`test_accept_does_not_clamp_when_cap_is_null`）。

### 三、`r_eff` 只允许**委派**，并用静态判据守住

`r_eff` 的唯一实现是 `contracts/pricing_card.compute_r_eff`（经
`Phase1Instance.r_eff`）。本层**不得**调用 `settlement_revenue`——那是 `R_i`
的实现，调用它就意味着要自己做差分求 `dR/dp`，即自造 `r_eff`。

界线刻意画在**符号级**而非「意图级」：`DQ-08` 用 AST 审计本模块源码，
禁用符号表是 `("settlement_revenue",)`。这样判据可判、可复现，且文档字符串里
提到该符号不算违规（`_collect_docstrings` 排除）。

历史依据：目标系数误写成 `q1·r_eff` 的那个 bug（ADR-0022 推翻 ADR-0021 的那句）
就是「把排序键又乘了一遍 `r_i`」——满足全部约束、**次优**、不报错。

### 四、计算与判定**分离**，使判据可以注入验证

`judge_derived(items, ...)` 只吃 `DerivedItem` 序列（不吃实例、不吃配置），
`compute_derived` 调用它。

**为什么这条是硬要求**：判据若与计算耦合，测试就只能验证「我的实现恰好是对的」，
而无法验证「判据能否抓到错的实现」——后者才是区分度。分离之后，
`tests/test_derived.py` 可以直接构造 `DerivedItem(floor=600, U=500)` 并断言
判据 FAIL。于是每条判据都做到**两个方向**：

* 正确的值不被误杀（判据太紧会把正常实现报成违规）；
* 错误的值必被抓住（判据没有区分力就等于没判）。

### 五、`L_i` 是**多来源取大**，不是覆盖

C3 重定义后的口径是「多来源取大」：`L_i = max(实例下界, L_i^tender, 0)`。
两条来源各有其依据（招标限价表的下限列 / 不平衡报价条款），**取大**；
不是二选一，也不是「后到者覆盖」——覆盖会让其中一条依据被另一条静默抹掉。

### 六、三档治理在本层的落地（ADR-0013）

| 情形 | 判定 | 依据 |
|---|---|---|
| `μ` 的 key 缺失 / 值为 null | **BLOCKED** | 算不出（ADR-0004）；两者理由不同、机器上可区分 |
| `μ = 0` | **PASS** | 合法取值（不允许任何亏损），与「未声明」是两件事 |
| `c_i=0` 且 `role=OPTIMIZABLE` | **BLOCKED** | 数据可疑（`field_schema.c_i`） |
| `unbalanced_clause` 整块缺失 / `enabled` 缺失 | **BLOCKED** | 沉默不是断言（ADR-0007） |
| `enabled=false` | **PASS** | 合法**结论**（已核查无该条款），`L_i` 取 0 |
| 条款 `enabled=true` 但 `tol_lo` 缺失 | **BLOCKED** | 禁用默认值：阈值没有招标依据时不得编造 |
| ★ 条款以 CAP 为基准，而该项 cap 为空 | **WARN** | 可解释性：条款对不限价项的适用性本身未声明，**不 BLOCKED、也不取 0 冒充** |
| `loss_acceptance` 未落值 | **WARN** + 按 DECLINE 算 | 「宁可判死也不静默放宽」 |

---

## 后果

### 正面

1. **SV-07 挂账闭合。** `verify-solution` 的 floor 默认改由本层生产。实测对照：

   | 输入 | SV-07 | 全表 |
   |---|---|---|
   | 不给 floor | **BLOCKED** | BLOCKED 4 / PASS 16 / WARN 6 |
   | 给 floor（`μ=0.1`、无条款） | **PASS** | BLOCKED 2 / PASS 22 / WARN 2 |

   余下 2 条 BLOCKED 即 **SV-13**（`Z_ref`，owner = T04-08），与本层无关。
   这正是三档治理的设计意图：BLOCKED 是**输入未给**，给了就真的能判。

2. **编译侧与判定侧从此共用一份地板**，规则⑨ 要求的「跨层对账」由单一来源
   在结构上保证，而不再依赖两边各自小心。

3. 判据 `DQ-01..DQ-11` 全部双向可测（55 项用例）。

### 代价与遗留

* **`μ` 与 `unbalanced_clause` 至今没有落值位置**（`open_items` OI-DQ-A / OI-DQ-B）。
  因此真实项目上 `derive-check` 与 `verify-solution` 的 floor 一路**必然是
  BLOCKED** —— 这是**如实反映数据未定**，不是实现缺陷。按项目规则，该命令
  **不进常驻验证环**（与 `verify-solution` 同）。
* `δ⁺` 因 `base_i := cap_i` 而失效（`U_i ≡ cap_i`），须在配置中显式标注
  「对本项目无作用」而非让它静默存在（OI-DQ-C）。
* 条款 × 空 cap 的组合（OI-DQ-D）判 WARN；若用户后续澄清条款对不限价项无效，
  应改**判据**而非改**判据集**（后者会削弱区分度）。

### 本条新增的通用教训

> **「空值」与「零值」在派生层必须分道**：凡口径里出现 `min(x, cap)` 这类以
> 可选量为界的运算，都要先问「界不存在时这个运算还有定义吗」。没有定义时
> 若退回 0，得到的是一个**看起来算完了、实则失效**的结果——它不报错，
> 只是把约束悄悄取消了。这与 DV-01（两侧口径不一致）同族：
> 都属于「不报错的错」，只能靠**显式的具名分支 + 双向测试**拦住。
