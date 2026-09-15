"""契约制品元数据机制。

闭合《实施路线 v3.2.1》§7.1.1 **断言 4「字段有效性判据机械化」**：

    所有 version 字段除「存在且非空」外，还须满足两项可由 CI 自动校验的条件——
    ① **hash 绑定**：字段值必须等于对应制品所在 Git tag 的 SHA-256 前 12 位；
    ② **占位符黑名单**：字段值不得命中正则 ``(?i)(todo|tbd|fixme|draft|placeholder|待|暂)``。

    并补全三字段：``input_protocol_schema`` / ``q1_assumption_spec`` /
    ``cost_assumption_spec`` 均须携带 ``_version / _hash / _frozen_at``。

设计说明
--------
* **hash 口径**：对制品文件的**原始字节**取 SHA-256 前 12 位，前缀 ``sha256:``。
  取原始字节（而非规范化 JSON）是刻意选择——任何字节变动都会使 hash 失配，
  从而强制「制品一改就要重新冻结」，这正是契约冻结想要的语义。
* **Git tag 校验**：本模块只负责「字段值 == 制品内容 hash」的本地可校验部分；
  「该 hash 对应一个已并入主分支的 tag」由 CI 用 ``git cat-file -p <tag>`` 完成。
  两者共同构成断言 4 的完整判据。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .states import CheckItem, Status

#: 占位符黑名单——逐字采用路线 §7.1.1 断言 4 原文正则
PLACEHOLDER_PATTERN = r"(?i)(todo|tbd|fixme|draft|placeholder|待|暂)"

HASH_PREFIX = "sha256:"
HASH_HEX_LEN = 12

#: 每个受控制品必须携带的三个元数据字段（断言 4）
METADATA_FIELDS = ("version", "hash", "frozen_at")


def sha256_short12(payload: bytes) -> str:
    """SHA-256 前 12 位十六进制。"""
    return hashlib.sha256(payload).hexdigest()[:HASH_HEX_LEN]


def compute_artifact_hash(path: Path) -> str:
    """制品 hash（含 ``sha256:`` 前缀）。"""
    return HASH_PREFIX + sha256_short12(path.read_bytes())


def _placeholder_hit(value: str) -> str | None:
    import re

    m = re.search(PLACEHOLDER_PATTERN, value)
    return m.group(0) if m else None


class ArtifactNotFreezable(RuntimeError):
    """制品自声明尚不完整（``freeze_blocker`` 非空），拒绝冻结。

    这是防止「把未完成制品冻成已通过」的安全阀：例如
    ``competitiveness_classification.json`` 的分类表为空、依赖真实招标清单，
    若仅因文件存在就获得 hash，Gate 0a 会误判其为已冻结。
    """


@dataclass(frozen=True)
class ArtifactRecord:
    """注册表中的一条受控制品记录。"""

    key: str
    kind: str = "versioned"  # versioned | enum
    artifact_path: str | None = None
    version: str | None = None
    hash: str | None = None
    frozen_at: str | None = None
    allowed: tuple[str, ...] = ()
    note: str = ""

    @property
    def is_enum(self) -> bool:
        return self.kind == "enum"

    @property
    def is_frozen(self) -> bool:
        return bool(self.version) and bool(self.hash) and bool(self.frozen_at)


def load_registry(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_registry(path: Path, registry: dict) -> None:
    path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def parse_records(registry: dict, gate_key: str) -> list[ArtifactRecord]:
    out: list[ArtifactRecord] = []
    for key, spec in registry.get(gate_key, {}).items():
        out.append(
            ArtifactRecord(
                key=key,
                kind=spec.get("kind", "versioned"),
                artifact_path=spec.get("artifact_path"),
                version=spec.get("version"),
                hash=spec.get("hash"),
                frozen_at=spec.get("frozen_at"),
                allowed=tuple(spec.get("allowed", ())),
                note=spec.get("note", ""),
            )
        )
    return out


def freeze_record(
    registry: dict,
    gate_key: str,
    key: str,
    config_dir: Path,
    now: datetime | None = None,
) -> ArtifactRecord:
    """计算制品 hash 并写入 version / hash / frozen_at 三字段（原地修改 registry）。"""
    spec = registry[gate_key][key]
    artifact_path = spec.get("artifact_path")
    if not artifact_path:
        raise ValueError(f"{gate_key}.{key} 未声明 artifact_path，无法冻结")
    target = config_dir / artifact_path
    if not target.exists():
        raise FileNotFoundError(f"制品不存在：{target}")

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and payload.get("freeze_blocker"):
        raise ArtifactNotFreezable(
            f"{gate_key}.{key} 自声明未完成，拒绝冻结：{payload['freeze_blocker']}"
        )

    digest = compute_artifact_hash(target)
    stamp = (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat()
    spec["version"] = digest
    spec["hash"] = digest
    spec["frozen_at"] = stamp
    return ArtifactRecord(
        key=key,
        kind=spec.get("kind", "versioned"),
        artifact_path=artifact_path,
        version=digest,
        hash=digest,
        frozen_at=stamp,
        allowed=tuple(spec.get("allowed", ())),
        note=spec.get("note", ""),
    )


def verify_versioned(rec: ArtifactRecord, config_dir: Path) -> CheckItem:
    """校验一条 versioned 记录（断言 4 的 ①② 两条 + 三字段完整性）。"""

    def bad(reason: str, actual=None, expected=None) -> CheckItem:
        return CheckItem(
            scope="§7.1.1-4", item=rec.key, status=Status.BLOCKED,
            reason=reason, actual=actual, expected=expected,
        )

    for field_name in METADATA_FIELDS:
        if not getattr(rec, field_name):
            return bad(
                f"三字段不完整：{field_name} 缺失或为空"
                "（断言 4 要求 _version/_hash/_frozen_at 齐备）"
            )

    # ② 占位符黑名单（先查，避免把占位值当成格式错误）
    for field_name in METADATA_FIELDS:
        raw = str(getattr(rec, field_name))
        hit = _placeholder_hit(raw)
        if hit:
            return bad(
                f"占位符黑名单命中：{field_name} 含 '{hit}'",
                actual=raw,
                expected=f"不得命中 {PLACEHOLDER_PATTERN}",
            )

    # 格式校验
    for field_name in ("version", "hash"):
        raw = str(getattr(rec, field_name))
        if not raw.startswith(HASH_PREFIX):
            return bad(f"{field_name} 格式非法（须以 {HASH_PREFIX} 开头）", actual=raw)
        hexpart = raw[len(HASH_PREFIX):]
        if len(hexpart) != HASH_HEX_LEN or any(
            c not in "0123456789abcdef" for c in hexpart.lower()
        ):
            return bad(
                f"{field_name} 非法：须为 SHA-256 前 {HASH_HEX_LEN} 位十六进制",
                actual=raw,
            )

    # ① hash 绑定：与制品内容比对
    if not rec.artifact_path:
        return bad("未声明 artifact_path，无法完成 hash 绑定校验")
    target = config_dir / rec.artifact_path
    if not target.exists():
        return bad(f"制品文件不存在：{rec.artifact_path}")
    computed = compute_artifact_hash(target)
    if computed != rec.hash:
        return CheckItem(
            scope="§7.1.1-4", item=rec.key, status=Status.BLOCKED,
            reason="hash 失配：制品已变更但未重新冻结（契约失效）",
            actual=rec.hash, expected=computed,
        )

    return CheckItem(
        scope="§7.1.1-4", item=rec.key, status=Status.PASS,
        reason="三字段齐备、无占位符、hash 与制品内容一致",
        actual=rec.hash, expected=computed,
    )


def advisories(registry: dict, config_dir: Path) -> list[dict]:
    """收集受控制品的遗留项（``freeze_blocker`` 与 ``open_items``）。

    这些**不参与** Gate 机械判定（闸门只认 §7.1 的机械判据），
    但必须在报告中显式暴露，避免"已冻结"被误读为"已完备"。
    """
    out: list[dict] = []
    for gate_key in ("gate_0a", "gate_0b"):
        for rec in parse_records(registry, gate_key):
            if not rec.artifact_path:
                continue
            path = config_dir / rec.artifact_path
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            if payload.get("freeze_blocker"):
                out.append(
                    {
                        "gate": gate_key, "key": rec.key, "kind": "freeze_blocker",
                        "text": str(payload["freeze_blocker"]),
                    }
                )
            for item in payload.get("open_items") or []:
                out.append(
                    {
                        "gate": gate_key, "key": rec.key, "kind": "open_item",
                        "text": str(item),
                    }
                )
    return out


def verify_enum(rec: ArtifactRecord, value: object, where: str) -> CheckItem:
    """校验枚举类字段（当前用于 ``adjustment_scope``）。

    断言 1 要求：未定态必须是 **key 完全缺失**，而不是任何非枚举字符串。
    """
    if value is None:
        return CheckItem(
            scope="§7.1.1-1/2", item=rec.key, status=Status.BLOCKED,
            reason=(
                "未定态（key 缺失）：Phase 0 直接判 BLOCKED，"
                "禁止放行任何下游开发（断言 2 未定态熔断）"
            ),
            actual="<missing>", expected=list(rec.allowed),
        )
    if str(value) not in rec.allowed:
        return CheckItem(
            scope="§7.1.1-1", item=rec.key, status=Status.BLOCKED,
            reason=(
                f"非法枚举值 {value!r}：只允许 {list(rec.allowed)}。"
                "注意：存 '未定'/'UNDETERMINED' 等非空字符串会被当成已冻结而绕过熔断点"
            ),
            actual=str(value), expected=list(rec.allowed),
        )
    return CheckItem(
        scope="§7.1.1-1", item=rec.key, status=Status.PASS,
        reason=f"枚举值合法（来源：{where}）",
        actual=str(value), expected=list(rec.allowed),
    )
