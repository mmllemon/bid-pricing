"""导入预览（H-006）：上传后先核对行数/字段覆盖/匹配覆盖/异常/待人工项/重复编码。

与求解层解耦、只依赖 ``MatchReport``，因此可以直接做单元测试（不拉起 FastAPI）。
API 层只做「读文件 → _parse_clean_match → 本模块」的接线，不做任何业务计算。
"""
from __future__ import annotations

from collections import Counter

from .io.match import MatchReport

#: 预览/优化共同依赖的"可适配字段"（用于字段映射/模板适配提示）。
PREVIEW_FIELDS = ("item_id", "item_name", "unit", "q0", "cap", "q1_point", "c_i")


def field_map(matched: MatchReport) -> dict[str, bool]:
    """模板适配预览：每个逻辑字段是否至少有 1 行被识别出来（任一侧）。"""
    return {key: any(getattr(m, key, None) is not None for m in matched.items)
            for key in PREVIEW_FIELDS}


def build_listing_preview(matched: MatchReport, project_id: str) -> dict:
    """构造导入预览：行数、字段覆盖、匹配覆盖、异常、待人工项、重复编码。"""
    cap_uws = Counter(m.unit_work for m in matched.items if m.cap_row)
    cost_uws = Counter(m.unit_work for m in matched.items if m.cost_row)
    by_id: dict[str, set] = {}
    for m in matched.items:
        by_id.setdefault(m.item_id, set()).add(m.unit_work)
    dup_cross_uw = sorted(iid for iid, uws in by_id.items() if len(uws) > 1)
    complete = lambda m: all(x is not None for x in (m.q0, m.q1_point, m.c_i, m.cap))
    optimizable = [m for m in matched.items if complete(m)]
    manual = [m for m in matched.items if not complete(m)]
    missing_cap = sorted(m.item_id for m in manual if m.cap is None)
    missing_cost = sorted(m.item_id for m in manual if m.c_i is None or m.q1_point is None)
    return {
        "status": "PASS",
        "project_id": project_id,
        "cap": {"rows": matched.n_cap_rows, "unit_works": dict(cap_uws)},
        "cost": {"rows": matched.n_cost_rows, "unit_works": dict(cost_uws)},
        "fields": field_map(matched),
        "match": {
            "master_keys": matched.n_master, "matched": matched.n_matched,
            "only_cap": matched.n_only_cap, "only_cost": matched.n_only_cost,
            "only_cap_ids": sorted(m.item_id for m in matched.items if m.cap_row and not m.cost_row),
            "only_cost_ids": sorted(m.item_id for m in matched.items if m.cost_row and not m.cap_row),
            "blocked": matched.blocked, "duplicate_keys": list(matched.duplicate_keys),
        },
        "coverage": dict(matched.coverage),
        "anomaly_count": len(matched.anomalies),
        "anomalies": [a.to_dict() for a in matched.anomalies],
        "optimizable_count": len(optimizable),
        "manual_count": len(manual),
        "missing_cap_ids": missing_cap,
        "missing_cost_ids": missing_cost,
        "duplicate_item_id_across_unit_work": dup_cross_uw,
    }