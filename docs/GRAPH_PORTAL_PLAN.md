# Portal 配置化 + 关联图谱 联合方案

> 2026-10-08 liam 提出。两个想法合流：Portal 从硬编码变为可配，关联图谱作为第一个"真数据"模块接入。
> 方案先行，确认后动手。

## 一、总体架构

```
┌─────────────────────────────────────────────────┐
│ Portal（展厅）                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │ 项目经营 │  │ 热点雷达 │  │ 关联图谱 ★   │  │
│  │ levels:3 │  │ levels:2 │  │ levels:2     │  │
│  │ api真数据 │  │ api真数据 │  │ api真数据    │  │
│  └──────────┘  └──────────┘  └──────────────┘  │
│         ▲ 配置驱动（portal.config.json）        │
└─────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────┐
│ 独立页面 /graph（图谱详情页）                     │
│  全屏 SVG 关系图 + 右侧详情面板                   │
└─────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────┐
│ 数据层（SQLite，现有表 + 1 个新字段）             │
│  exec_contract.client → 建设单位                  │
│  exec_subcontract.subcontractor → 劳务/分包       │
│  exec_material.supplier → 供应商（+ 新增 paid）   │
└─────────────────────────────────────────────────┘
```

**设计原则**：
- Portal 是"展厅"（看一眼），`/graph` 是"车间"（细看）
- Portal 图谱模块只显示 2 级（单位→项目），点穿透跳 `/graph` 看全图
- 所有模块统一走配置驱动，图谱是第一个吃真数据的示范

## 二、数据层改动

### 2.1 `exec_material` 加 `paid` 字段

```sql
ALTER TABLE exec_material ADD COLUMN paid REAL DEFAULT 0;
```

- 原因：供应商的"已付/应付"现在算不出，分包表有 `paid`，材料表对齐
- 迁移：`ALTER TABLE` 幂等，老数据默认 0
- 前端：材料表的编辑表单加"已付金额"输入框

### 2.2 图谱查询（3 个新 API，`api/app.py`）

```
GET /api/graph/units
→ [{ name, role: 'client'|'subcontractor'|'supplier', project_count, total_amount }]
  去重，role 按来源表区分

GET /api/graph/unit?name=xxx&role=subcontractor
→ {
    unit: { name, role },
    projects: [{
      project_id, project_name,
      contracts: [{ type, amount, paid, payable, status }],
      total_amount, total_paid, total_payable
    }]
  }

GET /api/graph/project?id=xxx
→ {
    project: { id, name },
    units: {
      clients: [{ name, amount }],
      subcontractors: [{ name, amount, paid, payable, status }],
      suppliers: [{ name, amount, paid, payable }]
    }
  }
```

**应付计算**：`payable = amount - paid`（分包/材料）；收入合同 `receivable = amount - received`（从 `exec_payment` 汇总）。

### 2.3 同名单位归一

风险：同一个单位在不同表/项目里写法不一致（"重庆重明" vs "重庆重明物资销售有限公司"）。

方案：
- V1：精确匹配 + 前端提示"疑似同一单位"（编辑距离 < 3 的列出来让用户确认）
- V2（以后）：单位别名表，用户手动合并
- V1 先做精确匹配，够用

## 三、Portal 配置化（含图谱模块）

### 3.1 配置结构

沿用 `docs/PORTAL_CONFIG_PLAN.md`，新增图谱模块：

```json
{
  "id": "graph",
  "code": "M-09",
  "name": "关联图谱",
  "icon": "graph",
  "color": "#7c3aed",
  "levels": 2,
  "visible": true,
  "dataSource": "api:/api/graph/units",
  "cardFields": ["name", "role", "project_count", "total_amount"],
  "cardLink": "/graph?unit={name}&role={role}"
}
```

### 3.2 图谱在 Portal 里的呈现

- 中心：图谱模块节点
- 第 1 级：单位节点（按角色着色：建设=蓝，劳务=橙，供应商=绿）
- 第 2 级：项目节点（连线粗细 = 合同金额）
- 点单位卡片 → 穿透到 `/graph?unit=xxx`

**不做 3 级**：图谱天然 2 级（单位↔项目），硬套 3 级就是用户说的"呆"。

## 四、独立页面 `/graph`

### 4.1 布局

```
┌──────────────────────────────────────────────────┐
│ 搜索框：[输入单位名]  角色筛选：[全部▼]            │
├──────────────┬───────────────────────────────────┤
│              │  详情面板                          │
│  SVG 关系图   │  重庆重明物资销售有限公司          │
│              │  角色：供应商                      │
│  ○单位       │  参与项目：3 个                    │
│   ╲ ╲        │  ┌─────────────────────────────┐  │
│    ○项目     │  │ 西永学校一期                 │  │
│              │  │ 合同：48.2万 已付：30万       │  │
│              │  │ 应付：18.2万 [穿透→]         │  │
│              │  └─────────────────────────────┘  │
│              │  │ 渝北10KV配电工程 ...          │  │
└──────────────┴───────────────────────────────────┘
```

### 4.2 交互

- 点单位节点 → 右侧显示该单位的所有项目+金额+应付
- 点项目节点 → 右侧显示该项目的所有单位（按角色分组）
- 点"穿透→" → 跳到 `/biz/:id` 对应 Tab（分包→执行 Tab，材料→执行 Tab）
- 搜索框：模糊搜单位名
- 连线粗细 ∝ 合同金额，一眼看出大头

### 4.3 技术

- SVG 手画（不用引入 D3/echarts，保持轻量）
- 力导向布局简化版：单位放左列，项目放右列（bipartite 布局，最清晰）
- 复用 Portal 的弹簧物理？不，图谱用静态布局，清晰优先

## 五、实施步骤

| Step | 内容 | 工作量 | 依赖 |
|------|------|--------|------|
| 1 | `exec_material` 加 `paid` 字段 + 迁移 | 1h | — |
| 2 | 3 个图谱 API（`api/app.py`） | 4h | Step 1 |
| 3 | `/graph` 独立页面（SVG + 详情面板） | 1 天 | Step 2 |
| 4 | `portal.config.json` + 字段字典 | 3h | — |
| 5 | SQLite `portal_config` 表 + 读写 API | 2h | — |
| 6 | `portalEngine` 支持可变深度 | 4h | Step 4 |
| 7 | `PortalDrawer` 动态卡片 + 穿透 | 3h | Step 4, 6 |
| 8 | 图谱模块接入 Portal（`levels: 2`） | 2h | Step 2, 7 |
| 9 | 设置页 UI（模块开关/字段勾选） | 4h | Step 4, 5 |

**交付节奏**：
- Step 1-3：图谱独立可用（约 1.5 天）
- Step 4-9：Portal 配置化 + 图谱接入（约 2 天）
- 总计：约 3-4 天

## 六、不做的

- 单位别名合并（V2 再做）
- 可视化拖拽编排节点
- 图谱导出图片
- 多用户配置隔离

## 七、要你确认的

1. **材料表加 `paid` 字段**：可以吗？（只是加一列，老数据默认 0）
2. **同名单位归一**：V1 先精确匹配，疑似项前端提示。你 OK 吗？
3. **图谱页面位置**：独立 `/graph` + Portal 模块。还是只要其中一个？
4. **先做哪半**：图谱（1-3）还是 Portal 配置化（4-9）？建议先图谱，数据先跑通。
