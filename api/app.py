"""网页前端的报价优化 API。"""
from __future__ import annotations

import hmac
import hashlib
import re
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bidpricing import project_overview, project_store
from bidpricing import sqlite_store
from bidpricing.deployment import log_event, safe_user, user_scope
from bidpricing.import_preview import build_listing_preview
from bidpricing.io.boq import assert_price_columns_present, parse_listing
from bidpricing.io.clean import clean_listing_rows
from bidpricing.io.match import MatchReport, match_canonical_rows
from bidpricing.plan_compare import compare_plans, same_project
from bidpricing.project_store import _safe_folder
from bidpricing.sqlite_store import (
    save_plan, list_plans, load_plan, delete_plan, mark_finalized, find_plan_by_strategy,
    find_group_by_plan_id, find_slot_plan_id, group_finalize, create_group, rename_group,
    list_groups, copy_group, delete_group, find_group_by_id, list_groups_for_project,
    upsert_slot, append_audit, list_audit,
    PlanOwnershipError, StoreWriteLockedError,
)
from bidpricing.quote_resolve import run_resolve
from bidpricing.quote_strategies import STRATEGIES
from bidpricing.validation.low_price_policy import DISPOSITION_NOTE

# H-012 多用户隔离（不鉴权，仅目录级）：以运行账号作为命名空间，各用户方案互不相见。
# 方案与方案组统一落到 SQLite，库文件沿用按用户重定向的 PROJECTS_DIR 模型。
CURRENT_USER = safe_user(os.environ.get("USERNAME") or os.environ.get("USER") or "default")
USER_PROJECTS = user_scope(ROOT / "outputs" / "projects", CURRENT_USER)
project_store.PROJECTS_DIR = USER_PROJECTS
sqlite_store.PROJECTS_DIR = USER_PROJECTS
LOG_DIR = ROOT / "outputs" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
# 一次性种子迁移：仅当本用户库尚未建立时把既有 JSON 树幂等归库；
# 此后库为唯一真相，避免把已在库中删除的方案从遗留 JSON 复活。
if not sqlite_store.resolve_db_path().exists():
    try:
        sqlite_store.import_json_tree(source_dir=USER_PROJECTS)
    except Exception as exc:  # noqa: BLE001 迁移失败不阻止服务启动
        print(f"[bidpricing] SQLite 种子迁移失败（将跳过）：{exc}")


#: 单个上传文件上限（MB）。超过则直接拒绝，避免内存占用异常放大。
#: 清单 xlsx 通常在数 MB 以内，10 MB 上限足够容容。
_MAX_UPLOAD_MB = int(os.environ.get("BIDPRICING_MAX_UPLOAD_MB", "10"))

#: job_id 白名单：仅接受 16~64 位十六进制（uuid4.hex / 派生 id），纵深防御路径穿越。
_JOB_ID_RE = re.compile(r"^[0-9a-f]{16,64}$")


def _valid_job_id(job_id: str) -> bool:
    return bool(_JOB_ID_RE.match(job_id or ""))


def _blocked_parse_error(exc: Exception, endpoint: str = "/api/quote/preview") -> JSONResponse:
    """Excel 解析失败的稳定错误响应：原始异常写日志，不回显内部路径/库名。

    O5（治理审查 P0）：此前两处 `except Exception` 把 `str(exc)` 直接回给用户，
    可能泄露绝对路径与底层库名，且不进 LOG_DIR。
    统一改为先记结构化日志、再返回固定文案。
    """
    log_event(LOG_DIR, CURRENT_USER, endpoint, "ERROR", detail=repr(exc))
    return JSONResponse(status_code=400, content={
        "status": "BLOCKED",
        "reason": "Excel 识别失败：文件无法解析（明细已记入服务端日志，请核对清单/成本文件是否为合规的 xlsx 且含单价列）",
    })


def _export_xlsx(rec_result: dict, out_id: str) -> str | None:
    """导出 JSON+XLSX 到 WEB_OUTPUT_DIR，返回 excel_download_url 或 None。

    O7（治理审查 P1）：此前 optimize / recompute / rebuild 三处各自
    write_text + subprocess.run(node build_web_result.mjs)，参数完全一致。
    统一为一个单点，失败时在 rec_result 上挂 excel_export_warning（不抛异常）。
    """
    json_path = WEB_OUTPUT_DIR / f"{out_id}.json"
    xlsx_path = WEB_OUTPUT_DIR / f"{out_id}.xlsx"
    json_path.write_text(json.dumps(rec_result, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        subprocess.run(["node", str(ROOT / "build_web_result.mjs"), str(json_path), str(xlsx_path)],
                       cwd=ROOT, check=True, capture_output=True, text=True, timeout=60)
        return f"/api/quote/download/{out_id}"
    except (subprocess.SubprocessError, OSError) as exc:
        rec_result["excel_export_warning"] = f"Excel 导出失败，仍可下载 JSON：{exc}"
        return None


def _validate_quote_params(*, vat_rate, surtax_rate, target_total, fixed_pretax,
                           cost_input_vat_rate=None, credit_ratio=None,
                           ratio_min=0.5, ratio_max=1.0) -> JSONResponse | None:
    """报价参数合法性校验。返回 JSONResponse(400) 或 None。

    O7（治理审查 P1）：此前 optimize 与 recompute 各自四段 if 校验，
    后者漏校验 target_total > 0 与 fixed_pretax >= 0，语义漂移已开始。
    统一为一个单点，可选参数缺省时跳过。
    """
    if not (0.0 <= vat_rate <= 1.0) or not (0.0 <= surtax_rate <= 1.0):
        return JSONResponse(status_code=400, content={"status": "BLOCKED", "reason": "税率非法：增值税率/附加税率须为 0～1 之间的小数（0.09 = 9%、0.12 = 12%），请勿输入百分数"})
    if target_total is None or target_total <= 0:
        return JSONResponse(status_code=400, content={"status": "BLOCKED", "reason": "目标总报价非法：须为正数"})
    if fixed_pretax is None or fixed_pretax < 0:
        return JSONResponse(status_code=400, content={"status": "BLOCKED", "reason": "固定税前项非法：须为非负数"})
    if not (0.0 <= ratio_min <= ratio_max <= 1.0):
        return JSONResponse(status_code=400, content={"status": "BLOCKED", "reason": "单项报价比率区间非法：必须满足 0 ≤ 下限 ≤ 上限 ≤ 1.00"})
    if cost_input_vat_rate is not None and not (0.0 <= cost_input_vat_rate <= 1.0):
        return JSONResponse(status_code=400, content={"status": "BLOCKED", "reason": "进项增值税率非法：须为 0～1 之间的小数（0.13 = 13%）"})
    if credit_ratio is not None and not (0.0 <= credit_ratio <= 1.0):
        return JSONResponse(status_code=400, content={"status": "BLOCKED", "reason": "进项税额抵扣比例非法：须为 0～1 之间的小数（0.70 = 70%）"})
    return None


async def _read_upload_limited(file: UploadFile, max_mb: int = _MAX_UPLOAD_MB) -> tuple[bytes | None, str | None]:
    """读取 UploadFile 内容并检查体积；超限返回 (None, reason) 而 (data, None)。"""
    data = await file.read()
    limit_bytes = max_mb * 1024 * 1024
    if len(data) > limit_bytes:
        return None, (
            f"上传文件超过 {_MAX_UPLOAD_MB} MB 上限"
            f"（实际 {len(data) / 1024 / 1024:.2f} MB）"
        )
    if not _is_xlsx_magic(data):
        return None, "上传文件格式错误：仅接受 .xlsx 文件（ZIP 魔数校验失败）"
    return data, None


#: xlsx 是 ZIP 格式，前 4 字节为 PK\\x03\\x04（O18：上传无 MIME/魔数校验）
_XLSX_MAGIC = b"PK\x03\x04"


def _is_xlsx_magic(data: bytes) -> bool:
    """检查文件魔数：xlsx 是 ZIP 格式，前 4 字节须为 PK\\x03\\x04。"""
    return data[:4] == _XLSX_MAGIC



def _parse_clean_match(cap_path: Path, cost_path: Path, project_id: str) -> tuple[str, MatchReport]:
    """解析 → 清洗 → 匹配 三步，预览与优化共用（同一份数据源避免两侧口径漂移）。"""
    pid = project_id.strip() or "当前项目"
    cap_report, cost_report = parse_listing(cap_path, pid), parse_listing(cost_path, pid)
    assert_price_columns_present(cap_report=cap_report, cost_report=cost_report)
    cap_rows, _ = clean_listing_rows(cap_report.rows, "cap")
    cost_rows, _ = clean_listing_rows(cost_report.rows, "cost")
    return pid, match_canonical_rows(cap_rows, cost_rows)


def _load_low_policy() -> tuple[dict, float, str | None]:
    """读取项目策略中的低价确认口径；未声明时回退 0.5 / 泛称。"""
    try:
        cfg = json.loads((ROOT / "config" / "project_quote_policy.json").read_text(encoding="utf-8"))
        low_policy = cfg.get("low_price_policy") or {}
    except (OSError, json.JSONDecodeError):
        low_policy = {}
    low_threshold = float(low_policy.get("low_price_threshold", 0.5)) if low_policy.get("low_price_threshold") is not None else 0.5
    return low_policy, low_threshold, (low_policy.get("clause_basis") or None)


def _run_resolve(all_items: list[dict], params: dict, low_policy: dict,
                 matched: MatchReport | None, tax_policy_override: dict | None = None,
                 strategy: str = "optimal") -> tuple:
    """解析结果，按 STRATEGIES 注册表分发（optimal=MILP / uniform=等比下浮解析解）。

    两个策略函数签名一致，可单测；配置目录固化为本项目 config。
    strategy 非法值在调用前由 API 层 400 拒绝，此处直接取注册表。"""
    fn = STRATEGIES[strategy]
    return fn(all_items, params, low_policy, config_dir=ROOT / "config",
              matched=matched, tax_policy_override=tax_policy_override)


def _build_tax_override(input_vat_credit_mode: str, cost_input_vat_rate, credit_ratio,
                        cost_composition) -> dict:
    """把前端传来的税口径字段组装成覆盖段（优先于 config/project_quote_policy.json）。

    cost_composition 可以是已解析的 list（来自已存方案的 params）或 JSON 字符串
    （来自表单）；二者皆空则回退到旧单税率三元组。
    """
    comp = cost_composition
    if isinstance(comp, str) and comp.strip():
        try:
            comp = json.loads(comp)
        except (json.JSONDecodeError, TypeError):
            comp = None
    if isinstance(comp, list) and comp:
        return {"input_vat_credit_mode": input_vat_credit_mode,
                "cost_input_vat_rate": cost_input_vat_rate,
                "credit_ratio": credit_ratio,
                "cost_composition": comp}
    return {"input_vat_credit_mode": input_vat_credit_mode,
            "cost_input_vat_rate": cost_input_vat_rate,
            "credit_ratio": credit_ratio}


def _low_price_guard(params: dict, low_policy: dict) -> JSONResponse | None:
    """比率下限低于低价阈值且未确认时返回 NEEDS_CONFIRMATION；否则 None。"""
    ratio_min = params["ratio_min"]
    ratio_max = params["ratio_max"]
    if ratio_min < float(low_policy.get("low_price_threshold", 0.5)) - 1e-9 and not params["low_ratio_confirmed"]:
        low_threshold = float(low_policy.get("low_price_threshold", 0.5))
        clause_basis = low_policy.get("clause_basis") or None
        return JSONResponse(status_code=400, content={"status": "NEEDS_CONFIRMATION", "reason": f"报价比率下限低于 {low_threshold:.0%}。这可能触发招标文件中的严重低价/废标审查，请确认招标文件允许后再计算。", "confirmation_required": True, "ratio_min": ratio_min, "ratio_max": ratio_max, "low_price_threshold": low_threshold, "clause_basis": clause_basis, "disposition_note": DISPOSITION_NOTE})
    return None

app = FastAPI(title="工程智算报价 API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],
                   allow_methods=["GET", "POST"], allow_headers=["Authorization", "X-API-Token", "Content-Type", "Accept"])
WEB_OUTPUT_DIR = user_scope(ROOT / "outputs" / "web-results", CURRENT_USER)
WEB_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

#: 槽位写入互斥锁：并发请求命中同组同策略槽位时，
#: 「读槽位 → 写 json/xlsx → 落 SQLite → 回写槽位」序列须原子化。
#: O4（治理审查 P0）：此前文件写入在 SQLite 锁之前，Windows 下 O_TRUNC 非原子，
#: 并发可能产出半成品产物。参照 deployment.py 的 threading.Lock 模式。
#:
#: 已知局限（O4-c，2026-09-24 登记，未修）：
#: (a) 本锁是 **threading.Lock**（进程内），在 async 路由内 with 会阻塞整个事件循环。
#:     锁内子进程调用（node build_web_result.mjs，timeout=60s）期间，其它请求的
#:     事件循环也被卡住。修法：改用 asyncio.Lock + asyncio.to_thread 包装 save_plan
#:     / upsert_slot / _export_xlsx（都是同步 IO）。当前单 worker 部署可接受。
#: (b) 本锁不跨进程。**多 worker 部署（uvicorn --workers N）下失效**：每个 worker
#:     各持一把锁，跨进程并发写同槽位仍可能产出半成品产物。当前部署是单 worker 进程
#:     （未使用 --workers），此锁足够；若需多 worker，须把本锁换成 SQLite 事务或
#:     外部锁（例如文件锁），并在部署手册中登记。
_SLOT_LOCK = threading.Lock()


@app.middleware("http")
async def _access_log(request, call_next):
    """H-012 生产访问日志：每个请求记录 时间/用户/端点和结果状态 到 JSONL。"""
    start = time.monotonic()
    response = await call_next(request)
    log_event(LOG_DIR, CURRENT_USER, f"{request.method} {request.url.path}",
              response.status_code, duration_ms=round((time.monotonic() - start) * 1000, 2))
    return response


# H-013 API token（可选加固）：设置环境变量 BIDPRICING_API_TOKEN 后，
# 全部 /api 路由（/api/health 除外）须携带 Authorization: Bearer <token>
# 或 X-API-Token: <token>。
#
# 默认行为：未设置 token 时保持纯本地无鉴权流程，但打印醒目告警。
# 强制模式：设 BIDPRICING_REQUIRE_TOKEN=1 后，未设 token 直接拒绝启动。
#
# **多用户隔离语义澄清**：本项目的多用户隔离基于 CURRENT_USER（os.USERNAME/USER），
# 在进程启动时定死。同一端口只服务**一个**逻辑用户——多人共用机器时须各自
# 起服务进程，不能通过同一 API 服务实现多用户。若需真正的多用户服务，
# 须改为按请求头 X-User 动态切 user_scope（配合 token 保护），当前版本不支持。
API_TOKEN = os.environ.get("BIDPRICING_API_TOKEN", "").strip()
_REQUIRE_TOKEN = os.environ.get("BIDPRICING_REQUIRE_TOKEN", "").strip().lower() in ("1", "true", "yes", "on")
if not API_TOKEN:
    if _REQUIRE_TOKEN:
        raise RuntimeError(
            "BIDPRICING_REQUIRE_TOKEN 已设置但 BIDPRICING_API_TOKEN 未设置。"
            "对外暴露服务时必须先设置 token，例如："
            "export BIDPRICING_API_TOKEN=$(openssl rand -hex 32)"
        )
    print("=" * 68)
    print("[bidpricing] 安全告警：BIDPRICING_API_TOKEN 未设置，/api 路由无鉴权可访问。")
    print("  纯本地单机使用可接受；对外暴露前必须设置 BIDPRICING_API_TOKEN，")
    print("  或设 BIDPRICING_REQUIRE_TOKEN=1 让本进程在无 token 时拒绝启动。")
    print("  多用户隔离基于启动账号（CURRENT_USER），同一端口只服务一个逻辑用户。")
    print("=" * 68)


@app.middleware("http")
async def _auth_guard(request, call_next):
    if not API_TOKEN or request.url.path == "/api/health":
        return await call_next(request)
    candidates = [request.headers.get("X-API-Token") or ""]
    authz = request.headers.get("Authorization") or ""
    if authz.startswith("Bearer "):
        candidates.append(authz[len("Bearer "):].strip())
    # 用 hmac.compare_digest 避免 timing attack（即使 localhost 风险低，也保持安全默认）。
    if not any(c and hmac.compare_digest(c.strip(), API_TOKEN) for c in candidates):
        return JSONResponse(status_code=401, content={
            "status": "UNAUTHORIZED",
            "reason": "API token 缺失或不正确（Authorization: Bearer <token> 或 X-API-Token）",
        })
    return await call_next(request)


#: F-16（UI/UX 审查 P2）：CSP header，限制内联脚本/事件处理器。
#: 静态文件由 uvicorn 直接服务，不经 API 路由，故仅对非 /api 响应注入。
_CSP_HEADER = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self' http://127.0.0.1:8000"
)


@app.middleware("http")
async def _csp_guard(request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Content-Security-Policy"] = _CSP_HEADER
    return response


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "bidpricing"}


@app.post("/api/quote/preview")
async def preview_quote(limit_file: UploadFile = File(...), cost_file: UploadFile = File(...), project_id: str = Form("当前项目"), project_name: str = Form("")):
    """导入预览（H-006）：上传后先核对行数/字段/匹配覆盖/异常/文件哈希，再进优化。"""
    proj_name = project_name.strip() or project_id.strip() or "当前项目"
    with tempfile.TemporaryDirectory(prefix="bidpricing-api-") as temp_dir:
        cap_path, cost_path = Path(temp_dir) / "limit.xlsx", Path(temp_dir) / "cost.xlsx"
        cap_data, cap_err = await _read_upload_limited(limit_file)
        cost_data, cost_err = await _read_upload_limited(cost_file)
        if cap_err or cost_err:
            return JSONResponse(status_code=413, content={"status": "BLOCKED", "reason": cap_err or cost_err})
        cap_path.write_bytes(cap_data)
        cost_path.write_bytes(cost_data)
        try:
            pid, matched = _parse_clean_match(cap_path, cost_path, proj_name)
        except Exception as exc:  # noqa: BLE001
            return _blocked_parse_error(exc, "/api/quote/preview")
        payload = build_listing_preview(matched, pid)
        payload["cap"]["hash_sha256"] = hashlib.sha256(cap_path.read_bytes()).hexdigest()[:16]
        payload["cost"]["hash_sha256"] = hashlib.sha256(cost_path.read_bytes()).hexdigest()[:16]
        return JSONResponse(status_code=200, content=payload)


@app.get("/api/quote/download/{job_id}")
def download_quote(job_id: str):
    if not _valid_job_id(job_id):
        return JSONResponse(status_code=400, content={"status": "BLOCKED", "reason": "非法的报价文件 id"})
    fname = _excel_filename(job_id)
    path = WEB_OUTPUT_DIR / f"{job_id}.xlsx"
    if path.exists() and path.parent == WEB_OUTPUT_DIR:
        return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=fname)
    # 自愈：存盘方案有结算结果但 xlsx 缺失（副本/历史导出清理等）时，即时重建后再下发
    rebuilt = _rebuild_xlsx(job_id)
    if rebuilt is not None:
        return FileResponse(rebuilt, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=fname)
    return JSONResponse(status_code=404, content={"status": "NOT_FOUND", "reason": "报价 Excel 不存在或已过期"})


def _excel_filename(job_id: str) -> str:
    """下载文件名规则：``<项目名称>-<报价金额>.xlsx``。"""
    rec = load_plan(job_id)
    if rec is None:
        return "报价结果_结算调整版.xlsx"
    name = _safe_folder(rec.get("project_name") or rec.get("project_id") or rec.get("name") or "方案")
    amt = (rec.get("params") or {}).get("target_total")
    try:
        amt_str = str(int(round(float(amt))))
    except (TypeError, ValueError):
        amt_str = ""
    return f"{name}-{amt_str}.xlsx" if amt_str else f"{name}.xlsx"


def _rebuild_xlsx(job_id: str) -> Path | None:
    """从方案库中该 id 的结算结果重建导出文件；非方案 id 则返回 None。"""
    rec = load_plan(job_id)
    if not rec or not rec.get("result"):
        return None
    xlsx_path = WEB_OUTPUT_DIR / f"{job_id}.xlsx"
    # O4：与 optimize_quote 一致，写 json/xlsx 须持 _SLOT_LOCK，
    # 防止下载时重建与 optimize 并发写同 plan_id 时 O_TRUNC 产出半成品 xlsx。
    with _SLOT_LOCK:
        _export_xlsx(rec["result"], job_id)
    return xlsx_path if xlsx_path.exists() else None


@app.post("/api/quote/optimize")
async def optimize_quote(limit_file: UploadFile = File(...), cost_file: UploadFile = File(...), project_id: str = Form("当前项目"), project_name: str = Form(""), target_total: float = Form(...), fixed_pretax: float = Form(0.0), vat_rate: float = Form(0.09), surtax_rate: float = Form(0.12), ratio_min: float = Form(0.5), ratio_max: float = Form(1.0), low_ratio_confirmed: bool = Form(False), low_price_confirmed_by: str = Form(""), clause_enabled: bool = Form(True), overview_id: str = Form(""), input_vat_credit_mode: str = Form("PARTIAL"), cost_input_vat_rate: float = Form(0.13), credit_ratio: float = Form(0.70), cost_composition: str = Form(""), strategy: str = Form("optimal"), group_id: str = Form("")):
    strategy = strategy.strip() or "optimal"
    if strategy not in STRATEGIES:
        return JSONResponse(status_code=400, content={"status": "BLOCKED", "reason": f"未知报价策略：{strategy}（可选：{'、'.join(sorted(STRATEGIES))}）"})
    if not clause_enabled:
        return JSONResponse(status_code=400, content={"status": "BLOCKED", "reason": "当前版本要求启用 C13 结算调整条款"})
    _param_err = _validate_quote_params(
        vat_rate=vat_rate, surtax_rate=surtax_rate, target_total=target_total,
        fixed_pretax=fixed_pretax, cost_input_vat_rate=cost_input_vat_rate,
        credit_ratio=credit_ratio, ratio_min=ratio_min, ratio_max=ratio_max)
    if _param_err is not None:
        return _param_err
    # 项目凭证：project_id 必须为经营概览的真实项目 id（UUID）；project_name 仅用于展示/目录/文件名。
    proj_uuid = project_id.strip()
    proj_name = project_name.strip() or proj_uuid or "当前项目"
    low_policy, _, _ = _load_low_policy()
    tax_override = _build_tax_override(input_vat_credit_mode, cost_input_vat_rate, credit_ratio, cost_composition)
    params = {"target_total": target_total, "fixed_pretax": fixed_pretax, "vat_rate": vat_rate, "surtax_rate": surtax_rate, "ratio_min": ratio_min, "ratio_max": ratio_max, "low_ratio_confirmed": low_ratio_confirmed, "low_price_confirmed_by": low_price_confirmed_by, "overview_id": overview_id, "input_vat_credit_mode": input_vat_credit_mode, "cost_input_vat_rate": cost_input_vat_rate, "credit_ratio": credit_ratio, "cost_composition": tax_override.get("cost_composition")}
    guard = _low_price_guard(params, low_policy)
    if guard is not None:
        return guard
    with tempfile.TemporaryDirectory(prefix="bidpricing-api-") as temp_dir:
        cap_path, cost_path = Path(temp_dir) / "limit.xlsx", Path(temp_dir) / "cost.xlsx"
        cap_data, cap_err = await _read_upload_limited(limit_file)
        cost_data, cost_err = await _read_upload_limited(cost_file)
        if cap_err or cost_err:
            return JSONResponse(status_code=413, content={"status": "BLOCKED", "reason": cap_err or cost_err})
        cap_path.write_bytes(cap_data)
        cost_path.write_bytes(cost_data)
        try:
            pid, matched = _parse_clean_match(cap_path, cost_path, proj_name)
        except Exception as exc:  # noqa: BLE001
            return _blocked_parse_error(exc, "/api/quote/optimize")
        all_items = [{"item_id": row.item_id, "item_name": row.item_name, "unit": getattr(row, "unit", "") or "", "q0": row.q0, "q1_point": row.q1_point, "c_i": row.c_i, "cap": row.cap, "L": (float(row.cap) * ratio_min if row.cap is not None else 0.0), "U": (float(row.cap) * ratio_max if row.cap is not None else None)} for row in matched.items if row.q0 is not None or row.q1_point is not None]
        result, payload, status_code = _run_resolve(all_items, params, low_policy, matched, tax_policy_override=tax_override, strategy=strategy)
        if status_code != 200:
            # 非 PASS（如无可优化项或跨单位工程重复 item_id 导致 BLOCKED）直接返回，
            # 不继续取空 p_by_id 建明细（防止 KeyError 吞掉报错文案）。
            return JSONResponse(status_code=status_code, content=payload)
        payload.update({"project_id": proj_uuid or pid, "project_name": proj_name, "fixed_pretax": fixed_pretax, "vat_rate": vat_rate, "surtax_rate": surtax_rate, "strategy": strategy})
        # H-007 方案持久化：PASS 后保存为可『打开 / 复制 / 重算』的本地方案。
        # H-008 方案组：一次测算=一组。命中同组同策略槽位复用其 plan_id 覆盖更新。
        #   未传 group_id 时回退该策略槽位覆盖（同项目同策略）并归入该项目的方案组。
        slot_key = proj_uuid or pid
        effective_group_id = (group_id or "").strip()
        # 未指定组：若能定位到既有同项目方案，则并入其组（同组同策略槽位覆盖）；
        # 否则为本次测算新建一组。
        if not effective_group_id:
            existing = find_plan_by_strategy(slot_key, strategy)
            if existing and find_group_by_plan_id(existing):
                effective_group_id = find_group_by_plan_id(existing)
        if not effective_group_id:
            effective_group_id = create_group(
                proj_uuid or pid, proj_name, target_total=target_total)["group_id"]
        # 同组同策略槽位复用；未命中则新建 plan_id
        # O4：「读槽位 → 写 json/xlsx → 落 SQLite → 回写槽位」序列须原子化，
        # 防止并发请求命中同槽位时 O_TRUNC 产出半成品产物。
        with _SLOT_LOCK:
            job_id = find_slot_plan_id(effective_group_id, strategy) or uuid.uuid4().hex
            # 校验 group 归属（A2）：防止跨项目写入他人的方案组
            if effective_group_id:
                group_info = find_group_by_id(effective_group_id)
                if group_info and proj_uuid and group_info.get("project_id") != proj_uuid:
                    return JSONResponse(
                        status_code=403,
                        content={"status": "FORBIDDEN",
                                 "reason": f"方案组 {effective_group_id} 归属项目 "
                                           f"{group_info.get('project_id')!r}，拒绝以当前项目 "
                                           f"{proj_uuid!r} 写入"}
                    )
            preview = build_listing_preview(matched, pid)
            preview["cap"]["hash_sha256"] = hashlib.sha256(cap_path.read_bytes()).hexdigest()[:16]
            preview["cost"]["hash_sha256"] = hashlib.sha256(cost_path.read_bytes()).hexdigest()[:16]
            payload["plan_id"] = job_id
            payload["group_id"] = effective_group_id
            # 先导出再落盘：保存的方案 result 也要带 excel_download_url，否则打开方案时下载按钮 href="#" 无反应
            excel_url = _export_xlsx(payload, job_id)
            if excel_url:
                payload["excel_download_url"] = excel_url
            try:
                save_plan({"name": proj_name, "project_id": proj_uuid or pid, "project_name": proj_name, "group_id": effective_group_id, "strategy": strategy, "params": dict(params), "all_items": all_items, "preview": preview, "result": payload}, plan_id=job_id)
                upsert_slot(effective_group_id, strategy, job_id)
            except (PlanOwnershipError, StoreWriteLockedError) as exc:
                return JSONResponse(status_code=409, content={"status": "BLOCKED", "reason": str(exc)})
        append_audit(CURRENT_USER, "quote.optimize", "PASS",
                     project_id=proj_uuid or pid, plan_id=job_id, group_id=effective_group_id,
                     objective=payload.get("objective"))
        return JSONResponse(status_code=200, content=payload)


@app.get("/api/project/list")
def project_list() -> JSONResponse:
    """按项目分组返回方案组摘要：前端右栏用关联项目定位，方案中心按项目列组。"""
    groups = list_groups()
    per_project: dict[str, dict] = {}
    for g in groups:
        pid = g.get("project_id") or g.get("project_name") or "未命名项目"
        entry = per_project.setdefault(pid, {"name": pid, "group_count": 0, "plans": [], "groups": []})
        entry["group_count"] += 1
        entry["groups"].append(g)
        for slot_key, s in (g.get("strategy_slots") or {}).items():
            sm = (s or {}).get("summary") or {}
            if s and s.get("plan_id"):
                entry["plans"].append({
                    "id": s["plan_id"], "slot": slot_key, "group_id": g.get("group_id"),
                    "name": f"{g.get('group_name')} · {slot_key}", "project_id": pid,
                    "project_name": g.get("project_name") or pid,
                    "saved_at": sm.get("saved_at"),
                    "strategy": sm.get("strategy") or slot_key.lower(),
                    "target_total": sm.get("target_total"),
                    "competitive_budget": sm.get("competitive_budget"),
                    "finalized": bool(g.get("finalized")),
                    "finalized_at": g.get("finalized_at"),
                })
    projects = list(per_project.values())
    projects.sort(key=lambda g: g["name"])
    return JSONResponse(status_code=200, content={"status": "PASS", "projects": projects})


# ============ 方案组（H-008）端点 ============
@app.get("/api/group/list")
def group_list(project_id: str = "") -> JSONResponse:
    """按项目（归一键）返回方案组列表；未传 project_id 返回全部组。"""
    if project_id and project_id.strip():
        data = list_groups_for_project(project_id.strip())
    else:
        data = list_groups()
    return JSONResponse(status_code=200, content={"status": "PASS", "groups": data})


@app.post("/api/group/create")
def group_create(project_id: str = Form(""), project_name: str = Form(""),
                 name: str = Form(""), target_total: float = Form(None)) -> JSONResponse:
    g = create_group(project_id.strip() or None, project_name.strip() or None,
                     group_name=name.strip() or None, target_total=target_total)
    return JSONResponse(status_code=200, content={"status": "PASS", "group": g})


@app.post("/api/group/rename")
def group_rename(group_id: str = Form(...), name: str = Form("")) -> JSONResponse:
    try:
        ok = rename_group(group_id.strip(), name.strip())
    except StoreWriteLockedError as exc:
        return JSONResponse(status_code=409, content={"status": "LOCKED", "reason": str(exc)})
    if not ok:
        return JSONResponse(status_code=404, content={"status": "NOT_FOUND", "reason": "方案组不存在或已删除"})
    return JSONResponse(status_code=200, content={"status": "PASS", "group_id": group_id.strip()})


@app.post("/api/group/finalize")
def group_set_finalized(group_id: str = Form(...), finalized: int = Form(1)) -> JSONResponse:
    if not group_finalize(group_id.strip(), finalized=finalized == 1):
        return JSONResponse(status_code=404, content={"status": "NOT_FOUND", "reason": "方案组不存在或已删除"})
    return JSONResponse(status_code=200, content={"status": "PASS", "group_id": group_id.strip(), "finalized": finalized == 1})


@app.post("/api/group/copy")
def group_copy(group_id: str = Form(...), name: str = Form("")) -> JSONResponse:
    new = copy_group(group_id.strip(), group_name=name.strip() or None)
    if new is None:
        return JSONResponse(status_code=404, content={"status": "NOT_FOUND", "reason": "方案组不存在或已删除"})
    return JSONResponse(status_code=200, content={"status": "PASS", "group": new})


@app.post("/api/group/delete")
def group_delete(group_id: str = Form(...), keep_plans: int = Form(0)) -> JSONResponse:
    try:
        ok = delete_group(group_id.strip(), keep_plans=keep_plans == 1)
    except StoreWriteLockedError as exc:
        return JSONResponse(status_code=409, content={"status": "LOCKED", "reason": str(exc)})
    if not ok:
        return JSONResponse(status_code=404, content={"status": "NOT_FOUND", "reason": "方案组不存在或已删除"})
    return JSONResponse(status_code=200, content={"status": "PASS", "deleted": group_id.strip()})


@app.get("/api/project/get")
def project_get(id: str) -> JSONResponse:
    rec = load_plan(id)
    if rec is None:
        return JSONResponse(status_code=404, content={"status": "NOT_FOUND", "reason": "方案不存在或已删除"})
    return JSONResponse(status_code=200, content={"status": "PASS", "plan": {"id": rec["id"], "name": rec.get("name"), "project_id": rec.get("project_id") or rec.get("name"), "project_name": rec.get("project_name"), "params": rec.get("params"), "all_items": rec.get("all_items"), "preview": rec.get("preview"), "result": rec.get("result"), "saved_at": rec.get("saved_at")}})


@app.post("/api/project/copy")
def project_copy(id: str, name: str = "") -> JSONResponse:
    rec = load_plan(id)
    if rec is None:
        return JSONResponse(status_code=404, content={"status": "NOT_FOUND", "reason": "方案不存在或已删除"})
    new_name = name.strip() or f"{rec.get('name') or id}（副本）"
    new_id = uuid.uuid4().hex
    copy = dict(rec)
    copy["name"] = new_name
    copy["params"] = dict(rec.get("params") or {})
    copy["all_items"] = list(rec.get("all_items") or [])
    copy["preview"] = rec.get("preview")
    copy["result"] = None  # 副本先清空结果，用户可重算后生成新结果
    copy["finalized"] = False  # 副本不继承定稿状态，避免同项目出现多份『已定稿』
    copy.pop("finalized_at", None)
    save_plan(copy, plan_id=new_id)
    return JSONResponse(status_code=200, content={"status": "PASS", "plan_id": new_id, "name": new_name})


@app.post("/api/project/recompute")
def project_recompute(id: str, target_total: float = Form(...), fixed_pretax: float = Form(0.0), vat_rate: float = Form(0.09), surtax_rate: float = Form(0.12), ratio_min: float = Form(0.5), ratio_max: float = Form(1.0), low_ratio_confirmed: bool = Form(False), low_price_confirmed_by: str = Form(""), clause_enabled: bool = Form(True), input_vat_credit_mode: str = Form(""), cost_input_vat_rate: float = Form(None), credit_ratio: float = Form(None), cost_composition: str = Form(""), strategy: str = Form("")) -> JSONResponse:
    rec = load_plan(id)
    if rec is None:
        return JSONResponse(status_code=404, content={"status": "NOT_FOUND", "reason": "方案不存在或已删除"})
    # 重算时的策略：请求字段优先 → 方案已存 strategy → 默认 optimal（兼容旧前端不传）
    strategy = (strategy or "").strip() or rec.get("strategy") or "optimal"
    if strategy not in STRATEGIES:
        return JSONResponse(status_code=400, content={"status": "BLOCKED", "reason": f"未知报价策略：{strategy}（可选：{'、'.join(sorted(STRATEGIES))}）"})
    if not clause_enabled:
        return JSONResponse(status_code=400, content={"status": "BLOCKED", "reason": "当前版本要求启用 C13 结算调整条款"})
    _param_err = _validate_quote_params(
        vat_rate=vat_rate, surtax_rate=surtax_rate, target_total=target_total,
        fixed_pretax=fixed_pretax, ratio_min=ratio_min, ratio_max=ratio_max)
    if _param_err is not None:
        return _param_err
    low_policy, _, _ = _load_low_policy()
    # 重算时保留方案原有的关联经营项目 id（前端重算表单不含该字段）
    _keep_ov = (rec.get("params") or {}).get("overview_id", "")
    # 税口径：请求字段优先 → 方案已存 params → 默认值（兼容旧前端/未传场景）
    rec_params = rec.get("params") or {}
    mode = (input_vat_credit_mode or "").strip() or rec_params.get("input_vat_credit_mode") or "PARTIAL"
    rate = cost_input_vat_rate if cost_input_vat_rate is not None else rec_params.get("cost_input_vat_rate", 0.13)
    cr = credit_ratio if credit_ratio is not None else rec_params.get("credit_ratio", 0.70)
    if not (0.0 <= float(rate) <= 1.0):
        return JSONResponse(status_code=400, content={"status": "BLOCKED", "reason": "进项增值税率非法：须为 0～1 之间的小数（0.13 = 13%）"})
    if not (0.0 <= float(cr) <= 1.0):
        return JSONResponse(status_code=400, content={"status": "BLOCKED", "reason": "进项税额抵扣比例非法：须为 0～1 之间的小数（0.70 = 70%）"})
    comp = cost_composition or rec_params.get("cost_composition") or ""
    tax_override = _build_tax_override(mode, rate, cr, comp)
    params = {"target_total": target_total, "fixed_pretax": fixed_pretax, "vat_rate": vat_rate, "surtax_rate": surtax_rate, "ratio_min": ratio_min, "ratio_max": ratio_max, "low_ratio_confirmed": low_ratio_confirmed, "low_price_confirmed_by": low_price_confirmed_by, "overview_id": _keep_ov, "input_vat_credit_mode": mode, "cost_input_vat_rate": rate, "credit_ratio": cr, "cost_composition": tax_override.get("cost_composition")}
    guard = _low_price_guard(params, low_policy)
    if guard is not None:
        return guard
    all_items = list(rec.get("all_items") or [])
    result, payload, status_code = _run_resolve(all_items, params, low_policy, None, tax_policy_override=tax_override, strategy=strategy)
    if status_code != 200:
        return JSONResponse(status_code=status_code, content=payload)
    payload.update({"project_id": rec.get("name") or id, "fixed_pretax": fixed_pretax, "vat_rate": vat_rate, "surtax_rate": surtax_rate, "strategy": strategy})
    payload["plan_id"] = id
    # O4：与 optimize_quote 一致，「导出 xlsx → 落 SQLite」序列须原子化，
    # 防止重算与 optimize 并发写同 plan_id 时 O_TRUNC 产出半成品产物。
    with _SLOT_LOCK:
        # 先导出再落盘：保存的方案 result 须带 excel_download_url，否则打开方案时「下载 Excel」为 '#' 无反应
        excel_url = _export_xlsx(payload, id)
        if excel_url:
            payload["excel_download_url"] = excel_url
        merged = dict(rec)
        merged["params"] = dict(params)
        merged["result"] = payload
        merged["strategy"] = strategy
        save_plan(merged, plan_id=id)
    return JSONResponse(status_code=200, content=payload)


@app.post("/api/project/delete")
def project_delete(id: str) -> JSONResponse:
    if not delete_plan(id):
        return JSONResponse(status_code=404, content={"status": "NOT_FOUND", "reason": "方案不存在或已删除"})
    return JSONResponse(status_code=200, content={"status": "PASS", "deleted": id})


@app.post("/api/project/mark-finalized")
def project_mark_finalized(id: str, finalized: int = 1, write: int = 1) -> JSONResponse:
    """设定方案的『已定稿』状态（方案卡片手动开关，或手动定稿回写后置标）。
    finalized=1 打上已定稿；0 取消定稿。同一项目只保留一份定稿方案。
    write=1（默认，方案库卡片『标为定稿』时）会把该方案的目标总报价回写为关联
    经营项目（方案保存的 overview_id 精确匹配，缺省按项目名归一匹配）的投标报价金额；
    write=0（手动『定稿并回写项目』已写过，避免二次覆盖）只打标、不再回写。"""
    rec = load_plan(id)
    if rec is None:
        return JSONResponse(status_code=404, content={"status": "NOT_FOUND", "reason": "方案不存在"})
    if not mark_finalized(id, finalized=finalized == 1):
        return JSONResponse(status_code=404, content={"status": "NOT_FOUND", "reason": "方案不存在"})
    wrote = False
    if finalized == 1 and write == 1:
        _params = rec.get("params") or {}
        target = _params.get("target_total")
        ov_id = (_params.get("overview_id") or "").strip()
        proj_name = (rec.get("project_id") or rec.get("name") or "").strip()
        matched = None
        for proj in project_overview.list_projects():
            if ov_id and proj.get("id") == ov_id:
                matched = proj
                break
            if (proj.get("name") or "").strip() == proj_name:
                matched = proj
                break
        if matched is not None and target not in (None, ""):
            if project_overview.finalize(matched.get("id"), target, ""):
                wrote = True
    return JSONResponse(status_code=200, content={"status": "PASS", "finalized": id, "wrote_back": wrote})


@app.post("/api/project/compare")
def project_compare(id: str = Form(...), base: str = Form("")) -> JSONResponse:
    """多方案对比（H-008）：id 支持逗号分隔多个方案，base 可选指定单价差异基准。"""
    ids = [i for i in (s.strip() for s in id.split(",")) if i]
    if not ids:
        return JSONResponse(status_code=400, content={"status": "BLOCKED", "reason": "请至少指定一个方案进行对比（多个 id 用逗号分隔）"})
    records, missing = [], []
    for i in ids:
        rec = load_plan(i)
        if rec is None:
            missing.append(i)
        else:
            records.append(rec)
    if missing:
        return JSONResponse(status_code=404, content={"status": "NOT_FOUND", "reason": f"以下方案不存在或已删除：{', '.join(missing)}"})
    if len(records) < 2:
        return JSONResponse(status_code=400, content={"status": "BLOCKED", "reason": "多方案对比至少需要 2 个有效方案"})
    ok, projects = same_project(records)
    if not ok:
        return JSONResponse(status_code=400, content={"status": "BLOCKED", "reason": f"多方案对比限定同一项目（单价差异与利润才有可比意义）：当前勾选涉及 {('、'.join(projects))}。请仅勾选同一项目的多个方案进行对比（可复制后改参数生成同项目的方案变体）。"})
    base_id = base.strip() or None
    if base_id is not None and base_id not in {r["id"] for r in records}:
        return JSONResponse(status_code=400, content={"status": "BLOCKED", "reason": f"基准方案 {base_id} 不在本次对比列表中"})
    return JSONResponse(status_code=200, content=compare_plans(records, base_id=base_id))


@app.get("/api/audit/list")
def audit_list(limit: int = 200, action: str = "", user: str = "") -> JSONResponse:
    """查询审计日志（库内 audit_log，按 ts 倒序），可选按 action/user 过滤。"""
    cap = max(1, min(int(limit), 1000))
    rows = list_audit(limit=cap, action=action.strip() or None, user=user.strip() or None)
    return JSONResponse(status_code=200, content={"status": "PASS", "audit": rows})


# ============ 项目经营概览（H-013）：全生命周期看板数据集 ============
def _overview_body(entries: list[tuple[str, Any]]) -> dict[str, Any]:
    """从 FastAPI form/query 请求中取出非空的可编辑字段。"""
    body = {}
    for k, v in entries:
        if v is None:
            continue
        s = str(v).strip()
        body[k] = s if s else v
    return body


@app.get("/api/project/overview/list")
def overview_list() -> JSONResponse:
    projects = project_overview.list_projects()
    return JSONResponse(status_code=200, content={"status": "PASS", "projects": projects})


@app.post("/api/project/overview/save")
def overview_save(pid: str = Form(""), name: str = Form(""), short_name: str = Form(""),
                  limit_total: str = Form(""), bid_open_date: str = Form(""), stage: str = Form(""),
                  bid_amount: str = Form(""), bid_cost: str = Form(""), actual_cost: str = Form(""),
                  actual_revenue: str = Form(""), settle_amount: str = Form(""),
                  completed_at: str = Form("")):
    """新建或编辑项目。pid 为空=新建，非空=覆盖编辑（同 id，不会静默覆盖别的项目）。"""
    form = _overview_body(locals().items())
    try:
        if pid.strip():
            rec = project_overview.update_project(pid.strip(), form)
            if rec is None:
                return JSONResponse(status_code=404, content={"status": "NOT_FOUND", "reason": "项目不存在或已删除"})
        else:
            rec = project_overview.create_project(form)
        append_audit(CURRENT_USER, "project.overview.save", "PASS", project_id=rec.get("id"))
        return JSONResponse(status_code=200, content={"status": "PASS", "project": rec})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"status": "BLOCKED", "reason": str(exc)})


@app.post("/api/project/overview/delete")
def overview_delete(id: str = Form(...)):
    if not project_overview.delete_project(id.strip()):
        return JSONResponse(status_code=404, content={"status": "NOT_FOUND", "reason": "项目不存在或已删除"})
    append_audit(CURRENT_USER, "project.overview.delete", "PASS", project_id=id.strip())
    return JSONResponse(status_code=200, content={"status": "PASS"})


@app.post("/api/project/overview/finalize")
def overview_finalize(id: str = Form(...), bid_amount: str = Form(""), bid_cost: str = Form("")):
    """报价定稿回写：把最终投标报价金额与投标成本测算写回对应项目，自动派生毛利/毛利率。"""
    rec = project_overview.finalize(id.strip(), bid_amount, bid_cost)
    if rec is None:
        return JSONResponse(status_code=404, content={"status": "NOT_FOUND", "reason": "项目不存在或已删除"})
    append_audit(CURRENT_USER, "project.overview.finalize", "PASS", project_id=id.strip(),
             detail={"bid_amount": rec.get("bid_amount")})
    return JSONResponse(status_code=200, content={"status": "PASS", "project": rec})
