# ADR-0009: 单项亏损承接口径（C4 地板钳制 + C6 总量兜底）

- 状态：Accepted
- 日期：2026-09-16
- 关联：T01-06 D07；C4/C6（constraint_schema）；loss_acceptance 选择项；ADR-0008
- 触发：T01-02 真实成本清单验收时 D07 实测 FAIL——西永L **8 项 c_i > cap_i**
  （030401002003 / 030403006001 / 030403006002 / 030403007001 / 030403007002 /
  030404017001 / 030408001006 / 030413001001），逐项可行域为空。

## 用户裁定（原文留痕）

> 考虑整体利润，本来单项清单就是有亏有赚的

## 决策

1. **新增项目级选择项 `loss_acceptance`**（ACCEPT / DECLINE，无默认值，
   selection_options 注册）：
   - `ACCEPT`：C4 地板钳制 `floor_i := min(floor_i, cap_i)`——单项允许
     p_i < c_i（p=cap 止损），**亏损总量仍由 C6（Σ s_i·q1 ≤ θ·P*）硬约束**
     ——与 C4 备注『C4 与 C6 必须并存』的既有设计一致，不是新机制。
     D07 对亏损项转 **WARN**，输出亏损项清单与最低亏损额 (c_i − cap_i)·q1_point。
   - `DECLINE` / 未声明：保持严格地板，任一 c_i > cap_i → D07 FAIL（可行域为空）。
2. **D07 判据同步 re-base**（validation_rules.json + checks.py + 测试三处互锁）。
3. 西永L 项目落值 `loss_acceptance = ACCEPT`（2026-09-16，operator，依据=用户原话）。

## 依据

- 规格书本身已预设该场景（memory/working notes：『c_i 是自身个别成本 ≠ 市场平均；
  C4 地板与 C6 亏损风险并存』）——C6 的存在意味着模型本就允许个别项亏损，
  只缺一个显式声明让 D07/C4 不把亏损项当「数据错误」判死。
- 工程实务：综合单价报价本就是组合策略，个别项低于成本、靠其他项利润找平。

## 后果

- WP4 求解层实现 C4 时须读 loss_acceptance：ACCEPT → floor 钳制到 cap。
- WP6 报价表须披露亏损项（项数 + 最低亏损额），供用户投标决策复核。
- 西永L 实测：8 项转 WARN，最低亏损合计见 validation_report.json evidence。
