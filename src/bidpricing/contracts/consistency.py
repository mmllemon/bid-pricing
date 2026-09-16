"""跨制品契约一致性判据（**闸门即代码**）。

存在理由
--------
本项目已多次因「同一份规则在两份制品里说法不同」而出错，且**每次都是靠人眼发现的**：

1. ``field_schema.item_id.note`` 写「13/15 位编码体系由 code_system 区分」，
   而 ``input_protocol_schema.code_identity_policy`` 明写「位数不参与合法性判定」——**两说相反**；
2. ``field_schema.code_system.range`` 用 ``GBT50500-2024``，同文件的
   ``rule_set_id.range`` 用 ``GB/T50500-2024``——两个**本应相等**的枚举两种写法。

这类漂移有一个共同结构：**改了一条口径，只改了被讨论的那份文件**。
靠纪律（「删改后全仓 grep」）只能降低概率，不能机械拦截，因此改为可执行判据。

本模块不判断业务对错，只判断**制品之间是否自相矛盾**——这正是人类评审最容易漏、
机器最擅长的部分。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..states import CheckItem, Status

SCOPE = "§7.1.1-契约自洽"

#: 参与交叉校验的制品。key 为展示名，value 为文件名。
ARTIFACTS = {
    "field_schema": "field_schema.json",
    "constraint_schema": "constraint_schema.json",
    "precision_profile": "precision_profile.json",
    "input_protocol_schema": "input_protocol_schema.json",
    "competitiveness_classification": "competitiveness_classification.json",
}

#: 金额/数量类字段必须声明缺失策略（否则「非空即通过」会绕过熔断点）。
_MISSING_POLICY_DOMAIN = {"BLOCK", "WARN", "DEFAULT", "IMPUTE", "IGNORE"}


class _LoadError(Exception):
    def __init__(self, artifact: str, detail: str) -> None:
        super().__init__(detail)
        self.artifact = artifact
        self.detail = detail


def _load(config_dir: Path) -> dict[str, dict]:
    loaded: dict[str, dict] = {}
    for key, fname in ARTIFACTS.items():
        path = config_dir / fname
        if not path.exists():
            raise _LoadError(key, f"制品缺失：{fname}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise _LoadError(key, f"JSON 解析失败：{exc}") from exc
        if not isinstance(payload, dict):
            raise _LoadError(key, f"顶层须为 JSON 对象，实为 {type(payload).__name__}")
        loaded[key] = payload
    return loaded


def _ok(item: str, reason: str, actual=None, expected=None) -> CheckItem:
    return CheckItem(scope=SCOPE, item=item, status=Status.PASS,
                     reason=reason, actual=actual, expected=expected)


def _bad(item: str, reason: str, actual=None, expected=None) -> CheckItem:
    return CheckItem(scope=SCOPE, item=item, status=Status.BLOCKED,
                     reason=reason, actual=actual, expected=expected)


# --------------------------------------------------------------------------- 检查


def _check_field_schema(art: dict) -> list[CheckItem]:
    out: list[CheckItem] = []
    fields = art.get("fields")
    if not isinstance(fields, list) or not fields:
        return [_bad("field_schema.fields", "fields 缺失或为空", actual=type(fields).__name__)]

    names = [f.get("name") for f in fields if isinstance(f, dict)]
    dupes = sorted({n for n in names if names.count(n) > 1})
    out.append(
        _bad("field_schema.唯一性", f"字段名重复：{dupes}", actual=dupes, expected="唯一")
        if dupes else
        _ok("field_schema.唯一性", f"{len(names)} 个字段名唯一")
    )

    illegal = [
        f.get("name") for f in fields
        if isinstance(f, dict) and f.get("missing_policy") not in _MISSING_POLICY_DOMAIN
    ]
    out.append(
        _bad(
            "field_schema.missing_policy",
            f"{len(illegal)} 个字段的 missing_policy 不在取值域内：{illegal[:8]}",
            actual=illegal[:8], expected=sorted(_MISSING_POLICY_DOMAIN),
        ) if illegal else
        _ok("field_schema.missing_policy",
            f"{len(names)} 个字段的 missing_policy 均在取值域内")
    )

    # 声明了「禁止 DEFAULT」的字段族，不得真的带 default
    forbidden = art.get("conventions", {}).get("no_default_field_families") or []
    if forbidden:
        offenders = [
            f.get("name") for f in fields
            if isinstance(f, dict) and f.get("default") is not None
            and f.get("missing_policy") == "DEFAULT"
            and f.get("name") in {"adjustment_scope", "rule_set_id", "c_i", "cap",
                                  "delta_eff", "mu", "floor"}
        ]
        out.append(
            _bad("field_schema.no_default_family",
                 f"禁止 DEFAULT 的字段族中出现默认值：{offenders}",
                 actual=offenders, expected="default=null 且 missing_policy != DEFAULT")
            if offenders else
            _ok("field_schema.no_default_family",
                "禁止 DEFAULT 的字段族均未设置默认值")
        )
    return out


def _check_constraint_inputs_are_declared(field_art: dict, cons_art: dict) -> list[CheckItem]:
    """**本模块的核心判据**：约束引用的每个输入都必须已在字段字典里声明。

    这是「约束字典凭空引用一个字段」的机械拦截——C13 引入
    ``unbalanced_clause`` / ``unbalanced_reference`` / ``unbalanced_tolerance``
    时正是靠它证明字段字典已同步。
    """
    declared = {f.get("name") for f in field_art.get("fields", []) if isinstance(f, dict)}
    #: 允许的非字段输入：模型级符号或中间量，另行声明于约束式自身。
    allowed_non_fields = {
        "P*", "P*_competitive", "Z", "q1_point", "floor", "p_bid", "pricing_role",
        "theta", "N_max", "d_max", "Z_min", "pi_target", "mu",
        "rho_i", "T_front", "kappa_max", "sigma_max", "R_min", "c_i", "q0", "q1",
    }
    missing: dict[str, list[str]] = {}
    for c in cons_art.get("constraints", []):
        if not isinstance(c, dict):
            continue
        unresolved = [
            n for n in (c.get("inputs") or [])
            if n not in declared and n not in allowed_non_fields
        ]
        if unresolved:
            missing[c.get("id", "?")] = unresolved

    if missing:
        return [_bad(
            "constraint_schema.inputs_declared",
            f"{len(missing)} 条约束引用了字段字典中不存在的输入：{missing}",
            actual=missing,
            expected="每个 inputs 名∈field_schema.fields[].name（或列入 allowed_non_fields）",
        )]
    n = len(cons_art.get("constraints", []))
    return [_ok("constraint_schema.inputs_declared",
                f"{n} 条约束的 inputs 全部在字段字典中已声明")]


def _check_constraint_tolerances(prec_art: dict, cons_art: dict) -> list[CheckItem]:
    """容差名必须指向精度档案里真实存在的 eps_* —— 否则容差是空话。"""
    text = json.dumps(prec_art, ensure_ascii=False)
    known = {f"eps_{k}" for k in ("solver", "price", "quantity", "abs", "total")}
    known |= {w for w in text.split('"') if w.startswith("eps_")}

    unresolved: dict[str, str] = {}
    for c in cons_art.get("constraints", []):
        if not isinstance(c, dict):
            continue
        tol = c.get("tolerance")
        if isinstance(tol, str) and tol.startswith("eps_") and tol not in known:
            unresolved[c.get("id", "?")] = tol
    if unresolved:
        return [_bad("constraint_schema.tolerance_defined",
                     f"约束引用了未定义的容差：{unresolved}",
                     actual=unresolved, expected=sorted(known))]
    return [_ok("constraint_schema.tolerance_defined",
                f"{len(known)} 个 eps_* 容差名均可解析")]


def _check_enum_agreement(field_art: dict) -> list[CheckItem]:
    """**本应相等的枚举，全文只能有一种写法。**

    实测事故：``field_schema`` 里 ``code_system`` 写 ``GBT50500-2024``、
    ``rule_set_id`` 写 ``GB/T50500-2024``，而前者又要求「与 rule_set_id 一致性校验」。

    **注意：必须比对原始字符串，不得先归一化。** 归一化（去掉斜杠、统一大小写）
    会把 ``GBT50500-2024`` 与 ``GB/T50500-2024`` 折叠成同一个值，
    恰好**放过**本条判据要拦的那个 bug —— 判据写成那样等于自我取消
    （与 ``guard_representation`` 的「未定态 = key 完全缺失」同类陷阱）。
    """
    ranges: dict[str, tuple[str, ...]] = {}
    for f in field_art.get("fields", []):
        if not isinstance(f, dict):
            continue
        rng = f.get("range")
        if isinstance(rng, list) and rng and all(
            isinstance(x, str) and "50500" in x for x in rng
        ):
            ranges[f["name"]] = tuple(rng)

    if len(ranges) < 2:
        return [_ok("field_schema.enum_agreement", "无需比对的规则集枚举")]

    distinct = {v for v in ranges.values()}
    if len(distinct) > 1:
        return [_bad(
            "field_schema.enum_agreement",
            "描述同一规则集的枚举出现了多种**原始写法**（须逐字一致，不得只做归一化比对）："
            f"{ {k: list(v) for k, v in ranges.items()} }",
            actual={k: list(v) for k, v in ranges.items()},
            expected="所有规则集枚举逐字一致",
        )]
    return [_ok("field_schema.enum_agreement",
                f"{len(ranges)} 个规则集枚举逐字一致：{list(next(iter(distinct)))}")]


def _check_listing_structure(ip_art: dict) -> list[CheckItem]:
    """输入协议若声明了清单结构，必须自洽：6 张表、别名非空、空值口径存在。"""
    ls = ip_art.get("listing_structure")
    if ls is None:
        return [_bad("input_protocol.listing_structure",
                     "未声明清单结构 —— 无声明就无法拦截「照示例模板外推」",
                     actual=None, expected="listing_structure 对象")]
    out: list[CheckItem] = []

    sheets = ls.get("sheets") or []
    out.append(
        _bad("listing_structure.sheets",
             f"清单表数量为 {len(sheets)}，实测应为 6（表-04/表-09×2/表-10/表-11/表-12）",
             actual=len(sheets), expected=6)
        if len(sheets) != 6 else
        _ok("listing_structure.sheets",
            "6 张表齐备：" + " / ".join(s.get("table_no", "?") for s in sheets),
            actual=len(sheets), expected=6)
    )

    aliases = ls.get("column_aliases") or {}
    #: ``policy`` 是说明性字符串，不是字段声明，跳过。
    #: 其余每个逻辑字段**必须**带非空 aliases —— 只有 logical 名不算声明，
    #: 因为查找发生在别名上，没有别名等于无法定位列。
    empty = [
        k for k, v in aliases.items()
        if isinstance(v, dict) and not v.get("aliases")
    ]
    n_alias = sum(1 for v in aliases.values() if isinstance(v, dict) and v.get("aliases"))
    out.append(
        _bad("listing_structure.column_aliases",
             f"以下逻辑字段未给出列名别名：{empty}（硬编码列名 = 换一个计价软件即失效）",
             actual=empty, expected="每个逻辑字段至少 1 个别名")
        if empty else
        _ok("listing_structure.column_aliases",
            f"{n_alias} 个逻辑字段均声明了别名集合",
            actual=n_alias, expected=">= 1 别名/字段")
    )

    out.append(
        _ok("listing_structure.empty_vs_absent",
            "已声明「空值 ≠ 缺列/缺行」口径（与 ADR-0006 同源）")
        if (ls.get("empty_vs_absent") or {}).get("rule") else
        _bad("listing_structure.empty_vs_absent",
             "未声明「空值 vs 缺列」的区分口径 —— 限价清单普遍「列在、行在、值空」",
             actual=None, expected="empty_vs_absent.rule")
    )
    return out


def _check_open_issues_naming(ip_art: dict) -> list[CheckItem]:
    """**沉默 ≠ 断言**（ADR-0007）的机械检查：

    开放问题若已 RESOLVED，必须带 ``decision`` 或 ``clause_inventory``；
    若声明了 ``observed``，其中**不得出现把用户原话写成否定性断言**的痕迹——
    这一条机器判不了语义，但可以强制要求：凡被纠正过的条目必须留 ``correction``，
    不得**静默改写** observed（否则撤销的旧结论会像事实一样留在制品里）。
    """
    issues = ip_art.get("open_issues") or []
    if not issues:
        return [_bad("input_protocol.open_issues", "open_issues 为空",
                     actual=0, expected=">=1")]

    bad: list[str] = []
    for oi in issues:
        if not isinstance(oi, dict):
            bad.append(f"{oi!r} 非对象")
            continue
        st = oi.get("status")
        if st == "RESOLVED" and not (oi.get("decision") or oi.get("clause_inventory")):
            bad.append(f"{oi.get('id')} 标 RESOLVED 但无 decision/clause_inventory")
        if oi.get("correction") and not oi["correction"].get("user_actual_words"):
            bad.append(f"{oi.get('id')} 有 correction 但未记录用户原话")
    if bad:
        return [_bad("input_protocol.open_issues", f"{len(bad)} 项不合格：{bad}",
                     actual=bad, expected="RESOLVED 须带结论；被纠正的须留用户原话")]
    return [_ok("input_protocol.open_issues",
                f"{len(issues)} 项开放问题结构合格"
                f"（其中 {sum(1 for o in issues if o.get('correction'))} 项带纠正留痕）")]


# --------------------------------------------------------------------------- 入口


def check_contract_consistency(config_dir: Path) -> list[CheckItem]:
    """执行全部跨制品一致性判据。返回判据列表（不抛异常，供闸门聚合）。"""
    try:
        loaded = _load(Path(config_dir))
    except _LoadError as exc:
        return [_bad(f"加载.{exc.artifact}", exc.detail)]

    out: list[CheckItem] = []
    out += _check_field_schema(loaded["field_schema"])
    out += _check_constraint_inputs_are_declared(loaded["field_schema"], loaded["constraint_schema"])
    out += _check_constraint_tolerances(loaded["precision_profile"], loaded["constraint_schema"])
    out += _check_enum_agreement(loaded["field_schema"])
    out += _check_listing_structure(loaded["input_protocol_schema"])
    out += _check_open_issues_naming(loaded["input_protocol_schema"])
    return out
