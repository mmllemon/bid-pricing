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
2. **样式**：`tokens.css`（唯一令牌源）→ `styles.css`（设计系统层）→ 视图层
   （`quote-dashboard.css` / `tools.css`）→ `results.css` → `agent.css`。
   `agent.css` 只含 `.agent-*`，与其它样式文件选择器集合无交集，但顺序仍须全站一致。

## 破缓存令牌（`?v=`）规则

- 同一份资产在**所有**引用它的页面里必须用**同一个**令牌——否则改了共享脚本/样式，
  只有部分页面生效（历史坑：`tool-common.js` 在 cable/well 是 `p2`、在 duct/earth 是 `duct`）。
- 只有文件的**行为**变了才升令牌；纯注释改动不升。
- 令牌只是个串，没有任何构建步骤会替你同步它：改完请自查全部引用页。
