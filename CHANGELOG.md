# 变更日志

本文件记录**里程碑级**变更。逐次提交请用 `git log`；本文件回答的是
「相比上一次里程碑，项目发生了什么变化」。

**格式约定**：每个里程碑对应一个 git tag，tag 名形如 `<主题>-v<N>`。
条目分类：`新增` / `变更` / `修正` / `移除` / `安全`。

---

## [未发布]

### T00-04 / T00-03 / T00-06 结清 + T04-02A 完成：LP 模型形式化

- `config/precision_profile.json`：`equality_tolerance_mode.current = "A"`
  （内部严格等式 + 输出层独立舍入调和）。三条机械判据：D1（决定性，与 benchmark
  无关）模式 B 使内外层判据同宽 ⇒ 复核层退化为内层判据的复制；D2 容差带
  R1 = eps_solver/HiGHS 默认容差 = 0.1 < 1 ⇒ 无任何放宽收益；D3 benchmark_status
  = NOT_RUN ⇒ 未证收益不得交换已证语义性质。含 `reopen_condition`（D1 不可交易）。
  冻结 hash → `sha256:146e8e6ffbc4`。
- **T00-03 / T00-04 / T00-06 三个前置任务结清**（制品早已就绪，状态漂移系任务板
  未跟进），T04-02A 依赖解封。
- `config/lp_formulation_spec.json`：变量/非变量/参数/索引集/目标/C1–C13 逐条
  映射/箱型预处理/求解器形态/F 判据 11 条/消费者/挂账。**核心结论**：目标对 `p`
  严格线性（`r_eff` 全外生 ⇒ P1 分支建模期已知）⇒ LP 成立，MILP 唯一来源是 C7
  的二元变量；`∂R/∂p = q0·r_eff` 与 `∂Z/∂p = q1·r_eff` 是两个不同的量。
- `src/bidpricing/solver/formulation.py`：把实例编译为求解器无关的 LP 词汇
  （**只形式化、不建模**——建模是 T04-02B，后端是 T04-02C）。新增本地状态域
  **SKIP**：缺实例时「没检查」必须与「检查过且通过」可区分。
- **三条约束改变位置**：C5 的 LP 下界抬到报价分辨率（否则 P*=1e6 时解为 1e-3 元，
  舍入成 0.00 ⇒ 提交的报价违反 C5）；C12 在可行域上是常量 ⇒ 作 `P*` 的前置
  可接受性判据而非 LP 约束；C11 的 MAD/σ 替换方向相反 ⇒ 挂账给 T04-02B。
- CLI `formulate-check`：LP 与 MILP 两变体各 11 条判据，**22/22 PASS**。

#### 修正

- `settlement_revenue` 的区间内分支漏了作用域判断：`SEGMENT ∧ alpha≠0` 时它返回
  含 `(1+alpha)` 的收入，而 `compute_r_eff` 返回 `r` ⇒ 相差 `(1+alpha)` 倍。按
  §5.3.1（alpha 只作用于 FULL）后者为错。`alpha = 0` 时完全不可见。
- `status.check_evidence` 第三处缺口：phase_0 的项目级输入
  （`project_classification_table`）本就不做版本冻结，按「hash 已冻结」判会永远
  不成立 ⇒ 改用「文件存在」，与 Phase 0 输入门的「声明式就绪」同向。
- 判据自身的一处反向风险：F-02 首版借道 `instance.r_eff`，被实例 `Phase1Params`
  覆盖了传入的 scope，**自己制造出假 FAIL**。据此确立原则：**判据的覆盖面不得
  取决于被测数据**（F-02 自扫 FULL/SEGMENT，不沿用实例 scope）。

### T04-00 完成：Phase 1 精确性条件与反例集（WP4 求解层第一块）

- `config/phase1_exactness_spec.json`：九条条件 `EC-1..EC-9` + 九个反例
  `CE-01..CE-09` + 一个正例 `PE-01`。每条条件含形式化命题、机械判据、
  违反后果与对应反例；每个反例含「误用解 vs 正确解」的数值见证。
- `src/bidpricing/solver/`：`instance`（Phase 1 论域与解校验）、
  `exactness`（EC 判定器）、`cases`（反例集机械复算器）。
- CLI `phase1-check`：跑制品里的全部实例，把 `expected` 与 `witness.assertions`
  逐条喂给实现——**制品与实现的双向锁定**。
- **证明路径**：定理 T1（阈值分割）用**交换论证**证明，不走 KKT。
  KKT 是 T04-02A/D 的实现路线，两者共用会让证明与实现按同一个误解同时成立，
  T04-08 的独立性验收即失去对象。
- **条件分两组**：A 组（EC-1..EC-7）违反 ⇒ 阈值分割解不是 P_A 最优解；
  B 组（EC-8 舍入可调和 / EC-9 上界有限）违反 ⇒ 只加实现性义务。
  `verdict` **只看 A 组**——首版把 EC-8 归 A 组的结果是任何实例都判不出
  `EXACT`（舍入上界 `0.005·Σq0` 几乎总超 `eps_total`）。
- **本项目真实结论**：EC-9 对西永L样本判 WARN（存在不限价项
  `031301017001`），故 Phase 1 算法**必须内建「空 cap 项固定为临界项」分支**，
  不得依赖「所有项都有 cap」这一假前提。
- 修正 `compute_r_eff` 的 SEGMENT 分支：`increase_threshold` 本身已是
  `(1 + θ_dev)`，原式再加 `1.0` 使越界段 `r_eff` 被系统性高估
  （例 2R 的 r=1.6 处算成 2.04 而非 1.24）。附录 B 例 2R 的期望值用例抓到。
- 新增 `compute_r_eff` / `settlement_revenue` 于 `contracts/pricing_card.py`
  作为**唯一实现**，测试用 `compute_p1` 逐值交叉锁定，防止出现第二事实源。
- 测试 477 → **527** 项；`phase1-check` 10/10 一致；contract-check 17/17；闸门全 PASS。
- **发现（既存，未修）**：`tools/extract_tasks.py --check` 长期报「任务板已过期」——
  `tasks.json` 中多个任务的 `evidence` 多于脚本内 `EVIDENCE` 字典（历史上手改过
  派生物）。本轮已把 T04-00 的证据写进 `EVIDENCE` 单一来源，其余任务的对齐
  需重跑 `extract_tasks.py`（会重写结构字段，属破坏性操作，待确认）。

## [boq-parser-v1] — 2026-09-16

### T01-00B 完成：清单解析器（WP1 第一块落地）

- `src/bidpricing/io/xlsx.py`：零依赖 xlsx 读取器（zip + XML，stdlib only）。
- `src/bidpricing/io/boq.py`：解析器。表号 → 角色识别；「逻辑字段 → 别名集合」
  双键列识别（命中 0 或 ≥2 即失败，**不猜**）；双行表头合并（综合单价/合价/
  暂估价在子表头行）；分节标题行四信号合取判据（编码列放分节名 C/B.3/一 +
  工程量/单价/单位/特征全空）；空值口径（空值 ≠ 缺行）；复合主键
  (project_id, unit_work, item_id)；code_kind 三分类、位数不判合法性。
- CLI `parse-boq`：三项产出（解析日志 JSON / 字段映射报告 md / 失败样本 csv）
  落盘 `docs/parsed/<文件名>/`。
- 真实配对样本实测：82 行、0 失败、键集合两侧一致；加权下浮 **8.0084%** 与
  已固化 pair.json **独立复算一致**（交叉印证）；确认已知数据缺口
  `031301017001 脚手架搭拆`（限价侧综合单价为空、报价侧 1370.75）。
- 新增 contract-check 第 11 项判据 `io.column_aliases_mirror`：代码侧别名表
  与契约 `listing_structure.column_aliases` **逐字一致**——两处独立存在即有
  漂移风险，解析器实际按代码侧工作。
- 测试 192 → **211**（+19）；Gate 0a 仍 PASS。

---

## [bound-clauses-v1] — 2026-09-16

### 单项下界的两类真实依据；输入 A 结构按真实文件固化

**背景**：用户指出两件事，都成立——

1. 用户实际提供的限价清单**就是**那份真实文件的结构（只是清单项与数据会不同）。
   此前所有输入口径都是照 3 份**示例模板**推的，而那些示例是**结算期**的表格。
2. 记录者把用户「只会限制①各项单价②整个项目总价」外推成了
   「用户明确：**没有给出单价下限**」。用户否认：原意是**有最高限价**，
   且**单项报价不能为 0**，且**有时有不平衡报价条款（如 ±50%）**。

#### 修正（本里程碑最重要的一条）
- `input_protocol_schema.open_issues[OI-04]` 重写，并**永久保留纠正留痕**：
  `correction.what_was_wrong` / `user_actual_words` / `failure_mode`。
  撤销的旧结论不删除——它解释了为什么 C3 曾经按 `δ⁻` 单来源设计。
- 新增 `docs/adr/ADR-0007-沉默不是断言.md`：把「用户未提及」记成「用户已声明为无」
  是一类结构性失效，与 ADR-0004（未定态 = key 完全缺失）同源——
  那条管机器，本条管人。

#### 变更 — 输入 A 结构固化
- `input_protocol_schema.listing_structure`（新增）：按真实文件固化
  6 张表（表-04 / 表-09 分部分项 / 表-09 技术措施 / 表-10 组织措施 / 表-11 其他 / 表-12 规费税金）、
  双行表头、**列名别名表**、分节标题行、单位工程维度、空值口径、总价限价位置。
  **关键修正**：真实限价清单单价列名是「**综合单价**」，而示例模板是「**最高限价**」
  → **禁止硬编码列名**，必须走「表号 + 别名集合」双键识别。
- 新增口径 **空值 ≠ 缺列/缺行**：限价侧普遍「列在、行在、值空」
  （合价列存在但为空、合计行存在但为空）。与 ADR-0006 同源。

#### 变更 — 约束层
- `constraint_schema.C3` **重定义**：由 `p_i >= base_i(1-δ⁻)` 单一来源
  改为**多来源取大**。δ⁻ 只在招标文件明示幅度时参与，否则不得编造；
  δ⁻ 取 0 会把报价钉死在限价上，是荒谬解。
- `constraint_schema.C5` **由 P1 升为 P0 且不可关**：语义由「非负性（求解器保险）」
  改为「**单项报价不得为零**」——用户明确这是招标条款，`p_i = 0` 算术上满足
  `p_i >= 0` 却直接违反招标文件。
- `constraint_schema.C13`（**新增**）：不平衡报价幅度约束（条件性）。
  声明 **4 条机制分支**（`BID_VALIDITY` / `SETTLEMENT_ADJUSTMENT` / `SCORING` / `NONE`）——
  前者是 `X_opt` 硬约束，中者是 `R_i(·)` 的改造而**不约束** `X_opt`，二者落点完全不同。
  机制进 Gate 0a（两分支都要实装），取值属 Phase 0。
- `constraint_schema.C4` 注释更新：显式声明它引用的是**重定义后**的 C3。

#### 新增 — 字段
- `field_schema` 新增 5 字段：`zero_price_prohibited`、`unbalanced_clause`（整块声明）、
  `unbalanced_reference`、`unbalanced_tolerance`、`unbalanced_mechanism`。
  全部 `missing_policy=BLOCK` 且**无默认值**。

#### 新增 — 第四条验证环 `contract-check`
- `src/bidpricing/contracts/consistency.py` — **跨制品一致性判据**（10 项）。
  与 `gate-check` 正交：后者判「制品是否被改动」，本判据判「制品彼此是否自洽」。
  一份**未被改动**的制品集照样可以自相矛盾——本项目已实测两次，两次都靠人眼发现：
  ① `field_schema` 写「13/15 位体系」而 `input_protocol_schema` 写「位数不参与判定」；
  ② `code_system.range` 与 `rule_set_id.range` 两个**本应相等**的枚举两种写法。
- 核心判据 `constraint_schema.inputs_declared`：约束引用的每个输入必须已在
  字段字典中声明（拦截「新增约束忘了加字段」）。
- 判据 `field_schema.enum_agreement` **必须比对原始字符串，不得先归一化**——
  归一化会把事故里的两种写法折叠成同一个值，等于判据自我取消。
- **反向断言**：`test_historical_code_system_spelling_bug_blocks` 精确复现事故写法，
  锁住该判据不得退化为归一化比对。
- `bidpricing contract-check` 子命令；`README` / `GOVERNANCE` 同步（三环 → 四环）。

#### 清理
- `tools/xlsx_dump.py` / `tools/xlsx_compact.py` — 零依赖 xlsx 读取器
  （本机无 openpyxl / pandas；xlsx 即 zip + XML，直接解析即可）。
- `cli.py` gate-check 的提示文案改为**只针对实际阻塞项**输出——
  原先 `adjustment_scope` 已落值却仍打印「选择项取值未定」，指向一个不存在的动作
  （与 `d3f358e` 修的是同一类毛病）。

#### 制品重新冻结
| 制品 | 旧 hash | 新 hash |
|---|---|---|
| `field_schema_version` | `sha256:7837eac655a6` | `sha256:26b940c21e0b` |
| `constraint_schema_version` | `sha256:9…` | `sha256:ebed21c439e8` |
| `input_protocol_schema` | `sha256:d6a26c25f5aa` | `sha256:41dc4f1bbd6e` |
| `rule_set_selector_spec` | `sha256:0dd335b5a8ae` | 不变 |
| `precision_profile_version` | `sha256:6ce483e8d221` | 不变 |
| `architecture_decision_version` | `sha256:3601adeed46c` | 不变 |
| `competitiveness_classification` | `sha256:2913378715d5` | 不变 |

#### 测试
- 165 → **192** 项（新增 `tests/test_contract_consistency.py` 25 项 + `test_status.py` 2 项）。
- `src/bidpricing/status.py` 采集并渲染跨制品一致性——**状态数字一律不手写**，
  快照里的「10/10」是复算出来的，不是抄的。
- Gate 0a 仍 **PASS 8/8**；`contract-check` **PASS 10/10**；
  Phase 0 输入门仍 BLOCKED（仅 `project_classification_table`）。

#### 待用户裁定（新增 OI-05）
- 「±50%」的**基准**是什么（cap / 控制价 / 评标基准价 / 成本占比）？
  若基准 = cap，则上浮侧与 C2 矛盾，条款实际只约束下浮侧。
- 超幅的**后果**是投标有效性问题，还是结算调整条款？
- 该条款在什么条件下出现（逐项目 / 金额门槛 / 计价方式）？

#### 同时发现的待确认项
- **总价限价不在限价清单文件内**：实测该文件表-04「投标报价合计 8,623.74」
  只等于措施 7,834.06 + 税金 789.68（分部分项为空），而单项就有 176,068.11 的变压器
  ——它绝不可能是总价限价。`P*_max` 须由用户**另行提供**，不得外推。

---

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
| `bound-clauses-v1` | 2026-09-16 | 单项下界的两类真实依据（不得为零 / 不平衡条款）；输入 A 结构按真实文件固化；新增 `contract-check` 第四环 |
