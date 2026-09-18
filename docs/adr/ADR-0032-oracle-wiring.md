# ADR-0032：不可行诊断的预言机接线（T04-02E）

日期：2026-09-18　状态：已接受　任务：T04-02E　前置：ADR-0031、ADR-0023、ADR-0028

## 背景

T03-06 的诊断器以 `Oracle = instance -> FEASIBLE|INFEASIBLE|UNKNOWN` 三态注入为
唯一可行性出口，规格（`infeasibility_diagnosis_spec.json` oracle 节）当时只接了
`phase1_builtin` 并预留 `lp_reserved`：LP/MILP 预言机由 T04-02E 接线。本 ADR 记录
接线决策。

## 决策

**D1——编译链预言机 `milp_oracle` 的状态映射**（唯一许可的映射）：

| 归一状态 | 预言机结论 |
|---|---|
| INFEASIBLE | INFEASIBLE |
| OPTIMAL / FEASIBLE | FEASIBLE |
| UNBOUNDED / AMBIGUOUS / UNAVAILABLE / UNSUPPORTED（含后端异常） | UNKNOWN |

- **backend UNAVAILABLE ⇒ UNKNOWN，不是缺口补位**：没跑成 ≠ 不可行（规格
  `lp_reserved` 原语义；与 ADR-0004「未定态不是断言」、ADR-0023
  UNAVAILABLE(SKIP)≠UNSUPPORTED(BLOCKED) 同族）。
- AMBIGUOUS（后端自述分不清无解/无界）不得折进 INFEASIBLE——折进去是无据断言
  （solver_backend_spec 状态域已钉，此处只沿用）。

**D2——链式 `chained_oracle(*oracles)`**：按序问，**首个非 UNKNOWN 胜出**；
整链 UNKNOWN ⇒ UNKNOWN。UNKNOWN 在链上不合并、不升级：unknown_semantics 的
原语义（UNKNOWN→FEASIBLE 才算恢复可行证据）。典型链 =
`chained_oracle(phase1_oracle(r), milp_oracle(r))`——解析侧适用域外
（EC-1..6 否定）时落编译侧，两侧相互独立，无共享内部状态。

**D3——注入点**：`milp_oracle(..., backend=, backend_spec=)` 透传
`solve_compiled` 的 BB-06 注入点。零依赖环境的测试用替身后端跑
build→compile→solve 全链路，不需要 pulp；真求解器路径由求解器环境的
端到端用例覆盖（低 B 实例由 HiGHS 实证 INFEASIBLE）。

**D4——CLI**：`diagnose --oracle phase1|milp|chain`（默认 phase1，行为与
T03-06 发布版完全一致）。零依赖环境选 `milp` 时输出 UNKNOWN ⇒ DG-01
BLOCKED——这是诚实降级，不是错误。

## 后果

- T04-02E 完成后，诊断器的预言机不再受解析侧适用域限制；C7（MILP 唯一
  z_i 语义）场景的可行性可由真求解器裁决。
- `lp_reserved` 条目从规格中移除，替换为 `milp_builtin`（已接线语义）。
- 测试 +9（test_diagnose 30→39），全量 1037→1046 双环境绿。
