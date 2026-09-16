# bid-pricing

**投标报价利润最大化测算模型 —— 实施路线 v3.2.1 的执行代码库**

本仓库是《投标报价模型 v0.3 实施路线与任务清单 v3.2.1》（68 任务 / 8 闸门）的代码落地。
首个开发增量聚焦 **WP0 模型契约冻结**与**闸门机械判据**——因为按路线自身的死锁断言，
WP1/WP2/WP3 的开工被 Gate 0a 门禁，而 Gate 0a 的起点是 T00-08（唯一无前置依赖的任务）。

## 快速开始

无需安装，标准库即可运行：

```bash
# 全量测试
PYTHONPATH=src python -m unittest discover -s tests -t . -v

# 规则集指纹自检（T00-07/T00-08 机械判据）
PYTHONPATH=src python -m bidpricing.cli ruleset-selftest

# 冻结契约制品（写入 version / hash / frozen_at 三字段）
PYTHONPATH=src python -m bidpricing.cli freeze --all

# 执行 Gate 0 全部机械判据
PYTHONPATH=src python -m bidpricing.cli gate-check --contract-date 2026-03-01

# 查看规则集选择过程（含判定链留痕）
PYTHONPATH=src python -m bidpricing.cli ruleset-select --contract-date 2026-03-01
```

或在仓库根目录执行 `pip install -e .` 后直接使用 `bidpricing` 命令。

## 目录结构

```
config/                                 机器可读契约制品（人可编辑）
  gate0_registry.json                   Gate 0a/0b 受控制品注册表（含 version/hash/frozen_at）
  field_schema.json                     T00-02 字段字典 v1
  constraint_schema.json                T00-03 约束字典 C1–C12
  precision_profile.json                T00-04 精度与容差策略表
  architecture_decision.json            T00-05 三层分割架构地位（ADR-0001）
  ruleset_selector_spec.json            T00-08 规则集选择器规格
  input_protocol_schema.json            T01-00A 输入协议 Schema
  competitiveness_classification.json   T00-06 可竞争性分类**规则书**（机制层，跨项目复用）
  project_classification_table.json     T00-06 分类**声明**（数据层，一项目一份：缺省角色 + 例外）
  project_selection.json                项目级选择项落值（adjustment_scope 等；未选 = 不写 value）
src/bidpricing/
  states.py                             §5 全局四态状态机 PASS/WARN/FAIL/BLOCKED
  artifact.py                           §7.1.1 断言 4 制品元数据机制（hash + 占位符黑名单）
  paths.py                              路径解析
  contracts/
    selector.py                         T00-08 规则集选择器 + 指纹自检
    rule_sets/base.py                   RuleSet 抽象接口（不含任何调价公式）
    rule_sets/gb50500_2013.py           GB 50500-2013 独立实现（分段累加）
    rule_sets/gbt50500_2024.py          GB/T 50500-2024 独立实现（调整单价本身）
  gates/gate0.py                        §7.1 + §7.1.1 六条死锁断言的可执行实现
  status.py                             状态快照派生（git / 闸门 / 制品 / 测试 / 任务板）
  cli.py                                命令行入口
tests/                                  单元测试（数量以 `bidpricing status` 输出为准）
tools/extract_tasks.py                  路线文档 → docs/tasks.json 单向派生器（含 --check）
docs/
  STATE.md                              **状态快照（自动生成，勿手改）** —— 跨会话交接入口
  tasks.json                            机器可读任务板（68 项；结构派生 + 状态人工）
  GOVERNANCE.md                         记录体系与跨会话延续机制
  adr/ADR-0001-three-layer-separation.md      三层分割架构
  adr/ADR-0002-判定时点与机制数据分层.md      判定时点对齐（两次踩坑的结论）
  adr/ADR-0003-状态快照自动派生.md            为什么文档不能手写状态
  adr/ADR-0004-未定态必须是机器可判状态.md    未定态表示法与制品冻结
CHANGELOG.md                            里程碑变更历史
DEVELOPMENT.md                          早期任务状态板（内容已并入 STATE.md，保留作沿革）
```

## 两条设计原则

**1. 契约制品先冻结，再开发。** `config/` 下的受控制品，其
`version` / `hash` / `frozen_at` 三字段由 `freeze` 命令写入，值等于制品内容的
SHA-256 前 12 位。制品一改，hash 失配，Gate 立即失效——无需人工记忆。
制品若自声明 `freeze_blocker`（尚不完整），冻结器**拒绝**写 hash。

**2. 闸门是代码，不是约定。** 路线 §7.1.1 的六条死锁断言全部实现为可执行判据，
包括「未定态必须是 key 缺失而非 `"未定"` 字符串」「配置层零默认值静态扫描」
「Gate 0b 未通过时 WP4 禁止构建」等。CI 与本地 `gate-check` 共用同一套判据。

## 一条贯穿全局的设计规则：判定时点必须与消耗时点对齐

同一个「未就绪」，放在错误的时点就会**用晚期决策卡住早期开发**。本项目
把两类东西严格拆开（两者都在 `config/` 里，但判定归属不同）：

| | 属 Gate 0a（开发开工前） | 属 Phase 0 输入门（求解启动前） |
|---|---|---|
| 性质 | **机制** —— 跨项目复用：规则集、字段字典、分类规则书、两套分支的实现要求 | **数据/取值** —— 一项目一份：`adjustment_scope` 的取值、项目级分类声明 |
| 未就绪 | BLOCKED（技术接口没冻结，代码不该写） | BLOCKED（但**不阻塞** WP1/WP2/WP3，只挡求解） |
| 典型错误 | 把「还没选作用域」当成开工阻塞 —— 而契约恰恰要求两条分支都实现 | 把某个项目的清单数据当成机制完备的前提 |

**配置冲突**（如 2013 规则集下落值 `FULL`）在两个时点下都 BLOCKED，不因时点放行。

## 当前状态

**不要在本文件里找状态数字。** 状态一律以自动生成的
[`docs/STATE.md`](docs/STATE.md) 为准——手写在文档里的数字必然会过期，
本项目已为此付出三次代价（见 [ADR-0003](docs/adr/ADR-0003-状态快照自动派生.md)）。

```bash
# 生成 / 刷新状态快照
PYTHONPATH=src python -m bidpricing.cli status --write

# 只看关键行（不写盘）
PYTHONPATH=src python -m bidpricing.cli status

# 机器可读
PYTHONPATH=src python -m bidpricing.cli status --json
```

快照内容：版本锚点（git commit / tag / 工作区状态）、三个闸门的状态与阻塞项、
契约制品冻结表（hash）、现场测试结果、68 项任务的进度与**证据核对**、
自动派生的下一步任务、遗留项汇总。

### 三个闸门的分工（结构说明，非状态）

| 闸门 | 判什么 | 未通过时阻挡 |
|---|---|---|
| **Gate 0a** | 机制：规则集、字段字典、分类规则书是否冻结 | WP1/WP2/WP3 开发 |
| **Phase 0 输入门** | 取值/数据：`adjustment_scope` 取值、项目级分类声明 | **仅**求解启动 |
| **Gate 0b** | 商务口径与合规：成本口径、假设声明书、桥接表 | WP4 求解层 |

## 跨会话延续机制

这是一个需要长期开发维护的项目，**仅靠对话上下文记忆是不够的**。
本项目采用六层记录体系，并把状态快照做成**生成物**而非著作物：

| 层 | 文件 | 作用 |
|---|---|---|
| 事实 | `config/`、`src/` | 系统当前是什么（唯一事实源） |
| 意图 | `docs/tasks.json` | 68 项任务的状态与证据 |
| 决策 | `docs/adr/` | **为什么**这么做、否决了什么 |
| 变更 | `CHANGELOG.md`、git tag | 什么时候变了什么 |
| 快照 | `docs/STATE.md` | **自动生成**，现在到哪了 |
| 交接 | `.workbuddy/memory/*.md` | 会话级流水 |

**接手者必做**：读 `docs/STATE.md` → 复算一次 → 读 `docs/adr/`。
**离场者必做**：提交 → `status --write` → 追加日志。

完整协议、变更同步义务矩阵与校验闭环见
[`docs/GOVERNANCE.md`](docs/GOVERNANCE.md)。

