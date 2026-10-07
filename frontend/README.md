# 网页版前端源码

这是独立的 HTML/CSS/JavaScript 页面：不依赖 Streamlit、不打包、无构建步骤。

直接双击 `index.html` 即可预览；也可以在 `frontend` 目录运行：

```powershell
python -m http.server 8080
```

然后打开 <http://localhost:8080>。

当前版本已实现界面、导航、参数填写、文件选择，并已接入 FastAPI/Python 计算接口。

启动后端（在**仓库根目录**执行——路径随仓库位置而变，不要写死绝对路径）：

```powershell
python -m pip install -r requirements-web.txt
$env:PYTHONPATH = "src"
uvicorn api.app:app --reload --port 8000
```

或直接用仓库根目录的 `.\run.ps1` 一键起「后端 8000 + 前端 8080 + 可选边车」，
它自带解释器能力探测、端口预检与真实探活（详见该脚本头部注释）。

## 两条加载顺序约定（改页面时必须遵守）

1. **脚本**：`js/escape.js` 必须是**第一个** `<script>` —— 它是全站唯一的 HTML 转义实现，
   契约见其文件头；随后 `js/workbench-nav.js` → `js/sidebar.js` → 其余页面脚本。
   业务脚本一律 `const esc = window.gcEsc;` 之类**别名**，禁止自带实现
   （历史上副本最多长到 6 份，一份漏改就开洞）。
2. **样式**：`tokens.css`（唯一令牌源）→ `styles.css`（设计系统层 + 跨页共用基础件）
   → 视图层（`quote-dashboard.css` / `tools.css`）→ `results.css` → `agent.css`。
   `agent.css` 只含 `.agent-*`，与其它样式文件选择器集合无交集，但顺序仍须全站一致。
   **工具页不加载 `quote-dashboard.css`**（报价页视图层）：实测它们只用到
   `.title-dot` / `.card-subtitle` / `.tabular` 三个基础件，已收进 `styles.css`；
   依赖面由判据钉住（新增依赖会红）。

## 破缓存令牌（`?v=`）规则

- 同一份资产在**所有**引用它的页面里必须用**同一个**令牌——否则改了共享脚本/样式，
  只有部分页面生效（历史坑：`tool-common.js` 在 cable/well 是 `p2`、在 duct/earth 是 `duct`）。
- 只有文件的**行为**变了才升令牌；纯注释改动不升。
- 令牌只是个串，没有任何构建步骤会替你同步它：改完请自查全部引用页——
  `npm test` 里有这条判据（同一资产多令牌即失败）。

## 前端回归冒烟（jsdom）

静态看代码看不出、一运行才炸的问题，已做成机械判据：

```powershell
cd frontend
npm ci        # 首次或依赖变更后（jsdom 30 要求 Node ≥ 22.22.2 / 24.15）
npm test      # node --test，28 项
```

| 文件 | 覆盖 |
|---|---|
| `test/smoke.test.mjs` | 6 个页面按真实顺序执行脚本无未捕获错误；`js/escape.js` 必须是每页第一个脚本；`toolEsc === gcEsc` 且五字符全转义；同一资产令牌一致；引用的本地资产都存在；`tool-well` 在「钢筋表非空 + 支室数>0」下不抛错；**静态契约**：坞主 CTA 无不可达回退分支（R6）、确认框只有一个创建点（R9）、孤儿样式表已删且 `:root` 仅在 tokens.css（R12）、工具页不依赖报价页视图层（R14） |
| `test/quote-flow.test.mjs` | 报价页交互路径：R5 焦点陷阱栈不平衡、R6 坞主 CTA 情境路由、R7 预览后导出仍指上一轮结果、R8 空目标报价被占位默认值兜成 `0.00`、R9 确认框的返回值/焦点陷阱/文案口径 |
| `test/_harness.mjs` | 共享加载器（内联脚本 → jsdom；fetch 桩；`waitForInit`） |

**静态判据先剥注释再看代码**（`stripJsComments` / `stripHtmlComments`）：本轮实测两条判据被自己的说明性
注释绊红（注释里为了讲清历史写了 `calculateBtn.click()` 与 `quote-dashboard.css`）——与本仓 CC-12 /
BB-05 记的是同一条教训：要拦的是**代码路径上的硬拷贝**，不是文档里提到这个词。

**新增测试文件要加进 `package.json` 的 `test` 脚本里**（显式文件列表，不用目录扫描：
`test/` 下的辅助模块会被 Node 的默认发现当成测试文件，多出一个 0 用例的空条目）。

三处**jsdom 时序陷阱**已在 `test/_harness.mjs` 里注释并封装，写新交互用例前请先读：
初始化尾部（被 `setTimeout` 延后的初始模块选择）会 `closeOverlays()` 并清空结果态；
加载后再改 `location.hash` 会排入额外 hashchange（应改为加载时带 `#quote`）；
「等请求已发出」不等于「等渲染完成」（要等可观察状态，如按钮 disabled 翻转）。

**边界**：jsdom 不是浏览器——没有布局与绘制，SVG 与部分 DOM API 覆盖有限。它能拦
「运行就炸」与「状态没跟着走」，**拦不住视觉回归**；视觉仍需人看。
