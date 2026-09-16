<!-- ⚠ 本文件由 `python -m bidpricing.cli status --write` 自动生成。
     请勿手工编辑——手写的状态一定会在某次改动后过期。
     要改内容，请改来源：git 提交 / config 注册表 / docs/tasks.json。 -->


# 项目状态快照

> 生成于 **2026-09-17 07:27:26** ｜ 合同基准日 `2026-03-01`
> 本文件是**生成物**，用于跨会话交接。改内容请改来源，不要改本文件。

---

## 一、版本锚点

- 提交：`bdcfba1` ｜ 累计 30 次提交
- 最新提交信息：feat(t00-01,t00-08): 计价规则卡 v1 —— P1 口径冻结与五项澄清（ADR-0010）
- 最近里程碑标签：`pricing-rule-card-v1`
- 工作区：有 13 处未提交改动

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
| `rule_set_selector_spec` | versioned | sha256:0dd335b5a8ae | 2026-09-16T23:25:57+00:00 |
| `field_schema_version` | versioned | sha256:0745655aa4b6 | 2026-09-16T23:25:57+00:00 |
| `constraint_schema_version` | versioned | sha256:771e84c8ec74 | 2026-09-16T23:25:57+00:00 |
| `precision_profile_version` | versioned | sha256:6ce483e8d221 | 2026-09-16T23:25:57+00:00 |
| `architecture_decision_version` | versioned | sha256:3601adeed46c | 2026-09-16T23:25:57+00:00 |
| `competitiveness_classification` | versioned | sha256:2913378715d5 | 2026-09-16T23:25:57+00:00 |
| `input_protocol_schema` | versioned | sha256:1696175b90ff | 2026-09-16T23:25:57+00:00 |
| `canonical_schema_version` | versioned | sha256:ff90d54cbb5e | 2026-09-16T23:25:57+00:00 |
| `pricing_rule_card_version` | versioned | sha256:29040209cd8b | 2026-09-16T23:25:57+00:00 |
| `adjustment_scope` | enum | **未冻结** | — |

> hash = 制品内容 SHA-256 前 12 位。制品一改即失配，闸门自动失效——无需人工记忆。

---

## 四、质量门

- 单元测试：**364** 项，结果 **通过**（OK）

```bash
cd bid-pricing && PYTHONPATH=src python -m unittest discover -s tests
```

- 跨制品一致性：**PASS**（16/16 项判据通过） —— 判「已冻结制品彼此是否自洽」，与闸门正交；两者的关系是「hash 对不对」与「说法一致不一致」，缺一不可
  - 核心判据：13 条约束的 inputs 全部在字段字典中已声明

```bash
cd bid-pricing && PYTHONPATH=src python -m bidpricing.cli contract-check
```

---

## 五、任务进度

| WP | 任务数 | 状态分布 |
|---|---|---|
| WP0 | 15 | done 10、not_started 3、partial 2 |
| WP1 | 11 | done 10、not_started 1 |
| WP2 | 5 | not_started 5 |
| WP3 | 7 | not_started 7 |
| WP4 | 13 | not_started 13 |
| WP5 | 5 | not_started 5 |
| WP6 | 8 | not_started 8 |
| WP7 | 4 | not_started 4 |

共 **68** 项任务。

### 已启动 / 已完成任务

> 共 22 项。生效状态由「人工声明」与「证据核对」共同决定（见 `src/bidpricing/status.py::effective_status`）。

| 任务 | 标题 | 生效状态 | 证据核对 | 备注 |
|---|---|---|---|---|
| T00-08 | 规则集选择器 | done | ✓ 成立 | 2026-09-16 复核确认已完成（任务板此前滞后未落账）：config/ruleset_selector_spec.json（spec v2）+ src/bidpricing/contracts/selector.py（select_rule_set / ruleset_self_test 指纹自检）+ 规则集三实现（2013/2024/base）。判据：输入 9 键、precedence_chain=Contract>Tender>Regional>Standard、2013 过渡双条件成立才回落否则 BLOCKED、adjustment_scope 未定态即 key 缺失。；src/bidpricing/contracts/selector.py 存在 |
| T00-01 | 合同计价与调价口径冻结 | done | — | 2026-09-16 完成《计价规则卡 v1》config/pricing_rule_card.json（Gate 0a 受控制品，freeze 后 hash sha256:cf6efb75b63c）：符号绑定 Q0/Q1/P0/P1/S/r、阈值与 ρ±、P1 公式三分支、**P1 五项澄清 P1-A~E 全 RESOLVED**、override 链与未登记键阻断、不平衡报价条款口径（OI-05/06）。实现 src/bidpricing/contracts/pricing_card.py + CLI pricing-card（展示/试算/--from-match 分支扫描）。ADR-0010 记录 re-base 与「ρ±=0 是机制层默认而非数据缺省」的性质区分。规范↔代码常量↔项目落值三层双向锁定（contract-check 第 12 判据）。真实数据：82 键中 IN_RANGE 75 / DECREASE 6 / INCREASE 0。 |
| T00-02 | 字段字典冻结 | done | ✓ 成立 | 2026-09-17 复核闭环（制品早已冻结，任务板滞后）：field_schema 36→38 字段。本轮补两处真缺口——①c_i=0 处理未表态（T00-02 四项要求之一，q0 已表态而 c_i 没有）→ 补：仅 PASS_THROUGH 项合法，OPTIMIZABLE 而 c_i=0 判 BLOCKED，且 0 与缺失必须机器可区分；②派生量 p1 / settlement_amount 未登记 → 补字段并新增 missing_policy 取值 DERIVED（值域增项，checker 仍以制品域为事实源）。另修契约矛盾：rho_plus/rho_minus 原为字段级 DEFAULT 0.0，与 conventions 声明的「合同口径类禁止 DEFAULT」自相矛盾 → 改 BLOCK，默认值改由 T00-01 规则卡提供（ADR-0010：机制层默认可审计，字段级静默填值不可）。tests/test_t0002_field_dictionary.py（15）：八属性齐全/值域/精度/唯一键与 key_spec 一致/百分比小数/零值表态/派生量。；field_schema_version 已冻结 sha256:0745655aa4b6 |
| T00-03 | 约束字典冻结 | done | ✓ 成立 | constraint_schema_version 已冻结 sha256:771e84c8ec74 |
| T00-04 | 精度与容差策略冻结 | done | ✓ 成立 | precision_profile_version 已冻结 sha256:6ce483e8d221 |
| T00-05 | 三层分割架构地位确认 | done | ✓ 成立 | architecture_decision_version 已冻结 sha256:3601adeed46c |
| T00-06 | 报价项可竞争性分类与变量集合冻结 | partial | ✓ 成立 | 规则书已冻结；项目级落值表为空，属 Phase 0 输入门判据；competitiveness_classification 已冻结 sha256:2913378715d5 |
| T00-06B | $P_{\text{competitive}}$ 与不可竞争费基数联动规则 | partial | ✓ 成立 | 恒等式判据已实现并过真实样本（残差 0）；P_competitive 扣减式与不可竞争费联动规则未落；src/bidpricing/identity.py 存在 |
| T00-07 | 规则集优先级冻结 | done | ✓ 成立 | rule_set_selector_spec 已冻结 sha256:0dd335b5a8ae |
| T00-09 | 成本口径证明包 | done | — | 2026-09-17 完成 config/cost_basis_spec.json 成本构成规范：C_individual 八项分解（labor/material/equipment/subcontract/management/allocated_overhead/tax_and_fee_treatment/risk_reserve），显式声明 ≠ 社会平均成本；含 2024 科目重映射（规费拆分、安全生产措施费、综合单价不含税）、分摊规则与风险储备的显式声明要求、partial_declaration_policy=BLOCKED。Gate 0b 受控制品已冻结。 |
| T00-11 | 成本 $c_i$ 假设与来源声明 | done | — | 2026-09-17 完成 config/cost_assumption_spec.json c_i 假设声明书（三要素：来源/格式/冻结时点）+ src/bidpricing/validation/cost_basis.py + CLI cost-check。来源词表 COST_DB/HISTORICAL_SETTLEMENT/SUPPLIER_QUOTE/EXPERT_ESTIMATE 且各有 required_when 附证要求；**未声明=BLOCKED 不静默补全**；说了但不在词表=FAIL（数据违反≠声明缺失）；未冻结=WARN（Gate 0b 前）。--declare-source/--evidence/--freeze 落值；**带病拒冻**（有阻断项时 --freeze 退出码 1）。当前真实状态：AS-01 BLOCKED（成本清单已提供但来源未声明，待用户一句话确认）。 |
| T01-00A | 招标文件计价口径与输入协议 Schema 冻结 | done | ✓ 成立 | input_protocol_schema 已冻结 sha256:1696175b90ff |
| T01-00B | 招标文件解析器实现 | done | — | 解析器 src/bidpricing/io/（零依赖读取器 + 表号/别名双键 + 双行表头合并 + 分节标题四信号判据）；CLI parse-boq 三项产出在真实配对样本上验证：82 行/0 失败/加权下浮 8.0084% 与 pair.json 交叉印证；tests/test_io_boq.py 19 项 |
| T01-01 | Canonical Schema 定义 | done | — | config/canonical_schema.json（Gate 0a 冻结 ff90d54cbb5e）：统一字段集 16 字段、三类输入映射、空值语义（cap 空=不限价）、normalization 规则（编码不做位数补零——D1）；tests/test_io_clean.py CanonicalSchemaArtifactTest 锁注册与冻结 |
| T01-02 | Excel Adapter | done | — | 2026-09-16 真实成本清单到位（真实案件示例/成本/…成本清单.xlsx，sha256 7a8110d65b24）完成严格验收：解析 81 条规范行 0 失败（STANDARD 67+补充14，分节标题 C/B.3 正确跳过）；import-register cost 侧登记；限价×成本真实匹配 81/82（唯一异常 ONLY_IN_CAP=031301017001 脚手架搭拆，成本清单无此行、限价侧本就是 no_cap）；D05 覆盖率 0.9878≥0.98。三份输入制品解析均零失败，验收闭环。副产品：修 validate-boq 单侧项 provenance cost=None 崩溃（+1 回归测试）。 |
| T01-02B | 输入变体测试集 | done | — | 2026-09-16 落 tests/test_t0102b_variants.py 十四类变体（Sheet 名/列序/合并单元格/空行/双行表头真实形态/合计行/隐藏行/表头带单位/千分位/中文括号全角/文本数字/百分比/公式有无缓存/多单位工程）+ 5 个 BLOCK 负例（表头带单位/未登录别名/同行重复别名/无表头/空表对照）。行为决策留痕：隐藏行按普通行处理（数据层不因展示属性丢数据）。底座 src/bidpricing/io/xlsxkit.py 零依赖 xlsx 构造器。 |
| T01-02C | Golden Dataset 建设与版本锁定 | done | ✓ 成立 | 2026-09-16 六类分层用例（A–F）各正例+负例建成，工具 tools/make_golden.py，制品 tests/data/golden/golden-v1/（12 用例 xlsx + manifest.json）。固定种子 20260916；manifest_hash 锁定期望（手改即失配）；tests/test_golden_dataset.py 逐用例复算断言（含可复现性 probe）——Gate 1「100% 通过」绑定 golden_version=golden-v1。；tests/data/xiyong_l_district/pair.json 存在（35937 字节） |
| T01-03 | 规范化与清洗 | done | — | src/bidpricing/io/clean.py + CLI clean-boq：数值归一（千分位/全角/空白）、编码标准化（不补零）、单位归一、精度归一（q 6 位/金额 2 位）、cap 空值语义 → no_cap、C5 零价信号、透传信号、数值失败进报告不猜；真实文件实测 82→82 两侧行、0 解析失败、031301017001 正确标记不限价；tests/test_io_clean.py 16 项 |
| T01-04 | 三表交叉匹配 | done | — | 2026-09-16 实现 src/bidpricing/io/match.py + CLI match-boq + 10 测试。master=cap∪cost 键并集；未匹配项 100% 进异常清单；同侧重复 key BLOCK 禁止自动合并；no_cap=合法语义单列计数。真实文件 e2e：82 键全匹配、0 异常、missing_limit=1（脚手架搭拆，合法 no_cap）。 |
| T01-04A | 多级 key 与重复 key 治理 | done | — | 2026-09-16 落 config/key_spec.json（canonical_key=(project_id,unit_work,item_id)；扩展键仅人工裁定触发；序号/名称键明令禁止；重复 key BLOCK 禁止自动合并）+ tests/test_key_spec.py 规范↔实现双向锁定。机械部分已于 T01-04 前移至 match.py。 |
| T01-05 | 源文件版本锁定与完整性 | done | — | 2026-09-16 实现 src/bidpricing/io/import_registry.py + CLI import-register/import-verify。整文件 sha256 + 逐 sheet 值矩阵哈希双层指纹；登记表追加式不可变；未登记=BLOCKED；文件被替换→BLOCKED+定位变化 sheet。真实文件 e2e：登记→PASS；字节级改动单字符串→BLOCKED 且精确定位「表-09 分部分项」。deps T01-02 属数据侧验收（真实成本清单到位后对 cost 侧补登记即可，机制不受阻）。 |
| T01-06 | D01–D12 校验实现 | done | — | 2026-09-16 实现 src/bidpricing/validation/checks.py + CLI validate-boq + config/validation_rules.json（规范事实源）。27 测试双向锁定规范↔实现。D01–D12 按 ADR-0008 re-base：D02→q1_point>0、D03→cap>0或no_cap、D05→两侧并集覆盖率、W02→价值比cap/c。真实文件 e2e：D01–D05/D07/D10/D11 PASS（覆盖率1.0）；D06 FAIL（82项attribution未标注=OI-01待补）；D08 BLOCKED（税口径未声明）；D09 BLOCKED（contract_type未声明）——三项均为真实 Phase 0 输入缺口，退出码 1。 |

---

## 六、下一步（自动派生）

> 判据：依赖任务均已 `done`/`partial`，且自身未完成。**由代码算出，非人工推荐。**

| 任务 | WP | 标题 | 产出物 | 状态 |
|---|---|---|---|---|
| T00-06 | WP0 | 报价项可竞争性分类与变量集合冻结 | 分类表 + 变量集合定义 | partial |
| T00-06B | WP0 | $P_{\text{competitive}}$ 与不可竞争费基数联动规则 | 总价分解计算规范（T00-06 的补充附件，冲突时以本规范为准） | partial |
| T00-10A | WP0 | $q^1$ 假设声明：格式与冻结时点 | 《$q^1$ 假设声明书（格式篇）》 | not_started |
| T00-10B | WP0 | $q^1$ 来源判定 | 《$q^1$ 假设声明书（来源篇）》 | not_started |
| T00-12 | WP0 | 利润口径桥接表 | 《利润口径桥接表》 | not_started |
| T01-03A | WP1 | 缺失值与异常值策略 | 缺失值规则表 | not_started |

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
