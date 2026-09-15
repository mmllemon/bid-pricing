# 开发状态板 —— 对照《实施路线 v3.2.1》

基线：《投标报价模型 v0.3 实施路线与任务清单 v3.2.1》（68 任务 / 8 闸门 / 19 条隐藏依赖）。

**状态标记**：`[已完成]` ｜ `[待人工落值]` 结构就位、待领域输入 ｜ `[未开工]` ｜ `[门禁阻塞]` 被 Gate 拦下。

---

## 一、闸门基础设施（本增量新增，非路线原始任务）

路线的闸门原本是**文档里的表格**，本增量把它变成了可执行代码。

| 路线条款 | 实现 | 状态 |
|---|---|---|
| §5 全局四态状态机 | `src/bidpricing/states.py` | [已完成] |
| §7.1 Gate 0a / 0b 机械判据 | `gates/gate0.py::check_gate_0a / check_gate_0b` | [已完成] |
| §7.1.1 断言 1 未定态表示法 | `gate0.guard_representation` | [已完成] |
| §7.1.1 断言 2 未定态熔断 | `check_gate_0a`（enum 判 BLOCKED） | [已完成] |
| §7.1.1 断言 3 双闸门独立 + 放行清单 | `check_gate_0a::release_scope` | [已完成] |
| §7.1.1 断言 4 字段有效性机械化 | `artifact.verify_versioned` | [已完成] |
| §7.1.1 断言 5 时序断言 | `gate0.assertion_5_sequence` | [已完成] |
| §7.1.1 断言 6 CI 门禁 | `gate0.assertion_6_config_zero_defaults`、`assert_wp4_build_allowed` | [已完成] |

> **为什么先做闸门**：按 §7.1.1 断言 2，`adjustment_scope` 未定则 Phase 0 直接 BLOCKED，
> WP1/WP2/WP3 不得开工。若闸门只停留在文档里，这个约束就靠人的自觉；
> 变成代码后，"未定态"会在构建阶段被机械拦下。

---

## 二、WP0 模型契约冻结（15 项）

| 任务 | 产出物 | 实现 / 制品 | 状态 |
|---|---|---|---|
| **T00-08** 规则集选择器（**起点任务**） | `select_rule_set()` 模块 | `contracts/selector.py` + `contracts/rule_sets/` | [已完成] |
| T00-01 合同计价与调价口径冻结 | 《计价规则卡》 | 规则集已承载调价口径；`adjustment_scope` 落值待人工裁决 | [待人工落值] |
| T00-02 字段字典冻结 | 《字段字典 v1》 | `config/field_schema.json`（已冻结 `sha256:858b0c997f85`） | [已完成] |
| T00-03 约束字典冻结 | 《约束字典 C1–C12》 | `config/constraint_schema.json`（已冻结） | [已完成] |
| T00-04 精度与容差策略冻结 | 《精度策略表》 | `config/precision_profile.json`（已冻结，含 2 项遗留） | [已完成] |
| T00-05 三层分割架构地位确认 | 架构决策记录 | `config/architecture_decision.json` + `docs/ADR-0001-*.md` | [已完成] |
| **T00-06** 可竞争性分类与变量集合冻结 | 分类表 + 变量集合 | 5 个 role + 启发式规则就位；分类表为空，待真实清单 | [待人工落值] |
| **T00-06B** P_competitive 与基数联动 | 总价分解计算规范 | 未开工（依赖 T00-06 分类结果） | [未开工] |
| **T00-07** 规则集优先级冻结 | 《规则优先级卡》 | 优先级链 `Contract>Tender>Regional>Standard` 已实现；强制测试见 `ruleset_self_test` | [已完成] |
| **T00-09** 成本口径证明包 | 成本构成规范 | 未开工（需造价专业取数） | [未开工] |
| **T00-10A** q^1 假设：格式与冻结时点 | 《q^1 假设声明书（格式篇）》 | 未开工（需人工） | [未开工] |
| **T00-10B** q^1 来源判定 | 《q^1 假设声明书（来源篇）》 | 未开工（依赖 T01-00B 合同解析） | [未开工] |
| **T00-11** 成本 c_i 假设与来源声明 | 《c_i 假设声明书》 | 未开工（需人工） | [未开工] |
| **T00-12** 利润口径桥接表 | 《利润口径桥接表》 | 未开工（依赖 T00-06B、T00-09） | [未开工] |
| **T01-00A** 输入协议 Schema 冻结（**属 WP0**） | 输入协议规范 | `config/input_protocol_schema.json`（已冻结） | [已完成] |

**WP0 已完成 7 / 15**，其余 8 项均需人工领域输入（合同解读 / 成本取数 / 真实清单）。

---

## 三、WP1–WP7（53 项）

| WP | 任务数 | 状态 |
|---|---|---|
| WP1 数据层 | 11 | [门禁阻塞] Gate 0a |
| WP2 配置层 | 5 | [门禁阻塞] Gate 0a |
| WP3 判定层 | 7 | [门禁阻塞] Gate 0a |
| WP4 求解层 | 13 | [门禁阻塞] Gate 0b（§7.1.1 断言 6② 硬门禁） |
| WP5 鲁棒性 | 5 | [门禁阻塞] Gate 3 |
| WP6 交付层 | 8 | [门禁阻塞] Gate 5A |
| WP7 闭环 | 4 | [门禁阻塞] 依赖 WP6（不阻塞交付） |

---

## 四、当前阻塞项（Gate 0a 评审结论）

```
$ PYTHONPATH=src python -m bidpricing.cli gate-check --contract-date 2026-03-01
Gate 0a = BLOCKED   （6/8 判据通过）
```

| # | 阻塞项 | 性质 | 解除方式 |
|---|---|---|---|
| 1 | `adjustment_scope` | **人工裁决** | 对 GB/T 50500-2024 §8.9.2 是否分段作出解读，落值为 `FULL` 或 `SEGMENT` |
| 2 | `competitiveness_classification` | **数据依赖** | 提供真实招标清单，逐项标注 `pricing_role` |

闭合后 Gate 0a 通过，放行 WP1 / WP2 / WP3（放行清单不含 T00-10B）。

Gate 0b 的 5 项制品与分级审批独立于 Gate 0a，不阻塞 WP1/WP2/WP3，但**阻塞 WP4 求解层**。

---

## 五、可复现的验证命令

```bash
# 55 项单元测试
PYTHONPATH=src python -m unittest discover -s tests -t .

# 规则集指纹：2013 连续 / 2024 跳降 / 两者可区分
PYTHONPATH=src python -m bidpricing.cli ruleset-selftest

# Gate 全量机械判定（人类可读）
PYTHONPATH=src python -m bidpricing.cli gate-check --contract-date 2026-03-01

# Gate 判定（机器可读，供 CI 消费）
PYTHONPATH=src python -m bidpricing.cli gate-check --contract-date 2026-03-01 --json

# 模拟"若 adjustment_scope 已裁决"的状态：仅剩 1 项阻塞
PYTHONPATH=src python -m bidpricing.cli gate-check --contract-date 2026-03-01 --adjustment-scope FULL
```

---

## 六、实施路线 vs 本代码的三处口径选择（需知悉）

1. **过渡项目回落 2013 的条件**：路线 T00-08 原文写「过渡项目**或**合同另有约定」，
   §8.3 校正一写「**且**」。代码采用 §8.3 的严格口径（两个条件同时成立），
   仅命中日期条件时输出 `BLOCKED` 而非默认取 2013——符合「禁止默认取任一侧」。

2. **2024 版减量侧作用域无分叉**：「减少后剩余部分」本就是全部 q1，
   故 `FULL` 与 `SEGMENT` 在 r<0.85 时等价；作用域分叉只出现在增量侧（r>1.15）。

3. **指纹判据存在已知退化条件**：ρ± 的规范默认值为 0，若探针也取 0，
   两套规则集的 r_eff 完全重合、指纹退化。故 `ruleset_self_test`
   强制使用非零探针（默认 0.01），并在 `ruleset_selector_spec.json` 中登记该退化条件。

---

## 七、下一步建议

| 优先级 | 动作 | 说明 |
|---|---|---|
| P0 | 裁决 `adjustment_scope` | 一项裁决即解除 Gate 0a 一半阻塞，且决定 WP3 的 R_i 分段代码结构 |
| P0 | 提供 1 套真实招标清单 | 解除 `competitiveness_classification`，同时为 T01-00B 解析器与 T01-02B 变体测试集提供样本 |
| P1 | 确认精度策略 §8.2 的模式 A / B | 当前 `precision_profile.json` 的 `equality_tolerance_mode.current` 为 null |
| P1 | 启动 T00-09 / T00-10A / T00-11 / T00-12 | 四项均需造价与合同专业输入，可并行推进，是 Gate 0b 的主体 |
