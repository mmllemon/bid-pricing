"""T01-04 三表交叉匹配 —— master item set 基准 LEFT JOIN + 异常清单。

**「三表」在已裁定输入模型下的收缩**（2026-09-16）：原路线按 3 份示例模板
设计（输入 A 限价 / 输入 B 结算量 / 输入 C 成本）；用户裁定**输入 B 由输入
C 兼任**（成本清单工程量 = 投标人对结算量的预判），因此实际参与匹配的是
**两侧**：cap 侧（q0/cap）与 cost 侧（q1_point/c_i）。

* **master item set = 两侧 key 的并集**——不是单侧。只在一侧存在的 key
  是「未匹配项」，**100% 进异常清单，禁止静默丢弃**（任务判据原文）。
* **key = (project_id, unit_work, item_id)**——与解析/清洗层同一主键；
  序号不可作主键（分节内各自重算），位数不参与合法性（D1）。
* **同侧重复 key 必须 BLOCK，禁止自动合并**（T01-04A 判据的机械部分，
  在匹配时点执行——合并等于擅自替用户决定哪一行是真数据）。
* **no_cap 是合法语义不是异常**（ALLOW_EMPTY_NO_CAP 裁定：cap 空 = 不限价
  但不得为 0）；它计入 missing_limit 覆盖统计，但**不得**与「cap 侧缺行」
  混同——前者有上界兜底（P* ≤ P*_max），后者连键都不存在。
* 匹配器只做机械比对，**不猜、不补、不静默丢弃**——与解析器/清洗器同一纪律。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .clean import CleanRow

__all__ = [
    "MatchedItem",
    "AnomalyRow",
    "MatchReport",
    "match_key",
    "match_canonical_rows",
]

ANOMALY_ONLY_IN_CAP = "ONLY_IN_CAP"
ANOMALY_ONLY_IN_COST = "ONLY_IN_COST"
ANOMALY_DUP_CAP = "DUPLICATE_KEY_CAP"
ANOMALY_DUP_COST = "DUPLICATE_KEY_COST"
ANOMALY_ZERO_CAP = "ZERO_PRICE_CAP"
ANOMALY_ZERO_COST = "ZERO_PRICE_COST"
ANOMALY_ATTR_MISMATCH = "ATTRIBUTE_MISMATCH"


def match_key(row: CleanRow) -> tuple[str, str, str]:
    """canonical 主键：(project_id, unit_work, item_id)。"""
    return (row.project_id, row.unit_work, row.item_id)


@dataclass
class MatchedItem:
    """master item set 中一个键的融合行（两侧字段 + 各自溯源）。

    任一侧缺行时其字段保持 ``None``——**缺行 ≠ 缺值 ≠ 值为 0**，
    三种状态在字段层必须可区分（ADR-0004 同源：不把「没有」压成一个值）。
    """

    project_id: str
    unit_work: str
    item_id: str
    code_kind: str
    item_name: str
    unit: str
    # cap 侧
    q0: float | None = None
    cap: float | None = None
    no_cap: bool = False
    cap_row: bool = False          # cap 侧该键是否存在（缺行时下方字段全 None）
    # cost 侧
    q1_point: float | None = None
    c_i: float | None = None
    cost_row: bool = False
    attribution: str | None = None
    pass_through: bool = False
    # 覆盖缺口（任务判据的三个逐字段计数逐项落在本行）
    missing: list[str] = field(default_factory=list)   # missing_limit/missing_cost/missing_quantity(_cap/_cost)
    anomalies: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AnomalyRow:
    """异常清单的一行：未匹配项 / 重复 key / 零价信号 / 属性不一致。

    异常**不阻断输出**（matched 行照常产出），但**阻断求解**——求解层
    不得在存在 DUPLICATE_KEY 或 ONLY_IN_* 异常时静默启动。
    """

    kind: str
    project_id: str
    unit_work: str
    item_id: str
    detail: str
    provenance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MatchReport:
    """匹配报告：master 并集 + 覆盖率 + 异常清单，无任何静默丢弃。"""

    n_cap_rows: int = 0
    n_cost_rows: int = 0
    n_master: int = 0
    n_matched: int = 0              # 两侧都有行
    n_only_cap: int = 0
    n_only_cost: int = 0
    n_no_cap: int = 0               # cap 值空（合法语义，单独计数）
    coverage: dict = field(default_factory=dict)   # missing_limit/cost/quantity(_cap/_cost)
    duplicate_keys: list[str] = field(default_factory=list)   # 触发 BLOCK 的键（格式化串）
    blocked: bool = False           # 同侧重复 key → True，禁止自动合并
    anomalies: list[AnomalyRow] = field(default_factory=list)
    items: list[MatchedItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["items"] = [i.to_dict() for i in self.items]
        d["anomalies"] = [a.to_dict() for a in self.anomalies]
        return d

    def summary_line(self) -> str:
        cov = self.coverage
        return (
            f"master {self.n_master} 键：两侧齐备 {self.n_matched}、"
            f"仅限价侧 {self.n_only_cap}、仅成本侧 {self.n_only_cost}；"
            f"缺失覆盖 missing_limit={cov.get('missing_limit', 0)} "
            f"missing_cost={cov.get('missing_cost', 0)} "
            f"missing_quantity={cov.get('missing_quantity', 0)}；"
            f"异常 {len(self.anomalies)} 条"
            + ("；**BLOCKED：同侧重复 key**" if self.blocked else "")
        )


def _dup_anomalies(
    rows: list[CleanRow], side_label: str, kind: str
) -> tuple[dict[tuple[str, str, str], list[CleanRow]], list[AnomalyRow], list[str]]:
    """同侧按 key 分组；重复 key 全部副本进异常清单，禁止自动合并。"""
    groups: dict[tuple[str, str, str], list[CleanRow]] = {}
    for r in rows:
        groups.setdefault(match_key(r), []).append(r)
    anomalies: list[AnomalyRow] = []
    dup_keys: list[str] = []
    for key, grp in groups.items():
        if len(grp) > 1:
            dup_keys.append("|".join(key))
            for r in grp:
                anomalies.append(AnomalyRow(
                    kind=kind, project_id=r.project_id, unit_work=r.unit_work,
                    item_id=r.item_id,
                    detail=f"{side_label}侧同键出现 {len(grp)} 次（source "
                           f"{r.provenance.get('source_sheet')} r{r.provenance.get('source_row')}）"
                           f"；禁止自动合并，须人工裁定保留哪一行",
                    provenance=dict(r.provenance),
                ))
    return groups, anomalies, dup_keys


def match_canonical_rows(cap_rows: list[CleanRow], cost_rows: list[CleanRow]) -> MatchReport:
    """两侧 canonical 行 → master 并集融合 + 覆盖率 + 异常清单。

    master item set = cap ∪ cost 的 key 并集。未匹配项 100% 进异常清单；
    同侧重复 key → ``blocked=True``（禁止自动合并）。
    """
    rep = MatchReport(n_cap_rows=len(cap_rows), n_cost_rows=len(cost_rows))

    cap_groups, cap_dups, cap_dup_keys = _dup_anomalies(cap_rows, "限价", ANOMALY_DUP_CAP)
    cost_groups, cost_dups, cost_dup_keys = _dup_anomalies(cost_rows, "成本", ANOMALY_DUP_COST)
    rep.anomalies.extend(cap_dups)
    rep.anomalies.extend(cost_dups)
    rep.duplicate_keys = cap_dup_keys + cost_dup_keys
    rep.blocked = bool(cap_dup_keys or cost_dup_keys)

    # 保留输入清单顺序：限价清单是报价表的主展示顺序，成本侧仅有的新增项
    # 按其在成本清单中的原始顺序追加。不要用 sorted(set(...))，否则项目编码
    # 会被重新排序，导致输出表与用户原清单难以逐行对齐。
    master: list[tuple[str, str, str]] = []
    seen_master: set[tuple[str, str, str]] = set()
    for row in [*cap_rows, *cost_rows]:
        key = match_key(row)
        if key not in seen_master:
            seen_master.add(key)
            master.append(key)
    rep.n_master = len(master)

    cov = {
        "missing_limit": 0,
        "missing_cost": 0,
        "missing_quantity": 0,
        "missing_quantity_cap": 0,
        "missing_quantity_cost": 0,
    }

    for key in master:
        project_id, unit_work, item_id = key
        crows = cap_groups.get(key, [])
        srows = cost_groups.get(key, [])
        crow = crows[0] if crows else None
        srow = srows[0] if srows else None

        item = MatchedItem(
            project_id=project_id,
            unit_work=unit_work,
            item_id=item_id,
            code_kind=(crow or srow).code_kind,
            item_name=(crow or srow).item_name,
            unit=(crow or srow).unit,
            cap_row=crow is not None,
            cost_row=srow is not None,
            provenance={
                "cap": dict(crow.provenance) if crow else None,
                "cost": dict(srow.provenance) if srow else None,
            },
        )

        if crow is not None:
            item.q0, item.cap, item.no_cap = crow.q0, crow.cap, crow.no_cap
        if srow is not None:
            item.q1_point, item.c_i = srow.q1_point, srow.c_i
            item.attribution = srow.attribution
        item.pass_through = bool((crow and crow.pass_through) or (srow and srow.pass_through))

        missing: list[str] = []
        # missing_limit：cap 值缺失（含仅 cost 侧存在）。no_cap 是合法语义，
        # 计数但走独立通道（n_no_cap），不进异常清单。
        if crow is None or crow.cap is None:
            missing.append("missing_limit")
            cov["missing_limit"] += 1
            if crow is not None and crow.no_cap:
                rep.n_no_cap += 1
        # missing_cost：成本价缺失（含仅 cap 侧存在）——该项无法进目标/下界。
        if srow is None or srow.c_i is None:
            missing.append("missing_cost")
            cov["missing_cost"] += 1
        # missing_quantity：任一侧量缺失（细分两个计数供归因）。
        if crow is None or crow.q0 is None:
            missing.append("missing_quantity_cap")
            cov["missing_quantity_cap"] += 1
        if srow is None or srow.q1_point is None:
            missing.append("missing_quantity_cost")
            cov["missing_quantity_cost"] += 1
        if "missing_quantity_cap" in missing or "missing_quantity_cost" in missing:
            missing.append("missing_quantity")
            cov["missing_quantity"] += 1
        item.missing = missing

        # 未匹配项 100% 进异常清单（禁止静默丢弃）
        if crow is None:
            rep.n_only_cost += 1
            item.anomalies.append(ANOMALY_ONLY_IN_COST)
            rep.anomalies.append(AnomalyRow(
                kind=ANOMALY_ONLY_IN_COST, project_id=project_id,
                unit_work=unit_work, item_id=item_id,
                detail="仅成本清单存在此键，限价清单无对应行——无最高限价锚点，"
                       "该单价进不了 C2 上界，须人工确认是新增项还是编码不一致",
                provenance={"cost": dict(srow.provenance) if srow else {}},
            ))
        if srow is None:
            rep.n_only_cap += 1
            item.anomalies.append(ANOMALY_ONLY_IN_CAP)
            rep.anomalies.append(AnomalyRow(
                kind=ANOMALY_ONLY_IN_CAP, project_id=project_id,
                unit_work=unit_work, item_id=item_id,
                detail="仅限价清单存在此键，成本清单无对应行——无成本锚点（c_i 缺失），"
                       "C4 成本地板与目标函数都吃不到这一项，须人工补成本或确认可放弃项",
                provenance={"cap": dict(crow.provenance) if crow else {}},
            ))

        # 零价信号（C5：单项报价不得为 0）——机械信号，交人工确认
        if crow is not None and crow.zero_price:
            item.anomalies.append(ANOMALY_ZERO_CAP)
            rep.anomalies.append(AnomalyRow(
                kind=ANOMALY_ZERO_CAP, project_id=project_id,
                unit_work=unit_work, item_id=item_id,
                detail="限价清单单价为 0——C5（报价≠0）与 cap=0 组合下该单项无合法报价空间",
                provenance=dict(crow.provenance),
            ))
        if srow is not None and srow.zero_price:
            item.anomalies.append(ANOMALY_ZERO_COST)
            rep.anomalies.append(AnomalyRow(
                kind=ANOMALY_ZERO_COST, project_id=project_id,
                unit_work=unit_work, item_id=item_id,
                detail="成本清单单价为 0——成本口径存疑（是赠项还是漏填？），不得默认按 0 成本优化",
                provenance=dict(srow.provenance),
            ))

        # 属性一致性（信息性 WARN 级异常）：两侧名称/单位应一致（用户口径：
        # 成本清单编码/名称/特征/单位与限价清单完全一致），不一致 ≈ 键对错位的前兆
        if crow is not None and srow is not None:
            if crow.item_name and srow.item_name and crow.item_name != srow.item_name:
                item.anomalies.append(ANOMALY_ATTR_MISMATCH)
                rep.anomalies.append(AnomalyRow(
                    kind=ANOMALY_ATTR_MISMATCH, project_id=project_id,
                    unit_work=unit_work, item_id=item_id,
                    detail=f"两侧名称不一致：限价「{crow.item_name}」/ 成本「{srow.item_name}」",
                    provenance={"cap": dict(crow.provenance), "cost": dict(srow.provenance)},
                ))
            if crow.unit and srow.unit and crow.unit != srow.unit:
                item.anomalies.append(ANOMALY_ATTR_MISMATCH)
                rep.anomalies.append(AnomalyRow(
                    kind=ANOMALY_ATTR_MISMATCH, project_id=project_id,
                    unit_work=unit_work, item_id=item_id,
                    detail=f"两侧单位不一致：限价「{crow.unit}」/ 成本「{srow.unit}」",
                    provenance={"cap": dict(crow.provenance), "cost": dict(srow.provenance)},
                ))

        if crow is not None and srow is not None:
            rep.n_matched += 1
        rep.items.append(item)

    rep.coverage = cov
    return rep
