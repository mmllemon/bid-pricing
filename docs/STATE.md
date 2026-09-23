<!-- ⚠ 本文件由 `python -m bidpricing.cli status --write` 自动生成。
     请勿手工编辑——手写的状态一定会在某次改动后过期。
     要改内容，请改来源：git 提交 / config 注册表 / docs/tasks.json。 -->


# 项目状态快照

> 生成于 **2026-09-23 11:49:50** ｜ 合同基准日 `2026-03-01`
> 本文件是**生成物**，用于跨会话交接。改内容请改来源，不要改本文件。

---

## 〇、快照新鲜度

> **快照较最新源为新鲜**：生成时点后未见 src/config/tests/docs 下的
> 变更晚于生成时点。若你刚刚改过代码，请运行 `status --write` 重新生成。

---

## 一、版本锚点

- 提交：`040b22f` ｜ 累计 95 次提交 ｜ 未推送 0 次提交
- 最新提交信息：exp(t04-02b): OI-MA-A 量化关闭——M_hi 放大对 B&B 收敛无影响（tools 可复算）
- 最近里程碑标签：`h002-cost-tax-basis-v1`
- 工作区：有 17 处未提交改动

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
| `rule_set_selector_spec` | versioned | sha256:0dd335b5a8ae | 2026-09-18T08:29:55+00:00 |
| `field_schema_version` | versioned | sha256:0745655aa4b6 | 2026-09-18T08:29:55+00:00 |
| `constraint_schema_version` | versioned | sha256:bccb081ed800 | 2026-09-18T08:29:55+00:00 |
| `precision_profile_version` | versioned | sha256:146e8e6ffbc4 | 2026-09-18T08:29:55+00:00 |
| `architecture_decision_version` | versioned | sha256:3601adeed46c | 2026-09-18T08:29:55+00:00 |
| `competitiveness_classification` | versioned | sha256:2913378715d5 | 2026-09-18T08:29:55+00:00 |
| `input_protocol_schema` | versioned | sha256:1696175b90ff | 2026-09-18T08:29:55+00:00 |
| `canonical_schema_version` | versioned | sha256:ff90d54cbb5e | 2026-09-18T08:29:55+00:00 |
| `pricing_rule_card_version` | versioned | sha256:d88298683924 | 2026-09-18T08:29:55+00:00 |
| `adjustment_scope` | enum | **未冻结** | — |

> hash = 制品内容 SHA-256 前 12 位。制品一改即失配，闸门自动失效——无需人工记忆。

---

## 四、质量门

- 单元测试：**1603** 项，结果 **通过**（OK）

```bash
cd bid-pricing && PYTHONPATH=src python -m unittest discover -s tests
```

- 跨制品一致性：**PASS**（17/17 项判据通过） —— 判「已冻结制品彼此是否自洽」，与闸门正交；两者的关系是「hash 对不对」与「说法一致不一致」，缺一不可
  - 核心判据：13 条约束的 inputs 全部在字段字典中已声明

```bash
cd bid-pricing && PYTHONPATH=src python -m bidpricing.cli contract-check
```

---

## 五、任务进度

| WP | 任务数 | 状态分布 |
|---|---|---|
| WP0 | 15 | done 15 |
| WP1 | 11 | done 11 |
| WP2 | 5 | done 5 |
| WP3 | 7 | done 7 |
| WP4 | 13 | done 13 |
| WP5 | 5 | done 5 |
| WP6 | 8 | done 8 |
| WP7 | 4 | deferred 1、partial 3 |

共 **68** 项任务。

### 已启动 / 已完成任务

> 共 68 项。生效状态由「人工声明」与「证据核对」共同决定（见 `src/bidpricing/status.py::effective_status`）。

| 任务 | 标题 | 生效状态 | 证据核对 | 备注 |
|---|---|---|---|---|
| T00-08 | 规则集选择器 | done | ✓ 成立 | 2026-09-16 复核确认已完成（任务板此前滞后未落账）：config/ruleset_selector_spec.json（spec v2）+ src/bidpricing/contracts/selector.py（select_rule_set / ruleset_self_test 指纹自检）+ 规则集三实现（2013/2024/base）。判据：输入 9 键、precedence_chain=Contract>Tender>Regional>Standard、2013 过渡双条件成立才回落否则 BLOCKED、adjustment_scope 未定态即 key 缺失。；src/bidpricing/contracts/selector.py 存在 |
| T00-01 | 合同计价与调价口径冻结 | done | ✓ 成立 | 2026-09-16 完成《计价规则卡 v1》config/pricing_rule_card.json（Gate 0a 受控制品，freeze 后 hash sha256:cf6efb75b63c）：符号绑定 Q0/Q1/P0/P1/S/r、阈值与 ρ±、P1 公式三分支、**P1 五项澄清 P1-A~E 全 RESOLVED**、override 链与未登记键阻断、不平衡报价条款口径（OI-05/06）。实现 src/bidpricing/contracts/pricing_card.py + CLI pricing-card（展示/试算/--from-match 分支扫描）。ADR-0010 记录 re-base 与「ρ±=0 是机制层默认而非数据缺省」的性质区分。规范↔代码常量↔项目落值三层双向锁定（contract-check 第 12 判据）。真实数据：82 键中 IN_RANGE 75 / DECREASE 6 / INCREASE 0。；contract_ruleset_version 已冻结 sha256:d88298683924；src/bidpricing/contracts/pricing_card.py 存在；ADR ADR-0017-contract-review-must-be-attributed.md 存在 |
| T00-02 | 字段字典冻结 | done | ✓ 成立 | 2026-09-17 复核闭环（制品早已冻结，任务板滞后）：field_schema 36→38 字段。本轮补两处真缺口——①c_i=0 处理未表态（T00-02 四项要求之一，q0 已表态而 c_i 没有）→ 补：仅 PASS_THROUGH 项合法，OPTIMIZABLE 而 c_i=0 判 BLOCKED，且 0 与缺失必须机器可区分；②派生量 p1 / settlement_amount 未登记 → 补字段并新增 missing_policy 取值 DERIVED（值域增项，checker 仍以制品域为事实源）。另修契约矛盾：rho_plus/rho_minus 原为字段级 DEFAULT 0.0，与 conventions 声明的「合同口径类禁止 DEFAULT」自相矛盾 → 改 BLOCK，默认值改由 T00-01 规则卡提供（ADR-0010：机制层默认可审计，字段级静默填值不可）。tests/test_t0002_field_dictionary.py（15）：八属性齐全/值域/精度/唯一键与 key_spec 一致/百分比小数/零值表态/派生量。；field_schema_version 已冻结 sha256:0745655aa4b6 |
| T00-03 | 约束字典冻结 | done | ✓ 成立 | 2026-09-17 结清。完成判据（实施路线 v3.2.1 L280「每条含表达式、输入字段、输出指标、threshold、tolerance、severity、可开关性」）已逐条核实：C1–C13 每条均含 expression / inputs / metric / tolerance / severity / toggleable，机制常量（θ、N_max、d_max、σ_max、R_min、tol_lo/hi）在各自 inputs 中显式列名，未写成字面量。制品 `constraint_schema.json` 已冻结（Gate 0a.constraint_schema_version = sha256:771e84c8ec74），并被 contract-check 的 constraint_schema.tolerance_defined 判据覆盖（13 条 tolerance 名全部可解析到 precision_profile 的 eps_*，无空话容差）。三条重定义留痕完备：C3/C5 的 supersedes + original_note_for_audit（ADR-0007 动因：把用户未提及误记为用户已声明）、C13 的 raised_at/open_question/resolved。状态故由 not_started 转 done —— 制品本身早已就绪，此前状态漂移系任务板未跟进。；constraint_schema_version 已冻结 sha256:bccb081ed800；config/constraint_schema.json 存在（18736 字节） |
| T00-04 | 精度与容差策略冻结 | done | ✓ 成立 | 2026-09-17 结清。完成判据：ε_solver/ε_price/ε_quantity/ε_abs/ε_total 全部给定 + ε_total = max(ε_abs, ε_rel·P*) + internal/display precision 分离 + **equality_tolerance_mode.current 非 null**（制品自身声明的 Gate 0a 前置）。末项是本轮实体工作：自主裁定 `current = "A"`（内部严格等式 + 输出层独立舍入调和）。裁定依据三条机械判据 —— D1（决定性，与 benchmark 无关）：模式 B 使内外层判据同宽 R2 = 1 ⇒ 复核层退化为内层判据的复制，丧失独立否定能力；要求 R2 ≥ 1e3，A 下 R2 = 1e6 PASS。D2：R1 = eps_solver/HiGHS默认容差 = 0.1 < 1 ⇒ 容差带不宽于默认容差，无任何放宽收益；同时否定「改 A 更难解」的顾虑（A 的求解器容差同样收到 1e-9，难度等价）。D3：§8.2 自陈「性能更差」须 benchmark 后决定 ⇒ benchmark_status = NOT_RUN ⇒ 未证收益不得交换已证语义性质。另记录 §8.2「两层同一 ε 口径」的读法：该条禁的是**松进严出**，A 使内层无放宽 ⇒ 无需补偿 ⇒ 更强满足，非违反。「未 benchmark」转为显式状态 + reopen_condition（含 D1 不可交易约束），owner = T04-06。制品冻结 hash 更新为 sha256:146e8e6ffbc4；contract-check 17/17，闸门全 PASS。；precision_profile_version 已冻结 sha256:146e8e6ffbc4；config/precision_profile.json 存在（7294 字节）；ADR ADR-0020-strict-equality-mode-a.md 存在 |
| T00-05 | 三层分割架构地位确认 | done | ✓ 成立 | architecture_decision_version 已冻结 sha256:3601adeed46c |
| T00-06 | 报价项可竞争性分类与变量集合冻结 | done | ✓ 成立 | 2026-09-17 结清。两层均已就绪：① 机制层规则书 `competitiveness_classification.json`（Gate 0a，sha256:2913378715d5）—— 五角色定义 + 四清单缺省角色 + not_itemized（规费/税金）+ 「缺省即角色、例外才登记」原则；② 项目层落值表 `project_classification_table.json`（Phase 0 输入门判据）—— xiyong_l_district / GB/T50500-2024、四清单缺省角色齐备、external_constants 三项（安全文明施工费/规费/税金）、exceptions = [] 且带 search_basis 说明「已检索、结论为空」。Phase 0 输入门判 PASS、准入 RELEASED，正是本判据在真实项目上通过的证据。原 partial 的理由（「项目级落值表为空」）已消失。**变量集合 X_opt 的定义因此闭合**：BOQ ∪ TECH_MEASURE 的 OPTIMIZABLE 项（扣清单自带列命中的例外）→ X_opt；ORG_MEASURE(NON_COMPETITIVE) + OTHER(PASS_THROUGH) + 规费税金 → P_fixed 侧。本条是 T04-02A 的第三个硬前置，故一并结清以解封。；competitiveness_classification 已冻结 sha256:2913378715d5；project_classification_table 存在（项目级输入，不冻结 hash）；config/competitiveness_classification.json 存在（14769 字节）；config/project_classification_table.json 存在（7050 字节） |
| T00-06B | $P_{\text{competitive}}$ 与不可竞争费基数联动规则 | done | ✓ 成立 | 恒等式判据已实现并过真实样本（残差 0）；P_competitive 扣减式与不可竞争费联动规则未落；src/bidpricing/total_price.py 存在；src/bidpricing/money.py 存在；ADR ADR-0014-total-price-is-a-partition.md 存在 |
| T00-07 | 规则集优先级冻结 | done | ✓ 成立 | rule_set_selector_spec 已冻结 sha256:0dd335b5a8ae |
| T00-09 | 成本口径证明包 | done | — | 2026-09-17 完成 config/cost_basis_spec.json 成本构成规范：C_individual 八项分解（labor/material/equipment/subcontract/management/allocated_overhead/tax_and_fee_treatment/risk_reserve），显式声明 ≠ 社会平均成本；含 2024 科目重映射（规费拆分、安全生产措施费、综合单价不含税）、分摊规则与风险储备的显式声明要求、partial_declaration_policy=BLOCKED。Gate 0b 受控制品已冻结。 |
| T00-10A | $q^1$ 假设声明：格式与冻结时点 | done | — | 需人工：q^1 格式与冻结时点声明 |
| T00-10B | $q^1$ 来源判定 | done | — | 依赖 T01-00B 合同解析产出 |
| T00-11 | 成本 $c_i$ 假设与来源声明 | done | — | 2026-09-17 完成 config/cost_assumption_spec.json c_i 假设声明书（三要素：来源/格式/冻结时点）+ src/bidpricing/validation/cost_basis.py + CLI cost-check。来源词表 COST_DB/HISTORICAL_SETTLEMENT/SUPPLIER_QUOTE/EXPERT_ESTIMATE 且各有 required_when 附证要求；**未声明=BLOCKED 不静默补全**；说了但不在词表=FAIL（数据违反≠声明缺失）；未冻结=WARN（Gate 0b 前）。--declare-source/--evidence/--freeze 落值；**带病拒冻**（有阻断项时 --freeze 退出码 1）。当前真实状态：AS-01 BLOCKED（成本清单已提供但来源未声明，待用户一句话确认）。 |
| T00-12 | 利润口径桥接表 | done | ✓ 成立 | 依赖 T00-06B、T00-09；profit_bridge_spec 已冻结 sha256:295530cf91f7；src/bidpricing/validation/profit_bridge.py 存在；src/bidpricing/total_price.py 存在；ADR ADR-0015-objective-must-be-named.md 存在 |
| T01-00A | 招标文件计价口径与输入协议 Schema 冻结 | done | ✓ 成立 | input_protocol_schema 已冻结 sha256:1696175b90ff |
| T01-00B | 招标文件解析器实现 | done | — | 解析器 src/bidpricing/io/（零依赖读取器 + 表号/别名双键 + 双行表头合并 + 分节标题四信号判据）；CLI parse-boq 三项产出在真实配对样本上验证：82 行/0 失败/加权下浮 8.0084% 与 pair.json 交叉印证；tests/test_io_boq.py 19 项 |
| T01-01 | Canonical Schema 定义 | done | — | config/canonical_schema.json（Gate 0a 冻结 ff90d54cbb5e）：统一字段集 16 字段、三类输入映射、空值语义（cap 空=不限价）、normalization 规则（编码不做位数补零——D1）；tests/test_io_clean.py CanonicalSchemaArtifactTest 锁注册与冻结 |
| T01-02 | Excel Adapter | done | — | 2026-09-16 真实成本清单到位（真实案件示例/成本/…成本清单.xlsx，sha256 7a8110d65b24）完成严格验收：解析 81 条规范行 0 失败（STANDARD 67+补充14，分节标题 C/B.3 正确跳过）；import-register cost 侧登记；限价×成本真实匹配 81/82（唯一异常 ONLY_IN_CAP=031301017001 脚手架搭拆，成本清单无此行、限价侧本就是 no_cap）；D05 覆盖率 0.9878≥0.98。三份输入制品解析均零失败，验收闭环。副产品：修 validate-boq 单侧项 provenance cost=None 崩溃（+1 回归测试）。 |
| T01-02B | 输入变体测试集 | done | — | 2026-09-16 落 tests/test_t0102b_variants.py 十四类变体（Sheet 名/列序/合并单元格/空行/双行表头真实形态/合计行/隐藏行/表头带单位/千分位/中文括号全角/文本数字/百分比/公式有无缓存/多单位工程）+ 5 个 BLOCK 负例（表头带单位/未登录别名/同行重复别名/无表头/空表对照）。行为决策留痕：隐藏行按普通行处理（数据层不因展示属性丢数据）。底座 src/bidpricing/io/xlsxkit.py 零依赖 xlsx 构造器。 |
| T01-02C | Golden Dataset 建设与版本锁定 | done | ✓ 成立 | 2026-09-16 六类分层用例（A–F）各正例+负例建成，工具 tools/make_golden.py，制品 tests/data/golden/golden-v1/（12 用例 xlsx + manifest.json）。固定种子 20260916；manifest_hash 锁定期望（手改即失配）；tests/test_golden_dataset.py 逐用例复算断言（含可复现性 probe）——Gate 1「100% 通过」绑定 golden_version=golden-v1。；tests/data/xiyong_l_district/pair.json 存在（35937 字节） |
| T01-03 | 规范化与清洗 | done | — | src/bidpricing/io/clean.py + CLI clean-boq：数值归一（千分位/全角/空白）、编码标准化（不补零）、单位归一、精度归一（q 6 位/金额 2 位）、cap 空值语义 → no_cap、C5 零价信号、透传信号、数值失败进报告不猜；真实文件实测 82→82 两侧行、0 解析失败、031301017001 正确标记不限价；tests/test_io_clean.py 16 项 |
| T01-03A | 缺失值与异常值策略 | done | ✓ 成立 | 缺失值规则表与可执行判定器已落地：required+missing、invalid numeric、派生量误作输入均 BLOCKED；cap 空值保留 no_cap 语义；0 与缺失可区分；inferred 值保留来源并告警。tests/test_missing_values.py 7 项，全量测试 1128 项通过（9 项显式跳过）。；config/missing_value_policy.json 存在；src/bidpricing/validation/missing_values.py 存在 |
| T01-04 | 三表交叉匹配 | done | — | 2026-09-16 实现 src/bidpricing/io/match.py + CLI match-boq + 10 测试。master=cap∪cost 键并集；未匹配项 100% 进异常清单；同侧重复 key BLOCK 禁止自动合并；no_cap=合法语义单列计数。真实文件 e2e：82 键全匹配、0 异常、missing_limit=1（脚手架搭拆，合法 no_cap）。 |
| T01-04A | 多级 key 与重复 key 治理 | done | — | 2026-09-16 落 config/key_spec.json（canonical_key=(project_id,unit_work,item_id)；扩展键仅人工裁定触发；序号/名称键明令禁止；重复 key BLOCK 禁止自动合并）+ tests/test_key_spec.py 规范↔实现双向锁定。机械部分已于 T01-04 前移至 match.py。 |
| T01-05 | 源文件版本锁定与完整性 | done | — | 2026-09-16 实现 src/bidpricing/io/import_registry.py + CLI import-register/import-verify。整文件 sha256 + 逐 sheet 值矩阵哈希双层指纹；登记表追加式不可变；未登记=BLOCKED；文件被替换→BLOCKED+定位变化 sheet。真实文件 e2e：登记→PASS；字节级改动单字符串→BLOCKED 且精确定位「表-09 分部分项」。deps T01-02 属数据侧验收（真实成本清单到位后对 cost 侧补登记即可，机制不受阻）。 |
| T01-06 | D01–D12 校验实现 | done | — | 2026-09-16 实现 src/bidpricing/validation/checks.py + CLI validate-boq + config/validation_rules.json（规范事实源）。27 测试双向锁定规范↔实现。D01–D12 按 ADR-0008 re-base：D02→q1_point>0、D03→cap>0或no_cap、D05→两侧并集覆盖率、W02→价值比cap/c。真实文件 e2e：D01–D05/D07/D10/D11 PASS（覆盖率1.0）；D06 FAIL（82项attribution未标注=OI-01待补）；D08 BLOCKED（税口径未声明）；D09 BLOCKED（contract_type未声明）——三项均为真实 Phase 0 输入缺口，退出码 1。2026-09-23 对抗审查（A1 回归）追加 D13 单价列完整性：明细表缺「综合单价/最高限价」列时不再静默按合法 no_cap 放行，缺列记失败样本并阻断（boq.parse_listing 留痕 + checks.run_validation D13 + api 解析前置断言 + 3 项回归测试），规则数 9→10 阻断 + 3 告警。 |
| T02-01 | Config Schema | done | ✓ 成立 | 已建立统一配置定义表，覆盖 project_selection、project_classification_table、phase0_runtime 三类配置；每个 key 均声明 type/required/default/min/max/enum/description，并提供 validate_config_schema 机械校验。tests/test_config_schema.py 4 项通过。；config/config_schema.json 存在；src/bidpricing/config_schema.py 存在 |
| T02-02 | defaults-fallback 合并器 | done | ✓ 成立 | 已实现 Config_eff 合并器：用户显式值优先，随后为 inferred/derived/defaulted；每个叶子值记录 value_source。required 字段禁止 default，缺失 required、未注册键和非法 derived 来源均 BLOCKED；None 不算显式值。tests/test_config_merge.py 6 项通过。；src/bidpricing/config_merge.py 存在 |
| T02-03 | Config Validator | done | ✓ 成立 | 已实现运行时 Config Validator，机械检出缺失/空值、类型错误、枚举或数值越界、未知 key、重复 key、schema_id/schema_version 不符和非法 value_source。tests/test_config_validator.py 4 项通过。；src/bidpricing/config_validator.py 存在 |
| T02-04 | 配置耦合度体检 | done | ✓ 成立 | 已实现配置耦合度体检：统计 Sheet 数、字段总数、重复字段、跨 Sheet 引用和默认值数量；校验引用端点与配置定义一致。选择项统一 value 槽位重复被识别为合法结构复用，其余同名字段判为风险。tests/test_config_coupling.py 3 项通过。；src/bidpricing/config_coupling.py 存在 |
| T02-05 | 版本绑定校验 | done | ✓ 成立 | 已实现版本绑定快照与校验：模型版本不符、制品未冻结、注册表 version/hash 不一致、制品文件漂移、运行绑定快照过期或引用未知制品均 BLOCKED。tests/test_version_binding.py 5 项通过。；src/bidpricing/version_binding.py 存在 |
| T03-01 | 结算规则引擎 | done | ✓ 成立 | config/settlement_rule_spec.json 存在（10724 字节）；src/bidpricing/settlement.py 存在；tests/test_settlement.py 存在；src/bidpricing/contracts/rule_sets/base.py 存在；src/bidpricing/contracts/pricing_card.py 存在；ADR ADR-0033-settlement-rule-engine.md 存在 |
| T03-02 | 派生量计算 | done | ✓ 成立 | 落地 L_i/U_i/floor_i/r_eff_i 的**唯一实现**（config/derived_quantities_spec.json + src/bidpricing/derived.py），判据 DQ-01..DQ-11 全双向可测（tests/test_derived.py，55 项）。★ 闭合 T04-02D 的 SV-07 挂账：floor_by_id 从此有唯一生产者；实测给 floor 后 SV-07 由 BLOCKED 转 PASS。★ 关键口径：ACCEPT 的钳制 min(floor,cap) **只在 cap 非空时生效**（空 cap = 不限价，折成 0 会把地板静默压到 0）；L_i 为多来源**取大**（实例下界 ∪ 条款 CAP·(1−tol_lo)）；r_eff 只委派 compute_r_eff（DQ-08 用 AST 审计禁调 settlement_revenue）。计算与判定分离（judge_derived 只吃 DerivedItem）使判据可注入验证。遗留：μ 与 unbalanced_clause 尚无落值位置（OI-DQ-A/B），故真实项目上 floor 一路如实 BLOCKED。；config/derived_quantities_spec.json 存在（15221 字节）；src/bidpricing/derived.py 存在；tests/test_derived.py 存在；ADR ADR-0025-derived-quantities.md 存在 |
| T03-03 | Phase 0 预检与可行性证书 | done | ✓ 成立 | config/phase0_precheck_spec.json 存在（11910 字节）；src/bidpricing/solver/precheck.py 存在；tests/test_precheck.py 存在；ADR ADR-0030-phase0-precheck.md 存在 |
| T03-06 | 不可行诊断 | done | ✓ 成立 | config/infeasibility_diagnosis_spec.json 存在（8357 字节）；src/bidpricing/solver/diagnose.py 存在；tests/test_diagnose.py 存在；ADR ADR-0031-infeasibility-diagnosis.md 存在 |
| T03-04 | 约束判定器 | done | ✓ 成立 | config/constraint_judge_spec.json 存在（15213 字节）；src/bidpricing/solver/constraint_judge.py 存在；tests/test_constraint_judge.py 存在；ADR ADR-0029-constraint-judge.md 存在 |
| T03-07 | 状态机与低价处置状态 | done | ✓ 成立 | 已实现全局四态聚合与三态低价处置状态：BLOCKED > FAIL > WARN > PASS；潜在不可行 > 成本证据不足 > 低价复核，未触发时不生成状态。6 项状态机测试通过。；config/state_machine_spec.json 存在；src/bidpricing/state_machine.py 存在；tests/test_state_machine.py 存在（1814 字节） |
| T03-05 | 判定层测试矩阵 | done | ✓ 成立 | config/judgment_test_matrix_spec.json（13 约束 × 6 边界类 = 78 格，12 格声明不适用；「缺失」拆 NOT_ACTIVE(SKIP)/MISSING_INPUT(BLOCKED) 两格；「1 单位」逐约束具名绑定——res 0.01 元 / tol_width / count / sigma_step 三种量纲）+ src/bidpricing/validation/judgment_matrix.py（枚举与覆盖审计：未声明空格⇒BLOCKED、零格⇒BLOCKED；参数化 judge_fn：真实实现与变异体同跑；25 条变异体注入审计，kills_by 按「声明 ⊆ 实际」对账，存活⇒FAIL；规则优先级 A1–A4；规则集切换两层判据 L1 数值/L2 元信息 + SEGMENT 退化登记为 WARN）+ tests/test_judgment_matrix.py 34 项元测试。实测：78 格零失配、25/25 变异体被杀、覆盖审计 PASS（66 覆盖 + 12 声明例外）、总结论 WARN（唯一来源＝SEGMENT 下数值指纹退化，已登记）。首轮 M-05/M-06 假存活（变异体依赖 reason 文案）已修正并加元测试钉住。CLI judgment-matrix。；config/judgment_test_matrix_spec.json 存在（19787 字节）；src/bidpricing/validation/judgment_matrix.py 存在；tests/test_judgment_matrix.py 存在；ADR ADR-0034-judgment-test-matrix.md 存在 |
| T04-00 | Phase 1 适用条件证明与反例集 | done | ✓ 成立 | 2026-09-17 完成《Phase 1 精确性条件》+ 反例集。**定理 T1（阈值分割）用交换论证证明**，刻意不走 KKT——KKT 是 T04-02A/D 的实现路线，两者共用会让「证明」与「实现」按同一个误解同时成立，T04-08 的独立性验收即失去对象（ADR-0019）。九条条件分两组：A 组（EC-1 作用域完备 / EC-2 排序键正确 / EC-3 权重正 / EC-4 系数非负 / EC-5 非退化 / EC-6 软约束不激活 / EC-7 可行域非空）违反则阈值分割解不再是 P_A 最优解；B 组（EC-8 舍入可调和 / EC-9 上界有限）违反只加实现性义务。**verdict 只看 A 组**——首版把 EC-8 放 A 组的结果是任何实例都判不出 EXACT（舍入上界 0.005·Σq0 几乎总超 eps_total），一个永远需要附注的 verdict 等于没有 verdict。反例集 CE-01..CE-09 每个都带「误用解 vs 正确解」数值见证，由 check_solution 代回原式复算；expected 做**双向**比对（实现判 FAIL 的条件不得漏声明——CE-07 首跑即踩到单向比对的漏洞）。正例 PE-01 = 附录 B 例 2R 的 SEGMENT 分支（本项目已落 SEGMENT），用 n=2 端点比较做**完整**最优性验证。副产品：修掉 compute_r_eff 的 SEGMENT 分支真 bug（increase_threshold 本身已是 1+θ_dev，原式再加 1.0 使越界段 r_eff 系统性高估）。本项目真实结论：EC-9 对西永L样本判 WARN（031301017001 cap 空），故 Phase 1 算法必须内建「空 cap 项固定为临界项」分支。测试 50 项；phase1-check 10/10 制品↔实现一致。；config/phase1_exactness_spec.json 存在（39093 字节）；src/bidpricing/solver/exactness.py 存在；src/bidpricing/solver/cases.py 存在；src/bidpricing/solver/instance.py 存在；tests/test_phase1_exactness.py 存在；ADR ADR-0019-phase1-exactness-by-exchange-argument.md 存在 |
| T04-01 | Phase 1 解析解 | done | ✓ 成立 | 2026-09-17：排序+二分+贪心定容解析解落地。spec=config/phase1_solver_spec.json（PS-01..PS-11）；实现 src/bidpricing/solver/phase1.py（solve_phase1/judge_phase1/phase1_report/两个内置探针）；Z 一律由 instance.check_solution 复算（不重实现 R_i）；lb_i 复用 formulation.merged_lower（_merged_lower 提升为公开名，唯一实现不变）。两个探针（free-cap/simple）verdict=PASS。测试 48 项全绿（全量 838），含 PS-06 双向交换探针、r vs r_eff 逆序实例、空 cap 临界项、平台 tie-break、不支持政策 BLOCKED、INFEASIBLE≠BLOCKED。CLI 新增 phase1-solve（--probe/--instance/--json）。遗留：PS-11 曾抓到制品把三容差入参写成一条，已拆分制品（判据先于实现纠错）；PS-06 首版只做单向交换，补齐「先增后减」方向。；config/phase1_solver_spec.json 存在（22640 字节）；src/bidpricing/solver/phase1.py 存在；tests/test_phase1_solver.py 存在；ADR ADR-0026-phase1-analytic-solver.md 存在 |
| T04-02A | LP 模型形式化 | done | ✓ 成立 | 2026-09-17 完成。交付 `config/lp_formulation_spec.json`（变量/非变量/参数/索引集/目标/C1–C13 逐条映射/箱型预处理/求解器形态/F 判据 11 条/消费者/挂账）+ `src/bidpricing/solver/formulation.py`（只形式化不建模）+ CLI `formulate-check`（LP 与 MILP 两变体各 11 条判据，22/22 PASS）。**核心结论一：目标对 p 严格线性** —— r_eff 由 (r_i, 规则集参数, alpha_i) 全外生决定，P1 分支在建模期已知 ⇒ R_i 对 p 线性 ⇒ LP 成立，MILP 的**唯一**来源是 C7 的二元变量 z_i（F-09 即以此判据：「MILP 切换条件唯一」）。区分两个边际：∂R/∂p = q0·r_eff（r_eff 的定义式，F-02 检它）与 ∂Z/∂p = q1·r_eff（目标系数，乘 r 倍）。**2026-09-17 修正（ADR-0022 决策三）**：此句后半**误**——∂Z/∂p = ∂R/∂p = q0·r_eff，写成 q1·r_eff 等于把 LP 排序键又乘一遍 r_i（次优且不报错），由 T04-02B 的 CC-07 跨来源代回抓到（676000 vs 420000）。**结论二：C1 按可竞争部分实现** —— Σ_{i∈C1_scope} p_i q0_i == P*_competitive，右端由 compute_P_competitive(P*, FIXED_PRETAX, 税率) 提供（入参是锁定总价而非报价向量，否则 C1 变成恒真式）；固定项不进左端。**结论三：三条约束须改变位置** —— ① C5 的 LP 下界必须抬到报价分辨率 lb_C5 = max(eps_price·P*, rounding.resolution)：P*=1e6 时裸 eps_price·P* 仅 1e-3 元，舍入后为 0.00 ⇒ 提交的报价违反 C5（内层约束与外层舍入的耦合点，ADR-0020 模式 A 的显式处理对象）；② C12 在可行域上是**常量**（两种作用域读法同结论）⇒ 应作 P* 的前置可接受性判据，写成 LP 约束会得到恒真/恒假的平凡约束并掩盖真实问题；③ C11 的 MAD/σ 替换方向相反（σ→MAD 收紧、MAD-with-free-center 放松）⇒ 挂账给 T04-02B，不静默选定。**本轮抓到两个 bug**：① 实现侧 settlement_revenue 的区间内分支漏了作用域判断（SEGMENT ∧ alpha≠0 时与 compute_r_eff 差 (1+α) 倍，alpha=0 时完全不可见）——已修，并加数值差分回归测试；② 判据自身首版借道 instance.r_eff，被实例 Phase1Params 覆盖了传入 scope，**自己制造假 FAIL** —— 修为先按 (scope, alpha) 构造 scoped 参数、解析式直用 compute_r_eff。据此确立原则：**判据的覆盖面不得取决于被测数据**（F-02 自扫 FULL/SEGMENT，不沿用实例 scope）。另修 status.check_evidence 第三处缺口：phase_0 项目级输入（project_classification_table）本就不做版本冻结，按「hash 已冻结」判会永远不成立 ⇒ 改用「文件存在」，与输入门的「声明式就绪」同向。本层状态域新增 SKIP（字符串，非全局 Status 四态枚举）：缺实例时「没检查」必须与「检查过且通过」可区分。测试 527 → 555（新增 tests/test_lp_formulation.py 28 项，含两个区分度测试：注入旧分叉必须FAIL、两组 p 向量必须真的不同）。contract-check 17/17，闸门全 PASS。；config/lp_formulation_spec.json 存在（39305 字节）；src/bidpricing/solver/formulation.py 存在；tests/test_lp_formulation.py 存在；ADR ADR-0021-lp-formulation-positions.md 存在 |
| T04-02B | 约束编译器 | done | ✓ 成立 | 2026-09-17 完成。交付 `config/lp_compiler_spec.json`（目标形式/展开规则/化简规则/后端/字面量白名单/CC-01..CC-12/消费者）+ `src/bidpricing/solver/compiler.py`（Formulation → CompiledModel 的机械翻译 + 零依赖求值器 evaluate + 惰性 PuLP 导出 + 12 条 CC 判据）+ CLI `compile-check`（LP/MILP 两变体各 12 条，24 条中 21 PASS / 3 SKIP / 0 待处理）。**核心：把「无手写约束」做成可机械判定的性质** —— 编译目标定为建模器/求解器无关的规范形式（零第三方依赖环境的硬约束），CC-01..CC-12 全部跨来源对账（一侧 Formulation、一侧 CompiledModel，CC-07 再加业务式 check_solution）。**修 T04-02A 遗留两处真 bug**：① C7 双向指示式原两式共用 M = c_i − lb_i，而两式恒真条件不同（下式覆盖下界、上式覆盖上界）⇒ 第三式在 z=0 处切掉 [c_i, ub_eff] 大部分区间（实测 c=50/lb=45/ub=120/eps=0.01 时共用 M=5 把合法区间从 [50,120] 压到 [50,54.99]）⇒ 业务侧判可行、编译侧判违反，误报 infeasible 且不报错 —— 已拆 M_lo/M_hi + 有效上界 ub_i^eff + 退化固定（z 固定界而非删除、C7 汇总 RHS 扣减 n_fixed_one），CC-08 锁死；② 目标系数原写 q1·r_eff，正确为 q0·r_eff（= ∂R/∂p，因 c_i·q1_i 与 p 无关）——写成 q1 等于把 LP 排序键又乘一遍 r_i（次优且不触发任何可行性检查，T04-00 EC-2 失效模式），由 CC-07 跨来源代回实测抓到（676000 vs 420000），已修并加数值差分回归测试。**裁定 C11 移出 LP**：σ(d) 是二阶锥约束而 HiGHS 不含 SOCP，MAD 替代由 Cauchy-Schwarz 是放松（最坏 √n，本项目 10.72 倍）且原式 (1/n)Σ|p−p̄| 不含 base_i 未归一化 ⇒ 两份制品同落 DISCRETE_CHECK，由 CC-10 锁死。**CC-12 规则定为「数值必须具名」而非按值白名单**：首版把模块自身容差与切片下标误报为手写系数（判据把正常实现报成违规），改判是否具名后 SLACK_ATOL=1e-9 通过、0.85*cap 被抓。**修 CLI 契约漂移**：误读 literal_allowlist.allowed（正确键 allowed_in_expressions），读错会静默退回模块默认值使制品不再是白名单真相来源；并把探针的求解层入参（formulation.PROBE_SOLVER_INPUTS）接入 build_formulation/compile_model，否则 C6/C7/C9/C10 占位行恒 NOT_COMPILED ⇒ MILP 变体 CC-05 恒 BLOCKED。口径修正已全仓 grep 旧表述并同步（lp_formulation_spec.relation_to_objective、formulation.objective_expr、lp_compiler_spec.coefficient_rule、compiler 文档串、CHANGELOG、T04-02A note）；ADR-0021 不可变，由 ADR-0022 决策三推翻其 ∂Z/∂p=q1·r_eff 一句。测试 555 → 587（tests/test_lp_compiler.py 32 项，含 12 条判据各自的错误注入区分度层 + evaluate + 惰性导出 + 字面量审计）。遗留：CC-09（PuLP 结构等价）本机恒 SKIP，须 T04-02C 复跑；M_hi 对分支定界收敛的影响已于 2026-09-22 量化关闭（OI-MA-A，见 T04-07 note 与 tools/oi_ma_a_experiment.py）。；config/lp_compiler_spec.json 存在（24898 字节）；src/bidpricing/solver/compiler.py 存在；tests/test_lp_compiler.py 存在；ADR ADR-0022-lp-compiler-positions.md 存在 |
| T04-02C | HiGHS backend adapter | done | ✓ 成立 | 2026-09-17 完成。交付 `config/solver_backend_spec.json`（分层/能力域/注册表/选择策略/状态域与两张映射表/序列化/BB-01..BB-09/静态审计基准/环境与证据指针）+ `src/bidpricing/solver/backend.py`（唯一允许接触求解器包的模块：选后端 → 复用 T04-02B 导出层 → 求解 → 状态归一 → 解回读 + 9 条 BB 判据）+ CLI `backend-check`（LP/MILP 两变体各 9 条）+ ADR-0023。**核心：把「业务逻辑不写死求解器」做成可机械判定的性质** —— 全仓只有 backend.py 可以 import 求解器包、可以调用 solve()（BB-03 静态 AST 判据）；后端的选择、能力矩阵、状态映射、审计基准全部住制品；加一个后端 = 制品注册一条目 + ADAPTERS 放一个实现体，业务侧零改动。**状态分域**：定义九值归一状态域并把 native→normalized 与 normalized→judge 两条映射分开（求解器的答案是业务结论，判据的答案是「这一环走样没有」，塞进同一枚举正是本仓反复出现的根因）。四条关键裁定：① AMBIGUOUS 独立存在（HiGHS kUnboundedOrInfeasible 与 PuLP Undefined 都自带歧义，折进 INFEASIBLE 是无据断言、折进 ERROR 是无据归因）；② 超时不含结论（kTimeLimit 等按有无 incumbent 分叉：有 ⇒ FEASIBLE 未证最优，无 ⇒ UNSOLVED）；③ UNAVAILABLE（环境缺失⇒SKIP+复跑条件）与 UNSUPPORTED（机制缺失⇒BLOCKED）分属不同档，合并会让一个把 MILP 交给 LP-only 后端的配置以「没跑」的样子长期留档；④ 原生别名表整张住制品，适配层源码不得出现任何别名串（BB-05 静态子判据）。**BB-05 首版按纯文本 grep 把模块自己 docstring 里的说明文字报成违规 —— 判据把正常实现报成违规，改为 AST 取字面量且排除 docstring**（要拦的是代码路径上的硬拷贝，不是文档提到这个词；与 CC-12 同一条教训）。**CC-09 复跑（T04-02B 挂账闭合）**：复跑前先把覆盖面补齐到逐行系数多重集 + 目标方向 + 目标常量，行比对由「按下标」改为「指纹多重集配对」（与 CC-02 同构，原按下标隐含假设了模型行序==约束插入序，该假设从未声明）。**首跑即 FAIL 两处真问题**：① 导出层把变量名交给建模器净化 —— PuLP 构造 LpVariable 时把 `+ - / > [ ]` 与空格一律换成 `_`，于是 p_P-DEC 导出后变 p_P_DEC、适配层按符号回读一个都取不到（解被判「全部变量缺失」），更糟的是两个不同符号净化后同名 ⇒ **两个决策变量静默合并成一个**（实测 a-b 与 a_b 的 .name 都是 a_b）；修法是导出层自持可逆编码（白名单 [A-Za-z0-9_] 原样、其余编码为 ~%04x），并由 CC-09 增判「编码在真实符号集上单射」与「往返一致」——单射那条是导出层唯一灾难性的失败；穷举实测 2026-09-17 PuLP 3.3.2 只改动七个字符（+ - / > [ ] 与空格）。② extract_pulp_structure 的优化方向反向映射对反了（写成 LpMinimize=1 的直觉版，实测 PuLP 是 LpMinimize=1/LpMaximize=-1，我写反）—— 方向若不比对，就永远发现不了有人把 to_pulp 写成 LpMinimize。**修 CC-09 三条出口不分家的缺陷**：to_pulp 原先在符号闭包缺口时让 lpSum 抛 KeyError，把整条校验以异常形态炸掉（而不是报一条 FAIL）—— 改为构造前自查并抛 CompilerError ⇒ CC-09 归一 BLOCKED，且「导出层拒绝」与「本机没装 PuLP」不再被读成同一件事。**能力不足即 BLOCKED 不得降级**：把含二元变量的模型交给 LP-only 后端会静默放松整数性（与 C7 共用 M 同族失效）；声明未实现的条目同样判 UNSUPPORTED 且不回退。**替换性实证**：active 由 pulp_highs 改为 pulp_cbc（或 --prefer），源码零改动，HiGHS 与 CBC 给出同一最优值 460000.0、C1 残差 0（0.004s vs 0.057s）；BB-06 在只有一个候选时判 FAIL 而非 PASS（无第二候选即无证据，不得把「无从验证」记成「已验证」）。**仓外验证**：为闭合 CC-09 在仓外建隔离 venv（PuLP 3.3.2 + HiGHS 1.15.1），仓内维持零依赖（无 PuLP 时 BB-07/BB-08/BB-09 与 CC-09 判 SKIP，BB-01..BB-06 仍全可判）。**CC-12 在适配层新写的代码上当场生效**：int(...,16) 的裸进制被自己抓出，提成 SYMBOL_ESCAPE_RADIX。测试 587 → 659（tests/test_solver_backend.py 62 项，每条 BB 判据配错误注入的区分度层 + CC-09 六种走样注入 + 符号编码回归）；零依赖环境 659 OK / 9 SKIP，装 PuLP 环境 659 OK / 0 SKIP。**输出文案的环境断言纠偏**：compile-check/backend-check 的「N 条 SKIP」提示原写死「本机无 PuLP」，在装 PuLP 的机器上成为假话（CC-09 已实跑，余下的 SKIP 是 LP 变体 CC-08 的结构性豁免）—— 改为读具名探针 pulp_available()（与 to_pulp 同源）决定文案，并加单测断言探针与导出层答案恒等；测试侧 TestCheckLayerGreen 原先断言 CC-09==SKIP（只在零依赖机成立），改为按 import pulp 探测取值（缺能力时假 PASS 与有能力时假 SKIP 同属回归）。**上游漂移实测并挂账**：PULP_CBC_CMD 已弃用（4.0 移除，pulp_cbc 因此是随版本失效的第二候选，升级须同步改制品否则 BB-06 会真 FAIL）；LpVariable(name,...) 直接构造与 prob.constraints 字典用法 4.0 将变（影响面在 T04-02B 导出层）。；config/solver_backend_spec.json 存在（38691 字节）；src/bidpricing/solver/backend.py 存在；tests/test_solver_backend.py 存在；ADR ADR-0023-solver-backend-adapter.md 存在 |
| T04-02D | 解校验器 | done | ✓ 成立 | 2026-09-17 完成。交付 `config/solution_verifier_spec.json`（两层容差定义 / 容差名→数值解析表（封闭动词集）/ 四族声明 / 五类层归属 / SV-01..SV-13 / 判定聚合 / 独立性（接口级 + 静态级）/ 参考值策略）+ `src/bidpricing/solver/verifier.py`（外层复核层）+ CLI `verify-solution`（LP/MILP 两变体各 13 条）+ ADR-0024。**核心：复核实现在接口级就够不着内层结论** —— verify_solution 的入参只有原始量（x / reported_objective / model / instance / profile / floor_by_id / reference / verifier_source / resolution），**刻意不过载 SolveResult**；再叠一层 AST 静态审计禁止调用 evaluate / check_solution / solve_compiled 与 import 任何求解器包（SV-12）。**两层容差的宽度比必须被具名并检验**（ADR-0020 D1）：R2 = eps_abs/eps_solver = 1e6 ≥ 1e3（SV-06），否则复核层退化成内层判据的复制。**三态分离**：SKIP（本轮没查）/ BLOCKED（这一环没查成，如无 Z_ref、floor 未接入）/ FAIL（查出问题）；空判据集 ⇒ BLOCKED；聚合序 FAIL > BLOCKED > WARN > SKIP > PASS。**★ 落地时实测出两处真缺陷（非推演）**：(DV-01) 行上声明的 tolerance 名字**从未被任何判据解析成数值** —— 内层实际用一个未具名的 1e-12，比声明的 eps_solver=1e-8 严 1e4 倍；把 C1 残差注入 5e-9（在声明容差**之内**）即被判不可行，且 BB-08 给出**错误归因**「导出层走样」（而 CC-09 已 PASS）。探针看不见它（最优值可精确表示，C1 slack 恰为 0）；真实规模项目上这是**必然触发**（HiGHS 原始可行容差 1e-7，PuLP 报告前还就地舍入）。修法分两半：① 编译侧 evaluate 增 tolerances 入参（唯一来源 verifier.resolve_tolerances），RowEval 拆 ok_exact / ok / in_tolerance_band；② 业务侧 check_solution 增 tolerances 入参，盒式约束（L/U）改用**声明名** eps_price 的宽度判（此前对 L/U 是严格比较、只有 C1 用 eps_total ⇒ 同一个 p=U+5e-12 编译侧判可行、业务侧判不可行 —— **只修一半比不修更隐蔽**）；结果新增 tolerance_name/value/resolved 自述口径，传了表却缺该名 ⇒ BB-08 判 BLOCKED（不静默按 0 冒充可比）。(DV-02) eps_price 有两种读法：**绝对**（profile 值 × P*，行级容差宽度）与**相对**（无量纲因子，compute_lb_c5 的入参、ε_Z 的相对项）。混用即「乘重一遍」：把已 ×P* 的 0.003 再喂给 compute_lb_c5 ⇒ lb_C5 由 0.01 元放大成 9000 元，所有项被判越下界 —— 与历史上目标系数误写 q1·r_eff 同族。**故二者在制品里是两个名字**（eps_price / eps_rel_price，同源不同用法）。**判据覆盖面的自省**：目标系数 ∂Z/∂p = q0·r_eff（不是 q1）；SV-03 要求「容差带必须被本实例走到」，探针恰好走不到 ⇒ 判 WARN 而非 PASS（「这一轮没走到」不得读成「已成立」）；SV-13 在 T04-08 落地前恒 BLOCKED（禁止用本层自算的业务式顶替 —— 那与 CC-07 同源，构成恒真式）。**仓外验证**：装 PuLP 环境 backend-check 18 PASS / 0 SKIP（BB-09 的 CC-09 挂账闭合、BB-08 双侧含新口径均 PASS）；verify-solution 在补齐 floor（T03-02）与 Z_ref（T04-08）后升到 WARN，余下唯一 WARN 即 SV-03（探针走不到容差带）。测试 659 → 735（tests/test_solution_verifier.py 60 项 + 两侧容差区分度层 + BB-08 口径三态层），零依赖 735 OK / 9 SKIP，装 PuLP 735 OK / 0 SKIP。**未结**：SV-07 的 floor 一路（owner T03-02）、SV-13 的 Z_ref（owner T04-08），以及 solve_compiled 的 eps_total / tolerances 双入参过渡态（已登记进 solver_backend_spec.open_items）。；config/solution_verifier_spec.json 存在（29246 字节）；src/bidpricing/solver/verifier.py 存在；tests/test_solution_verifier.py 存在；ADR ADR-0024-solution-verifier.md 存在 |
| T04-02E | 不可行诊断对接 | done | ✓ 成立 | src/bidpricing/solver/diagnose.py 存在；tests/test_diagnose.py 存在；ADR ADR-0032-oracle-wiring.md 存在 |
| T04-07 | MILP 独立验收协议 | done | ✓ 成立 | 2026-09-18：MILP 独立验收协议落地。spec=config/milp_acceptance_spec.json（MA-01..MA-10 + 六字段 + 三容差具名）；实现 src/bidpricing/solver/milp_acceptance.py（build_acceptance 生产 / judge_milp 判定分离，只吃 MilpFacts 原始量）；适配层 backend._pulp_diagnostics 以 hasattr 能力探测取 best_bound/mip_gap/integrality_violation，取不到即留空（不用 Z 顶替）。最优性四项全满足才标 OPTIMAL，否则单向下坡降级 FEASIBLE（never_upgrade）；超时按有无 incumbent 分叉；禁 KKT 证 MILP 最优性。38 项测试（全量 877→915，双环境全绿），含注入『FEASIBLE 状态却给 OPTIMAL』必 FAIL、无 bound 却标 OPTIMAL 必 FAIL、制品漏声明容差必 BLOCKED、超时写成 INFEASIBLE 必 FAIL。CLI milp-check（--form LP|MILP|both / --time-limit / --json）。★ 接线首跑抓到真口径错误：HiGHS 的 mip_dual_bound 不含 objective_constant（探针常量 −2,270,000；只做 min→max 取反得 bound=2,730,000 对 Z=460,000，复算间隙 4.9 而自报 0.0），由 MA-06 跨来源对账抓出，补两步换算后一致。★ 实测能力差异：pulp_highs ⇒ OPTIMAL（已证）；pulp_cbc（命令行后端 solverModel=None）⇒ diagnostics 为空 ⇒ MA-05 WARN + MA-06 BLOCKED ⇒ 降级 FEASIBLE 未证（若硬编码『一定有诊断量』，CBC 上会静默宣称最优）。遗留 OI-MA-A 已于 2026-09-22 量化关闭（T04-02B 挂账项）：tools/oi_ma_a_experiment.py 在 60 项 C7 合成实例（n_max=3、60 个二值 z）上把 M_hi 放大 k∈{1,2,5,10,100} 逐项对比——最优值 Z、LP 松弛目标（=MILP，零过松弛）、B&B 节点数（根节点即闭）与耗时在各档均无差异（结果 docs/oi_ma_a_experiment.json，可复算）。结构性原因：带 C2 显式箱上界的项其 C7.upper 被箱主导，M_hi 幅度不进入松弛；仅 C1 隐式上界的项放大后也只使该行更松，本实例族未产生松弛质量差异。结论：**维持紧值 M_hi = ub_eff − c_i + eps（现设计）**——放大无收敛收益，CC-08 已禁缩小方向；探针规模不构成证据的 T04-02C 说法由本实验补上 60 项口径。；config/milp_acceptance_spec.json 存在（16121 字节）；src/bidpricing/solver/milp_acceptance.py 存在；tests/test_milp_acceptance.py 存在；ADR ADR-0028-milp-acceptance-protocol.md 存在 |
| T04-08 | 独立 Reference Implementation | done | ✓ 成立 | 2026-09-17：独立参考实现落地。spec=config/reference_impl_spec.json（RI-01..RI-11 + ISO-1/2/3）；实现 src/bidpricing/refimpl/{reference,isolation}.py，**不 import 任何生产模块**（连数据结构也不 import，靠冻结快照取属性），公式由路线 §5.3 S0 + 利润桥接表 + 规则卡推导；Z_total/Z_competitive 两个口径两个名字；ε_Z=eps_abs+eps_rel_price·max（缺项 BLOCKED）。39 项测试（全量 838→877），含手算钉死六分支组合、注入错 Z/篡改逐项必 FAIL、制品少声明分支必 BLOCKED、审计抓 settlement_revenue、ISO-2 运行时复读探针。CLI ref-check；verify-solution 默认向参考层取 Z_ref ⇒ **SV-13 挂账闭合**（LP/MILP 两变体均 PASS，Δ=0）。接线首跑即抓到真 bug：C7 二值 z_i 与 p_i 共用 item_id，映射被 0/1 覆盖（按 family=="p" 过滤修复）。遗留 OI-RI-A：ISO-3 作者分离需第二人签署（docs/reference_review_signoff.json，signed=false）⇒ 未签前 T04-04 对拍结论强制 BLOCKED。；config/reference_impl_spec.json 存在（11123 字节）；src/bidpricing/refimpl/reference.py 存在；tests/test_reference_impl.py 存在；ADR ADR-0027-reference-implementation.md 存在 |
| T04-04 | Phase 1/2 对拍器 | done | ✓ 成立 | 已实现三级对拍器（L1 状态 / L2 数值 / L3 层归属+残差）与 A/B 两组；独立性签署已 PASS。2026-09-20 收口（ADR-0036）：① 容差改由 phase12_parity_spec.json 唯一提供（修 DV-01 家族）；② 补齐 L1 状态可比性与 L3 约束残差（residual_abs，单侧残差判「口径不可比」BLOCKED）；③ 补 B 组义务与 floor 来源声明；④ 新增 CLI parity-check，报告由代码产出并自带复算命令（原报告无生成器，搬为 prior_measurement.json）。2026-09-20 收口②（ADR-0036 遗留 1/2）：新增 bundle 生成器 src/bidpricing/solver/parity_suite.py，从 golden_dataset_v1 构造求解层实例（补 p0=cap/L=0/B=Σ(cap_i·q0_i) + tie_break=CANONICAL_ITEM_ID），分别跑 Phase 1 解析解与 Phase 2 编译 LP，两侧目标值取自同一独立裁判 check_solution.Z；新增 CLI parity-suite 生产 bundle（结果是留痕），parity-check --bundle 消费之。实例集覆盖：A/D/F 正例两路径均产出且三层对拍一致 ⇒ 报告结论 PASS（L3）；B_pos（可行域退化单点，LP INFEASIBLE）、E_pos（2000 行极端尺度）、C_pos（无两侧齐备项）及全部负例显式写入 provenance.skipped 留痕。复算：parity-suite → parity-check --bundle docs/phase12_parity_bundle.json（PASS L3，exit 0）。70 项 parity 测试通过（新增 test_parity_suite 5 项）。；config/phase12_parity_spec.json 存在；src/bidpricing/solver/parity.py 存在；src/bidpricing/solver/parity_runner.py 存在；docs/phase12_parity_report.json 存在（3752 字节）；docs/phase12_parity_prior_measurement.json 存在（1918 字节）；tests/test_parity.py 存在；tests/test_parity_runner.py 存在；ADR ADR-0036-parity-reproducibility.md 存在；src/bidpricing/solver/parity_suite.py 存在；docs/phase12_parity_bundle.json 存在（8088 字节）；tests/test_parity_suite.py 存在 |
| T04-05 | Phase 3 验证 | done | ✓ 成立 | 已实现 Phase 3 LP/MILP 验证：LP 检查 primal/dual feasibility、stationarity、complementary slackness、objective recomputation；MILP 检查 primal feasibility、objective recomputation、MIP gap，缺少诊断量一律 BLOCKED，禁止用 KKT 伪证 MILP 最优性。6 项测试通过。；config/phase3_verification_spec.json 存在；src/bidpricing/solver/phase3.py 存在；tests/test_phase3.py 存在 |
| T04-06 | 数值稳定性处理 | done | ✓ 成立 | 已实现数值稳定性预处理/后处理：epsilon 截断、相对容差、最大绝对系数归一与恢复、平台效应识别（明确排除 q0=0）、P95 延迟基线；空样本/全零/非有限输入不伪造结论，按规范返回 BLOCKED/未知。6 项测试通过。；config/numerical_stability_spec.json 存在；src/bidpricing/solver/stability.py 存在；tests/test_stability.py 存在 |
| T04-06B | 退化与多最优解处理 | done | ✓ 成立 | 已实现退化处理：平台组检测、q0=0 排除、可分配平台的多最优告警、canonical item_id 顺序分配、加权 L1 次级目标与边界对偶区间输出。未知/缺失输入不静默降级。5 项测试通过。；config/degeneracy_spec.json 存在；src/bidpricing/solver/degeneracy.py 存在；tests/test_degeneracy.py 存在 |
| T05-00 | Baseline 定义与冻结 | done | ✓ 成立 | 已实现 Baseline 三选一与冻结校验：UNIFORM_DISCOUNT / PREVIOUS_MANUAL / COMPANY_CONVENTION；要求显式 version+frozen=true，按指纹检测变更；Z_baseline 通过外部 contribution 函数复算，避免复制利润公式。5 项测试通过。；config/baseline_spec.json 存在；src/bidpricing/baseline.py 存在；tests/test_baseline.py 存在 |
| T05-01 | $q^1$ 扰动实验 | done | ✓ 成立 | 已实现四类 q1 扰动：独立、分组守恒、全局比例、历史误差重采样；固定 N=1000/seed=20260915/95% 置信度，明确 stress_test 与 empirical_simulation，输出 P5/P50/P95/VaR95/CVaR95。缺失历史误差、非法 q1 均阻断。6 项测试通过。；config/q1_perturbation_spec.json 存在；src/bidpricing/robustness.py 存在；tests/test_robustness.py 存在 |
| T05-02 | 三指标价值评估 | done | ✓ 成立 | 已实现三指标：Optimization Gain = Z_opt−Z_baseline；Prediction Risk = Q95−Q5；Robustness Ratio = Gain/Risk。最优性未证时标 WARN 并标注 Gain 为下界；分位数顺序非法 FAIL；Risk=0 时 Ratio 未定义并 BLOCKED。5 项测试通过。；config/value_metrics_spec.json 存在；src/bidpricing/value_metrics.py 存在；tests/test_value_metrics.py 存在 |
| T05-03 | $c_i$ 区间情景 | done | ✓ 成立 | 已实现大宗物资 c_i 区间情景复算：默认 0.8/1.0/1.2 三档，显式限定 material_ids，非物资项保持不变，输出 objective 与相对基准 delta；缺失/负值成本阻断。4 项测试通过。；config/cost_interval_spec.json 存在；src/bidpricing/cost_scenarios.py 存在；tests/test_cost_scenarios.py 存在 |
| T05-04 | $k^+/k^-$ 情景 | done | ✓ 成立 | 已实现 k⁺/k⁻ 同步缩放三档情景（0/0、0.5/0.5、1/1），通过外部 evaluator 复算目标值与排序，并标记相对基准的排序变化；非法参数或空情景阻断。4 项测试通过。；config/k_scenario_spec.json 存在；src/bidpricing/k_scenarios.py 存在；tests/test_k_scenarios.py 存在 |
| T06-01 | 报价表输出 | done | ✓ 成立 | 已生成 Excel 报价表：报价表主表包含工程量、最高限价、c_i、投标单价、合价、成本合价、毛利、毛利率、r_eff、层归属、状态与说明列；不可竞争项、固定项、说明单独分区。投标单价与 Phase 1/2 输出保持为空，不伪造报价结论。已用 Artifact Tool 检查关键范围、公式错误（0 命中）并完成渲染复核。；tests/data/t06-01/报价表.xlsx 存在（60895 字节） |
| T06-02 | 风险体检单 | done | ✓ 成立 | 已实现 9 项风险体检单：每项输出 PASS/WARN/FAIL/BLOCKED、actual、threshold、delta；缺少 actual/threshold 明确 BLOCKED，数值差值保留方向，禁止用综合描述替代机械结果。4 项测试通过。；config/risk_check_spec.json 存在；src/bidpricing/risk_checklist.py 存在；tests/test_risk_checklist.py 存在 |
| T06-03 | 决策支持结论页 | done | ✓ 成立 | 已实现机器决策支持结论页：结构合理性与定价基准风险按四态机械聚合，输出 PROCEED_TO_HUMAN_REVIEW/HOLD_FOR_REVIEW/BLOCKED；低价项强制携带 item、bid_price、estimated_individual_cost、margin、reason、supporting_data，并映射 T03-07 三态；人工审批字段默认 PENDING，不生成投/不投结论。4 项测试通过。；config/decision_support_spec.json 存在；src/bidpricing/decision_support.py 存在；tests/test_decision_support.py 存在 |
| T06-04 | 一键复算 | done | ✓ 成立 | 已实现一键复算协议：R1-A 对同输入连续运行的 canonical result 计算稳定 hash 并比对；R1-B 支持绑定 golden expected 做正确性校验，未绑定时明确 BLOCKED；R1-C 记录 Python/PuLP/HiGHS/OS/arch/solver_options/random_seed。4 项测试通过。；config/rerun_spec.json 存在；src/bidpricing/rerun.py 存在；tests/test_rerun.py 存在 |
| T06-05 | 全链追溯 | done | ✓ 成立 | 已实现 Calculation Trace：强制覆盖 Source→Normalized→Derived→Constraint→Solver→Postprocess→Report 七阶段；每节点要求 source_refs、inputs、outputs、derivation、upstream_ids；阶段缺失、重复节点或断链均输出 BLOCKED。4 项测试通过。；config/calculation_trace_spec.json 存在；src/bidpricing/calculation_trace.py 存在；tests/test_calculation_trace.py 存在 |
| T06-06 | 总价重算与舍入调和 | done | ✓ 成立 | 已实现独立总价调和模块：分项金额舍入、总价重算、0.01 元差额修正、修正后约束复验；修正会产生负合价或约束复验失败时输出 BLOCKED，不生成可提交报价。4 项测试通过。；config/reconciliation_spec.json 存在；src/bidpricing/reconciliation.py 存在；tests/test_reconciliation.py 存在 |
| T06-07 | 报告元信息与 hash 分层 | done | ✓ 成立 | 已实现报告元信息分层：calculation_hash 排除 timestamp/run_id/operator，artifact_hash 对最终制品字节计算；每份报告强制绑定 model_version、config_version、input_hash、rule_set_version，并保留 run_id、created_at、operator。4 项测试通过。；config/report_metadata_spec.json 存在；src/bidpricing/report_metadata.py 存在；tests/test_report_metadata.py 存在 |
| T06-08 | 不可变审计运行记录 | done | ✓ 成立 | 已实现不可变审计运行记录链：RunID→Input→Config→RuleSet→Model→Solver→Output→Decision；每段包含 run_id、operator、created_at、payload、previous_hash、event_hash，篡改或断链校验为 BLOCKED。4 项测试通过。；config/audit_log_spec.json 存在；src/bidpricing/audit_log.py 存在；tests/test_audit_log.py 存在 |
| T07-01 | 历史项目回放 | deferred | ✓ 成立 | 已实现历史项目回放框架：机制测试 4 项通过，但仅有 1 个真实历史项目样本，不足以达到『≥3 个历史项目完整复算』的 Gate 6 门槛。标记为【待定/跳过】：不误报完成，也不作为可开工遗留，待后续补充真实项目数据后恢复。；config/historical_replay_spec.json 存在；src/bidpricing/historical_replay.py 存在；tests/test_historical_replay.py 存在 |
| T07-02 | $Q_0 \to Q_1$ 实际对照 | partial | ✓ 成立 | 已实现 Q0→Q1 逐项对照框架，并正式绑定实际结算口径：actual_q1=成本清单 q1_point，settlement_unit_price=报价 p_bid，settlement_amount=两者相乘；输出 signed_error、absolute_error、relative_error。predicted_q1 现经闭环声明书机制接入（T07-03）；西永真实 81 项样本对照级已验证 PASS。5 项测试通过。；config/quantity_reconciliation_spec.json 存在；src/bidpricing/quantity_reconciliation.py 存在；tests/test_quantity_reconciliation.py 存在 |
| T07-03 | 精度监控 | partial | ✓ 成立 | 已实现 MAE/WAPE/sMAPE 监控、小工程量 q1<q_min 单独口径，以及基于 sample_size、confidence_interval、segment、project_type 的升级闸门；并接入闭环编排（closed_loop.py：对照→精度→校准），predicted_q1 来源独立性契约登记于 config/closed_loop_spec.json（来源限 historical_replay/model/manual 且不得与 cost.q1_point 同源，未登记即该级 BLOCKED、不得用 q0/actual 顶替）。预测值事实源=声明书机制（predicted_q1.py + config/predicted_q1_spec.json + CLI predict-register）：留痕四件（source/declared_by/declared_at/rationale）缺一拒登；闭环经 predicted_q1_declaration 引用声明书，缺值由声明书补齐、异值判篡改、未覆盖项判无登记来源。闸门输入源绑定声明于 precision_monitor_spec.promotion_input_sources：CI 未显式提供时由本次对照逐项相对误差 bootstrap 计算（N=1000/seed=20260915/95%，具名留痕、<2 观测返 None 不伪造）；segment 取记录集 unit_work 唯一值（跨多分部判未定）；project_type 待 T00-01 规则表/显式声明。新增 CLI 命令 precision-monitor / closed-loop / predict-register。14 项闭环 + 17 项声明书 + 4+3 项监控测试通过。西永真实 81 项验收：补 project_type 后升级闸门已翻 READY（CI/segment 自动解析），HOLD 缺口收窄为 project_type 一项。；config/precision_monitor_spec.json 存在；src/bidpricing/precision_monitor.py 存在；tests/test_precision_monitor.py 存在；config/closed_loop_spec.json 存在；src/bidpricing/closed_loop.py 存在；tests/test_closed_loop.py 存在；config/predicted_q1_spec.json 存在；src/bidpricing/predicted_q1.py 存在；tests/test_predicted_q1.py 存在 |
| T07-04 | 参数校准 | partial | ✓ 成立 | 已实现参数校准记录框架：只有 replay=PASS、实际对照=PASS、精度 promotion=READY 才生成版本化建议；建议记录 old_value/new_value/reason，永不直接覆盖当前 config，审批默认 PENDING。已接入闭环编排（closed_loop.py 按 spec.stages 串联，证据键与校准三门前置一一对应，整体状态域 READY/BLOCKED，缺数据逐级如实 BLOCKED/HOLD）；预测值事实源=声明书机制（predicted_q1.py：留痕四件 + 逐项交叉校验，闭环经 predicted_q1_declaration 引用）。西永真实 81 项验收：补 project_type（演示占位）后精度闸门 READY，三门仅剩 replay_status 未齐——对应 T07-01 历史项目回放（deferred：真实历史项目样本 1/3，待补数据后恢复）。新增 CLI 命令 calibrate / closed-loop / predict-register。17 项声明书 + 14 项闭环 + 4 项校准测试通过。；config/calibration_spec.json 存在；src/bidpricing/calibration.py 存在；tests/test_calibration.py 存在；src/bidpricing/closed_loop.py 存在；tests/test_closed_loop.py 存在；src/bidpricing/predicted_q1.py 存在；tests/test_predicted_q1.py 存在 |

---

## 六、下一步（自动派生）

> 判据：依赖任务均已 `done`/`partial`，且自身未完成。**由代码算出，非人工推荐。**

| 任务 | WP | 标题 | 产出物 | 状态 |
|---|---|---|---|---|
| T07-03 | WP7 | 精度监控 | 监控模块 | partial |
| T07-04 | WP7 | 参数校准 | 校准记录 | partial |

---

## 七、遗留项与已知限制

- cost_input_tax_spec.json → known_limits: 本机制现已支持**分项多税率精算**（cost_composition）：把含税成本按进项税率桶（默认：材料设备 13% / 劳务及措施 9%）拆段，每段带 proportion 与 input_vat_rate，k = 1 − Σ p_j·r_j/(1+r_j) 对任意段数/税率严格精确。给定 composition 时优先于单税率路径；不给定则回退旧单税率（兼容 CLI/旧配置）。FULL/PARTIAL 在构成路径下产生相同 k（构成已含各段真实税率）。
- cost_input_tax_spec.json → known_limits: cost_composition 的 proportion 是**项目级单一分解**（前端可逐项目自定义）。若同一项目内不同清单的货物/劳务占比差异极大，项目级分解仍会产生项间近似——逐项覆盖（按清单覆盖 composition）属后续扩展，本制品当前不支持。
- cost_input_tax_spec.json → known_limits: 换算只作用于 c_i。结算收入侧的销项税口径（vat_rate）不在本制品范围内，见 rate_names.vat_rate 的 used_by。
- cost_input_tax_spec.json → known_limits: 隐形成本（业务费/公司管理费/融资费/风险储备）尚未进入 c_i（H-003，见 project_quote_policy.hidden_cost_policy）——本制品只保证**已进入 c_i 的那部分成本**口径正确，不保证 c_i 完整。二者是两件事，都解决之前利润仍是『清单贡献利润』口径。
- phase1_exactness_spec.json → known_limits: T1 的结论只覆盖 P_A（C1 + 箱型）。C6/C9/C10/C11/C12/C13 激活时的结构由 §7.3 三层分割描述，本制品不证明其最优性。
- phase1_exactness_spec.json → known_limits: 交换论证假设 R_i(p_i) 对 p_i 线性——即 r_i 与 p_i 无关。这在本模型成立（q0/q1 均为外生预测），但对「单价影响结算量」的反向情形不成立。该情形不在本模型范围内。
- phase1_exactness_spec.json → known_limits: EC-5 的机械判据只能给出「存在平台」的必要信号，不能枚举全部多最优解。完整处理见 T04-06B（退化与多最优解处理）。
- phase1_exactness_spec.json → known_limits: EC-8 的判据给出的是**理论上界**（0.005 · sum q0）。实际舍入残差通常远小于上界，但判据按保守侧取——因为舍入调和环节的有无是结构性问题，不应依赖运气。
- phase1_exactness_spec.json → known_limits: 反例集不覆盖 T04-07 的 MILP 模式（C7 升 MILP 后 KKT 不适用，须走独立验收协议）。
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
