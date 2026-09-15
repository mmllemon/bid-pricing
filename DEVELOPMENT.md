# 开发状态板 —— 对照《实施路线 v3.2.1》

基线：《投标报价模型 v0.3 实施路线与任务清单 v3.2.1》（68 任务 / 8 闸门 / 19 条隐藏依赖）。

**状态标记**：`[已完成]` ｜ `[待人工落值]` 结构就位、待领域输入 ｜ `[未开工]` ｜ `[门禁阻塞]` 被 Gate 拦下。

---

## 一、闸门基础设施（非路线原始任务）

路线的闸门原本是**文档里的表格**，本增量把它变成了可执行代码。

| 路线条款 | 实现 | 状态 |
|---|---|---|
| §5 全局四态状态机 | `src/bidpricing/states.py` | [已完成] |
| §7.1 Gate 0a / 0b 机械判据 | `gates/gate0.py::check_gate_0a / check_gate_0b` | [已完成] |
| §7.1.1 断言 1 未定态表示法 | `gate0.guard_representation` | [已完成] |
| §7.1.1 断言 2 未定态熔断 | `check_gate_0a`（选择项判 BLOCKED） | [已完成] |
| §7.1.1 断言 3 双闸门独立 + 放行清单 | `check_gate_0a::release_scope` | [已完成] |
| §7.1.1 断言 4 字段有效性机械化 | `artifact.verify_versioned` | [已完成] |
| §7.1.1 断言 5 时序断言 | `gate0.assertion_5_sequence` | [已完成] |
| §7.1.1 断言 6 CI 门禁 | `gate0.assertion_6_config_zero_defaults`、`assert_wp4_build_allowed` | [已完成] |
| **选择项判据**（本增量新增） | `gate0.check_selectable_option` + `selection_options.py` | [已完成] |

> **为什么先做闸门**：按 §7.1.1 断言 2，`adjustment_scope` 未定则 Phase 0 直接 BLOCKED，
> WP1/WP2/WP3 不得开工。若闸门只停留在文档里，这个约束就靠人的自觉；
> 变成代码后，"未定态"会在构建阶段被机械拦下。

---

## 二、选择项机制 —— `adjustment_scope` 的落地方式

`adjustment_scope` 决定 GB/T 50500-2024 §8.9「工程量偏差」的结算口径。
它既不是可由代码推断的常量，也不适合"一次裁决后写死"——**不同项目、不同合同条款下正确口径可能不同**。
故实现为**项目级选择项**，四条硬约束：

| # | 约束 | 落地 |
|---|---|---|
| 1 | 取值集合**按规则集而变** | 2024 → `FULL` / `SEGMENT`；2013 → 仅 `SEGMENT`（§9.6.2 明文分段）。在 2013 项目上落值 `FULL` 判为**配置冲突 → BLOCKED**，不再静默覆盖 |
| 2 | **不设默认值** | 注册表 `default` 恒为 `None`；断言 6① 静态扫描拒绝 `default` / `template` |
| 3 | 未选择 = **key 完全缺失** | 与断言 1 同构，使"还没选"成为机器可判状态 |
| 4 | 落值带**来源与依据** | `source` / `actor` / `selected_at` / `rationale` 写入 `config/project_selection.json`，构成决策依据快照 |

**解析优先级**：`CLI`（临时） → `config/project_selection.json`（项目落值） → `RULE_SET_DETERMINED`（规范明文确定，仅 2013） → **未定（BLOCKED）**。

落值来源与"人工选择"在审计上严格区分——2013 的口径标记为 `RULE_SET_DETERMINED`，
**不构成"未证假设"**；人工落值则必须带依据，缺失时命令会显式提示。

### 影响度量（选择前先看到代价）

```bash
$ PYTHONPATH=src python -m bidpricing.cli scope-impact --q0 100 --q1 130 --p0 10 --rho-plus 0.05
  FULL    结算金额 = 1235.000000
  SEGMENT 结算金额 = 1292.500000
  差额（SEGMENT − FULL） = 57.500000   （4.6559%）
  2013 参照值 = 1292.500000    SEGMENT 与 2013 同值：是
```

> **边界**：这是**规则层**分叉（同一报价在两种口径下的结算差）。
> 规格书附录 B 例 2R 中约 **4.5 倍**的最优利润差属**报价决策层**，
> 须由 WP4 在两条口径下分别求解后比较——二者不可互相替代，代码输出中已显式声明。

### 一个必须知悉的副作用：选择 SEGMENT 会使指纹判据退化

`r_eff` 在 `r = 1.15` 处的跳变量（T00-07/08 机械判据）：

| 规则集 / 作用域 | 跳变量 | 鉴别力 |
|---|---|---|
| GB 50500-2013（SEGMENT） | `≈ 0`（连续） | — |
| GB/T 50500-2024 **FULL** | `≈ −1.15·ρ⁺` | 与 2013 分离度显著 ✓ |
| GB/T 50500-2024 **SEGMENT** | `≈ 0`（连续） | **与 2013 同形 → 指纹退化** |

即：一旦项目选择 `SEGMENT`，数值指纹**不再能证明两套实现相互独立**。
此时区分依据退回条款覆盖（2024 拆为 §8.2 清单缺陷 / §8.9 工程变更，2013 为 §9.6.2 单条款）
与两版代码路径的独立实现。`ruleset-selftest` 会把该退化作为**遗留项**显式输出，
而不是让"自检 PASS"掩盖"此刻指纹已无鉴别力"。

---

## 三、WP0 模型契约冻结（15 项）

| 任务 | 产出物 | 实现 / 制品 | 状态 |
|---|---|---|---|
| **T00-08** 规则集选择器（**起点任务**） | `select_rule_set()` 模块 | `contracts/selector.py` + `contracts/rule_sets/` | [已完成] |
| T00-01 合同计价与调价口径冻结 | 《计价规则卡》 | 规则集已承载调价口径；`adjustment_scope` 已实现为**选择项**（落值通道就位，值待定） | [待人工落值] |
| T00-02 字段字典冻结 | 《字段字典 v1》 | `config/field_schema.json`（已冻结 `sha256:858b0c997f85`） | [已完成] |
| T00-03 约束字典冻结 | 《约束字典 C1–C12》 | `config/constraint_schema.json`（已冻结） | [已完成] |
| T00-04 精度与容差策略冻结 | 《精度策略表》 | `config/precision_profile.json`（已冻结，含 2 项遗留） | [已完成] |
| T00-05 三层分割架构地位确认 | 架构决策记录 | `config/architecture_decision.json` + `docs/ADR-0001-*.md` | [已完成] |
| **T00-06** 可竞争性分类与变量集合冻结 | 分类表 + 变量集合 | 5 个 role + 启发式规则就位；分类表为空，待真实清单 | [待人工落值] |
| **T00-06B** P_competitive 与基数联动 | 总价分解计算规范 | 未开工（依赖 T00-06 分类结果） | [未开工] |
| **T00-07** 规则集优先级冻结 | 《规则优先级卡》 | 优先级链 + 强制指纹测试；**已登记指纹退化条件** | [已完成] |
| **T00-09** 成本口径证明包 | 成本构成规范 | 未开工（需造价专业取数） | [未开工] |
| **T00-10A** q^1 假设：格式与冻结时点 | 《q^1 假设声明书（格式篇）》 | 未开工（需人工） | [未开工] |
| **T00-10B** q^1 来源判定 | 《q^1 假设声明书（来源篇）》 | 未开工（依赖 T01-00B 合同解析） | [未开工] |
| **T00-11** 成本 c_i 假设与来源声明 | 《c_i 假设声明书》 | 未开工（需人工） | [未开工] |
| **T00-12** 利润口径桥接表 | 《利润口径桥接表》 | 未开工（依赖 T00-06B、T00-09） | [未开工] |
| **T01-00A** 输入协议 Schema 冻结（**属 WP0**） | 输入协议规范 | `config/input_protocol_schema.json`（已冻结） | [已完成] |

**WP0 已完成 7 / 15**，其余 8 项均需人工领域输入（合同解读 / 成本取数 / 真实清单）。

---

## 四、WP1–WP7（53 项）

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

## 五、当前阻塞项（Gate 0a 评审结论）

```
$ PYTHONPATH=src python -m bidpricing.cli gate-check --contract-date 2026-03-01
Gate 0a = BLOCKED   （7/8 判据通过）
```

| # | 阻塞项 | 性质 | 解除方式 |
|---|---|---|---|
| 1 | `adjustment_scope` | **人工选择**（可选，非裁决） | `bidpricing options set --key adjustment_scope --value {FULL\|SEGMENT} --rule-set GB/T50500-2024 --rationale "..."` |
| 2 | `competitiveness_classification` | **数据依赖** | 提供真实招标清单，逐项标注 `pricing_role` |

落值后 Gate 0a **仅剩第 2 项**（已实测）。两项闭合后放行 WP1 / WP2 / WP3（放行清单不含 T00-10B）。

Gate 0b 的 5 项制品与分级审批独立于 Gate 0a，不阻塞 WP1/WP2/WP3，但**阻塞 WP4 求解层**。

---

## 六、可复现的验证命令

```bash
# 89 项单元测试（在"未落值"与"已落值"两种项目状态下均通过 —— 已显式验证隔离性）
PYTHONPATH=src python -m unittest discover -s tests -t .

# 规则集指纹自检（含 SEGMENT 作用域的退化登记）
PYTHONPATH=src python -m bidpricing.cli ruleset-selftest

# 选择项：清单 / 落值 / 撤销
PYTHONPATH=src python -m bidpricing.cli options list --rule-set GB/T50500-2024
PYTHONPATH=src python -m bidpricing.cli options set --key adjustment_scope \
    --value FULL --rule-set GB/T50500-2024 --rationale "招标文件未约定分段"
PYTHONPATH=src python -m bidpricing.cli options clear --key adjustment_scope

# 选择项影响度量（规则层分叉）
PYTHONPATH=src python -m bidpricing.cli scope-impact --q0 100 --q1 130 --p0 10 --rho-plus 0.05

# Gate 全量机械判定（人类可读 / 机器可读）
PYTHONPATH=src python -m bidpricing.cli gate-check --contract-date 2026-03-01
PYTHONPATH=src python -m bidpricing.cli gate-check --contract-date 2026-03-01 --json
```

---

## 七、实施路线 vs 本代码的口径选择（需知悉）

1. **过渡项目回落 2013 的条件**：路线 T00-08 原文写「过渡项目**或**合同另有约定」，
   §8.3 校正一写「**且**」。代码采用 §8.3 的严格口径（两个条件同时成立），
   仅命中日期条件时输出 `BLOCKED` 而非默认取 2013——符合「禁止默认取任一侧」。

2. **2024 版减量侧作用域无分叉**：「减少后剩余部分」本就是全部 q1，
   故 `FULL` 与 `SEGMENT` 在 r<0.85 时等价；作用域分叉只出现在增量侧（r>1.15）。

3. **指纹判据存在两类退化条件**：① ρ± 规范默认值为 0，探针取 0 时两版指纹重合；
   ② 项目选择 `SEGMENT` 时 2024 与 2013 同形。两者均已在
   `ruleset_selector_spec.json` 与 `ruleset-selftest` 输出中显式登记。

4. **2013 项目落值 FULL 由「静默覆盖」改为「配置冲突」**：原实现把 FULL 悄悄改成 SEGMENT
   并只在 decisions 里留言——审计链上"人工落了什么"与"系统用了什么"的差异消失。
   现改为显式 BLOCKED，要求以正确规则集重新选择。

5. **选择项落值文件未纳入 Gate 0a 受控制品注册表**：变更不留 hash 失效信号。
   是否升级为受控制品待定（已登记于 `ruleset_selector_spec.json` 的 `known_limits`）。

---

## 八、下一步建议

| 优先级 | 动作 | 说明 |
|---|---|---|
| P0 | 选择 `adjustment_scope` | 落值即解除 Gate 0a 一半阻塞，且决定 WP3 的 R_i 分段代码结构；建议先跑 `scope-impact` 看本项目的规则层分叉 |
| P0 | 提供 1 套真实招标清单 | 解除 `competitiveness_classification`，同时为 T01-00B 解析器与 T01-02B 变体测试集提供样本 |
| P1 | 确认精度策略 §8.2 的模式 A / B | 当前 `precision_profile.json` 的 `equality_tolerance_mode.current` 为 null |
| P1 | 启动 T00-09 / T00-10A / T00-11 / T00-12 | 四项均需造价与合同专业输入，可并行推进，是 Gate 0b 的主体 |
| P2 | 决定选择项落值文件是否纳入受控注册表 | 纳入即获得"一改就失效"的契约语义 |
