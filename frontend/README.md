# 网页版前端源码

这是独立的 HTML/CSS/JavaScript 页面，不依赖 Streamlit。

直接双击 `index.html` 即可预览；也可以在 `frontend` 目录运行：

```powershell
python -m http.server 8080
```

然后打开 <http://localhost:8080>。

当前版本已实现界面、导航、参数填写、文件选择，并已接入 FastAPI/Python 计算接口。

启动后端：

```powershell
cd "E:\liam proj\work\2026-09-15-19-46-14\bid-pricing"
python -m pip install -r requirements-web.txt
$env:PYTHONPATH = "src"
uvicorn api.app:app --reload --port 8000
```

然后另开终端启动本页面：

```powershell
cd frontend
python -m http.server 8080
```
