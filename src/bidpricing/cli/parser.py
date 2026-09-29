"""argparse 组装（自 bidpricing/cli.py 逐字拆出）。

build_parser 只做参数定义与 func 绑定；命令实现见各域模块。
"""
from __future__ import annotations

import argparse
from ..paths import GATE0_REGISTRY, PROJECT_SELECTION, config_dir, repo_root
from .boq import cmd_clean_boq, cmd_import_register, cmd_import_verify, cmd_match_boq, cmd_parse_boq, cmd_validate_boq
from .closedloop import cmd_calibrate, cmd_closed_loop, cmd_precision_monitor, cmd_predict_register
from .common import PREDICTED_Q1_SOURCE_CHOICES, RULE_SET_CHOICES
from .governance import cmd_audit_verify, cmd_freeze, cmd_gate_check, cmd_identity_check, cmd_options, cmd_ruleset_select, cmd_ruleset_selftest, cmd_scope_impact, cmd_status
from .parity import cmd_parity_check, cmd_parity_suite
from .profit import cmd_profit_check, cmd_total_price_check
from .quote import cmd_cost_check, cmd_pricing_card, cmd_qty_check
from .solver_checks import cmd_backend_check, cmd_compile_check, cmd_constraint_check, cmd_contract_check, cmd_derive_check, cmd_diagnose, cmd_formulate_check, cmd_judgment_matrix, cmd_milp_check, cmd_phase1_check, cmd_phase1_solve, cmd_precheck, cmd_ref_check, cmd_settlement_check, cmd_verify_solution


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bidpricing",
        description="投标报价利润最大化测算模型 —— 实施路线 v3.2.1 执行工具",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_selection_args(p):
        p.add_argument("--tender-document-date", default=None, help="招标文件发布日期 YYYY-MM-DD")
        p.add_argument("--contract-date", default=None, help="合同签订日期 YYYY-MM-DD")
        p.add_argument("--standard-version-declared", default=None, help="招标文件/合同声明的规范版本")
        p.add_argument("--region", default=None)
        p.add_argument("--project-type", default=None)
        p.add_argument("--funding-type", default=None)
        p.add_argument("--tender-document-override", default=None)
        p.add_argument("--contract-override", default=None)
        p.add_argument("--adjustment-scope", default=None, choices=["FULL", "SEGMENT"],
                       help="选择项 adjustment_scope 的临时落值（优先级高于落值文件）")
        p.add_argument("--selection-file", default=None,
                       help=f"选择项落值文件，默认 config/{PROJECT_SELECTION}")

    p_gate = sub.add_parser("gate-check", help="执行 Gate 0 全部机械判据")
    add_selection_args(p_gate)
    p_gate.add_argument("--gate-0b-passed-at", default=None, help="Gate 0b 通过时间戳（ISO 8601）")
    p_gate.add_argument("--phase1-first-build-at", default=None, help="WP4 Phase 1 首次构建时间戳")
    p_gate.add_argument("--json", action="store_true", help="输出 JSON")
    p_gate.set_defaults(func=cmd_gate_check)

    p_sel = sub.add_parser("ruleset-select", help="执行 T00-08 规则集选择")
    add_selection_args(p_sel)
    p_sel.set_defaults(func=cmd_ruleset_select)

    p_ruleset_selftest = sub.add_parser("ruleset-selftest", help="执行 T00-07/T00-08 机械判据自检")
    p_ruleset_selftest.add_argument("--rho-probe", type=float, default=0.01)
    p_ruleset_selftest.set_defaults(func=cmd_ruleset_selftest)

    p_fz = sub.add_parser("freeze", help="冻结契约制品（写入 version/hash/frozen_at）")
    p_fz.add_argument("--all", action="store_true", help="冻结注册表内全部已存在的制品")
    p_fz.add_argument("--gate", default=None, choices=["gate_0a", "gate_0b"])
    p_fz.add_argument("--key", default=None)
    p_fz.set_defaults(func=cmd_freeze)

    # ------------------------------------------------------------ options
    p_opt = sub.add_parser(
        "options",
        help="查看 / 落值 / 撤销项目级选择项（adjustment_scope 等）",
    )
    p_opt.add_argument("action", choices=["list", "set", "clear"])
    p_opt.add_argument("--key", default=None, help="选择项 key（set/clear 必填）")
    p_opt.add_argument("--value", default=None, help="取值（set 必填）")
    p_opt.add_argument("--rule-set", default=None, choices=list(RULE_SET_CHOICES),
                       help="规则集——合法取值集合随规则集而变，故必须显式给出")
    p_opt.add_argument("--rationale", default=None, help="选择依据（计入审计快照）")
    p_opt.add_argument("--actor", default="operator", help="落值人标识")
    p_opt.add_argument("--json", action="store_true", help="输出 JSON（list）")
    p_opt.set_defaults(func=cmd_options)

    # ------------------------------------------------------- scope-impact
    p_si = sub.add_parser(
        "scope-impact",
        help="度量 adjustment_scope 两个取值在**规则层**的结算分叉",
    )
    p_si.add_argument("--q0", type=float, required=True, help="投标基准工程量")
    p_si.add_argument("--q1", type=float, required=True, help="实施工程量")
    p_si.add_argument("--p0", type=float, required=True, help="投标单价")
    p_si.add_argument("--rho-plus", type=float, default=0.0, help="ρ⁺（默认 0，规范无量化依据）")
    p_si.add_argument("--rho-minus", type=float, default=0.0, help="ρ⁻（默认 0）")
    p_si.add_argument("--json", action="store_true")
    p_si.set_defaults(func=cmd_scope_impact)

    # ------------------------------------------------------------ status
    p_stat = sub.add_parser(
        "status",
        help="生成项目状态快照（全部现场派生，可写入 docs/STATE.md）",
    )
    p_stat.add_argument("--contract-date", default="2026-03-01",
                        help="合同基准日 YYYY-MM-DD（决定规则集选择）")
    p_stat.add_argument("--write", action="store_true",
                        help="写入 docs/STATE.md（跨会话交接用）")
    p_stat.add_argument("--print-md", action="store_true",
                        help="配合 --write 时仍打印完整 Markdown")
    p_stat.add_argument("--json", action="store_true", help="输出 JSON 原始快照")
    p_stat.set_defaults(func=cmd_status)

    # ------------------------------------------------------ identity-check
    p_id = sub.add_parser(
        "identity-check",
        help="总价恒等式核验（对真实样本执行数值判据）",
    )
    p_id.add_argument(
        "--fixture",
        default=str(repo_root() / "tests" / "data" / "xiyong_l_district" / "pair.json"),
        help="限价/报价配对样本 JSON 路径",
    )
    p_id.add_argument("--side", choices=["bid", "cap"], default="bid",
                      help="核验哪一侧：bid=投标报价（默认，数据完整）/ cap=招标限价")
    p_id.add_argument("--json", action="store_true", help="输出 JSON")
    p_id.set_defaults(func=cmd_identity_check)

    # ------------------------------------------------------ total-price-check
    p_tp = sub.add_parser(
        "total-price-check",
        help="T00-06B 总价分解核验（划分闭合 + P_competitive 联动往返）",
    )
    p_tp.add_argument(
        "--fixture",
        default=str(repo_root() / "tests" / "data" / "xiyong_l_district" / "pair.json"),
        help="限价/报价配对样本 JSON 路径",
    )
    p_tp.add_argument("--side", default="bid", choices=("bid", "cap"),
                      help="报价侧(bid) 或限价侧(cap)")
    p_tp.add_argument("--json", action="store_true", help="输出 JSON")
    p_tp.set_defaults(func=cmd_total_price_check)

    # ------------------------------------------------------ profit-check
    p_profit_check = sub.add_parser(
        "profit-check",
        help="T00-12 利润口径桥接表核验（目标口径 / 同源同值 / 亏损政策）",
    )
    p_profit_check.add_argument(
        "--fixture",
        default=str(repo_root() / "tests" / "data" / "xiyong_l_district" / "pair.json"),
        help="用于 PB-03 数值对账的配对样本",
    )
    p_profit_check.add_argument("--side", default="bid", choices=("bid", "cap"))
    p_profit_check.add_argument("--no-fixture", dest="with_fixture", action="store_false",
                      default=True, help="跳过 PB-03 数值对账")
    p_profit_check.add_argument("--json", action="store_true")
    p_profit_check.add_argument("--freeze", action="store_true",
                      help="写入 frozen_at（须先解除全部阻断项）")
    p_profit_check.add_argument("--actor", default=None,
                      help="冻结执行人标识，**必填且如实填写**："
                           "业务声明须为 user（ADR-0007）；机制冻结若由 Agent "
                           "代操作，须写明 agent(...)，不得冒充用户")
    p_profit_check.set_defaults(func=cmd_profit_check)

    # ------------------------------------------------------ contract-check
    p_contract_check = sub.add_parser(
        "contract-check",
        help="跨制品契约一致性判据（拦截「同一规则在两份制品里说法不同」）",
    )
    p_contract_check.add_argument("--json", action="store_true", help="输出 JSON")
    p_contract_check.set_defaults(func=cmd_contract_check)

    # ------------------------------------------------------------ parse-boq
    p_parse_boq = sub.add_parser(
        "parse-boq",
        help="T01-00B：解析清单 xlsx 为规范行（解析日志 + 字段映射报告 + 失败样本清单）",
    )
    p_parse_boq.add_argument("xlsx", help="清单文件路径（限价/报价/成本清单同构）")
    p_parse_boq.add_argument("--project-id", required=True,
                      help="项目编号（主键第一段；身份命名空间，不携带计价规则）")
    p_parse_boq.add_argument("--out-dir", default=None,
                      help="三项产出的落盘目录（默认 docs/parsed/<文件名>）")
    p_parse_boq.set_defaults(func=cmd_parse_boq)

    # ------------------------------------------------------------ clean-boq
    p_cb = sub.add_parser(
        "clean-boq",
        help="T01-03：解析 + 规范化清洗 → 类型化 canonical 行（含空值语义与异常清单）",
    )
    p_cb.add_argument("xlsx", help="清单文件路径（限价/报价/成本清单同构）")
    p_cb.add_argument("--project-id", required=True,
                      help="项目编号（主键第一段）")
    p_cb.add_argument("--side", required=True, choices=["cap", "cost"],
                      help="清单侧：cap=限价清单（q0/cap），cost=成本清单（q1_point/c_i）")
    p_cb.add_argument("--attribution", default=None,
                      choices=["DRAWING_DIFF", "CHANGE_ORDER", "BOTH", "UNKNOWN"],
                      help="q0≠q1 的变化归因标签（OI-01；默认 UNKNOWN）")
    p_cb.add_argument("--out-dir", default=None,
                      help="产出落盘目录（默认 docs/cleaned/<文件名>/<side>）")
    p_cb.set_defaults(func=cmd_clean_boq)

    # ------------------------------------------------------------ match-boq
    p_mb = sub.add_parser(
        "match-boq",
        help="T01-04：限价侧 + 成本侧 → master 并集融合 + 覆盖率 + 异常清单",
    )
    p_mb.add_argument("--cap-xlsx", required=True, help="限价清单 xlsx")
    p_mb.add_argument("--cost-xlsx", required=True, help="成本清单 xlsx")
    p_mb.add_argument("--project-id", required=True,
                      help="项目编号（主键第一段）")
    p_mb.add_argument("--attribution", default=None,
                      choices=["DRAWING_DIFF", "CHANGE_ORDER", "BOTH", "UNKNOWN"],
                      help="q0≠q1 的变化归因标签（OI-01；默认 UNKNOWN）")
    p_mb.add_argument("--out-dir", default=None,
                      help="产出落盘目录（默认 docs/matched/<project_id>）")
    p_mb.set_defaults(func=cmd_match_boq)

    # -------------------------------------------------------- import-register
    p_ir = sub.add_parser(
        "import-register",
        help="T01-05：登记一次源文件导入（指纹 + 逐 sheet 哈希，追加式）",
    )
    p_ir.add_argument("xlsx", help="源清单 xlsx")
    p_ir.add_argument("--project-id", required=True, help="项目编号")
    p_ir.add_argument("--side", required=True, choices=["cap", "cost"],
                      help="清单侧（登记表按 project×side 分文件）")
    p_ir.add_argument("--source-owner", default="UNKNOWN",
                      help="文件来源方（招标人/用户/…）")
    p_ir.add_argument("--version-note", default=None,
                      help="人工版本说明（缺省=内容指纹 sha256[:12]）")
    p_ir.set_defaults(func=cmd_import_register)

    # ---------------------------------------------------------- import-verify
    p_iv = sub.add_parser(
        "import-verify",
        help="T01-05：复算前校验源文件指纹（被替换 → 拒绝复用旧复算结果）",
    )
    p_iv.add_argument("xlsx", help="源清单 xlsx")
    p_iv.add_argument("--project-id", required=True, help="项目编号")
    p_iv.add_argument("--side", required=True, choices=["cap", "cost"],
                      help="清单侧")
    p_iv.set_defaults(func=cmd_import_verify)

    p_vb = sub.add_parser("validate-boq",
                          help="T01-06：D01–D13 数据校验（10 阻断 + 3 告警）")
    p_vb.add_argument("--cap-xlsx", required=True, help="限价清单 xlsx")
    p_vb.add_argument("--cost-xlsx", required=True, help="成本清单 xlsx")
    p_vb.add_argument("--project-id", required=True)
    p_vb.add_argument("--attribution", default=None,
                      help="q1_point 归属标签（DRAWING_DIFF/CHANGE_ORDER/BOTH/UNKNOWN）")
    p_vb.add_argument("--p-star", type=float, default=None, help="报价总价（用户给定）")
    p_vb.add_argument("--p-star-max", type=float, default=None, help="总价限价")
    p_vb.add_argument("--p-star-min", type=float, default=None, help="总价下界（可选）")
    p_vb.add_argument("--basis-json", default=None,
                      help="税口径声明 JSON（cap_tax_scope/cost_tax_scope）")
    p_vb.set_defaults(func=cmd_validate_boq)

    # ---- T00-01 计价规则卡 -----------------------------------------------
    p_pricing_card = sub.add_parser(
        "pricing-card", help="T00-01 计价规则卡：展示口径 / 试算单项 P1")
    p_pricing_card.add_argument("--q0", type=float, default=None,
                      help="招标清单工程量 Q0（试算用）")
    p_pricing_card.add_argument("--q1", type=float, default=None,
                      help="结算预期工程量 Q1（试算用）")
    p_pricing_card.add_argument("--p0", type=float, default=None,
                      help="中标综合单价 P0（试算用）")
    p_pricing_card.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                      help="override：rho_plus/rho_minus/adjustment_scope 等"
                           "（未登记键一律阻断）")
    p_pricing_card.add_argument("--from-match", default=None, metavar="MATCH_REPORT",
                      help="读取 T01-04 匹配报告，统计真实各项的 r 分支分布"
                           "（分支只依赖 r=Q1/Q0，与 P0 无关）")
    p_pricing_card.set_defaults(func=cmd_pricing_card)

    # ---- T00-09 / T00-11 成本口径 ----------------------------------------
    p_cost_check = sub.add_parser(
        "cost-check", help="T00-09 成本口径证明包 + T00-11 c_i 假设声明书 + "
                           "H-002 含税成本转换 + H-003 隐形成本分列 + "
                           "H-004 低价确认留痕校验")
    p_cost_check.add_argument("--declare-source", default=None,
                      choices=["COST_DB", "HISTORICAL_SETTLEMENT",
                               "SUPPLIER_QUOTE", "EXPERT_ESTIMATE"],
                      help="声明 c_i 来源并落值（写入假设声明书，需 --actor）")
    p_cost_check.add_argument("--actor", default=None, help="声明人（与 --declare-source 同用）")
    p_cost_check.add_argument("--evidence", action="append", default=[],
                      help="来源证据条目（可多次），如 '询价日期=2026-09-10'")
    p_cost_check.add_argument("--freeze", action="store_true",
                      help="冻结假设声明书（写 frozen_at；须先解除全部阻断项）")
    p_cost_check.set_defaults(func=cmd_cost_check)

    # ---- T00-10A / T00-10B 结算工程量 q1 -------------------------------
    p_qc = sub.add_parser(
        "qty-check", help="T00-10A/10B 结算工程量 q1 假设声明书校验")
    p_qc.add_argument("--declare-sensitivity", default=None,
                      choices=["RATIO_SCAN", "SCENARIO_SWEEP",
                               "NOT_REQUIRED_JUSTIFIED"],
                      help="声明点值 q1 的敏感性义务并落值（需 --actor）")
    p_qc.add_argument("--actor", default=None,
                      help="声明人（与 --declare-sensitivity 同用）")
    p_qc.add_argument("--freeze", action="store_true",
                      help="冻结 q1 假设声明书（须先解除全部阻断项）")
    p_qc.set_defaults(func=cmd_qty_check)

    # ---- T04-00 Phase 1 精确性条件 -------------------------------------
    p_p1 = sub.add_parser(
        "phase1-check",
        help="T04-00 Phase 1 精确性条件判定 + 反例集复算")
    p_p1.add_argument("--case", default="all",
                      help="只跑指定 case（CE-01…CE-09 / PE-01）；默认 all")
    p_p1.add_argument("--instance", default=None,
                      help="对自定义实例 JSON 跑判定（结构见 "
                           "Phase1Instance.from_dict）")
    p_p1.add_argument("--json", action="store_true", help="输出 JSON")
    p_p1.set_defaults(func=cmd_phase1_check)

    # ---- T04-01 Phase 1 解析解 ------------------------------------------
    p_p1s = sub.add_parser(
        "phase1-solve",
        help="T04-01 Phase 1 解析解（排序+二分+贪心定容；输出 λ 与层归属）")
    p_p1s.add_argument("--instance", default=None,
                       help="对自定义实例 JSON 求解（结构见 Phase1Instance.from_dict）")
    p_p1s.add_argument("--probe", default="free-cap", choices=("free-cap", "simple"),
                       help="无 --instance 时用哪个内置探针：free-cap（含不限价项与"
                            "平台）或 simple（上界全有限、λ 内点唯一）")
    p_p1s.add_argument("--floor-json", default=None,
                       help="显式 floor_i 表 JSON：{item_id: 值}。不给则自动向 "
                            "T03-02 派生量层索取（与 verify-solution 共用同一处解析）")
    p_p1s.add_argument("--json", action="store_true", help="输出 JSON")
    p_p1s.set_defaults(func=cmd_phase1_solve)

    # ---- T03-04 约束判定器 ----------------------------------------------
    p_cj = sub.add_parser(
        "constraint-check",
        help="T03-04 约束判定器：对候选报价向量逐条判定 C1–C13（六元组）")
    p_cj.add_argument("--instance", default=None,
                      help="JSON 文件：{'instance': {...}, 'p': {...}, 'z': {...},"
                           " 'Z': ..., 以及 N_max/d_max/Z_min/pi_target/R_min/"
                           "sigma_max/kappa_max/front_rho}。缺 instance 键时整个"
                           "文档视为实例，p 取 Phase 1 解析解")
    p_cj.add_argument("--probe", default="free-cap", choices=("free-cap", "simple"),
                      help="无 --instance 时用哪个内置探针")
    p_cj.add_argument("--floor-json", default=None,
                      help="显式 floor_i 表 JSON：{item_id: 值}（缺省自动向 "
                           "T03-02 派生量层索取）")
    p_cj.add_argument("--json", action="store_true", help="输出 JSON")
    p_cj.set_defaults(func=cmd_constraint_check)

    # ---- T03-05 判定层测试矩阵 ------------------------------------------
    p_jm = sub.add_parser(
        "judgment-matrix",
        help="T03-05 判定层测试矩阵：13 约束 × 6 边界类 = 78 格 + 变异体存活审计"
             " + 规则优先级 / 规则集切换")
    p_jm.add_argument("--json", action="store_true", help="输出 JSON")
    p_jm.add_argument("--cases", action="store_true",
                      help="列出全部 78 格的逐格结论（默认只列失配格）")
    p_jm.add_argument("--no-mutants", action="store_true",
                      help="跳过变异体审计（仅供快速自检；正式结论不得据此通过）")
    p_jm.add_argument("--no-precedence", action="store_true", help="跳过规则优先级检查")
    p_jm.add_argument("--no-switch", action="store_true", help="跳过规则集切换检查")
    p_jm.set_defaults(func=cmd_judgment_matrix)

    # ---- T03-03 Phase 0 预检与可行性证书 ---------------------------------
    p_precheck = sub.add_parser(
        "precheck",
        help="T03-03 Phase 0 预检：可行性证书（P_min/P_max/P*_var/P*_eff/ΔP）"
             " + PC-01..PC-08 判定；越界判 INFEASIBLE 且不进求解器")
    p_precheck.add_argument("--instance", default=None,
                      help="JSON 文件：{'instance': {...}, 'rule_set_id': ...,"
                           " 'contract_type': ..., 'pi_target': ..., "
                           "'alpha_cap': ..., 'fixed_pretax': ..., "
                           "'vat_rate': ..., 'surtax_rate': ..., "
                           "'supplied_material': ..., 'env_tax': ...}")
    p_precheck.add_argument("--probe", default="simple", choices=("free-cap", "simple"),
                      help="无 --instance 时用哪个内置探针（默认 simple：全项"
                           "有界、全链可 PASS；free-cap 演示 SKIP 与声明矛盾）")
    p_precheck.add_argument("--json", action="store_true", help="输出 JSON")
    p_precheck.set_defaults(func=cmd_precheck)

    # ---- T03-06 不可行诊断 ------------------------------------------------
    p_dg = sub.add_parser(
        "diagnose",
        help="T03-06 不可行诊断：结构冲突（Pass A）+ 删除过滤器冲突集"
             "（Pass B）+ §6.3 建议动作；三态 INFEASIBLE/UNKNOWN/BLOCKED 分列")
    p_dg.add_argument("--instance", default=None,
                      help="JSON 文件：{'instance': {...}, 'floor': {...}}")
    p_dg.add_argument("--probe", default="simple", choices=("free-cap", "simple"),
                      help="无 --instance 时用哪个内置探针")
    p_dg.add_argument("--oracle", default="phase1",
                      choices=("phase1", "milp", "chain"),
                      help="预言机：phase1=解析侧内置（T03-06）；milp=编译链"
                           "（T04-02E，零依赖环境自动退 UNKNOWN）；"
                           "chain=phase1 优先、MILP 兜底（首个非 UNKNOWN 胜出）")
    p_dg.add_argument("--json", action="store_true", help="输出 JSON")
    p_dg.set_defaults(func=cmd_diagnose)

    # ---- T03-01 结算规则引擎 ----------------------------------------------
    p_settlement_check = sub.add_parser(
        "settlement-check",
        help="T03-01 结算规则引擎：三段调价 / 边界归属 / 规则集分发 / 合同覆盖；"
             "--judge 跑 SR-01..SR-09 判据套件")
    p_settlement_check.add_argument("--rule-set", default="GB/T50500-2024",
                      dest="rule_set",
                      help="rule_set_id（未注册 ⇒ BLOCKED，不默认取任一侧）")
    p_settlement_check.add_argument("--q0", type=float, default=None, help="招标清单工程量")
    p_settlement_check.add_argument("--q1", type=float, default=None, help="结算预期工程量")
    p_settlement_check.add_argument("--p0", type=float, default=None, help="中标综合单价")
    p_settlement_check.add_argument("--scope", default=None,
                      choices=("SEGMENT", "FULL"),
                      help="adjustment_scope（2024 未冻结 ⇒ BLOCKED）")
    p_settlement_check.add_argument("--override", action="append", default=None,
                      metavar="KEY=VALUE",
                      help="合同层覆盖（可重复）；未登记键 ⇒ BLOCKED")
    p_settlement_check.add_argument("--override-layer", default="contract",
                      dest="override_layer",
                      help="覆盖来源层标签（contract/tender/regional；"
                           "standard 标签下不得偏离实现常量）")
    p_settlement_check.add_argument("--declared-by", default=None, dest="declared_by",
                      help="依据出处（合同条款号等），留痕用")
    p_settlement_check.add_argument("--judge", action="store_true",
                      help="跑 SR-01..SR-09 判据套件（固定探针网格）")
    p_settlement_check.add_argument("--json", action="store_true", help="输出 JSON")
    p_settlement_check.set_defaults(func=cmd_settlement_check)

    # ---- T04-07：MILP 独立验收协议 --------------------------------
    p_ma = sub.add_parser(
        "milp-check",
        help="MILP 独立验收协议（T04-07）——这次求解够不够格被当作「已证最优」",
        description=(
            "按 config/milp_acceptance_spec.json 验收一次求解：六字段"
            "（status / integer_feasible / objective_gap / best_bound /"
            " time_limit / incumbent）逐项核验，输出「最优性已证 / 未证 / 不可判」。"
            "★ 求解器自报 Optimal 不是验收结论；never_upgrade；禁 KKT 证 MILP。"
        ),
    )
    p_ma.add_argument(
        "--form", choices=("LP", "MILP", "both"), default="both",
        help="要验收的模型形态（默认 both：LP 应判 SKIP、MILP 才适用）",
    )
    p_ma.add_argument(
        "--time-limit", type=float, default=30.0,
        help="求解时限（秒）。未声明时限 ⇒ MA-07 判 BLOCKED（无法区分算完与被中断）",
    )
    p_ma.add_argument("--json", action="store_true", help="输出 JSON")
    p_ma.set_defaults(func=cmd_milp_check)

    # ---- T04-08 独立参考实现 --------------------------------------------
    p_ref = sub.add_parser(
        "ref-check",
        help="T04-08 独立参考实现（第二条路径重算 R_i/残差/Z + 三层隔离证明）")
    p_ref.add_argument("--instance", default=None,
                       help="对自定义实例 JSON 重算（结构见 Phase1Instance.from_dict）")
    p_ref.add_argument("--probe", default="free-cap", choices=("free-cap", "simple"),
                       help="无 --instance 时用哪个内置探针")
    p_ref.add_argument("--p-json", default=None,
                       help="显式报价向量 JSON：{item_id: p}。不给则用 T04-01 "
                            "解析解（仅作「给参考层喂一组 p」的用途）")
    p_ref.add_argument("--z-solver", type=float, default=None,
                       help="对照侧的 Z_solver（不给则用独立裁判 check_solution 的 Z）")
    p_ref.add_argument("--json", action="store_true", help="输出 JSON")
    p_ref.set_defaults(func=cmd_ref_check)

    p_compile_check = sub.add_parser(
        "compile-check",
        help="T04-02B 约束编译判定（Formulation → CompiledModel 的保真性）")
    p_compile_check.add_argument("--instance", default=None,
                      help="对自定义实例 JSON 跑判定")
    p_compile_check.add_argument("--json", action="store_true",
                      help="输出完整模型（含稀疏行与化简台账），供 T04-02C 消费")
    # 求解层入参（不属实例结构，须单独给）。探针分支用合成值；--instance 分支
    # 缺省为 None ⇒ 对应占位行 NOT_COMPILED ⇒ CC-05 BLOCKED（ADR-0013）。
    p_compile_check.add_argument("--n-max", type=float, default=None,
                      help="C7 亏损项数上限 N_max（缺 ⇒ C7 汇总行不编译）")
    p_compile_check.add_argument("--theta", type=float, default=None,
                      help="C6 亏损缺口上限 θ（×P*）")
    p_compile_check.add_argument("--d-max", type=float, default=None,
                      help="C8 地板下浮上限 d_max")
    p_compile_check.add_argument("--z-min", type=float, default=None,
                      help="C9a 盈利门槛 Z_min")
    p_compile_check.add_argument("--pi-target", type=float, default=None,
                      help="C9b 目标利润率 π")
    p_compile_check.add_argument("--tf-terms", default=None,
                      help="C10 的 T_front 三元组 JSON 文件：{item_id: [rho, q0, c]}")
    p_compile_check.set_defaults(func=cmd_compile_check)


    # ------------------------------------------------------- formulate-check
    p_fm = sub.add_parser(
        "formulate-check",
        help="T04-02A LP 形式化（变量/目标/约束映射 + 制品↔实现双向锁定）")
    p_fm.add_argument("--instance", default=None,
                      help="Phase 1 实例 JSON；省略则用内置探针实例")
    p_fm.add_argument("--json", action="store_true", help="输出 JSON")
    p_fm.set_defaults(func=cmd_formulate_check)

    # ------------------------------------------------------- backend-check
    p_bk = sub.add_parser(
        "backend-check",
        help="T04-02C 求解后端适配（BB-01..BB-09 + CC-09 复跑）")
    p_bk.add_argument("--instance", default=None,
                      help="对自定义实例 JSON 跑判定")
    p_bk.add_argument("--prefer", default=None,
                      help="临时指定后端条目（不写制品，用于替换性检验）")
    p_bk.add_argument("--json", action="store_true", help="输出 JSON")
    p_bk.set_defaults(func=cmd_backend_check)

    # ------------------------------------------------------- verify-solution
    p_vs = sub.add_parser(
        "verify-solution",
        help="T04-02D 解校验器（SV-01..SV-13：可行性/目标值/上下界/层归属）")
    p_vs.add_argument("--instance", default=None,
                      help="对自定义实例 JSON 跑复核；省略则用内置探针实例")
    p_vs.add_argument("--prefer", default=None,
                      help="临时指定后端条目（求解步用）")
    p_vs.add_argument("--reference", type=float, default=None,
                      help="独立参考实现给出的 Z_ref（owner = T04-08）；不给则 SV-13 判 BLOCKED")
    p_vs.add_argument("--floor-json", default=None,
                      help="显式指定 floor_i 表 JSON：{item_id: 值}。"
                           "**不给**时本命令自动向 T03-02 派生量层索取"
                           "（唯一生产者）；两者都拿不到才判 BLOCKED，"
                           "且不得用 L_i 或 c_i 冒充")
    p_vs.add_argument("--json", action="store_true", help="输出 JSON")
    p_vs.set_defaults(func=cmd_verify_solution)

    # --------------------------------------------------------- derive-check
    p_dq = sub.add_parser(
        "derive-check",
        help="T03-02 派生量计算（DQ-01..DQ-10：L/U/floor/r_eff 与地板口径）")
    p_dq.add_argument("--instance", default=None,
                      help="对自定义实例 JSON 跑判定；省略则用内置探针实例")
    p_dq.add_argument("--mu", type=float, default=None,
                      help="允许亏损深度 μ。**不给 = 未声明** ⇒ floor 判 BLOCKED"
                           "（μ=0 是合法取值，与「未声明」不是一回事）")
    p_dq.add_argument("--loss-acceptance", default=None,
                      choices=("ACCEPT", "DECLINE"),
                      help="覆盖项目落值；不给则读 project_selection.json")
    p_dq.add_argument("--unbalanced-json", default=None,
                      help="不平衡报价条款块 JSON：{enabled, reference, tol_lo}")
    p_dq.add_argument("--no-unbalanced-clause", action="store_true",
                      help='等价于 --unbalanced-json \'{"enabled": false}\''
                           "（已核查：本项目无该条款）")
    p_dq.add_argument("--json", action="store_true", help="输出 JSON")
    p_dq.set_defaults(func=cmd_derive_check)

    p_p12 = sub.add_parser(
        "parity-check",
        help="T04-04 Phase 1/2 对拍（L1 状态 / L2 数值 / L3 层归属+残差；A/B 两组）")
    p_p12.add_argument("--bundle", default=None,
                       help="两侧结果的留痕 JSON（schema_id=phase12_parity_input_v1）。"
                            "不给 ⇒ 结论 BLOCKED 并具名 owner——**这不是「已通过」**，"
                            "也不是「不适用」")
    p_p12.add_argument("--out", default="docs/phase12_parity_report.json",
                       help="报告落盘路径（生成物，勿手改）")
    p_p12.add_argument("--signoff", default="docs/reference_review_signoff.json",
                       help="T04-08 独立性签署文件")
    p_p12.add_argument("--no-write", action="store_true",
                       help="只打印结论，不落盘")
    p_p12.add_argument("--json", action="store_true", help="输出 JSON")
    p_p12.set_defaults(func=cmd_parity_check)

    p_suite = sub.add_parser(
        "parity-suite",
        help="T04-04：从 golden_dataset_v1 生成对拍 input bundle（两条路径结果留痕）")
    p_suite.add_argument("--out", default="docs/phase12_parity_bundle.json",
                         help="bundle 落盘路径（可复算输入，勿手改）")
    p_suite.add_argument("--json", action="store_true", help="输出 JSON")
    p_suite.set_defaults(func=cmd_parity_suite)

    # ---- T07-03 精度监控
    p_pm = sub.add_parser(
        "precision-monitor",
        help="T07-03：Q1 精度监控（MAE/WAPE/sMAPE + 四元升级闸门；"
             "predicted_q1 来源未登记时如实 BLOCKED）",
    )
    p_pm.add_argument("--records", required=True,
                     help="闭环输入束 JSON（对象或记录数组；字段见 "
                          "config/closed_loop_spec.json）")
    p_pm.add_argument("--json", action="store_true", help="输出 JSON")
    p_pm.set_defaults(func=cmd_precision_monitor)

    # ---- T07-04 参数校准
    p_cf = sub.add_parser(
        "calibrate",
        help="T07-04：参数校准记录（三门前置齐备 → 版本化建议，审批 PENDING；"
             "永不直接覆盖当前 config）",
    )
    p_cf.add_argument("--records", required=True,
                     help="闭环输入束 JSON（字段见 config/closed_loop_spec.json）")
    p_cf.add_argument("--json", action="store_true", help="输出 JSON")
    p_cf.set_defaults(func=cmd_calibrate)

    # ---- T07-02→04 闭环编排
    p_cl = sub.add_parser(
        "closed-loop",
        help="Q0→Q1 闭环编排：对照 → 精度监控 → 参数校准（缺数据逐级如实 BLOCKED/HOLD）",
    )
    p_cl.add_argument("--records", required=True,
                     help="闭环输入束 JSON（字段见 config/closed_loop_spec.json）")
    p_cl.add_argument("--out", default="docs/closed_loop_report.json",
                      help="报告落盘路径（生成物，勿手改）")
    p_cl.add_argument("--no-write", action="store_true",
                     help="只打印结论，不落盘")
    p_cl.add_argument("--json", action="store_true", help="输出 JSON")
    p_cl.set_defaults(func=cmd_closed_loop)

    # ---- T07-03/T07-04 predicted_q1 声明书登记
    p_pr = sub.add_parser(
        "predict-register",
        help="登记 predicted_q1 独立来源声明书（source 域见 config/predicted_q1_spec.json；"
             "留痕四件必给，闭环经 predicted_q1_declaration 引用并交叉校验）",
    )
    p_pr.add_argument("--input", required=True,
                     help="取值文件：{item: 值} 对象 / records 数组 / 含 records 键的对象")
    p_pr.add_argument("--source", required=True,
                     choices=list(PREDICTED_Q1_SOURCE_CHOICES),
                     help="来源（须登记在 closed_loop_spec.predicted_q1_sources）")
    p_pr.add_argument("--actor", default=None,
                     help="声明人，**必填且如实填写**：业务声明=user，Agent 代操作=agent(...)")
    p_pr.add_argument("--rationale", default=None,
                     help="依据，**必填**（留痕四件之一；空 = 未声明）")
    p_pr.add_argument("--at", default=None, help="声明时间戳（缺省=当前 UTC）")
    p_pr.add_argument("--out", default="docs/predicted_q1/predicted_q1.json",
                      help="声明书落盘路径（已存在须 --replace，旧版先留版本）")
    p_pr.add_argument("--replace", action="store_true",
                      help="覆盖已存在的声明书（须已备份/提交旧版）")
    p_pr.set_defaults(func=cmd_predict_register)

    # ---- O19 审计链独立复核
    p_av = sub.add_parser(
        "audit-verify",
        help="O19：独立复核历史审计链（previous_hash/event_hash/时序/operator/"
             "外置锚点；外部审计员可脱离业务进程离线核验）",
    )
    p_av.add_argument("--input", required=True,
                      help="审计链 JSON：事件数组，或含 events 键的对象")
    p_av.add_argument("--anchor", default=None,
                      help="外置留存的链尾 event_hash；缺失则整体重写无法检测")
    p_av.add_argument("--json", action="store_true", help="输出 JSON")
    p_av.set_defaults(func=cmd_audit_verify)

    return parser
