# 前端 UI 重构计划 · 对齐 L叔工作台 DESIGN.md V2

> 状态：**待批准**
> 撰写日期：2026-10-06
> 目标：把 `frontend/` 全站视觉对齐 [DESIGN.md](../..)（L叔工作台 V2：黑白极简 + 橙/黄专色 + 像素秩序 + 打印终端感）
> 备份：`backup/pre-ui-refactor-20261006`（commit `5e80cd3`） + `../_backup_ui_refactor_20261006/frontend`（85 文件 / 5.15 MB）

---

## 0. 前提澄清（必须先接受，否则计划不成立）

| 事项 | 事实 | 结论 |
|---|---|---|
| 技能规范适用范围 | `DESIGN.md` 是给「L叔工作台」（React+TS 工程）写的，其 §13「允许修改 `AppShell.tsx` / `components/icons.tsx`」等**文件级约束对本项目不适用** | 本次只采纳其**视觉设计系统**（令牌、组件合同、响应式、可访问性），照搬工程合同无效 |
| 视觉方向冲突 | 本仓库已有 `docs/前端UI_UX深度审查.md`，其主张为「保留暖纸风、只修工程债」，与 V2 的「禁止米色/暖白/渐变/阴影/大圆角」**直接冲突** | 采用 V2 后，该文档的**视觉类**建议作废；其**工程类**发现（F-01/F-02/F-03/F-06/F-08/F-11/F-18）仍然有效，本计划一并吸收 |
| 改动性质 | 本项目当前用暖纸底 `#f4f3f0` + 深黑渐变侧栏 + 5 色模块轮转 + 4 联矿物色 KPI | 这是**全站换皮**，不是视觉打磨 |

---

## 1. 已核实的事实基础（写计划时现场取证）

**页面清单（6 个可访问入口）**

| 页面 | 行数 | 引入 CSS（顺序） | 引入 JS（顺序） |
|---|---|---|---|
| [index.html](file:///d:/Lee-proj/TRAE/bid-pricing-build/bid-pricing/frontend/index.html) | 568 | styles → agent → quote-dashboard → results → workbench → MiSansVF | escape → sidebar → toast → dropdown → workbench → agent → app |
| [tools.html](file:///d:/Lee-proj/TRAE/bid-pricing-build/bid-pricing/frontend/tools.html) | 65 | styles → quote-dashboard → tools → MiSansVF | sidebar |
| [tool-well.html](file:///d:/Lee-proj/TRAE/bid-pricing-build/bid-pricing/frontend/tool-well.html) | 215 | styles → quote-dashboard → tools → MiSansVF | sidebar → dropdown → tool-common → tool-well |
| [tool-cable.html](file:///d:/Lee-proj/TRAE/bid-pricing-build/bid-pricing/frontend/tool-cable.html) | 79 | 同上 | sidebar → dropdown → tool-common → tool-cable |
| [tool-duct.html](file:///d:/Lee-proj/TRAE/bid-pricing-build/bid-pricing/frontend/tool-duct.html) | 82 | 同上 | sidebar → tool-common → tool-duct |
| [tool-earth.html](file:///d:/Lee-proj/TRAE/bid-pricing-build/bid-pricing/frontend/tool-earth.html) | 106 | 同上 | sidebar → dropdown → tool-common → tool-earth |

**死代码（不在改动范围）**
- `workbench.html`（31 行）只是 `location.replace('index.html#workbench')` 的跳转存根。
- `workbench-standalone.css`（509 行）**全仓库无任何引用**（grep 确认），不进入改动清单。

**样式文件规模**

| 文件 | 行数 | 自带 `:root`？ |
|---|---|---|
| styles.css | 498 | 是（L5–78，主令牌源，约 60 个 token） |
| quote-dashboard.css | 863 | 是，2 处局部（L6 `--brand-gold`；L299 `--intake-*`/`--cobalt-soft`/`--emerald-soft`） |
| tools.css | 323 | 否 |
| workbench.css | 227 | 否（作用域 `#workbenchView`） |
| agent.css | 222 | 否 |
| results.css | 23 | 否 |
| workbench-standalone.css | 509 | 是（**死代码，不动**） |

**关键缓冲：现有 token 已被大量使用**
index.html 的内联 `style="..."` 与内联 SVG 大量引用 `var(--text-secondary)`、`var(--module-2)`、`var(--success)`、`var(--warn)`、`var(--danger)`、`var(--border)`、`var(--surface-card)`。**只要重定义这些变量，这部分会自动跟随换色**——这是本计划能用「别名映射」而非「全量重写」的工程依据。

**已还清的工程债（不需重复做）**：z-index 已 token 化（styles.css:62–77，`--z-*` 15 个）、`:focus-visible` 已有全局环（styles.css:96）、`--fs-min:12px` 已定义。

---

## 2. 不可破坏约束（红线）

1. **不改后端**：`api/`、`src/`、`agent-service/`、`config/`、`run.ps1` 一律不动。
2. **不改业务逻辑**：不改任何 API 路径、请求时机、路由、数据结构、handler 行为；JS 只允许改「生成视觉的字符串/类名」部分。
3. **类名契约冻结**：JS 依赖的类名必须保持可用——`#sbToggle`/`.sb-backdrop`/`.app-shell`、`.toast-pill`/`.toast-success`/`.toast-error`/`#toastStack`、`.cs`/`.cs-trigger`/`.cs-list`、`.nav-item`/`data-module`、`#workbenchView`。**只改样式，不改名**；确需改名必须同步改 JS 并回归。
4. **不伪造**：不新增假数据、假按钮、假状态。
5. **保留全部功能与状态**：loading / empty / error / disabled / hover / focus / active 七态齐全；抽屉、筛选、分页、上传、导出、KPI 穿透一律保留。

---

## 3. 令牌映射方案（核心风险与收益都在这里）

做法遵循 `DESIGN.md` §4.3「兼容别名」：**新建单一事实源 `frontend/tokens.css`，把旧变量名整体重指向 V2 四色**。这样既有页面无需大改即可换色。

### 3.1 新增 V2 本体令牌

```
--ui-white #FFFFFF  --ui-black #111111  --ui-orange #FF5A1F  --ui-yellow #FFC928
--ui-overlay rgba(17,17,17,.52)
--line-thin 1px solid var(--ui-black)   --line-strong 2px solid var(--ui-black)
--line-accent 2px solid var(--ui-orange)
--notch-sm 6px  --notch-md 10px  --shadow-action 2px 2px 0 var(--ui-black)
--space-1..7 = 4/8/12/16/24/32/48px
--font-pixel/--font-display = "LShu Pixel",ui-monospace,...  --font-body = MiSans（保留）
--text-display/h1/h2/h3/body/small/micro
--dur-fast 120ms --dur-base 180ms --dur-slow 280ms  --ease-out/--ease-in-out
```

### 3.2 旧令牌 → V2 重指向（styles.css `:root` 迁移到 tokens.css）

| 旧 token | 现值 | 新值 | 说明 |
|---|---|---|---|
| `--page-bg` | `#f4f3f0` | `#ffffff` | 禁暖白 |
| `--surface-card` / `--surface-nested` | `#fcfbf8` / `#f7f6f1` | `#ffffff` | 卡片唯一实体底色 |
| `--border` / `--border-input` | `#ecebe5` / `#e0ded6` | `#111111` | 细线一律黑 |
| `--text` | `#232220` | `#111111` | |
| `--text-secondary` | `#736e65` | `rgba(17,17,17,.62)` | 用透明度弱化，不建灰色板 |
| `--text-tertiary` | `#b6b1a6` | `rgba(17,17,17,.45)` | |
| `--accent` | `#2f2e2b` | `#ff5a1f` | ⚠️ **高风险**：原为深灰，被当作深底/深字用，需逐处核对，见 §6 风险 |
| `--accent-600` | `#262522` | `#111111` | 链接/强调文字用黑（避免橙色泛滥） |
| `--accent-muted` | `#efeee8` | `#ffffff` | |
| `--on-accent` | `#f4f3f0` | `#111111` | V2 主按钮=橙底黑字 |
| `--module-1..6` | 5 色轮转 | 全部 `#111111` | 取消多色；强调交给橙/黄 |
| `--success` / `--success-soft` | `#4d7c59` / `#e8efe9` | `#111111` / `#ffffff` | 完成=黑勾，不用绿 |
| `--danger` / `--danger-soft` | `#ba4a38` / `#f7ebe9` | `#ff5a1f` / `#ffffff` | 错误=橙 |
| `--warn` / `--warn-soft` | `#c97a2b` / `#f8f1e7` | `#ffc928` / `#ffffff` | 提醒=黄 |
| `--drawer-bg` / `--drawer-bg-top` | `#23211e` / `#2d2c29` | `#ffffff` | 侧栏转白底 |
| `--drawer-text` / `--drawer-text-mute` | `#f4f3f0` / `rgba(...)` | `#111111` / `rgba(17,17,17,.62)` | |
| `--drawer-hover` / `--drawer-active` | 白 8% / 12% | `#ffc928` / `#ff5a1f` | hover 黄、active 橙 |
| `--radius-control/tile/card/sheet` | 8/12/16/22px | `0px` | 全域直角 |
| `--shadow-card/overlay/modal/popover/tooltip` | 5 种阴影 | `none` | 仅主按钮保留硬阴影 |
| `--card-pad` | 18px | `16px` | 归 4px 网格 |
| `--sidebar-w` | 258px | `248px` | 对齐 DESIGN §7.1 |
| `--brand-gold`(quote-dashboard:6) | `#e6b96a` | `#ffc928` | |
| `--intake-cap`/`--intake-cost` | `#3d6cad`/`#1c6b4e` | `#111111` | 取消冷蓝/墨绿 |
| `--cobalt-soft`/`--emerald-soft` | 淡蓝/淡绿 | `#ffffff` | |

### 3.3 硬编码清理

`index.html` 内联 SVG 有 `stroke="#dfdcd3"`、`stroke="#fff"`、`fill="url(#gMargin)"`（渐变）等裸值；全 CSS 另有若干裸 hex（审查文档 F-02 计数 64 处）。**验收判据**：`grep -E "#[0-9a-fA-F]{6}" frontend/*.css` 只允许出现在 `tokens.css`。

---

## 4. 分阶段任务

### Phase 1 · 令牌层与字体（地基）
1. 新建 `frontend/tokens.css`：§3.1 本体 + §3.2 别名映射。
2. `styles.css` 删除 L5–78 的 `:root`，改为消费 tokens.css（保留 `--select-arrow` 等非颜色令牌，箭头描边改黑）。
3. 复制技能字体到本地：`c:\Users\leema\.trae-cn\skills\lshu-workbench\app\frontend\src\assets\fonts\fusion-pixel-12px-proportional-{latin,zh_hans}.otf.woff2` + `OFL.txt` → `frontend/assets/fonts/pixel/`；新增 `@font-face`（**禁止 CDN**）。
4. 6 个 HTML 的 `<head>` 首位插入 `tokens.css`，版本号统一为 `?v=2026-10-06-v2a`。
5. 像素字体适用范围严格按 DESIGN §5.1：标题 / 导航编号 / 按钮 / Tab / Chip / 徽章 / 时间 / 数值 / 状态码；**长中文正文一律 MiSans**。

### Phase 2 · 应用壳层
- `.app-shell` 纯白；`.sidebar` 宽 248px、白底、右侧 `2px` 黑竖线、无阴影。
- 导航项：默认白底黑字 `1px` 黑框；**当前项橙底黑字 + `2px` 黑框**；hover 黄底（不做位移）；`focus-visible` `3px` 橙 outline / `2px` offset。
- 新增**导航编号**（本项目的编号体系，非照搬技能）：`报价 Q-01`、`实施成本 C-02`、`AI 助手 A-03`、`项目台账 L-04`、`结算 S-05`、`速算工具箱 T-06`。
- 侧栏底部用户区/版本行改为黑字 + `1px` 分隔线。
- 底部轻量**只读**状态条（不得伪造可点按钮）。

### Phase 3 · 组件合同落地（styles/tools/agent/quote-dashboard 共用层）
| 组件 | 现状 | 目标（DESIGN §8） |
|---|---|---|
| `.card` | 米白底 + 16px 圆角 + 阴影 | 白底 + `2px` 黑框 + 统一裁角；标题行 ~40px + `1px` 底线；模块间距 16–24px |
| `.btn-primary` | 墨灰底 | 橙底 + 黑字 + `2px` 黑框 + `2px 2px 0` 硬阴影 |
| `.btn-secondary` | 灰底 | 白底 + 黑字 + `2px` 黑框 |
| 表头/表格 | 灰底头 | 表头白底黑粗字 + `2px` 黑底线；行 hover 黄细条 / selected 橙细条；`tabular-nums` |
| `.filter-chip`/`.scheme-tab` | 漂浮胶囊 | 分段控制条（同一条），active 橙底/橙下线，非 active 白底黑字 |
| 徽章/`.delta-badge`/`.risk-corner` | 胶囊 | 矩形小标签，`0` 圆角 |
| 表单 `input/select` | 8px 圆角灰框 | 白底 `1px`/`2px` 黑框 `0` 圆角；placeholder 黑 + 降透明；focus-visible 橙环 |
| 开关/checkbox | 绿色系 | 开启=橙或黑实心，**不用绿** |
| 抽屉 `.plan-hub`/`.agent-settings`/`.cmp-modal` | 圆角 + 阴影 | 白底、`2px` 黑线、`0` 圆角、无阴影、遮罩 `--ui-overlay`；Esc + `44×44` 关闭键 |
| 图表/迷你图 | 5 色 + 渐变 | 纯白底、黑坐标轴；主系列橙、次黄、第三黑；去 `linearGradient`；tooltip 白底 `2px` 黑框 |
| toast | 彩色圆角 | 白底黑框 + 图标 + 文字（成功=黑勾，错误=橙描边） |

### Phase 4 · 逐页落地（顺序即建议验收顺序）
1. **报价页** `index.html`：`quote-dashboard.css`（863 行，最大头）→ `results.css` → `styles.css` 中报价相关段。重点：4 联矿物色 KPI 卡改黑白橙黄；安全防线双滑块（`--warn`/`--danger` 已映射）；上传舱 `.intake-*`；就绪清单 `.prep-*`。
2. **工具箱**：`tools.css`（323 行）+ `tools.html`/`tool-*.html` 4 页。**注意保留**既有三栏字段布局、`.tool-inline` 水平排列、`[hidden]` 覆盖样式等已有约定（见项目记忆）。
3. **个人工作台**：`workbench.css`（227 行，作用域 `#workbenchView`）+ `workbench.js` 中生成视觉字符串的部分。
4. **AI 助手**：`agent.css`（222 行）+ `index.html` 的 `#agentView` 结构。

### Phase 5 · 工程债合并（对照 `前端UI_UX深度审查.md`）
只做与本次换皮同源的项，避免范围膨胀：
- F-02 裸 hex 收敛（并入 §3.3 验收）。
- F-06 `:focus-visible` 补全覆盖（当前仅全局一条，交互元素逐个补）。
- F-08 `prefers-reduced-motion` 全局降级。
- F-09 `transition:all` 展开为具名属性。
- F-10 断点收敛为 4 档（1280/1024/768/560）。
- F-18 微字号（<12px）清零；F-19 非标间距归一 4px 网格。
- **不做**（超出换皮范围，另行立项）：F-11 innerHTML/XSS 重构、F-12 AbortController、F-14 ES module 化、F-15 测试基建、F-16 CSP、F-17 多主题。

### Phase 6 · 验证与验收
1. 启动：`.\run.ps1`（或 `python -m http.server 8080 --directory frontend`）。
2. 用浏览器子代理覆盖 6 个视口：`2560×1000 / 1920×1080 / 1440×900 / 1280×800 / 1024×768 / 390×844`，并检查 `1101/1099px` 断点两侧。
3. 交互回归：上传 xlsx → 计算 → KPI 穿透 → 表格分页 → 方案中心抽屉 → 对比弹层 → 导出；工具箱 4 页计算；工作台；AI 助手发送/设置抽屉。
4. 机械判据自检（grep）：
   - `:root\s*\{` 在 `*.css` 中只剩 `tokens.css` 1 处（`workbench-standalone.css` 死代码除外）
   - `#[0-9a-fA-F]{6}` 只出现在 `tokens.css`
   - `z-index:\s*\d` 只出现在 `tokens.css`
   - `font-size:\s*(10(\.5)?|11(\.5)?)px` = 0
   - `cubic-bezier` 只出现在 `tokens.css`
   - 全站无 `#f4f3f0`/`#fcfbf8`/`#ecebe5`/`#232220` 等旧品牌色
5. 视觉清单（DESIGN §14.1）：纯白底、仅黑白橙黄四色实体、无纸纹/噪点/渐变/模糊阴影、橙 ≤4% 黄 ≤2%、无大圆角胶囊、无 UI emoji。

---

## 5. 文件影响清单

**新增**：`frontend/tokens.css`、`frontend/assets/fonts/pixel/`（2 woff2 + OFL.txt）
**改写**：`styles.css`、`quote-dashboard.css`、`tools.css`、`workbench.css`、`agent.css`、`results.css`
**改 head 引用**：`index.html`、`tools.html`、`tool-well.html`、`tool-cable.html`、`tool-duct.html`、`tool-earth.html`
**小改（视觉字符串/内联 SVG）**：`app.js`、`workbench.js`、`agent.js`、`js/toast.js`、`js/dropdown.js`
**不动**：`api/`、`src/`、`config/`、`agent-service/`、`run.ps1`、`js/tool-*.js`（除非出现硬编码颜色）、`workbench.html`、`workbench-standalone.css`

---

## 6. 风险与回滚

| 风险 | 说明 | 缓解 |
|---|---|---|
| `--accent` 语义反转 | 原为深灰（可作深底/深字），新为橙色。若某处把它当深色背景用，会变成大面积橙，违反橙 ≤4% | Phase 1 后先 `grep -n "var(--accent)" frontend/*.css` 逐条核对，深底用途改用 `--ui-black` |
| JS/CSS 类名耦合 | 重命名类名会静默打断 toast/下拉/侧栏 | 红线 §2.3：只改样式不改名 |
| 像素字体可读性 | 长中文正文用像素字会难读；DESIGN 明确禁止 | 仅用于短标签/数值；正文坚持 MiSans 与 ≥13px |
| 无前端测试基线 | 仓库无 JS/CSS 测试，回归靠人工 | 依赖备份 + Phase 6 截图矩阵 |
| 未跟踪文件 | `agent.js`/`agent.css`/`agent-service/` 未提交，普通 tag 备份会漏 | 已用 `git add -A + write-tree` 快照进备份分支，工作区未被改动 |

**回滚方式**
- 单文件：从 `../_backup_ui_refactor_20261006/frontend/` 覆盖回来。
- 全量：`git checkout backup/pre-ui-refactor-20261006 -- frontend` 或 `git reset --hard backup/pre-ui-refactor-20261006`（后者会丢弃之后所有改动，慎用）。

---

## 7. 验收定义（Done 的标准）

1. 6 个页面在 6 个视口下无页面级横向溢出，均无竖排错位。
2. DESIGN §14.1 视觉清单全部打勾。
3. §4 Phase 6.4 的 6 条机械判据全绿。
4. 报价全流程（上传→计算→穿透→对比→导出）与工具箱 4 页计算结果**与重构前一致**（数值不回归）。
5. 全部功能与七态未缺失。
