# ADR-0008: D 系列校验规则在已裁定输入模型下的 re-base

- 状态：Accepted
- 日期：2026-09-16
- 关联：T01-06；model_v0.3 §3.5（D01–D12）、model_v0.3_R2 §3.6（D09/D10 重排、W01–W05）；OI-01、ALLOW_EMPTY_NO_CAP、base:=cap、q1_point:=成本量、C2/C4/C5
- 事实源：`config/validation_rules.json`（规范）↔ `src/bidpricing/validation/checks.py`（实现），由 `tests/test_validation_rules.py` 双向锁定

## 背景

任务板 T01-06 引用 v0.3 编号：D01–D09 阻断 + D10–D12 告警。R2 把告警改名
W01–W03（+W04/W05）、D09/D10 重定义为阻断。自 v0.3-R2 以来，输入模型经多轮
用户裁定已实质变化，部分 D 规则的**判据对象**随之失效，须显式 re-base 而非
照抄旧公式。

## 决策

| 规则 | v0.3 原文 | re-base 后判据 | 依据 |
|---|---|---|---|
| D01 | 编码唯一且 12 位合法 | 唯一性（重复 key BLOCK）；位数不参与合法性、UNKNOWN 不阻塞仅记录 | D1 裁定 |
| D02 | q_i^0 > 0 | **q1_point > 0**（pass_through 豁免）——投标清单量在新输入模型下无独立来源 | OI-01（输入 B 由 C 兼任） |
| D03 | base_i > 0 且 cap ≥ base | **cap_i > 0 或 no_cap**——base:=cap 后 cap≥base 恒真，判据收缩为上界自身有效 | base:=cap 裁定 + ALLOW_EMPTY_NO_CAP + C5 |
| D04 | c_i > 0 且口径一致 | c_i > 0（口径一致独立为 D08） | R2 同构 |
| D05 | 三表覆盖 ≥ 98% | **两侧 master 并集覆盖率** n_matched/n_master ≥ 98%，失败输出缺失清单 | 输入 B 由 C 兼任 |
| D06 | q1 置信度标注，N ≤ 20% | attribution 标注完成：未标注（None）与 UNKNOWN 是两种失败；UNKNOWN ≤ 20% | OI-01（须补 attribution） |
| D07 | L_i ≤ U_i | **c_i ≤ cap_i**（L:=floor:=c_i，U:=cap_i；no_cap 不参与） | C2 单边上界 + C4 地板 |
| D08 | 税口径一致 | 两侧 tax_scope **声明**存在且一致；声明缺失 = 未定态 BLOCKED（口径是声明不是数据） | ADR-0007 |
| D09 | contract_type/rule_set_id/ρ 非空 | contract_type 缺失 → BLOCKED；rule_set_id 由分类表 code_system 承载；ρ 未声明按 0（既有裁定，仅记录） | 西永L 2024 落值；ρ 默认 0 裁定 |
| D10 | pricing_role 分类完整 | 分类**声明**就位（covered_lists key 不得缺失）+ 例外行结构合法 + 行级 sheet→covered_lists 机械映射 | T00-06「声明+例外」 |
| D11 | P* ∈ [P*_min, P*_max] | 不变；P* 缺失 = 未定态 BLOCKED，P*_min 无来源则不判下侧 | P* 用户给定裁定 |
| D12(w) | W01/W02/W03 | W01 不变（UNKNOWN 金额占比 > 15%）；**W02 re-base 为价值比 cap/c ∈ [0.2, 5.0]**（原效率比 q̂1/q0 无双向量）；W03 不变，history 缺失 → 显式 SKIP | 输入模型裁定 |

## 状态语义（与闸门层同构）

- `FAIL`：数据违反规则 → 阻断级拒绝运行（违反 ≠ 未定态，ADR-0005）。
- `BLOCKED`：前置声明缺失，无法判定（未定态 = key 完全缺失，ADR-0004/0006）。
- `WARN`：告警触发，写入体检单不阻断。
- `SKIP`：输入数据不足，**显式跳过，不静默通过**。

## 真实样本实证（西永L，2026-09-16）

`validate-boq` 对真实限价 × 报价文件：D01–D05、D07、D10、D11 全 PASS
（覆盖率 1.0、无零价、无可行域为空）；**D06 FAIL**（82 项 attribution 未标注
——正是 OI-01 要求待补的输入）；**D08 BLOCKED**（税口径未声明）；**D09
BLOCKED**（contract_type 未声明）。三者均为真实 Phase 0 输入缺口，非实现缺陷。

## 后果

- 新增 Phase 0 待办三项（用户输入）：①82 项 attribution 标注；②税口径声明
  （两侧均不含增值税）；③contract_type（预计 UNIT_PRICE，须用户显式声明）。
- validation_rules.json 成为 D 系列唯一规范事实源；改阈值/判据须同改实现与
  测试（三处互锁）。
