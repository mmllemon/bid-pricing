# 项目治理与跨会话延续机制

本文件回答一个问题：**这是一个要开发数月、会换人（或换 AI 会话）接手、
需要长期维护迭代的项目。凭什么保证下一个人能准确知道「已经做了什么、为什么这么做」？**

答案不是"把文档写详细"，而是**把记录成本从人身上转移到工具身上**——
因为本项目已经用三次事故证明了"要求人记得同步文档"这个约定不成立（见 ADR-0003）。

---

## 一、六层记录体系

不同性质的信息放在不同层，**各层有自己的权威源与更新时机**。
把六种信息混在一个文件里，是漂移的起点。

| 层 | 文件 | 写入者 | 记录什么 | 权威性 |
|---|---|---|---|---|
| **L1 事实** | `config/*.json`、`src/**` | 开发时改 | 系统当前是什么 | 唯一事实源 |
| **L2 意图** | `docs/tasks.json` | `tools/extract_tasks.py` + 人工补状态 | 68 个任务的状态与证据 | 结构派生、状态人工 |
| **L3 决策** | `docs/adr/ADR-*.md` | 做不可逆决策时 | **为什么**这么做、否决了什么 | 不可变，追加式 |
| **L4 变更** | `CHANGELOG.md`、git tag | 达里程碑时 | 什么时候变了什么 | 追加式 |
| **L5 快照** | `docs/STATE.md` | **脚本自动生成** | 现在到哪了 | **生成物，勿手改** |
| **L6 交接** | `.workbuddy/memory/YYYY-MM-DD.md` | 每次会话结束 | 本次做了什么、踩了什么坑 | 流水，不承载权威结论 |

**关键设计**：L5 是**生成物**。它把 L1（代码/配置）、L2（任务板）、git（变更历史）
现场汇总成一份人类可读的快照。因此**快照永远不会与代码漂移**——
这条性质是整套机制的地基。

**为什么 L3 与 L5 必须分开**：L5 回答"现在在哪"（会变），L3 回答"为什么在这条路上"（不变）。
决策记录如果混进状态快照，每次重新生成就会丢掉推理过程，
下一个人只会看到结论而无法判断该结论是否仍适用。

---

## 二、新会话开工协议（接手者必做）

接手一个已开发一段时间的项目时，**按顺序**执行：

```bash
cd bid-pricing

# 1. 读状态快照（30 秒了解全貌：在哪、卡在哪、下一步是什么）
cat docs/STATE.md

# 2. 复算快照（不要相信任何未复算过的数字，包括快照本身）
PYTHONPATH=src python -m bidpricing.cli status
PYTHONPATH=src python -m bidpricing.cli gate-check --contract-date 2026-03-01
PYTHONPATH=src python -m unittest discover -s tests

# 3. 读决策记录（了解为什么走到这里、有哪些路已被否决）
ls docs/adr/ && grep -l "反面清单\|不得" docs/adr/*.md

# 4. 读最近交接日志（了解上一轮踩了什么坑）
ls -t ../.workbuddy/memory/*.md | head -3
```

**第 2 步不可跳过。** `STATE.md` 是生成物，但生成物可能来自旧提交
（例如快照生成后又提交了新代码）。复算一次即可确认当前真实状态。
若复算结果与 `STATE.md` 不一致，**以复算为准，并立即重新生成快照**。

### 必须优先读的三份文件

| 文件 | 回答的问题 |
|---|---|
| `docs/STATE.md` | 现在在哪？下一步能做什么？ |
| `docs/adr/ADR-0002-*.md` | 判据该挂哪个闸门？（**已两次踩坑**的地方） |
| `docs/adr/ADR-0003-*.md` | 为什么文档不能手工写状态？ |

---

## 三、会话结束协议（离场者必做）

每次实质性工作结束后，**至少**完成前两项：

| # | 动作 | 命令 |
|---|---|---|
| 1 | 提交代码并**打里程碑标签**（达里程碑时） | `git commit` + `git tag -a <主题>-v<N>` |
| 2 | **重新生成状态快照**并提交 | `PYTHONPATH=src python -m bidpricing.cli status --write` |
| 3 | 追加当日工作日志 | 写 `.workbuddy/memory/YYYY-MM-DD.md` |
| 4 | 做了不可逆决策 → 补 ADR | 新建 `docs/adr/ADR-000N-*.md` |
| 5 | 更新 `CHANGELOG.md`（达里程碑时） | — |

**第 2 项是这套机制的核心闭环。** 只要每次会话结束都重新生成快照，
下一个会话读到的 `STATE.md` 就必然反映最新状态——**没有任何人需要记得手动更新任何数字**。

---

## 四、变更同步义务矩阵

改动某一类文件时，**必须**同步的关联项。这是防漂移的操作手册：

| 改了什么 | 必须同步 | 为什么 |
|---|---|---|
| `config/*.json`（受控制品） | `bidpricing freeze --all` → `gate-check` → `contract-check` | hash 失配会让闸门失效；**且改动会让制品间产生新的不一致**（例如新增约束引用了字典里还没有的字段） |
| `config/project_classification_table.json` | `status --write` | 影响 Phase 0 输入门判据 |
| `src/**` | 跑全量测试 → `status --write` | 测试数是快照的一部分 |
| 新增/删除受控制品 | 更新 `config/gate0_registry.json` | 未声明的制品不会被校验；**注册表未声明时判 BLOCKED** |
| 路线文档（`impl_plan_v3*.md`）升版 | `python tools/extract_tasks.py` | 结构派生源变了，任务板必须重提取（CI 有 `--check` 兜底） |
| 完成某任务 | 在 `docs/tasks.json` 补 `status` / `note` / `evidence` | 让状态可被下一个人复核 |
| 做出不可逆技术决策 | 新建 ADR | 否则下一个人只会看到结论，无法判断是否仍适用 |
| 达里程碑 | `git tag` + 更新 `CHANGELOG.md` | 提供"回到某个已知状态"的锚点 |

---

## 五、规范

### 提交信息

```
<type>(<scope>): <主题>

<body：问题是什么、为什么这样改、实测结果>
```

- `type`：`feat` / `fix` / `docs` / `test` / `refactor` / `chore`
- `scope`：任务号（`t00-06`）或模块名（`gate` / `status` / `wp0`）

**body 必须写「问题是什么」**。本项目的 commit `315f53d` 与 `a17e07c` 都在 body 里
记录了用户质疑的原文与两次错误的同型性——这类信息在半年后比 diff 本身更有价值。

### 里程碑标签

`<主题>-v<N>`，例如 `options-phase-split-v1`、`classification-split-v1`。

**触发条件**（满足其一即打）：
1. 一个闸门的状态发生变化（BLOCKED → PASS）；
2. 产生一个 ADR 级决策；
3. 一个工作包（WP）完成。

### ADR

`docs/adr/ADR-000N-<中文短标题>.md`，编号不复用、不删除。
必含五段：**背景 / 决策 / 理由 / 后果 / 相关判据**。
已否决的替代方案写进「理由」或「反面清单」。

### 状态标记

统一用文字，不用 emoji（PDF 字体缺字形，已实测）：

| 标记 | 含义 |
|---|---|
| `done` | 已完成，且证据核对成立 |
| `partial` | 机制就绪，项目级数据未填 |
| `ready` | 依赖已满足，可立即开工 |
| `not_started` | 未开工 |
| `blocked` | 被闸门拦下 |

---

## 六、校验闭环

机制要闭环才有意义。"派生"没有校验，只是更省事的誊抄。当前闭环有三环：

| 环 | 命令 | 拦下什么 |
|---|---|---|
| 结构漂移 | `python tools/extract_tasks.py --check` | 路线文档改了但任务板未重提取 |
| 契约漂移 | `bidpricing gate-check` | 制品被改但未重新冻结（hash 失配） |
| **制品间矛盾** | `bidpricing contract-check` | **两份已冻结制品对同一规则说法相反**（hash 全部匹配、闸门全绿，但互相打架） |
| 状态漂移 | `bidpricing status`（复算） | 快照与代码实际不一致 |

**第四环（`contract-check`）与前三环正交，不是它的加强版。** `gate-check` 判的是
「制品是否被改动过」（hash 对不对），`contract-check` 判的是「制品彼此是否自洽」。
一份**未被改动**的制品集照样可以自相矛盾——本项目已实测两次：

- `field_schema.item_id.note` 写「13/15 位编码体系由 code_system 区分」，
  而 `input_protocol_schema.code_identity_policy` 明写「位数不参与合法性判定」；
- `field_schema.code_system.range` 用 `GBT50500-2024`，同文件的 `rule_set_id.range`
  用 `GB/T50500-2024`，而前者又要求「与 rule_set_id 一致性校验」。

两次都是**靠人眼**发现的，两次都不是 hash 能拦住的。因此机械化为第四条判据。

四环均可在 CI 中串成一条流水线：

```bash
cd bid-pricing
python tools/extract_tasks.py --check          \
  && PYTHONPATH=src python -m unittest discover -s tests \
  && PYTHONPATH=src python -m bidpricing.cli gate-check --contract-date 2026-03-01 \
  && PYTHONPATH=src python -m bidpricing.cli contract-check
```

> **CI 接线状态**：尚未配置（当前为纯本地仓库，无远端）。
> 上表是接线时应执行的命令，已在此登记，避免"机制存在于口头"。

---

## 七、这套机制不能替代什么

诚实地划出边界——以下四件事仍需人的判断，工具无法代劳：

1. **决策的实质正确性**。ADR 记录的是"为什么这么决定"，不保证决定是对的。
   本项目的 ADR-0002 正是两次错误决策的产物。
2. **遗留项是否可接受**。`known_limits` 汇总了自声明限制，但"这个限制能不能带进交付"
   需要人判断。
3. **领域输入的来源合法性**。`c_i`、`q^1` 这类假设的来源与依据，只有造价专业人员能确认。
4. **路线文档本身的演进**。`tools/extract_tasks.py` 保证任务板与文档**一致**，
   但保证不了文档**正确**——若路线升到 v3.3，结构提取会重跑，内容判断仍需人工。
