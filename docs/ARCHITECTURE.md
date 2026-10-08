# 系统架构

> 给非程序员维护者的一页纸：出问题先看这张图，知道去哪找。

## 进程

```
┌─────────────┐         ┌──────────────┐
│  :3456      │         │  :8000       │
│  Node       │────────▶│  Python      │
│  Express    │  反代   │  FastAPI     │
│             │ /api/*  │              │
│ 唯一 Web    │         │  纯后端 API  │
│ 入口        │         │              │
└─────────────┘         └──────────────┘
       │                        │
       │ React SPA              │ 报价计算
       │ 工作台 API             │ 文件解析
       │ /agent                 │ 数据存储
```

- **:3456**（`workbench-server/`）：用户唯一访问的端口。React 前端 + 工作台 API（待办/知识库/财务）+ `/agent` + 报价接口反代到 :8000。
- **:8000**（`api/app.py`）：纯后端。报价计算、BOQ 解析、SQLite 数据。

`run.ps1` 一键启动两个进程，`Ctrl+C` 全停。

## 数据在哪

| 数据 | 位置 | 说明 |
|------|------|------|
| 报价方案/组 | SQLite（`outputs/projects/<user>/quote.db`） | 唯一真相源 |
| 项目概览 | SQLite + `projects.json`（导出视图） | ⚠️ 双真相待收敛（B-P1-2） |
| 执行七表 | SQLite（同库） | 收入合同/成本台帐/进度款/签证变更 |
| 项目文档 | 文件（`outputs/projects/<user>/docs/`）+ 元数据进库 | |
| 待办/知识库 | Node 侧 better-sqlite3 | 工作台数据 |
| 快照/UI 偏好 | 浏览器 localStorage | 不重要，可丢 |

**备份**：拷走整个 `outputs/` 目录即可。

## 前端路由

| 路径 | 页面 |
|------|------|
| `/portal` | 全景大盘（Pixel Neural Portal） |
| `/biz` | 项目经营（看板） |
| `/biz/:id` | 项目主页（5 Tab） |
| `/quote` | 投标报价 |
| `/tools` | 速算工具箱 |
| `/tools/cable\|duct\|earthwork\|manhole` | 4 个速算工具 |
| `/todos` `/finance` `/knowledge` `/hotspots` | 待办/财务/知识库/热点 |
| `/scan` `/settings` `/performance` | 扫描/设置/内容表现 |

## 出问题先看哪

| 现象 | 看哪 |
|------|------|
| 页面打不开 | :3456 进程在不在（`run.ps1` 输出） |
| 报价计算报错 | :8000 日志（`outputs/logs/`） |
| 数据丢了 | `outputs/` 在不在，先别动，拷走再查 |
| Portal 布局错乱 | `portalEngine.ts` 的 `targets()`，先跑 `portalEngine.test.ts` |
