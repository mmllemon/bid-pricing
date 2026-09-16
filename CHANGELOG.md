# 变更日志

本文件记录**里程碑级**变更。逐次提交请用 `git log`；本文件回答的是
「相比上一次里程碑，项目发生了什么变化」。

**格式约定**：每个里程碑对应一个 git tag，tag 名形如 `<主题>-v<N>`。
条目分类：`新增` / `变更` / `修正` / `移除` / `安全`。

---

## [未发布]

### 真实样本接入：总价恒等式获得外部锚点（2026-09-16）

**背景**：拿到第一份**同一项目**的「招标限价 + 投标报价」配对样本
（西永L分区公立学校一期工程等项目配电工程，电气设备安装工程，81 条明细）。
此前只有分属不同项目的示例模板，跨项目恒等式不闭合（实测差 3.21 倍），
中心不变量始终没有真实样本背书。

#### 新增
- `tests/data/xiyong_l_district/pair.json` + `PROVENANCE.md` — 首份真实配对样本。
  含限价/报价两侧逐项 81 条（编码、名称、单位、工程量、限价单价、报价单价、合价）、
  措施表、其他项目表、规费税金表、表-04 汇总值，并逐列记录提取口径。
- `src/bidpricing/identity.py` — **总价恒等式的可执行判据**。
  `Totals` / `TaxDecomposition` / `decompose()` / `check_identity()` /
  `check_component_sum()`；容差取自 `precision_profile.json` 的
  `eps_total = max(eps_abs, eps_price × P*)`，**求解层与复核层共用同一函数**。
- `bidpricing identity-check` 子命令 — 对样本执行数值判据，支持 `--side bid|cap`。
- `tests/test_identity.py` — 33 项用例。
- `docs/adr/ADR-0005-恒等式闭合不等于数据完整.md`。

#### 修正
- `src/bidpricing/status.py` — `check_evidence` 新增 `file` 证据类型
  （数据类制品存在即成立），与 `module` 判定方式相同、语义不同。
- `tools/extract_tasks.py` — 登记 T00-06B 的模块证据、T01-02C 的样本证据。

#### 实测结论
- **报价侧恒等式精确闭合**：残差 **0.0000**。
  增值税 115,790.94 / 附加税 13,894.91 / 税金 129,685.85 / 总价 1,416,251.85，
  与源工作簿逐项相符。
- **限价侧也闭合（残差 0）但数据不完整**：其表-04「分部分项工程费」为空，
  逐项单价合计实为 1,374,238.77 元。据此确立 **ADR-0005：闭合 ≠ 完整**，
  完整性由独立的「输入保真」判据承担。
- **实证 D3 建模口径**：安全文明施工费在限价与报价中**同为 7,834.06 元**，
  投标人未改动 → 外生固定常量，进总价、不进 `X_opt`。
- **报价结构不是单一系数下浮**：加权总下浮 8.008%（0.919916），
  逐项下浮比呈明显分簇——0.810（标识牌 12 条）/ 0.833（补充编码绝缘工器具 10 条）/
  0.918（变压器与低压柜 13 条）/ 0.981–0.984（调试类几乎不下浮）。
  这一组聚类即模型要回答"是否最优"的对象。
- 编码实测：12 位 67 条 + 6 位 14 条，无 13/15 位；序号在分节内各自从 1 重算
  （安装工程 52 条 / 准备运行费 29 条），实证"不得用序号作主键"。

---

### 工程治理（2026-09-16）

#### 新增
- `docs/STATE.md` — **状态快照，自动生成**。含版本锚点、三闸门状态、制品冻结表、
  现场测试结果、任务进度、自动派生的下一步、遗留项汇总。
  由 `bidpricing status --write` 生成，头部标注"勿手改"。
- `docs/tasks.json` — 机器可读任务板，68 项任务。结构字段从路线文档派生，
  状态字段人工维护，二者互不污染。
- `docs/adr/` — 架构决策记录目录。新增 ADR-0002（判定时点与机制数据分层）、
  ADR-0003（状态快照自动派生）、ADR-0004（未定态必须是机器可判状态）。
- `tools/extract_tasks.py` — 路线文档 → 任务板的单向派生器，含 `--check` 校验模式。
- `bidpricing status` 子命令 — 支持 `--write` / `--json` / `--print-md`。
- 本文件 `CHANGELOG.md` 与 `docs/GOVERNANCE.md`。

#### 变更
- `docs/ADR-0001-three-layer-separation.md` → `docs/adr/` 目录（用 `git mv` 保留历史）。

#### 修正
- **消除三处文档漂移**（详见 ADR-0003）：`README.md` 的「Gate 0a 6/8」、
  `DEVELOPMENT.md` 的「89 项测试」、以及已被推翻的「真实清单=开工前置」表述。
  改为统一指向自动生成的 `STATE.md`。

---

## [classification-declaration-v1] — 2026-09-16

### 分类改为「声明 + 例外」；判据由《行数》改为《声明式就绪》

**背景**：用户 2026-09-16 提出两点，均成立——

1. 「如果没有特殊说明，分部分项清单里面的应都是可竞争项，所以为什么要做这个分类？」
   → 分部分项清单内**缺省即可竞争**，例外（`其中:暂估价` 列 / 甲供材）在清单里
   **是列**、机械可读，不需要人工逐行填表。原设计属**过度设计**。
2. 用户同时说明**实际可提供的资料**只有两份：招标限价清单（逐项只有单价、
   不超限价；另给一个项目总价限价金额）+ 成本清单（编码/名称/特征/单位一致，
   工程量不同、单价为成本价）。此前所有输入契约都是照**示例模板**推的，不是
   照用户实际能提供的资料推的——这是本轮 3 项 OI 的根因。

#### 变更
- `config/competitiveness_classification.json`（规则书）：新增
  `assignment_scope.defaults_and_exceptions`——逐张清单的**缺省角色**与
  **例外信号**（`role_defaults_by_list`）；`assignment_scope.answer` 改为区分
  「优化对象的主体」与「总价的完全划分」两件事；`assignment_protocol` 改为
  声明式（`artifact_shape` / `readiness_criterion` / `exception_row_fields` /
  `coverage_check_location`）。
- `config/project_classification_table.json`（项目级）：结构由 `rows[]`
  改为 `project_id` / `code_system` / `covered_lists` / `external_constants` /
  `exceptions` / `search_basis` + `field_semantics` 逐字段说明。
- `config/gate0_registry.json`：`phase_0` 规格改为
  `required_scalar_fields` / `required_list_fields` / `required_covered_list_fields` /
  `required_exception_row_fields` / `required_external_constant_fields`。
- `src/bidpricing/gates/gate0.py::_check_project_input`：**重写**为三层声明式判据。
  必需 key 缺失 → BLOCKED；**列表字段取 `[]` → PASS**（已核查、结论为空）；
  逐条校验缺省角色、例外行字段与角色、外部常量取值与依据。
- `docs/adr/ADR-0006-声明式就绪而非行数.md`。
- 文档同步：`README.md`、`DEVELOPMENT.md`、`src/bidpricing/paths.py`、
  `gate0.py` 模块说明、`cli.py` 的 gate-check 提示文案。

#### 修正
- `config/field_schema.json` → `item_id.note` 仍写「13/15 位编码体系由
  code_system 区分」——该口径早在 D1 裁定中删除，输入协议已明写「位数不参与
  合法性判定」。**同一份字段字典与输入协议对同一条规则说法相反**，已修正。
  （教训：删除一条口径时必须全仓搜索旧表述。）
- `config/field_schema.json` → `code_system.range` 原写 `GBT50500-2024`（无斜杠），
  而同一文件的 `rule_set_id.range` 写 `GB/T50500-2024`，且该字段的注释要求
  「与 rule_set_id 一致性校验」。**两个应当相等的枚举用了两种写法**，已统一。

#### 新增（待决问题登记）
- `config/input_protocol_schema.json` → `open_issues`：
  - `OI-01` 成本清单工程量与招标清单不一致 → **RESOLVED**：该量即预估结算量
    `q1`，输入 B 由输入 C 兼任；须补 `attribution` 归属标签。
  - `OI-02` 限价清单单价是 cap 还是 base → **RESOLVED**：仅最高限价，
    `base_i := cap_i`；连带 **δ⁺ 失效**（`U_i ≡ cap_i`）。
  - `OI-03` P* 由谁定 → **RESOLVED**：用户定总价，模型给最优单价结构，不扩范围。
  - `OI-04` **新增**：`C3` 合规下界 `L_i` 缺招标依据（招标文件不设单价下限），
    `δ⁻` 取值来源未定 → PENDING_USER_DECISION。

#### 制品重新冻结
| 制品 | 旧 hash | 新 hash |
|---|---|---|
| `field_schema_version` | `sha256:858b0c997f85` | `sha256:7837eac655a6` |
| `competitiveness_classification` | `sha256:5610c8d879dd` | `sha256:2913378715d5` |
| `input_protocol_schema` | `sha256:92c3edea3d46` | `sha256:d6a26c25f5aa` |

#### 测试
- 155 → **165** 项（`ProjectInputArtifactTest` 由 6 项重写为 15 项，含
  `test_missing_exceptions_key_blocks_while_empty_list_passes` 这一**反向断言**：
  同一 payload，`[]` → PASS，删 key → BLOCKED）。
- Gate 0a 仍 **PASS 8/8**；Phase 0 输入门仍 BLOCKED（现为「声明未就位」而不再是「表为空」）。

> 里程碑索引见文末。

---

## [classification-split-v1] — 2026-09-16

> 修正 commit `a17e07c`：`fix(t00-06): 分类表拆为机制层/数据层 —— 真实清单不再是开工前置`

### 修正
- **T00-06 拆分**（用户质疑"为什么需要真实清单"）：
  - `config/competitiveness_classification.json` 收敛为**规则书**（角色集合 + 启发式 + 覆盖范围
    + 外生常量），删除 `classification_table` 与 `freeze_blocker`；
  - 新增 `config/project_classification_table.json` 作为**项目级落值表**（数据侧）；
  - 注册表新增 `phase_0` 段；`gate0.check_project_input_artifacts` 校验文件存在 → 行非空
    → 逐行字段与 `pricing_role` 合法；**注册表未声明时判 BLOCKED，不允许空真通过**。
- 分类表覆盖范围明确为**分部分项 + 表-09 + 表-10 + 表-11 四类清单**
  （非"选一套做基准"）：只取分部分项会丢失表-09 的可竞价空间与表-10 的唯一
  `NON_COMPETITIVE` 实例。

### 结果
- **Gate 0a = PASS（8/8）**，放行 WP1 / WP2 / WP3。
- Phase 0 输入门 = BLOCKED（`adjustment_scope`、`project_classification_table`）。
- 测试 98 项全通过。

---

## [options-phase-split-v1] — 2026-09-16

> 修正 commit `315f53d`：`fix(gate): 选择项判定时点后移 —— 机制就绪与取值已定拆为两个时点`

### 修正
- **`adjustment_scope` 判定时点后移**（用户质疑"为何一定要现在确定"）：
  `check_selectable_option` 增加 `phase` 参数，拆开两类判定：
  - `phase="gate_0a"` → 只判**机制就绪**，取值未定 **PASS**；
  - `phase="phase_0"` → 判**取值**，未定 **BLOCKED**。
- 新增 `check_phase0_inputs` —— §7.1.1 断言 2「Phase 0 直接 BLOCKED」的正确落点
  （早前误挂在 `check_gate_0a` 上）。
- 配置冲突（2013 落 `FULL`）在**两个时点下都 BLOCKED**，不因时点放行。

### 变更（回应实测偏差 D1/D2/D3）
- `input_protocol_schema.json`：**删除「13 位 / 15 位」编码位数对应关系**，
  改为 `code_identity_policy` —— 位数不参与合法性判定，唯一键含 `unit_work`。
- `competitiveness_classification.json`：新增 `external_constants` ——
  安全文明施工费 = 投标期**外生常量**（删除结算期「人工费 + 机械费」基数口径）；
  规费 / 税金 = 外生输入，模型不复算。

### 结果
- Gate 0a 从 `BLOCKED 6/8` → `BLOCKED 7/8`（仅剩分类表）。
- 测试 90 项全通过。

---

## [options-adjustment-scope-v1] — 2026-09-16

> 实现 commit `5b35aa3`：`feat(wp0): adjustment_scope 升级为项目级选择项`

### 新增
- `src/bidpricing/selection_options.py` — 选择项机制：`default` 恒为 `None`，
  取值集合**按规则集而变**，落值带 `source/actor/selected_at/rationale` 依据快照。
- `src/bidpricing/contracts/scope_impact.py` — `scope-impact` 命令，
  量化 `FULL`/`SEGMENT` 在**规则层**的结算分叉。
- `config/project_selection.json` — 落值通道（未选择 = 不写 `value` 字段）。

### 变更
- `adjustment_scope` 从「一次性裁决常量」升级为「项目级选择项」。

### 已知限制（实测发现）
- **选择 `SEGMENT` 会使 T00-07/08 数值指纹退化**：此时 2024 与 2013 的跳变量同为 `≈0`
  （实测 `1.99e-9`），指纹失去鉴别力。区分依据退回条款覆盖 + 代码路径独立实现。
  已登记为遗留项，由 `ruleset-selftest` 显式输出。

---

## [contracts-wp0-v1] — 2026-09-16

> 实现 commits：`833003e`（契约冻结与闸门）、`c0a82c7`（状态板去 emoji）

### 新增
- 建立 `bid-pricing/` 代码仓库，**零第三方依赖**（JSON 配置 + stdlib `unittest`）。
- `src/bidpricing/artifact.py` — §7.1.1 断言 4 制品元数据机制（`_version`/`_hash`/
  `_frozen_at` + 占位符黑名单 + `freeze_blocker` 拒绝冻结）。
- `src/bidpricing/states.py` — §5 全局四态状态机 `PASS/WARN/FAIL/BLOCKED`。
- `src/bidpricing/contracts/` — 规则集抽象接口 + 2013/2024 两版**独立实现** + 选择器 + 指纹自检。
- `src/bidpricing/gates/gate0.py` — §7.1.1 六条死锁断言的**可执行实现**。
- `src/bidpricing/cli.py` — `gate-check` / `ruleset-select` / `ruleset-selftest` / `freeze`。
- `config/` — 7 项 Gate 0a 受控制品 + 注册表。

### 结果
- Gate 0a = BLOCKED 6/8；Gate 0b = BLOCKED。测试 55 项全通过。

---

## 里程碑索引

| tag | 日期 | 一句话 |
|---|---|---|
| `contracts-wp0-v1` | 2026-09-16 | WP0 契约冻结 + Gate 0 机械门禁落地 |
| `options-adjustment-scope-v1` | 2026-09-16 | `adjustment_scope` 升级为项目级选择项 |
| `options-phase-split-v1` | 2026-09-16 | 选择项判定时点后移（机制 / 取值分离） |
| `classification-split-v1` | 2026-09-16 | 分类表拆为规则书 / 项目落值表 |
| `project-governance-v1` | 2026-09-16 | 状态快照自动派生 + 任务板 + ADR 目录 |
| `classification-declaration-v1` | 2026-09-16 | 分类改为「声明 + 例外」；判据由行数改为声明式就绪 |
