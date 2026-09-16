"""T01-02C Golden Dataset —— 六类分层用例（A–F），固定种子，版本锁定。

**为什么要有它**（任务板原文）：Gate 1 的「100% 通过」必须绑定本数据集
**版本号**，不允许开发人员用一个简单 Excel 声称通过。

设计口径：

* **六类 × 正例/负例**：A 正常随机 / B 边界随机 / C 退化随机 / D 不可行
  随机 / E 极端尺度 / F 对抗构造。负例验证的是**拒绝路径**（异常清单、
  BLOCK、失败样本），正例验证的是**通过路径**（行数/数值精确）。
* **固定随机种子**：数据集是**制品**（生成一次、提交 git、版本锁定），
  不是每次测试现生成——否则「通过」针对的数据集每次都在漂移。
* **期望摘要机器可判**：每用例记录 ``{rows, failures, skipped, matched,
  blocked, anomalies}`` 与抽样数值核对点（``spot_check``），由
  ``tests/test_golden_dataset.py`` 逐用例复算比对。
* **manifest_hash**：期望表内容的 sha256——手改期望（让红变绿）会失配。
  期望改了必须走生成器重生成，不允许在制品上手补。

本模块只**生成**数据集与期望；断言逻辑在测试侧，避免「自己出题自己判」。
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from .xlsxkit import write_xlsx

__all__ = ["GOLDEN_VERSION", "GOLDEN_SEED", "GoldenCase", "generate_golden",
           "manifest_hash"]

GOLDEN_VERSION = "golden-v1"
GOLDEN_SEED = 20260916

# 真实双行表头形态（与 tests/test_t0102b_variants.py 同一形态）
_HDR = ["项目编码", "项目名称", "项目特征描述", "计量单位", "工程量",
        "综合单价（元）", "金额（元）", ""]
_SUB = ["", "", "", "", "", "", "合价", "其中:暂估价"]
_TITLE = "表-09 分部分项工程项目清单计价表【{}】"


def _sheet(rows: list[list], unit_work: str = "电气设备安装工程") -> list[list]:
    return [[f"表-09 分部分项工程项目清单计价表【{unit_work}】"], [], _HDR, _SUB] + rows


def _row(item_id: str, name: str, feature: str, unit: str,
         q: str, price: str) -> list[str]:
    return [item_id, name, feature, unit, q, price, "", ""]


def _fmt(x: float, digits: int = 6) -> str:
    """定点字符串，避免科学计数法进清单。"""
    s = f"{x:.{digits}f}".rstrip("0").rstrip(".")
    return s if s else "0"


@dataclass
class GoldenCase:
    """一个 Golden 用例：两侧行矩阵 + 机器可判的期望摘要。"""

    case_id: str                    # 如 A_pos
    category: str                   # A–F
    kind: str                       # positive / negative
    desc: str
    cap_sheets: dict[str, list[list]] | None = None
    cost_sheets: dict[str, list[list]] | None = None
    expect: dict = field(default_factory=dict)
    spot_check: dict = field(default_factory=dict)   # {item_id: {q0, cap, c_i, q1_point}}


def _rand_code(rnd: random.Random) -> str:
    return str(rnd.randint(300000000000, 399999999999))


# ---------------------------------------------------------------- 六类生成


def _build_cases(rnd: random.Random) -> list[GoldenCase]:
    cases: list[GoldenCase] = []

    # ---- A 正常随机（24 行，两侧对齐）--------------------------------
    a_rows_cap, a_rows_cost = [], []
    a_spot = {}
    for i in range(24):
        cid = _rand_code(rnd)
        q = _fmt(rnd.uniform(0.5, 500))
        cap = _fmt(rnd.uniform(10, 50000), 2)
        cost = _fmt(float(cap) * rnd.uniform(0.7, 0.95), 2)
        a_rows_cap.append(_row(cid, f"项目{i}", "规格描述", "m", q, cap))
        a_rows_cost.append(_row(cid, f"项目{i}", "规格描述", "m", q, cost))
        if i < 3:
            a_spot[cid] = {"q0": float(q), "cap": float(cap),
                           "c_i": float(cost), "q1_point": float(q)}
    cases.append(GoldenCase(
        "A_pos", "A", "positive", "正常随机 24 行，两侧对齐",
        {"表-09 分部分项【电气】": _sheet(a_rows_cap)},
        {"表-09 分部分项【电气】": _sheet(a_rows_cost)},
        expect={"rows": 48, "failures": 0, "matched": 24, "blocked": False,
                "anomalies": 0},   # rows=两侧总和（cap 24 + cost 24）
        spot_check=a_spot,
    ))
    a2 = list(a_rows_cap)   # 同一批 cap 行（负例只动 cost 侧）
    extra_cost = a_rows_cost + [
        _row(_rand_code(rnd), f"新增项{i}", "", "m", _fmt(1), _fmt(100 + i))
        for i in range(3)
    ]
    cases.append(GoldenCase(
        "A_neg", "A", "negative", "成本侧多 3 行 → ONLY_IN_COST 异常",
        {"表-09 分部分项【电气】": _sheet(a2)},
        {"表-09 分部分项【电气】": _sheet(extra_cost)},
        expect={"rows": 51, "failures": 0, "matched": 24, "blocked": False,
                "anomalies": 3},   # cap 24 + cost 27
    ))

    # ---- B 边界随机 --------------------------------------------------
    b_cap = [
        _row("301000000001", "最小量", "", "m", "0.000001", "0.01"),
        _row("301000000002", "最大量", "", "m", "99999999.99", "1.00"),
        _row("301000000003", "千分位", "", "m", "1,234.5", "9,999,999.99"),
        _row("301000000004", "全角数字", "", "m", "１２.５", "８８.８８"),
        _row("301000000005", "空限价", "", "m", "5", ""),   # no_cap
    ]
    b_cost = [
        _row("301000000001", "最小量", "", "m", "0.000001", "0.009"),
        _row("301000000002", "最大量", "", "m", "99999999.99", "0.99"),
        _row("301000000003", "千分位", "", "m", "1,234.5", "8,000,000.00"),
        _row("301000000004", "全角数字", "", "m", "12.5", "70.00"),
        _row("301000000005", "空限价", "", "m", "5", "4.00"),
    ]
    cases.append(GoldenCase(
        "B_pos", "B", "positive", "边界值：极小/极大量、千分位、全角、no_cap",
        {"表-09 分部分项【电气】": _sheet(b_cap)},
        {"表-09 分部分项【电气】": _sheet(b_cost)},
        expect={"rows": 10, "failures": 0, "matched": 5, "blocked": False,
                "anomalies": 0, "no_cap": 1},   # cap 5 + cost 5
        spot_check={
            "301000000001": {"q0": 1e-06, "cap": 0.01, "c_i": 0.01},  # c_i 0.009 经金额 2 位精度归一
            "301000000003": {"q0": 1234.5, "cap": 9999999.99},
            "301000000004": {"q0": 12.5, "cap": 88.88},
            "301000000005": {"q0": 5.0, "cap": None, "no_cap": True},
        },
    ))
    b2_cap = [
        _row("301000000001", "零价A", "", "m", "1", "0"),
        _row("301000000002", "零价B", "", "m", "1", "0.00"),
        _row("301000000003", "正常", "", "m", "1", "10"),
    ]
    b2_cost = [
        _row("301000000001", "零价A", "", "m", "1", "5"),
        _row("301000000002", "零价B", "", "m", "1", "5"),
        _row("301000000003", "正常", "", "m", "1", "8"),
    ]
    cases.append(GoldenCase(
        "B_neg", "B", "negative", "零价（C5 信号）×2 → 异常清单",
        {"表-09 分部分项【电气】": _sheet(b2_cap)},
        {"表-09 分部分项【电气】": _sheet(b2_cost)},
        expect={"rows": 6, "failures": 0, "matched": 3, "blocked": False,
                "anomalies": 2},   # cap 3 + cost 3
    ))

    # ---- C 退化随机（ADR-0006：空是合法结论）--------------------------
    cases.append(GoldenCase(
        "C_pos", "C", "positive", "两侧明细 0 数据行 = 合法结论（非 BLOCK）",
        {"表-09 分部分项【电气】": _sheet([])},
        {"表-09 分部分项【电气】": _sheet([])},
        expect={"rows": 0, "failures": 0, "matched": 0, "blocked": False,
                "anomalies": 0},
    ))
    c2_cap = [
        ["302000000001", "缺量A", "", "m", "", "10"],
        ["302000000002", "缺量B", "", "m", "", "20"],
        ["302000000003", "缺量C", "", "m", "", "30"],
    ]
    cases.append(GoldenCase(
        "C_neg", "C", "negative", "全部行缺工程量 → 失败样本清单",
        {"表-09 分部分项【电气】": _sheet(c2_cap)},
        None,
        expect={"rows": 0, "failures": 3, "matched": 0, "blocked": False,
                "anomalies": 0},
    ))

    # ---- D 不可行随机（c_i > cap_i：数据层正常，求解层不可行）----------
    d_cap = [_row(f"30300000000{i}", f"D{i}", "", "m", "10", _fmt(100 + i))
             for i in range(10)]
    d_cost = [_row(f"30300000000{i}", f"D{i}", "", "m", "10", _fmt(150 + i))
              for i in range(10)]
    cases.append(GoldenCase(
        "D_pos", "D", "positive", "c_i > cap_i 全部项（求解层不可行，数据层可解析）",
        {"表-09 分部分项【电气】": _sheet(d_cap)},
        {"表-09 分部分项【电气】": _sheet(d_cost)},
        expect={"rows": 20, "failures": 0, "matched": 10, "blocked": False,
                "anomalies": 0},
    ))
    d2_cap = [
        _row("304000000001", "重复A-1", "", "m", "1", "10"),
        _row("304000000001", "重复A-2", "", "m", "2", "20"),
        _row("304000000002", "正常", "", "m", "1", "10"),
    ]
    d2_cost = [
        _row("304000000003", "重复B-1", "", "m", "1", "9"),
        _row("304000000003", "重复B-2", "", "m", "3", "8"),
        _row("304000000002", "正常", "", "m", "1", "8"),
    ]
    cases.append(GoldenCase(
        "D_neg", "D", "negative", "两侧各 1 个重复 key → BLOCK 禁止自动合并",
        {"表-09 分部分项【电气】": _sheet(d2_cap)},
        {"表-09 分部分项【电气】": _sheet(d2_cost)},
        expect={"rows": 6, "failures": 0, "matched": 1, "blocked": True,
                "anomalies": 6},   # 4 副本重复异常 + 2 ONLY_IN（重复键不匹配对侧）
        spot_check={},
    ))

    # ---- E 极端尺度 ----------------------------------------------------
    e_cap, e_cost = [], []
    for i in range(2000):
        cid = f"305{i:09d}"
        q = _fmt(rnd.uniform(1, 1000000), 3)
        cap = _fmt(rnd.uniform(1, 1e8), 2)
        e_cap.append(_row(cid, f"项{i}", "长特征" * 10, "m", q, cap))
        e_cost.append(_row(cid, f"项{i}", "长特征" * 10, "m", q,
                           _fmt(float(cap) * 0.9)))
    cases.append(GoldenCase(
        "E_pos", "E", "positive", "极端尺度：2000 行、量至 1e6、价至 1e8",
        {"表-09 分部分项【电气】": _sheet(e_cap)},
        {"表-09 分部分项【电气】": _sheet(e_cost)},
        expect={"rows": 4000, "failures": 0, "matched": 2000, "blocked": False,
                "anomalies": 0},
    ))
    e2_cap = [
        _row("306000000001", "超长特征", "长" * 5000, "m", "1", "10"),
        _row("306000000002", "超长名称", "", "m", "1", "10"),
    ]
    e2_cost = [
        _row("306000000001", "超长特征", "长" * 5000, "m", "1", "9"),
        _row("306000000002", "超长名称", "", "m", "1", "9"),
    ]
    e2_cap[1][1] = "名" * 3000
    e2_cost[1][1] = "名" * 3000
    cases.append(GoldenCase(
        "E_neg", "E", "negative", "超长字符串（5 千字符特征/3 千字符名称）不崩溃",
        {"表-09 分部分项【电气】": _sheet(e2_cap)},
        {"表-09 分部分项【电气】": _sheet(e2_cost)},
        expect={"rows": 4, "failures": 0, "matched": 2, "blocked": False,
                "anomalies": 0},
    ))

    # ---- F 对抗构造 ----------------------------------------------------
    f_cap = [
        ["一", "第一章 安装工程", "", "", "", "", "", ""],        # 分节标题（四空）
        ["307000000001", "项1", "", "m", "1", "10"],              # 序号分节重算背景下
        ["二", "第二章", "", "", "", "", "", ""],
        ["307000000002", "项2", "", "m", "2", "20"],
        ["0303B001", "补充编码项", "", "套", "3", "30"],           # 补充编码
        ["XYZ987654321", "异形编码", "", "m", "1", "15"],          # UNKNOWN 不阻塞
    ]
    f_cost = [
        ["一", "第一章 安装工程", "", "", "", "", "", ""],
        ["307000000001", "项1", "", "m", "1", "9"],
        ["二", "第二章", "", "", "", "", "", ""],
        ["307000000002", "项2", "", "m", "2", "18"],
        ["0303B001", "补充编码项", "", "套", "3", "27"],
        ["XYZ987654321", "异形编码", "", "m", "1", "13"],
    ]
    cases.append(GoldenCase(
        "F_pos", "F", "positive", "对抗但合法：分节标题夹数据 + 补充/异形编码",
        {"表-09 分部分项【电气】": _sheet(f_cap)},
        {"表-09 分部分项【电气】": _sheet(f_cost)},
        expect={"rows": 8, "failures": 0, "matched": 4, "blocked": False,
                "anomalies": 0},
    ))
    f2_cap = [[
        "项目编码", "项目名称", "工程量(m)", "综合单价(元/m)",
    ], [
        "307000000001", "项1", "1", "10",
    ]]
    cases.append(GoldenCase(
        "F_neg", "F", "negative", "对抗：表头带单位 → 定位不到表头 → BLOCK",
        {"表-09 分部分项【电气】": [[
            "表-09 分部分项工程项目清单计价表【电气】"], []] + f2_cap},
        None,
        expect={"rows": 0, "failures": 1, "matched": 0, "blocked": False,
                "anomalies": 0},
    ))
    return cases


# ---------------------------------------------------------------- 生成与指纹


def manifest_hash(manifest: dict) -> str:
    """期望表指纹：cases 部分的 canonical JSON sha256。

    只对 cases 求哈希——生成时间戳等元数据变化不得使旧期望失效；
    手改期望（让红变绿）会失配。
    """
    payload = json.dumps(
        {"golden_version": manifest["golden_version"],
         "cases": manifest["cases"]},
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_golden(out_dir: Path, version: str = GOLDEN_VERSION,
                    seed: int = GOLDEN_SEED) -> dict:
    """生成六类 Golden Dataset + manifest（xlsx 落盘、期望入清单）。"""
    rnd = random.Random(seed)
    cases = _build_cases(rnd)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    for c in cases:
        files = {}
        for side, sheets in (("cap", c.cap_sheets), ("cost", c.cost_sheets)):
            if sheets is None:
                continue
            p = write_xlsx(out_dir / f"{c.case_id}_{side}.xlsx", sheets)
            files[side] = p.name
        entries.append({
            "case_id": c.case_id, "category": c.category, "kind": c.kind,
            "desc": c.desc, "files": files, "expect": c.expect,
            "spot_check": c.spot_check,
        })

    manifest = {
        "golden_version": version,
        "seed": seed,
        "generated_at": "2026-09-16T22:05:00+08:00",
        "generator": "src/bidpricing/io/golden.py::generate_golden",
        "binding": "Gate 1 的「100% 通过」绑定 golden_version；期望改动必须重跑生成器，不得手改制品",
        "cases": entries,
    }
    manifest["manifest_hash"] = manifest_hash(manifest)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest
