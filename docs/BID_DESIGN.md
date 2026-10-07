# 不平衡报价设计（2026-10-07，2026-10-07 修订：并入报价页方案 C）

> **2026-10-07 修订（合并决策）**：本功能不再作为独立工具页存在，已并入报价页
> （`index.html`）作为**第三种报价策略 `unbalanced`（方案 C 槽位）**，与
> `optimal`（A 槽位）/`uniform`（B 槽位）共用同一套解析→优化→存储→导出链路。
> 独立页 `tool-bid.html`、`/api/bid/*` 路由、`bid_package.py` 存储已下线（见删除清单 §6）。

## 1. 数据模型（合并后）

不再使用独立的 BidPackage JSON；不平衡报价的结果作为报价页**方案（plan）**
存入 `quote.db`，`strategy='unbalanced'`，参数随方案持久化：

```
plan.params: {
  ...通用参数（target_total / ratio_min / ratio_max / 税口...）,
  unbalanced_m_min: float,        # 默认 0.0
  unbalanced_m_max: float,        # 默认 0.3
  unbalanced_strategies: {...},   # 明确指定的 {item_id: 策略}（V1 为空，由规则生成）
  unbalanced_kw_rules: str,        # 关键字规则文本，每行 `关键字=策略`
}
```

## 2. 算法（`src/bidpricing/unbalanced.py`，被复用）

**输入**：清单项（工程量 / 有效成本单价 c_i（H-002 换算后不含税）/ 控制价 / 策略标签）
＋ 可竞争预算 B（由 `compute_P_competitive` 从含税目标总价反推）
**输出**：每项报价单价 p_i，满足 Σ(p_i·q_i) = B，且每项落在 [下界, 上界] 内。

```
策略权重 w_i：
  前期（早收款）/ 预计工程量增加 → 1.5
  正常 → 1.0
  预计工程量减少 → 0.5
  让利（B < 成本总价）时权重反转：预计减项多让、预计增项少让

约束：c_i·(1+m_min) ≤ p_i ≤ min(cap_i, c_i·(1+m_max))
      （cap 缺失时上界退化为 c_i·(1+m_max)）

分配（迭代 clamp）：按 w_i·q_i 比例分摊差额，顶界项逐轮剔除；
单价保留 2 位小数，尾差按 1 分步进贪心吸收（从小工程量项开始）；
不可达时返回原因（哪几项卡界），上游转 422。
```

策略标签来源（V1）：`unbalanced_kw_rules` 关键字规则，
每行 `关键字=策略`，命中项目名称/编码即打标，多条命中取第一条；
`unbalanced_strategies` 明确指定的单项覆盖规则结果。V1 不做锁定（lock）——
算法已预留 `locked` 参数，待权重逻辑经 2~3 个真实项目验证后 V2 再加前端。

## 3. 管线集成（`src/bidpricing/quote_strategies.py::solve_unbalanced`）

与 `solve_uniform` 同构：H-002 税口换算 → 过滤可优化项 → 权重分配 →
`reconcile_total` 调和 → `QuotePipelineResult(solver_status=UNBALANCED_WEIGHTED)` →
中文明细行（多一列"报价策略"）→ payload（含 `unbalanced` 回显段：
实际策略映射 / m 界 / 利润 / 是否反转）。非法策略标签回退 normal。

## 4. 前端

- 方案中心槽位 C：`{ key:'C', label:'不平衡报价', strategy:'unbalanced' }`
  （原"策略待定"占位已激活；scheme tabs 的 C 灰显逻辑已删除）
- 参数区新增"不平衡报价参数"卡：m_min / m_max 输入＋策略关键字规则 textarea
- `buildOptimizeForm` 附加三个字段；`fillParams` 打开已存方案时回填
- `renderResult` 零改动（payload 同构）

## 5. 验证方式

拿一个**已完工的真实历史项目**回测：用当时的清单+成本跑 C 槽位，
对比手工报出的单项价——看总价是否一致、单项偏离是否合理、
策略是否符合当时判断。需要一份脱敏清单 Excel（两份：限价+成本）。

**已完成的合成验证（2026-10-07）**：
- `tests/test_unbalanced.py` 9 项（算法）、`tests/test_solve_unbalanced.py` 6 项（管线集成，含与 uniform 的 payload 同构断言）
- 前端冒烟 30 项全过（含 slot C 激活后的页面加载）

## 6. 删除清单（2026-10-07 合并时执行，已确认）

- `frontend/tool-bid.html`、`frontend/js/tool-bid.js`（独立页下线）
- `src/bidpricing/bid_package.py`、`tests/test_bid_package.py`
- `api/app.py` 的 `/api/bid/*` 6 个路由及相关 import
- `frontend/tools.html` 第 5 卡、`frontend/test/_harness.mjs` 与 `smoke.test.mjs` 的 tool-bid 登记
- 保留：`src/bidpricing/unbalanced.py`、`tests/test_unbalanced.py`、本文件

## 7. 假设（待真实回测纠正）

- m_min 缺省 0（不亏本）、m_max 缺省 0.3 是否符合电力工程习惯
- 让利时权重反转是否符合他的手工习惯
- 重庆招标对单项超控制价是废标还是扣分（当前按硬约束处理）
