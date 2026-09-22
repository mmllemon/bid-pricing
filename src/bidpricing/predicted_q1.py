"""T07-03/T07-04 predicted_q1 独立来源声明书：登记、加载、交叉校验与值合并。

q1 在投标期不可观测（config/q1_assumption_spec.json 的 observability 一栏）：
一切 predicted_q1 取值都是假设，不是数据。声明书就是这份假设的**可审计事实源**：

- 留痕四件必须齐备：source / declared_by / declared_at / rationale（缺件拒登）；
- source 必须登记在 spec.source_domain（与 closed_loop_spec.predicted_q1_sources
  由测试双向锁定），且不得与 actual_q1 绑定源 cost.q1_point 同源（该判据在
  closed_loop.check_predicted_source 处执行，此处只管 schema 侧）；
- 值必须是非负实数，缺项不静默补 0；
- 闭环 bundle 引用声明书后，逐项 predicted_q1 以声明书为准：
  records 里已带值必须逐项相等（不等 = 篡改/漂移），未覆盖项 = 无登记来源。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

SPEC_FILENAME = "predicted_q1_spec.json"
DECLARATION_SCHEMA_ID = "predicted_q1_declaration_v1"
PROVENANCE_FIELDS = ("source", "declared_by", "declared_at", "rationale")


class PredictionDeclarationError(ValueError):
    """声明书结构/留痕非法，或登记条件不满足。"""


@dataclass(frozen=True)
class PredictedQ1Declaration:
    source: str
    declared_by: str
    declared_at: str
    rationale: str
    records: Mapping[str, float]
    path: str | None

    def items(self) -> tuple[str, ...]:
        return tuple(sorted(self.records))

    def to_doc(self) -> dict[str, Any]:
        return {
            "schema_id": DECLARATION_SCHEMA_ID,
            "source": self.source,
            "declared_by": self.declared_by,
            "declared_at": self.declared_at,
            "rationale": self.rationale,
            "records": [
                {"item": item, "predicted_q1": self.records[item]} for item in self.items()
            ],
        }


def load_predicted_q1_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


def _validate_values(raw_records: list[Any], errors: list[str]) -> dict[str, float]:
    records: dict[str, float] = {}
    for raw in raw_records:
        if not isinstance(raw, Mapping):
            errors.append("records 每项须为对象")
            continue
        item = str(raw.get("item") or "")
        value = raw.get("predicted_q1")
        if not item:
            errors.append("records 存在缺 item 的行")
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{item}: predicted_q1 须为数值（收到 {type(value).__name__}）")
            continue
        if value < 0:
            errors.append(f"{item}: predicted_q1 不得为负")
            continue
        if item in records:
            errors.append(f"{item}: 重复项——同项多版本须另行声明，不得混写")
            continue
        records[item] = float(value)
    return records


def _validate_provenance(doc: Mapping[str, Any], errors: list[str]) -> dict[str, str]:
    provenance: dict[str, str] = {}
    for key in ("source", "declared_by", "declared_at", "rationale"):
        value = doc.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"留痕缺失：{key}")
            provenance[key] = ""
        else:
            provenance[key] = value
    return provenance


def load_declaration(path: Path | str) -> PredictedQ1Declaration:
    """加载并结构校验一份声明书（source 域是否登记由闭环层判，本层只判结构）。"""
    p = Path(path)
    if not p.exists():
        raise PredictionDeclarationError(f"声明书不存在：{p}")
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PredictionDeclarationError(f"声明书不是合法 JSON：{exc}") from exc
    if not isinstance(doc, Mapping):
        raise PredictionDeclarationError("声明书必须是 JSON 对象")
    errors: list[str] = []
    if doc.get("schema_id") != DECLARATION_SCHEMA_ID:
        errors.append(f"schema_id 须为 {DECLARATION_SCHEMA_ID!r}（收到 {doc.get('schema_id')!r}）")
    provenance = _validate_provenance(doc, errors)
    raw_records = doc.get("records") or []
    if not isinstance(raw_records, list):
        errors.append("records 须为对象数组")
        records: dict[str, float] | None = None
    else:
        records = _validate_values(raw_records, errors)
        if not records:
            errors.append("records 为空——空声明无意义，拒绝作为事实源")
    if errors or records is None:
        raise PredictionDeclarationError("声明书非法：" + "；".join(errors))
    return PredictedQ1Declaration(
        source=provenance["source"],
        declared_by=provenance["declared_by"],
        declared_at=provenance["declared_at"],
        rationale=provenance["rationale"],
        records=records,
        path=str(p),
    )


def register_declaration(
    *,
    source: str,
    records: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    declared_by: str,
    declared_at: str,
    rationale: str,
    spec: Mapping[str, Any],
    out_path: Path | str,
    replace: bool = False,
) -> PredictedQ1Declaration:
    """登记一份声明书：校验 source 域 + 留痕 + 值，通过后落盘。

    - ``records`` 接受 ``{item: value}`` 映射或 ``[{"item", "predicted_q1"}]`` 数组；
    - 已存在的声明书默认**拒写**（旧版须先留版本，``replace=True`` 才允许覆盖）；
    - 留痕三件（declared_by / declared_at / rationale）缺一即拒——不写等于把责任归属留空。
    """
    registered = tuple(spec.get("source_domain", ()))
    if source not in registered:
        raise PredictionDeclarationError(f"source {source!r} 未登记（已登记：{list(registered)}）")
    if isinstance(records, Mapping):
        records = [{"item": str(k), "predicted_q1": v} for k, v in records.items()]
    errors: list[str] = []
    for field, value in (("declared_by", declared_by), ("declared_at", declared_at), ("rationale", rationale)):
        if not isinstance(value, str) or not value.strip():
            errors.append(f"留痕 {field} 必须给出（不得为空）")
    if not records:
        errors.append("records 为空——空声明无意义")
    values = _validate_values(list(records), errors)
    if errors:
        raise PredictionDeclarationError("登记被拒：" + "；".join(errors))
    out = Path(out_path)
    if out.exists() and not replace:
        raise PredictionDeclarationError(f"声明书已存在 {out}（须先留版本；确认覆盖用 replace=True）")
    declaration = PredictedQ1Declaration(
        source=source,
        declared_by=declared_by.strip(),
        declared_at=declared_at.strip(),
        rationale=rationale.strip(),
        records=values,
        path=str(out),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(declaration.to_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return declaration


def verify_and_merge(
    records: Sequence[Mapping[str, Any]],
    declaration: PredictedQ1Declaration,
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    """把 records 与声明书对账，产出 (合并后的 records, BLOCKED 原因列表)。

    三类情况，全部不静默：

    - 记录缺 predicted_q1 且声明书覆盖 → 以声明书值补齐（来源已登记，不是顶替）；
    - 记录带值且与声明书逐项不等 → 篡改/漂移，BLOCKED 并具名；
    - 记录未被声明书覆盖 → 无登记来源，BLOCKED 并具名。
    """
    declared = declaration.records
    errors: list[str] = []
    merged: list[dict[str, Any]] = []
    for raw in records:
        rec = dict(raw)
        item = str(rec.get("item", "<missing>"))
        if item not in declared:
            errors.append(f"{item}: 未被声明书覆盖（predicted_q1 无登记来源）")
        elif rec.get("predicted_q1") is not None:
            if float(rec["predicted_q1"]) != declared[item]:
                errors.append(f"{item}: 记录值 {rec['predicted_q1']!r} 与声明书 {declared[item]!r} 不一致（篡改/漂移）")
            else:
                rec["predicted_q1"] = declared[item]
        else:
            rec["predicted_q1"] = declared[item]
        merged.append(rec)
    return merged, tuple(errors)
