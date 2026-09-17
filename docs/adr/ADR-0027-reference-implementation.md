# ADR-0027：独立参考实现（T04-08）与三层隔离证明

- 状态：已接受（2026-09-17）
- 关联：ADR-0015（目标必须具名）／ADR-0022（目标系数 `∂Z/∂p = q0·r_eff`）／
  ADR-0024（解校验器，SV-13 挂账）／路线 v3.2.1 P2-⑩、§5.3 S0
- 受控制品：`config/reference_impl_spec.json`（RI-01..RI-11 + ISO-1/2/3）

## 背景

路线 §5.3 判据 S0：**solver objective 正确 ≠ 业务利润正确**。复核层若与生产层共用
同一份 `R_i` / constraint / objective 实现，则「两条路径一致」只是同一错误的两次
复现（共因错误），对拍恒绿而无信息量。SV-13 因此长期 BLOCKED，显式写明 owner =
T04-08，并禁止本层自造「业务式重算」顶替（那与 CC-07 同源，构成恒真式）。

## 决策

### ① 参考实现**不 import 任何生产模块**（ISO-1 的最强形态）

`src/bidpricing/refimpl/reference.py` 靠冻结快照 + 取属性（鸭子类型）读实例，
连 `Phase1Item`/`Phase1Instance` 都不 import。于是「源码文件不重叠」不是纪律声明，
而是**可机械审计的事实**：AST 审计按制品声明的禁名/禁模块清单扫描，
命中即 BLOCKED，清单住 `config/reference_impl_spec.json`（不住代码——
让被测对象自带答案等于没有判据）。

*允许多次被问的那一点*：底层数据结构本可共享（路线原文许可），本实现选择连它也不共享——
代价是多写几行快照代码，收益是审计结论从「我们声明没共享」升级为「可复算地没共享」。

### ② 公式来源是**制品与路线文档**，不是生产代码

`Z = Σ[R_i(p_i) − c_i·q_i^1]` 取自路线 §5.3 S0 原文；目标**层**口径取自
`profit_bridge_spec.json`（`objective.level=Z_OBJECTIVE`、`EXCL_VAT`）；
三分支 × 作用域与阈值/ρ± 取自 `pricing_rule_card.json` + ADR-0010。
★ 因此 `increase_threshold` **本身已是** `1+θ_dev` 这条口径在参考实现里是**独立地再写一遍**，
而不是照抄生产注释——历史上真实踩过（写成 `1+increase_threshold` 使越界段系统性高估，
`test_phase1_exactness.py` 例 2R 抓到过）。测试用**手算数值**钉死六个分支组合。

### ③ 两个口径两个名字：`Z_total` / `Z_competitive`

§5.3 S0 是全量口径，利润桥接表的目标层是 `i∈X_opt`。二者差 `constant_part`。
★ 与 DV-02 同族：同一个物理量有两种读法必须两个名字，混用即把同一个量算两遍，
不报错而静默偏掉一个常数。SV-13 用 `Z_total`（与 `check_solution`、LP 目标复算同口径）。

### ④ ε_Z 必须**相对 + 绝对混合**，且两项具名

`ε_Z = eps_abs + eps_rel_price · max(|Z_solver|, |Z_ref|)`，两项均由
`precision_profile.json` 经 `resolve_tolerances` 具名供给；缺任一项 ⇒ BLOCKED，
**不按 0 放行**（那会把「不可比」读成「一致」）。理由见 §4.1：单价量级跨 0.01 至 1e5。

### ⑤ 三层隔离证明中，**③（作者分离）不得伪造**

①源码不重叠、②不共享可变状态 可机械证明（②用运行时探针：产结果后改输入，
复读结果必须不变）。③「独立实现不得由生产代码作者单人完成」**机械判据无法证明**
——因此它只读签署记录 `docs/reference_review_signoff.json`：
未签署 ⇒ BLOCKED，owner = 用户（Liam）。★ 绝不因为「应该没问题」而代为签署：
伪造 PASS 等于把共因错误重新引进来，比不做更隐蔽。

后果（按路线）：ISO-3 未 PASS ⇒ T04-04 对拍结论栏**强制标 BLOCKED**，
不得出现「对拍通过」字样。`ref-check` 与 `verify-solution` 均如实打印该状态。

### ⑥ 计算与判定分离（继承 T03-02/T04-01 的同款设计）

`judge_reference` 只吃数据（objective/residuals/params/tolerances/isolation），
不读实例与配置 ⇒ 判据可注入验证：注入差 10000 的 `Z_solver` 必须 FAIL、
注入被篡改的逐项贡献必须 FAIL、制品少声明一个分支必须 BLOCKED。
只验证「我的实现恰好对了」的测试没有信息量。

### ⑦ SV-13 挂账闭合（含一处被它自己抓到的真 bug）

`verify-solution` 未给 `--reference` 时，默认向参考层索取 `Z_ref`，
并**自述来源**（与 T03-02 的 floor 同款三项优先级 + 来源自述）。
首次接线即出现 MILP 变体 SV-13 FAIL，真因：C7 的二值 `z_i` 与 `p_i` **共用 `item_id`**，
按 `item_id` 建映射时 0/1 把单价覆盖掉（不报错，只是 `Z_ref` 静默偏小）；
按变量族 `family == "p"` 过滤后修复。★ 这条正好是「跨来源对照」的价值实证：
若参考层只是生产层的复制，这个映射错误不会被任何一条判据发现。

## 后果

| 项 | 前 | 后 |
|---|---|---|
| SV-13（verify-solution，LP/MILP 两变体） | BLOCKED（owner 未落地） | **PASS**（Δ=0 ≤ ε_Z=0.01046） |
| T04-04 对拍结论 | 无从产出 | 可取 Z_ref；但 **ISO-3 未签 ⇒ 强制 BLOCKED** |
| Z_ref 的生产者 | 无 | `src/bidpricing/refimpl/reference.py`（唯一） |

## 未决（挂账，非缺陷）

- **OI-RI-A**：ISO-3 需第二人复核签署（`docs/reference_review_signoff.json`，
  `signed=false`）。**这是 Liam 的一个具体动作**：复核 `refimpl/reference.py` 的
  三分支公式与成本口径后填 `reviewer/date` 并置 `signed=true`。
- **OI-RI-B**：成本口径 `c_i·q_i^1` 目前只有路线 §5.3 S0 与利润桥接表（后者按
  `i∈X_opt` 表述）；若裁定目标口径应改用 `Z_competitive`，须改**制品**而非改实现。
- **OI-RI-C**：若 T00-04 后续引入专属 `eps_Z`，本制品须同步（两处不得各说一套）。
