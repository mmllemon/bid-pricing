"""反代分流前缀一致性（前端唯一入口 :3456 能否走到后端路由）。

背景（回归 2026-10-08）：前端整合后 :3456 是唯一入口，报价域 /api/* 由
workbench-server/src/quoteProxy.ts 按 QUOTE_PREFIXES 同源反代到 :8000，其余 /api/*
由 workbench-server 本地处理。新增「关联图谱」时后端加了 /api/graph/*，但本表漏登记
'graph' —— 前端经 :3456 调 /api/graph/units 得 404（直连 :8000 才 200），图谱页
在真实使用路径上完全不可用。

这类「手工清单 ↔ 真实来源」的漂移（同族：sqlite_store._SCHEMA_OBJECTS 漏登记新表）
靠人记同步必然复发。本测试机械比对三方集合，漏登记即刻红：

    api/app.py 里的 /api/<seg>  ⊆  QUOTE_PREFIXES（反代）  ∪  workbench 本地段

另两条不变量：
  - QUOTE_PREFIXES ⊆ api 段：反代表里不得有后端不存在的段（否则转发到上游 404）。
  - 本地段 ∩ QUOTE_PREFIXES == 空：分流边界两边零重叠（quoteProxy 注释的声明）。

api/ 当前只有 app.py、无 APIRouter，故直接扫 app.py 即可覆盖全部后端路由。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_APP = ROOT / "api" / "app.py"
WB_SRC = ROOT / "workbench-server" / "src"
QUOTE_PROXY = WB_SRC / "quoteProxy.ts"

# FastAPI：@app.get("/api/<seg>/...")
_API_ROUTE_RE = re.compile(r"""@app\.(?:get|post|put|delete|patch)\(\s*['"]/api/([^/'"]+)""")
# Express：app.get('/api/<seg>/...')
_TS_ROUTE_RE = re.compile(r"""\.(?:get|post|put|delete|patch)\(\s*['"]/api/([^/'"]+)""")
# QUOTE_PREFIXES = new Set([ 'quote', ... ])
_SET_BLOCK_RE = re.compile(r"QUOTE_PREFIXES\s*=\s*new\s+Set\(\s*\[(.*?)\]\s*\)", re.S)
_TOKEN_RE = re.compile(r"'([^']+)'")


def _api_segments() -> set[str]:
    text = API_APP.read_text(encoding="utf-8")
    return {m.group(1) for m in _API_ROUTE_RE.finditer(text)}


def _workbench_segments() -> set[str]:
    segs: set[str] = set()
    for f in WB_SRC.rglob("*.ts"):
        if f.name.endswith(".test.ts"):
            continue
        segs.update(m.group(1) for m in _TS_ROUTE_RE.finditer(f.read_text(encoding="utf-8")))
    return segs


def _quote_prefixes() -> set[str]:
    text = QUOTE_PROXY.read_text(encoding="utf-8")
    m = _SET_BLOCK_RE.search(text)
    if not m:
        raise AssertionError("未能在 quoteProxy.ts 里定位 QUOTE_PREFIXES 集合声明")
    return set(_TOKEN_RE.findall(m.group(1)))


class FrontendProxyPrefixesTest(unittest.TestCase):
    def test_api_routes_reachable_through_single_entry(self):
        """后端每个 /api/<seg> 必须被反代表或工作台本地段覆盖，否则经 :3456 得 404。"""
        api, proxy, local = _api_segments(), _quote_prefixes(), _workbench_segments()
        uncovered = sorted(api - proxy - local)
        self.assertEqual(
            uncovered, [],
            msg=(f"这些后端路由段经唯一入口 :3456 不可达（未登记反代、也非工作台本地）：{uncovered}。"
                 "把它们加进 workbench-server/src/quoteProxy.ts 的 QUOTE_PREFIXES，"
                 "或确认应由工作台本地处理。"),
        )

    def test_proxy_prefixes_all_exist_in_backend(self):
        """反代表里的段必须在后端存在，否则是转发到上游 404 的死前缀。"""
        api, proxy = _api_segments(), _quote_prefixes()
        dead = sorted(proxy - api)
        self.assertEqual(dead, [], msg=f"QUOTE_PREFIXES 里这些段后端没有对应路由（死转发）：{dead}")

    def test_proxy_and_local_disjoint(self):
        """分流边界两边零重叠：本地段不得同时出现在反代表里。"""
        proxy, local = _quote_prefixes(), _workbench_segments()
        both = sorted(proxy & local)
        self.assertEqual(both, [], msg=f"这些段同时属于反代与工作台本地，分流边界重叠：{both}")


if __name__ == "__main__":
    unittest.main()
