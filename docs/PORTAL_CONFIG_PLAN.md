# Portal 配置化方案（详细设计）

> 目标：Portal 从"硬编码 demo"变为"用户可配"，节点深度按模块定，卡片可穿透到真页面。
> 不做完整 CMS，做 JSON 配置驱动 + 简单设置 UI。

## 现状问题

| 问题 | 位置 | 影响 |
|------|------|------|
| 数据全硬编码 | `portalData.ts` 697 行 | 改个字要改代码 |
| 3 级写死 | `PortalModule.branches` + `data` | 有些模块 2 级够，有些要 4 级 |
| 卡片不穿透 | `PortalDrawer.tsx` 纯展示 | 点卡片无处可去 |
| 8 个模块写死 | `MODULES` 数组 | 增删模块要改代码 |

## 设计

### 1. 配置结构（`portal.config.json`）

```json
{
  "modules": [
    {
      "id": "biz",
      "code": "M-01",
      "name": "项目经营",
      "icon": "briefcase",
      "color": "#ff5a1f",
      "levels": 3,                    // ← 按模块定深度，不一刀切
      "visible": true,                // ← 用户可隐藏
      "branches": [
        { "id": "overview", "code": "B-1", "label": "项目总览", "isDefault": true },
        { "id": "funding", "code": "B-2", "label": "资金状况" }
      ],
      "dataSource": "api:/api/project/overview/list",
      "cardFields": ["name", "stage", "bid_amount"],  // ← 卡片显示哪些字段
      "cardLink": "/biz/{id}"                        // ← 穿透到真页面
    },
    {
      "id": "hotspots",
      "name": "热点雷达",
      "levels": 2,                    // ← 热点 2 级就够
      "dataSource": "api:/api/hotspots/list",
      "cardFields": ["title", "source", "time"],
      "cardLink": "/hotspots"
    }
  ]
}
```

**关键**：
- `levels`：每个模块独立定（1-4 级），渲染器照做
- `dataSource`：`api:` 前缀走真接口，`static:` 走内置 demo（过渡期用）
- `cardFields`：字段字典的子集，用户勾选
- `cardLink`：`{id}` 占位符，点卡片跳真页面

### 2. 字段字典（轻量，不建表）

```ts
// portalFields.ts —— 全站字段定义，一处管理
export const FIELD_DICT = {
  name:        { label: '项目名称', type: 'text' },
  stage:       { label: '阶段', type: 'badge' },
  bid_amount:  { label: '中标金额', type: 'money' },
  progress:    { label: '进度', type: 'percent' },
  // ... 约 30 个字段
} as const;
```

用户在设置页勾选"卡片显示哪些字段"，存的是字段 key 数组。加新字段？改这一个文件，加一行。

### 3. 存储

| 内容 | 存哪 |
|------|------|
| 默认配置 | `portal.config.json`（随代码走） |
| 用户修改 | SQLite `portal_config` 表（单行 JSON，`user_id` 主键） |
| 字段字典 | `portalFields.ts`（代码，随版本走） |

启动时：读用户配置 → 没有则用默认 → 合并。

### 4. 渲染器改造

`portalEngine.ts` 的 `targets()` 现在假设 3 级：
```ts
// 现在：写死 3 级
// 改后：读 module.levels，动态生成
function targetsForModule(mod: PortalModuleConfig, depth: number) {
  // depth=1: 只有模块节点
  // depth=2: 模块 + 分支
  // depth=3: 模块 + 分支 + 卡片
  // depth=4: 再加一层明细
}
```

`PortalDrawer.tsx`：卡片渲染从 `cardFields` 动态生成，点卡片按 `cardLink` 跳转。

### 5. 设置 UI（`/settings` 加一节）

```
Portal 配置
├── 模块列表（拖拽排序、开关显示）
│   ├── 项目经营 [开] levels: [3▼] 
│   ├── 热点雷达 [开] levels: [2▼]
│   └── ...
├── 选中模块：项目经营
│   ├── 卡片字段：[x]名称 [x]阶段 [ ]中标金额 [x]进度
│   └── 穿透链接：/biz/{id}
└── [恢复默认]
```

## 实施步骤（约 2-3 天）

| Step | 内容 | 工作量 |
|------|------|--------|
| 1 | 建 `portal.config.json`（从现有 8 模块提取） | 2h |
| 2 | 建 `portalFields.ts` 字段字典 | 1h |
| 3 | SQLite `portal_config` 表 + 读写 API | 2h |
| 4 | 改造 `portalEngine.targets()` 支持可变深度 | 4h |
| 5 | 改造 `PortalDrawer` 动态卡片 + 穿透 | 3h |
| 6 | 设置页 UI（模块开关/字段勾选） | 4h |
| 7 | 数据源接入（先接 Biz/Hotspots 真接口，其余 `static`） | 4h |

**可独立交付**：Step 1-4 做完，Portal 就能按配置渲染；5-7 渐进增强。

## 不做的

- 可视化拖拽编排（过度设计）
- 字段类型自定义（字典够用了）
- 多用户配置隔离（单用户，先不做）
- 历史版本/回滚（git 管配置文件就够）

## 风险

- `portalEngine` 改动影响现有动画 → 有 `portalEngine.test.ts` 兜底，改完跑测试
- 真接口数据结构和卡片字段对不上 → `dataSource` 先用 `static`，逐个模块接真数据
