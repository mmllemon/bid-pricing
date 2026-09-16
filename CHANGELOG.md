# 变更日志

本文件记录**里程碑级**变更。逐次提交请用 `git log`；本文件回答的是
「相比上一次里程碑，项目发生了什么变化」。

**格式约定**：每个里程碑对应一个 git tag，tag 名形如 `<主题>-v<N>`。
条目分类：`新增` / `变更` / `修正` / `移除` / `安全`。

---

## [未发布]

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
