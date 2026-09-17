# ADR-0017 合同条款核对结论须署名，且只能由合同责任方作出

- 日期：2026-09-17
- 状态：已采纳
- 触发：Gate 0b 的 `contract_ruleset_version` 判定只校验 hash 与三字段

## 背景

Gate 0b 的 `contract_ruleset_version` 原判据是「制品已冻结且 hash 与内容一致」。
但 hash 只证明一件事：**这个文件从冻结之后没被改过**。它证明不了**合同条款
被看过**。一个从未打开过招标文件合同条款专章的人，同样能让这个字段全绿。

这正是路线隐藏依赖 19 要防的形态——「熔断点形同虚设」。区别在于：隐藏依赖 19
防的是**审批**被勾选走过场，而这里防的是**核对**被 hash 冒充。

用户 2026-09-17 就本项裁定：

> 合同条款用户自行斟酌

## 决策

规则卡新增 `contract_review` 字段，Gate 0b 增加业务层判据
（`_check_contract_review`）：合同条款核对结论必须**被声明、被署名、可复核**。

词表五态（机制层常量 `CONTRACT_REVIEW_VOCAB`）：

| 取值 | 含义 | 门禁 |
|---|---|---|
| `USER_DISCRETION` | 用户明示由本人斟酌并承担结论（本项目采用） | 通过 |
| `REVIEWED_NO_EXTRA_CLAUSES` | 已逐条核对，未发现本卡未覆盖的条款 | 通过 |
| `REVIEWED_WITH_FINDINGS` | 已核对并发现差异，**差异须逐条列出** | 通过（缺 findings 判 FAIL） |
| `NOT_REVIEWED` | 尚未核对 | **BLOCKED** |

判据要点：

1. 字段缺失 → **BLOCKED**（不是 FAIL：这是声明缺失，不是声明错误，ADR-0008）。
2. `declared_by` 缺失 → **BLOCKED**——核对结论没有责任人等于没有结论。
3. 声明「有发现」却不列 `findings` → **FAIL**，结论不可复核。
4. **词表由机制层定义**，制品自带的 `vocabulary` 只作说明且须与常量逐字一致
   （不一致判 FAIL）。若让判据读制品自带的词表，改词表就等于改判据，
   而且两份词表必然分叉（ADR-0002：机制 vs 数据）。

## 为什么 Agent 不能代为断言

Agent 未获得招标文件的合同条款专章。**「未提及」不等于「无此条款」**
（ADR-0007：沉默不是断言）。由 Agent 写下 `REVIEWED_NO_EXTRA_CLAUSES`
是一句无法追溯的不实陈述。

因此本项目的落值是 `USER_DISCRETION` + `agent_assertion: "NONE"`，
并在 `why_not_agent_asserted` 里写明上述理由——**把「谁没做什么」也记录下来**，
而不是留一个看着像「已核对」的空白。

## 附带修正：一处路径悬空

`gate_0b.contract_ruleset_version` 原声明 `artifact_path = contract_ruleset_card.json`，
**该文件从不存在**，故这条登记从未被冻结过。

路线 §2.1 原文为「= T00-01 规则卡**经合同条款核对后的最终冻结版**，**其 v1**
已在 Gate 0a 前产出」——「其 v1」表明这是**同一制品的两个阶段**，不存在第二份文件。

修正为指向 `pricing_rule_card.json`，并在 note 中说明两阶段含义：
v1 在 Gate 0a 冻结（机制层：符号/参数/公式/优先级链），
最终版在 Gate 0b 冻结（业务层：`contract_review` 的核对结论与责任人）。

**教训**：注册表里声明的路径若不存在，三字段校验会先报「version 缺失」，
而不是「文件不存在」——**报告看起来像「还没做」，实际是「指向了不存在的东西」**。
`freeze` 时报 `FileNotFoundError` 才会暴露。

## 后果

- 本项目：`USER_DISCRETION`，结论由用户承担，Agent 不作任何断言。
- 若日后发现招标文件合同条款与本卡冲突（付款/结算/调价/质保/工期索赔），
  须重跑 T00-01 并重新冻结，且受影响的下游制品
  （`profit_bridge_spec` 的差额项、`q1_assumption_spec` 的取值依据）须一并复核。
  该后果已写入制品字段 `consequence`，不依赖本 ADR 被记住。
