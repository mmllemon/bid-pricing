"""投标报价优化的第一版用户界面。

运行：
    python -m pip install -r requirements-ui.txt
    streamlit run app/streamlit_app.py

界面只负责输入、展示和下载；Excel 解析、匹配和 Phase 2 MILP 仍由
``bidpricing`` 内核完成，避免把业务规则复制到前端。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bidpricing.io.boq import parse_listing
from bidpricing.io.clean import clean_listing_rows
from bidpricing.io.match import match_canonical_rows
from bidpricing.quote_pipeline import run_settlement_adjusted_quote_pipeline


def _save_upload(uploaded, directory: str, name: str) -> Path:
    path = Path(directory) / name
    path.write_bytes(uploaded.getbuffer())
    return path


def _prepare_inputs(cap_file, cost_file, project_id: str, directory: str):
    cap_path = _save_upload(cap_file, directory, "limit.xlsx")
    cost_path = _save_upload(cost_file, directory, "cost.xlsx")
    cap_report = parse_listing(cap_path, project_id)
    cost_report = parse_listing(cost_path, project_id)
    cap_rows, cap_clean = clean_listing_rows(cap_report.rows, "cap")
    cost_rows, cost_clean = clean_listing_rows(cost_report.rows, "cost")
    matched = match_canonical_rows(cap_rows, cost_rows)
    return cap_report, cost_report, cap_clean, cost_clean, matched


def _items_from_match(matched, min_price: float) -> list[dict]:
    items = []
    for row in matched.items:
        if row.q0 is None or row.q1_point is None or row.c_i is None:
            continue
        # 当前结算调整 MILP 需要有限最高限价；无最高限价先在异常区提示，
        # 不将空值错误地压成 0。
        items.append({
            "item_id": row.item_id,
            "item_name": row.item_name,
            "q0": row.q0,
            "q1_point": row.q1_point,
            "c_i": row.c_i,
            "cap": row.cap,
            "L": min_price,
        })
    return items


def _result_rows(result, items):
    by_id = {x["item_id"]: x for x in items}
    rows = []
    for item_id, price in result.p_by_id.items():
        src = by_id.get(item_id, {})
        rows.append({
            "项目编码": item_id,
            "项目名称": src.get("item_name", ""),
            "工程量": src.get("q0"),
            "成本工程量": src.get("q1_point"),
            "含税成本单价": src.get("c_i"),
            "最高限价": src.get("cap"),
            "最优报价单价": price,
            "报价合价": (src.get("q0") or 0) * price,
        })
    return rows


def main() -> None:
    st.set_page_config(page_title="工程智算", page_icon="◒", layout="wide", initial_sidebar_state="expanded")
    st.markdown(
        """
        <style>
        :root { --ink:#172033; --muted:#697386; --blue:#1677ff; --line:#e8edf3; --panel:#ffffff; }
        .stApp { background: #f5f7fb; color: var(--ink); }
        [data-testid="stSidebar"] { background: #fbfcfe; border-right: 1px solid #e7ebf1; }
        [data-testid="stSidebar"] > div:first-child { padding-top: 1.25rem; }
        [data-testid="stSidebar"] label, [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span, [data-testid="stSidebar"] div[data-baseweb="select"] * { color:#172033 !important; }
        [data-testid="stSidebar"] [role="radiogroup"] label { color:#344054 !important; font-weight:600; }
        [data-testid="stSidebar"] [role="radiogroup"] label[data-checked="true"] { color:#1677ff !important; }
        [data-testid="stSidebar"] div[data-testid="stButton"] > button { text-align:left; justify-content:flex-start; border:0; border-radius:11px; padding:11px 14px; background:transparent; color:#344054 !important; font-size:14px; font-weight:550; box-shadow:none; }
        [data-testid="stSidebar"] div[data-testid="stButton"] > button:hover { background:#f0f2f6; color:#172033 !important; }
        [data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"] { background:#dce7f7; color:#172033 !important; font-weight:750; }
        .param-card { background:#fff; border:1px solid #e5e5ea; border-radius:18px; padding:18px 20px 4px; margin:0 0 24px; box-shadow:0 1px 3px rgba(0,0,0,.04),0 6px 20px rgba(0,0,0,.04); }
        .param-head { color:#1c1c1e; font-size:14px; font-weight:800; margin-bottom:2px; }
        .param-sub { color:#6b6b70; font-size:12px; margin-bottom:13px; }
        .stApp label, .stApp label p, .stApp [data-testid="stWidgetLabel"] p { color:#1c1c1e !important; font-weight:600 !important; }
        .stApp input { background:#ffffff !important; color:#1c1c1e !important; border:1px solid #d1d1d6 !important; border-radius:10px !important; }
        .stApp input::placeholder { color:#8e8e93 !important; }
        .stApp [data-testid="stNumberInput"] button { background:#ffffff !important; color:#6b6b70 !important; border-color:#d1d1d6 !important; }
        .stApp [data-testid="stFileUploader"] section { background:#ffffff !important; border:1px dashed #c7c7cc !important; border-radius:12px !important; }
        .stApp [data-testid="stFileUploader"] button { background:#ffffff !important; color:#1c1c1e !important; border:1px solid #d1d1d6 !important; }
        .stApp [data-testid="stFileUploader"] small, .stApp [data-testid="stFileUploader"] span { color:#6b6b70 !important; }
        .brand { padding: .35rem .65rem 1.3rem; }
        .brand-mark { display:inline-flex; width:34px; height:34px; border-radius:11px; align-items:center; justify-content:center; background:linear-gradient(135deg,#1677ff,#65b6ff); color:white; font-weight:700; font-size:20px; margin-right:9px; vertical-align:middle; }
        .brand-title { font-size:18px; font-weight:700; letter-spacing:.2px; vertical-align:middle; }
        .brand-sub { color:#8a94a6; font-size:11px; margin:8px 0 0 44px; }
        .page-kicker { color:#6b778c; font-size:13px; margin-bottom:4px; }
        .page-title { color:#172033; font-size:32px; font-weight:750; letter-spacing:-.8px; margin:0; }
        .page-subtitle { color:#748096; font-size:14px; margin:7px 0 24px; }
        .hero-workbench { position:relative; overflow:hidden; background:linear-gradient(100deg,#ffffff 0%,#ffffff 58%,#eaf3ff 100%); border:1px solid #e5e5ea; border-radius:22px; padding:27px 32px; margin:18px 0 24px; box-shadow:0 1px 3px rgba(0,0,0,.05),0 8px 25px rgba(0,0,0,.05); }
        .hero-workbench:after { content:""; position:absolute; width:180px; height:180px; right:42px; top:-78px; border-radius:50%; background:rgba(10,132,255,.10); }
        .hero-eyebrow { color:#0a60d0; font-size:12px; font-weight:750; letter-spacing:.05em; }
        .hero-heading { color:#1c1c1e; font-size:25px; font-weight:800; letter-spacing:-.04em; margin-top:7px; }
        .hero-copy { color:#6b6b70; font-size:13px; margin-top:6px; max-width:600px; }
        .hero-stats { display:flex; gap:0; margin-top:21px; }
        .hero-stat { min-width:155px; padding-right:24px; }
        .hero-stat + .hero-stat { border-left:1px solid #d1d1d6; padding-left:24px; }
        .hero-stat-value { color:#1c1c1e; font-size:19px; font-weight:800; }
        .hero-stat-label { color:#6b6b70; font-size:11px; margin-top:2px; }
        .hero-chip { position:absolute; z-index:2; right:24px; top:24px; border-radius:999px; background:#e8f1fe; color:#0a60d0; padding:7px 12px; font-size:11px; font-weight:750; }
        .step-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin:0 0 24px; }
        .step-card { background:#fff; border:1px solid #e5e5ea; border-radius:14px; padding:14px 15px; box-shadow:0 1px 3px rgba(0,0,0,.035); }
        .step-num { width:27px; height:27px; display:grid; place-items:center; border-radius:9px; background:#e8f1fe; color:#0a60d0; font-size:12px; font-weight:800; margin-bottom:10px; }
        .step-title { color:#1c1c1e; font-size:13px; font-weight:750; }
        .step-desc { color:#6b6b70; font-size:11px; margin-top:3px; }
        .section-title { color:#172033; font-weight:700; font-size:18px; margin:8px 0 4px; }
        .section-subtitle { color:#7b8798; font-size:13px; margin-bottom:14px; }
        .card { background:var(--panel); border:1px solid var(--line); border-radius:16px; padding:20px 22px; box-shadow:0 8px 24px rgba(23,32,51,.04); }
        .upload-card { min-height:132px; }
        .upload-icon { color:var(--blue); font-size:25px; margin-bottom:12px; }
        .upload-title { color:#172033; font-size:15px; font-weight:650; }
        .upload-hint { color:#8a94a6; font-size:12px; margin-top:5px; }
        .pill { display:inline-block; padding:5px 10px; border-radius:999px; background:#edf5ff; color:#1677ff; font-size:12px; font-weight:650; }
        div[data-testid="stMetric"] { background:#fff; border:1px solid var(--line); border-radius:14px; padding:13px 16px; box-shadow:0 5px 16px rgba(23,32,51,.035); }
        div[data-testid="stButton"] > button { border-radius:10px; font-weight:650; }
        .nav-label { color:#9aa4b2; font-size:11px; font-weight:700; letter-spacing:.08em; margin:12px 8px 6px; }
        </style>
        """, unsafe_allow_html=True,
    )

    with st.sidebar:
        st.markdown('<div class="brand"><span class="brand-mark">◒</span><span class="brand-title">工程智算</span><div class="brand-sub">工程项目智能决策平台</div></div>', unsafe_allow_html=True)
        st.markdown('<div class="nav-label">功能模块</div>', unsafe_allow_html=True)
        modules = [("◈", "投标报价"), ("◫", "实施成本"), ("▤", "项目台账"), ("◴", "结算管理")]
        if st.session_state.get("active_module") not in {label for _, label in modules}:
            st.session_state["active_module"] = "投标报价"
        for icon, label in modules:
            active = st.session_state["active_module"] == label
            if st.button(f"{icon}    {label}", key=f"nav_{label}", type="primary" if active else "secondary", use_container_width=True):
                st.session_state["active_module"] = label
                st.rerun()
        module = st.session_state["active_module"]
        if module != "投标报价":
            st.info(f"{module}模块已预留，后续接入对应业务流程。")
            st.stop()

    st.markdown('<div class="page-kicker">投标报价 / 新建测算</div><h1 class="page-title">投标报价优化</h1><div class="page-subtitle">从限价与成本清单出发，计算满足总价约束的最优综合单价。</div>', unsafe_allow_html=True)
    st.markdown('''<div class="hero-workbench"><div class="hero-chip">Phase 2 · 联合优化</div><div class="hero-eyebrow">QUICK START</div><div class="hero-heading">开始一次新的报价测算</div><div class="hero-copy">上传限价清单和成本清单，系统会自动完成数据识别、项目匹配、异常检查和联合优化。</div><div class="hero-stats"><div class="hero-stat"><div class="hero-stat-value">Excel</div><div class="hero-stat-label">固定格式自动识别</div></div><div class="hero-stat"><div class="hero-stat-value">MILP</div><div class="hero-stat-label">联合最优报价模型</div></div><div class="hero-stat"><div class="hero-stat-value">C13</div><div class="hero-stat-label">结算调整规则已接入</div></div></div></div>''', unsafe_allow_html=True)
    st.markdown('<div class="section-title">测算流程</div><div class="section-subtitle">三步完成一次报价优化。</div>', unsafe_allow_html=True)
    st.markdown('''<div class="step-grid"><div class="step-card"><div class="step-num">01</div><div class="step-title">上传资料</div><div class="step-desc">导入限价清单与成本清单</div></div><div class="step-card"><div class="step-num">02</div><div class="step-title">检查数据</div><div class="step-desc">自动匹配并提示异常项目</div></div><div class="step-card"><div class="step-num">03</div><div class="step-title">输出结果</div><div class="step-desc">生成最优单价与利润结果</div></div></div>''', unsafe_allow_html=True)
    st.markdown('<div class="param-card"><div class="param-head">本次报价参数</div><div class="param-sub">参数只影响当前测算，不会修改原始 Excel 文件。</div>', unsafe_allow_html=True)
    p1, p2, p3 = st.columns(3, gap="large")
    with p1:
        project_id = st.text_input("项目标识", value="当前项目")
        target_total = st.number_input("目标总报价（元）", min_value=0.01, value=1260000.0, step=1000.0)
    with p2:
        fixed_pretax = st.number_input("措施项目/固定税前金额（元）", min_value=0.0, value=22381.74, step=100.0)
        vat_rate = st.number_input("增值税率", min_value=0.0, max_value=1.0, value=0.09, step=0.01, format="%.4f")
    with p3:
        surtax_rate = st.number_input("附加税率", min_value=0.0, max_value=1.0, value=0.12, step=0.01, format="%.4f")
        min_price = st.number_input("单项最低报价（仅防止 0 报价）", min_value=0.01, value=0.01, step=0.01, format="%.2f")
    clause_enabled = st.checkbox("启用 C13 结算调整条款", value=True)
    st.caption("基准：最高限价 · 严重低价阈值：50% · 工程量偏差阈值：15%")
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">上传报价资料</div><div class="section-subtitle">系统将自动识别固定格式 Excel，并完成编码匹配与异常检查。</div>', unsafe_allow_html=True)
    up1, up2 = st.columns(2, gap="large")
    with up1:
        st.markdown('<div class="card upload-card"><div class="upload-icon">↥</div><div class="upload-title">限价清单</div><div class="upload-hint">综合单价列作为不含税最高限价</div></div>', unsafe_allow_html=True)
        cap_file = st.file_uploader("选择限价清单", type=["xlsx"], key="cap", label_visibility="collapsed")
    with up2:
        st.markdown('<div class="card upload-card"><div class="upload-icon">↥</div><div class="upload-title">成本清单</div><div class="upload-hint">综合单价列作为含税成本单价</div></div>', unsafe_allow_html=True)
        cost_file = st.file_uploader("选择成本清单", type=["xlsx"], key="cost", label_visibility="collapsed")

    if not cap_file or not cost_file:
        st.info("请先上传两份清单。上传完成后，将出现“识别文件并计算”按钮。")
        st.stop()

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    if st.button("识别文件并计算  →", type="primary", use_container_width=True):
        with tempfile.TemporaryDirectory(prefix="bidpricing-ui-") as temp_dir:
            try:
                prepared = _prepare_inputs(cap_file, cost_file, project_id.strip() or "当前项目", temp_dir)
            except Exception as exc:  # noqa: BLE001 - UI 统一显示可读错误
                st.error(f"Excel 识别失败：{exc}")
                st.stop()
        cap_report, cost_report, cap_clean, cost_clean, matched = prepared
        st.session_state["prepared"] = prepared
        st.session_state["target_total"] = target_total
        st.session_state["fixed_pretax"] = fixed_pretax
        st.session_state["vat_rate"] = vat_rate
        st.session_state["surtax_rate"] = surtax_rate
        st.session_state["min_price"] = min_price
        st.session_state["clause_enabled"] = clause_enabled

    prepared = st.session_state.get("prepared")
    if not prepared:
        st.stop()
    cap_report, cost_report, cap_clean, cost_clean, matched = prepared

    st.markdown('<div class="section-title">数据检查</div><div class="section-subtitle">确认两侧清单已正确识别后，再运行报价优化。</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4, gap="medium")
    c1.metric("限价规范行", len(cap_report.rows))
    c2.metric("成本规范行", len(cost_report.rows))
    c3.metric("匹配总项", matched.n_master)
    c4.metric("异常项", len(matched.anomalies))

    if matched.anomalies:
        with st.expander("查看异常数据", expanded=True):
            st.warning(matched.summary_line())
            st.dataframe([a.to_dict() for a in matched.anomalies], use_container_width=True)
    no_cap = [i.item_id for i in matched.items if i.no_cap]
    if no_cap:
        st.warning(f"有 {len(no_cap)} 项限价综合单价为空：这表示没有最高限价，不按 0 处理。当前 C13 结算调整求解需要有限最高限价，暂不自动求解这些项目。")

    items = _items_from_match(matched, st.session_state["min_price"])
    missing_cap = [x["item_id"] for x in items if x["cap"] is None]
    if missing_cap:
        st.error("当前版本无法对含 C13 的无最高限价项建立严重低价判断，请先补充最高限价或关闭 C13。")
        st.stop()

    if not st.session_state["clause_enabled"]:
        st.error("当前界面第一版只接入 C13 结算调整模式，请启用“不平衡报价条款”。")
        st.stop()

    clause = {
        "enabled": True, "reference": "CAP", "tol_lo": 0.5, "tol_hi": 0.5,
        "mechanism": "SETTLEMENT_ADJUSTMENT",
    }
    if st.button("重新计算", type="secondary"):
        with st.spinner("正在运行 Phase 2 MILP，并进行独立利润复算…"):
            result = run_settlement_adjusted_quote_pipeline(
                target_total=st.session_state["target_total"], items=items,
                fixed_pretax=st.session_state["fixed_pretax"],
                vat_rate=st.session_state["vat_rate"],
                surtax_rate=st.session_state["surtax_rate"],
                config_dir=ROOT / "config", unbalanced_clause=clause,
            )
        st.session_state["result"] = result

    result = st.session_state.get("result")
    if not result:
        st.info("文件识别完成。点击“重新计算”运行联合优化。")
        st.stop()
    if result.status != "PASS":
        st.error(f"计算未通过：{result.reason}")
        if result.warnings:
            st.warning("；".join(result.warnings))
        st.stop()

    rows = _result_rows(result, items)
    m1, m2, m3 = st.columns(3)
    m1.metric("状态", result.solver_status or "OPTIMAL")
    m2.metric("竞争性分部分项预算", f"{result.competitive_budget:,.2f}")
    m3.metric("结算调整后利润", f"{result.objective:,.2f}")
    st.success(result.reason)
    st.dataframe(rows, use_container_width=True, hide_index=True)
    payload = {
        "status": result.status, "target_total": result.target_total,
        "competitive_budget": result.competitive_budget,
        "objective": result.objective, "p_by_id": dict(result.p_by_id),
        "warnings": list(result.warnings), "unbalanced_clause": clause,
        "items": rows,
    }
    st.download_button("下载报价结果 JSON", json.dumps(payload, ensure_ascii=False, indent=2),
                       file_name="报价结果_结算调整版.json", mime="application/json")


if __name__ == "__main__":
    main()
