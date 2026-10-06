"""lshu-workbench（Express，默认 :3456）的过渡期反向代理。

为什么需要这一层：
    lshu 的 CORS 白名单只放行 localhost:5173/5180/3456（见其
    backend/src/http/localCors.ts），不含静态前端的 8080；而本项目静态前端由
    `python -m http.server` 提供（run.ps1），没有反代能力。因此统一由 FastAPI
    转发，前端只认 8000 一个后端——与既有 /api/project/* 同源同 CORS 策略。

路径约定：
    /api/wb/<path>  →  http://127.0.0.1:3456/api/<path>
    与项目自有 /api/project/*、/api/group/* 无前缀冲突。

收编期用法（D-2 strangler fig）：
    每个模块用 Python 重写等价接口后，在本层把该路径短路成本地实现即可——
    前端契约（/api/wb/<path>）不变，页面零改动。全部收编完，Node/Express 下线。

只依赖标准库 urllib：本项目的 Python 环境没有 httpx / requests，
不为了一个过渡层新增依赖。
"""
from __future__ import annotations

import asyncio
import os
import urllib.error
import urllib.request

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

router = APIRouter()

#: 上游地址。可用环境变量覆盖（lshu 换端口时无需改代码）。
UPSTREAM = os.environ.get("WORKBENCH_UPSTREAM", "http://127.0.0.1:3456").rstrip("/")
#: 单次转发超时（秒）。上游是本地 SQLite 读取，正常在毫秒级；30s 只用于兜住异常。
_PROXY_TIMEOUT = float(os.environ.get("WORKBENCH_PROXY_TIMEOUT", "30"))

#: 逐跳首部：由本层自行决定，不透传（RFC 9110 §7.6.1）。
#: content-length/content-encoding 一并剥离：长度由本层按实际字节重算，
#: 编码本层不参与（已向上游声明 identity），透传会导致长度不符或二次解压。
_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
    "content-length", "content-encoding", "host",
})

#: 浏览器上下文首部：本层是服务端到服务端的转发，这些首部描述的是「浏览器从哪个页面
#: 发起」，对上游没有意义，必须剥离。**这不是可选项**——lshu 的 localCors 只放行
#: 5173/5180/3456，若把本项目的 Origin（:8080）透传上去，上游会直接 500
#: `CORS origin denied`。剥离后 isAllowedCorsOrigin(undefined) 为 true，正常放行。
#: （P1 只用 curl 验过反代，curl 不发 Origin，故此缺陷当时未暴露。）
_BROWSER_CONTEXT = frozenset({"origin", "referer"})


def _forward(req: urllib.request.Request) -> tuple[int, list[tuple[str, str]], bytes]:
    """同步转发（由 asyncio.to_thread 承载，不阻塞事件循环）。

    HTTPError 是 urllib 表达「上游返回了 4xx/5xx」的方式，它也是合法响应，
    必须按响应而非异常向上抛——否则上游的 400/404 会被误报成 502。
    """
    try:
        with urllib.request.urlopen(req, timeout=_PROXY_TIMEOUT) as resp:
            return resp.status, list(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, list(exc.headers.items()), exc.read()


@router.api_route(
    "/api/wb/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
async def proxy_workbench(path: str, request: Request) -> Response:
    query = request.url.query
    target = f"{UPSTREAM}/api/{path}" + (f"?{query}" if query else "")

    body = await request.body()
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP and k.lower() not in _BROWSER_CONTEXT
    }
    # 让上游不做压缩：urllib 不会自动解压，压缩体透传出去浏览器也会二次解压失败。
    headers["accept-encoding"] = "identity"

    upstream_req = urllib.request.Request(
        target,
        data=body if body else None,
        method=request.method,
        headers=headers,
    )

    try:
        status, resp_headers, payload = await asyncio.to_thread(_forward, upstream_req)
    except Exception as exc:  # noqa: BLE001 连接层故障一律收敛成 502，避免 500 掩盖病因
        return JSONResponse(
            status_code=502,
            content={
                "status": "UPSTREAM_UNAVAILABLE",
                "reason": f"lshu-workbench 上游不可达（{UPSTREAM}）：{exc}",
                "hint": "确认 :3456 已启动（run.ps1 会尝试拉起；也可手工跑 skill 目录的 Start.ps1）。",
            },
        )

    out_headers = [(k, v) for k, v in resp_headers if k.lower() not in _HOP_BY_HOP]
    # media_type=None 表示不由本层补 content-type，沿用上游那一条（含其 charset）。
    return Response(content=payload, status_code=status, headers=dict(out_headers), media_type=None)
