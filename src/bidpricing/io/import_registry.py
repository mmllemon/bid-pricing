"""T01-05 源文件版本锁定与完整性 —— 导入登记表 + 复算前指纹校验。

**要拦的事故**：源 xlsx 被替换（改了一行单价/换了一个版本）之后，旧的
复算结果——解析缓存、清洗产物、匹配报告——被静默复用，全部下游数字
对着一个已经不存在的文件成立。

**判据**（任务板原文）：每次导入记录
``file_name / file_hash / file_version / sheet_hash / import_timestamp / source_owner``；
源文件被替换后必须**能识别并拒绝**复用旧复算结果。

设计口径：

* **登记表 = 事实记录，不可变追加**（与 ADR 目录同一纪律）：每次导入
  追加一条 ``ImportRecord``，带递增 ``import_seq``；不删旧行——旧登记
  解释了旧复算结果当时对着哪个文件。
* **两层指纹**：``file_sha256``（整文件字节）判「文件换没换」；
  ``sheet_hash``（逐 sheet 内容矩阵哈希）在文件确实换了时**定位变化点**——
  哪张表变了，人工复核就先看哪张表。
* **``file_version`` = 内容版本指纹**（sha256 前 12 位）。xlsx 没有可靠的
  内建版本号，不猜；调用方可用 ``file_version_note`` 附带人工版本说明。
* **未登记 = BLOCKED**（不是空真通过）：没有登记就没有比对基准，
  「复算结果可复用」这一断言无从成立。
* 登记表按 ``(project_id, side)`` 分文件存放，避免多项目/多侧混写。
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .xlsx import Workbook, load_workbook

__all__ = [
    "ImportRecord",
    "VerifyResult",
    "file_sha256",
    "compute_sheet_hashes",
    "registry_path_for",
    "register_import",
    "verify_import",
    "load_registry",
]

# ---------------------------------------------------------------- 指纹


def file_sha256(path: str | Path) -> str:
    """整文件字节级 sha256。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _sheet_content_hash(rows: list[list[str]]) -> str:
    h = hashlib.sha256()
    for row in rows:
        for cell in row:
            h.update(cell.encode("utf-8"))
            h.update(b"\x1f")            # 单元格分隔
        h.update(b"\x1e")                # 行分隔
    return h.hexdigest()


def compute_sheet_hashes(wb: Workbook) -> dict[str, str]:
    """逐 sheet 内容矩阵哈希：{sheet_name: sha256}。

    用**解析后的值矩阵**而不是 xlsx 内部 XML——XML 里无关元数据
    （列宽、样式 id）一变就误报；值矩阵不变 = 数据没变。
    """
    return {s.name: _sheet_content_hash(s.rows) for s in wb.sheets}


def _combined_sheet_hash(sheet_hashes: dict[str, str]) -> str:
    h = hashlib.sha256()
    for name in sorted(sheet_hashes):
        h.update(name.encode("utf-8"))
        h.update(sheet_hashes[name].encode("ascii"))
    return h.hexdigest()


# ---------------------------------------------------------------- 登记记录


@dataclass
class ImportRecord:
    """一次导入的事实记录（追加式，不可变）。"""

    import_seq: int                  # 同一登记表内递增
    project_id: str
    side: str                        # cap / cost / bid …
    file_name: str
    file_path: str                   # 导入时路径（溯源用，不作指纹）
    file_hash: str                   # 整文件 sha256（指纹）
    file_version: str                # 内容版本指纹 = file_hash[:12]
    sheet_hash: dict[str, str]       # {sheet_name: 内容哈希}
    sheet_hash_combined: str         # 跨 sheet 组合哈希
    import_timestamp: str            # ISO 8601 本地时间（带时区偏移）
    source_owner: str                # 文件来源方（招标人/用户/…），默认 UNKNOWN

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VerifyResult:
    """复算前校验结果：PASS 可复用；BLOCKED 拒绝复用并给原因。"""

    status: str                      # PASS / BLOCKED
    reason: str
    record: ImportRecord | None = None    # 命中的登记（BLOCKED 时=最新旧登记）
    changed_sheets: list[str] = field(default_factory=list)  # 定位变化点

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "record": self.record.to_dict() if self.record else None,
            "changed_sheets": self.changed_sheets,
        }


# ---------------------------------------------------------------- 登记


def registry_path_for(base_dir: Path, project_id: str, side: str) -> Path:
    return base_dir / "imports" / project_id / f"import_registry_{side}.json"


def load_registry(path: Path) -> list[ImportRecord]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [ImportRecord(**r) for r in payload.get("records", [])]


def _save_registry(path: Path, records: list[ImportRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"records": [r.to_dict() for r in records]},
            ensure_ascii=False, indent=1,
        ),
        encoding="utf-8",
    )


def register_import(
    xlsx_path: str | Path,
    project_id: str,
    side: str,
    base_dir: Path,
    source_owner: str = "UNKNOWN",
    file_version_note: str | None = None,
) -> ImportRecord:
    """登记一次导入（追加式）。返回写入的记录。

    同一指纹重复登记**允许**（事实记录不拦截），但记录保持递增序号；
    ``verify_import`` 以**最新**一条为比对基准。
    """
    path = Path(xlsx_path)
    if not path.exists():
        raise FileNotFoundError(f"源文件不存在：{path}")
    wb = load_workbook(path)
    fh = file_sha256(path)
    sheet_hashes = compute_sheet_hashes(wb)
    reg_path = registry_path_for(base_dir, project_id, side)
    records = load_registry(reg_path)
    rec = ImportRecord(
        import_seq=len(records) + 1,
        project_id=project_id,
        side=side,
        file_name=path.name,
        file_path=str(path),
        file_hash=fh,
        file_version=file_version_note or fh[:12],
        sheet_hash=sheet_hashes,
        sheet_hash_combined=_combined_sheet_hash(sheet_hashes),
        import_timestamp=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        source_owner=source_owner,
    )
    records.append(rec)
    _save_registry(reg_path, records)
    return rec


def verify_import(
    xlsx_path: str | Path,
    project_id: str,
    side: str,
    base_dir: Path,
) -> VerifyResult:
    """复算前校验：当前文件指纹 vs 该 (project, side) 最新登记。

    * PASS —— 指纹一致，旧复算结果可复用；
    * BLOCKED（NOT_REGISTERED）—— 无登记即无基准，拒绝复用；
    * BLOCKED（FILE_REPLACED）—— 文件已被替换，**拒绝复用旧复算结果**，
      并用 sheet_hash 定位变化点供人工复核。
    """
    path = Path(xlsx_path)
    if not path.exists():
        return VerifyResult(
            status="BLOCKED", reason=f"源文件不存在：{path}")
    reg_path = registry_path_for(base_dir, project_id, side)
    records = load_registry(reg_path)
    if not records:
        return VerifyResult(
            status="BLOCKED",
            reason=f"未登记导入（{project_id}/{side}）——无比对基准，"
                   "须先 register-import；未登记 ≠ 空真通过")
    latest = records[-1]
    fh = file_sha256(path)
    if fh == latest.file_hash:
        return VerifyResult(
            status="PASS",
            reason=f"指纹一致（file_version={latest.file_version}，"
                   f"导入于 {latest.import_timestamp}），旧复算结果可复用",
            record=latest,
        )

    # 文件被替换 → 定位变化点
    wb = load_workbook(path)
    current_sheet_hashes = compute_sheet_hashes(wb)
    changed = [
        name for name, h in current_sheet_hashes.items()
        if latest.sheet_hash.get(name) != h
    ]
    for name in latest.sheet_hash:
        if name not in current_sheet_hashes:
            changed.append(f"[删除] {name}")
    return VerifyResult(
        status="BLOCKED",
        reason=(
            f"源文件已被替换：登记 {latest.file_hash[:12]}"
            f"（{latest.file_name}，{latest.import_timestamp}）→ "
            f"当前 {fh[:12]}。拒绝复用旧复算结果；变化 sheet：{changed or '未知'}"
        ),
        record=latest,
        changed_sheets=changed,
    )
