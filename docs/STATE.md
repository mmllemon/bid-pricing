<!-- ⚠ 本文件由 `python -m bidpricing.cli status --write` 自动生成。
     请勿手工编辑——手写的状态一定会在某次改动后过期。
     要改内容，请改来源：git 提交 / config 注册表 / docs/tasks.json。 -->


# 项目状态快照

> 生成于 **2026-09-16 21:41:44** ｜ 合同基准日 `2026-03-01`
> 本文件是**生成物**，用于跨会话交接。改内容请改来源，不要改本文件。

---

## 一、版本锚点

- 提交：`4b56409` ｜ 累计 23 次提交
- 最新提交信息：feat(t01-04): 三表交叉匹配器 —— master 并集 LEFT JOIN + 异常清单；Phase 0 分类声明落值（西永L/2024）
- 最近里程碑标签：`classification-declared-t0104-v1`
- 工作区：有 7 处未提交改动

> 版本锚点是**结论可复算**的前提：任何一份交付物都能追到某个提交。
>
> **注意快照的固有滞后**：本文件本身要被提交，因此它记录的 HEAD 通常比当前 HEAD
> 少一次提交（生成快照所需的那次变更尚未提交）。若上列 commit 与 `git log -1` 不一致，
> 属正常现象——**以复算结果为准**，并重新生成快照。

---

## 二、闸门状态

| 闸门 | 状态 |
|---|---|
| Gate 0a — 技术接口与规则集冻结 | **PASS** |
| Gate 0b — 商务口径与合规冻结 | **BLOCKED** |
| Phase 0 输入门 — 项目级数据/取值 | **PASS** |
| Phase 0 准入（综合） | **RELEASED** |
| WP4 求解层构建 | **BLOCKED** |

**Gate 0a 无阻塞项**，已放行 WP1 数据层 / WP2 配置层 / WP3 判定层。

---

## 三、契约制品冻结表

| 制品 key | 类型 | hash | 冻结时间 |
|---|---|---|---|
| `rule_set_selector_spec` | versioned | sha256:0dd335b5a8ae | 2026-09-16T09:56:59+00:00 |
| `field_schema_version` | versioned | sha256:330cf6165ad9 | 2026-09-16T09:56:59+00:00 |
| `constraint_schema_version` | versioned | sha256:b07f2cf70697 | 2026-09-16T09:56:59+00:00 |
| `precision_profile_version` | versioned | sha256:6ce483e8d221 | 2026-09-16T09:56:59+00:00 |
| `architecture_decision_version` | versioned | sha256:3601adeed46c | 2026-09-16T09:56:59+00:00 |
| `competitiveness_classification` | versioned | sha256:2913378715d5 | 2026-09-16T09:56:59+00:00 |
| `input_protocol_schema` | versioned | sha256:1696175b90ff | 2026-09-16T09:56:59+00:00 |
| `canonical_schema_version` | versioned | sha256:ff90d54cbb5e | 2026-09-16T09:56:59+00:00 |
| `adjustment_scope` | enum | **未冻结** | — |

> hash = 制品内容 SHA-256 前 12 位。制品一改即失配，闸门自动失效——无需人工记忆。

---

## 四、质量门

- 单元测试：**252** 项，结果 **通过**（OK）

```bash
cd bid-pricing && PYTHONPATH=src python -m unittest discover -s tests
```

- 跨制品一致性：**PASS**（11/11 项判据通过） —— 判「已冻结制品彼此是否自洽」，与闸门正交；两者的关系是「hash 对不对」与「说法一致不一致」，缺一不可
  - 核心判据：13 条约束的 inputs 全部在字段字典中已声明

```bash
cd bid-pricing && PYTHONPATH=src python -m bidpricing.cli contract-check
```

---

## 五、任务进度

| WP | 任务数 | 状态分布 |
|---|---|---|
| WP0 | 15 | done 7、not_started 5、partial 3 |
| WP1 | 11 | done 6、not_started 4、partial 1 |
| WP2 | 5 | not_started 5 |
| WP3 | 7 | not_started 7 |
| WP4 | 13 | not_started 13 |
| WP5 | 5 | not_started 5 |
| WP6 | 8 | not_started 8 |
| WP7 | 4 | not_started 4 |

共 **68** 项任务。

### 已启动 / 已完成任务

> 共 17 项。生效状态由「人工声明」与「证据核对」共同决定（见 `src/bidpricing/status.py::effective_status`）。

| 任务 | 标题 | 生效状态 | 证据核对 | 备注 |
|---|---|---|---|---|
| T00-08 | 规则集选择器 | done | ✓ 成立 | src/bidpricing/contracts/selector.py 存在 |
| T00-01 | 合同计价与调价口径冻结 | partial | — | 规则集已承载调价口径；adjustment_scope 为选择项，取值待项目落值 |
| T00-02 | 字段字典冻结 | done | ✓ 成立 | field_schema_version 已冻结 sha256:330cf6165ad9 |
| T00-03 | 约束字典冻结 | done | ✓ 成立 | constraint_schema_version 已冻结 sha256:b07f2cf70697 |
| T00-04 | 精度与容差策略冻结 | done | ✓ 成立 | precision_profile_version 已冻结 sha256:6ce483e8d221 |
| T00-05 | 三层分割架构地位确认 | done | ✓ 成立 | architecture_decision_version 已冻结 sha256:3601adeed46c |
| T00-06 | 报价项可竞争性分类与变量集合冻结 | partial | ✓ 成立 | 规则书已冻结；项目级落值表为空，属 Phase 0 输入门判据；competitiveness_classification 已冻结 sha256:2913378715d5 |
| T00-06B | $P_{\text{competitive}}$ 与不可竞争费基数联动规则 | partial | ✓ 成立 | 恒等式判据已实现并过真实样本（残差 0）；P_competitive 扣减式与不可竞争费联动规则未落；src/bidpricing/identity.py 存在 |
| T00-07 | 规则集优先级冻结 | done | ✓ 成立 | rule_set_selector_spec 已冻结 sha256:0dd335b5a8ae |
| T01-00A | 招标文件计价口径与输入协议 Schema 冻结 | done | ✓ 成立 | input_protocol_schema 已冻结 sha256:1696175b90ff |
| T01-00B | 招标文件解析器实现 | done | — | 解析器 src/bidpricing/io/（零依赖读取器 + 表号/别名双键 + 双行表头合并 + 分节标题四信号判据）；CLI parse-boq 三项产出在真实配对样本上验证：82 行/0 失败/加权下浮 8.0084% 与 pair.json 交叉印证；tests/test_io_boq.py 19 项 |
| T01-01 | Canonical Schema 定义 | done | — | config/canonical_schema.json（Gate 0a 冻结 ff90d54cbb5e）：统一字段集 16 字段、三类输入映射、空值语义（cap 空=不限价）、normalization 规则（编码不做位数补零——D1）；tests/test_io_clean.py CanonicalSchemaArtifactTest 锁注册与冻结 |
| T01-02C | Golden Dataset 建设与版本锁定 | partial | ✓ 成立 | 首份真实配对样本已固化；六类分层用例（A–F）未建，版本未锁定；tests/data/xiyong_l_district/pair.json 存在（35937 字节） |
| T01-03 | 规范化与清洗 | done | — | src/bidpricing/io/clean.py + CLI clean-boq：数值归一（千分位/全角/空白）、编码标准化（不补零）、单位归一、精度归一（q 6 位/金额 2 位）、cap 空值语义 → no_cap、C5 零价信号、透传信号、数值失败进报告不猜；真实文件实测 82→82 两侧行、0 解析失败、031301017001 正确标记不限价；tests/test_io_clean.py 16 项 |
| T01-04 | 三表交叉匹配 | done | — | 2026-09-16 实现 src/bidpricing/io/match.py + CLI match-boq + 10 测试。master=cap∪cost 键并集；未匹配项 100% 进异常清单；同侧重复 key BLOCK 禁止自动合并；no_cap=合法语义单列计数。真实文件 e2e：82 键全匹配、0 异常、missing_limit=1（脚手架搭拆，合法 no_cap）。 |
| T01-04A | 多级 key 与重复 key 治理 | done | — | 2026-09-16 落 config/key_spec.json（canonical_key=(project_id,unit_work,item_id)；扩展键仅人工裁定触发；序号/名称键明令禁止；重复 key BLOCK 禁止自动合并）+ tests/test_key_spec.py 规范↔实现双向锁定。机械部分已于 T01-04 前移至 match.py。 |
| T01-05 | 源文件版本锁定与完整性 | done | — | 2026-09-16 实现 src/bidpricing/io/import_registry.py + CLI import-register/import-verify。整文件 sha256 + 逐 sheet 值矩阵哈希双层指纹；登记表追加式不可变；未登记=BLOCKED；文件被替换→BLOCKED+定位变化 sheet。真实文件 e2e：登记→PASS；字节级改动单字符串→BLOCKED 且精确定位「表-09 分部分项」。deps T01-02 属数据侧验收（真实成本清单到位后对 cost 侧补登记即可，机制不受阻）。 |

---

## 六、下一步（自动派生）

> 判据：依赖任务均已 `done`/`partial`，且自身未完成。**由代码算出，非人工推荐。**

| 任务 | WP | 标题 | 产出物 | 状态 |
|---|---|---|---|---|
| T00-01 | WP0 | 合同计价与调价口径冻结 | 《计价规则卡》 | partial |
| T00-06 | WP0 | 报价项可竞争性分类与变量集合冻结 | 分类表 + 变量集合定义 | partial |
| T00-06B | WP0 | $P_{\text{competitive}}$ 与不可竞争费基数联动规则 | 总价分解计算规范（T00-06 的补充附件，冲突时以本规范为准） | partial |
| T00-09 | WP0 | 成本口径证明包 | 成本构成规范 | not_started |
| T00-10A | WP0 | $q^1$ 假设声明：格式与冻结时点 | 《$q^1$ 假设声明书（格式篇）》 | not_started |
| T00-10B | WP0 | $q^1$ 来源判定 | 《$q^1$ 假设声明书（来源篇）》 | not_started |

---

## 七、遗留项与已知限制

- ruleset_selector_spec.json → known_limits: region / project_type / funding_type 三个输入当前不参与判定，仅留痕——待 T00-01 补充规则表后启用
- ruleset_selector_spec.json → known_limits: 2024 版减量侧（r < 0.85）FULL 与 SEGMENT 等价（「减少后剩余部分」本就是全部 q1），作用域分叉只出现在增量侧
- ruleset_selector_spec.json → known_limits: 规则层分叉（同一报价在两种口径下的结算差）不等于报价层的最优利润差：规格书附录 B 例 2R 的约 4.5 倍差需由 WP4 在两条口径下分别求解后比较
- ruleset_selector_spec.json → known_limits: 选择项落值文件未纳入 Gate 0a 受控制品注册表（不入 hash 绑定）：变更不留契约失效信号，是否升级为受控制品待定

> 遗留项从各配置的 `known_limits` / `freeze_blocker` 自声明字段汇聚，
> 因此不会被「汇总为一句已完成」而掩盖。

---

## 八、复现全部结论

```bash
cd bid-pricing
# 1. 状态快照（本文件的来源）
PYTHONPATH=src python -m bidpricing.cli status --write
# 2. 闸门机械判定
PYTHONPATH=src python -m bidpricing.cli gate-check --contract-date 2026-03-01
# 3. 全量测试
PYTHONPATH=src python -m unittest discover -s tests
# 4. 规则集指纹自检（含退化条件登记）
PYTHONPATH=src python -m bidpricing.cli ruleset-selftest
```
