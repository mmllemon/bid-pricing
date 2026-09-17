"""Gate 0a / 0b 与 §7.1.1 六条断言的测试。"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from bidpricing.artifact import (
    compute_artifact_hash,
    freeze_record,
    load_registry,
)
from bidpricing.contracts.selector import select_rule_set
from bidpricing.gates.gate0 import (
    GATE_0A_RELEASE_EXCLUSIONS,
    GATE_0B_APPROVAL_ROLES,
    assert_wp4_build_allowed,
    assertion_5_sequence,
    assertion_6_config_zero_defaults,
    check_gate_0a,
    check_gate_0b,
    check_phase0_inputs,
    check_project_input_artifacts,
    evaluate_gate_0,
    guard_representation,
)
from bidpricing.paths import (
    GATE0_REGISTRY,
    PROJECT_CLASSIFICATION_TABLE,
    config_dir,
)
from bidpricing.states import Status


@contextmanager
def _config_with_empty_classification_table():
    """真实配置 + **空壳分类表**的临时 config 目录。

    「分类表未声明 → Phase 0 熔断」这一行为判据不得耦合仓库实时状态——
    2026-09-16 分类表已落值（xiyong_l_district / GB/T50500-2024）后，
    直读真实 config 的用例全部过期。本 helper 复制真实配置后把分类表
    覆写为「key 在、标量为空」的未声明形态，使断言永远测的是**行为**
    而不是某天恰好成立的**数据**。
    """
    with tempfile.TemporaryDirectory() as tmp:
        cdir = Path(tmp)
        for f in config_dir().glob("*.json"):
            shutil.copy2(f, cdir / f.name)
        (cdir / PROJECT_CLASSIFICATION_TABLE).write_text(
            json.dumps(
                {
                    "project_id": None,
                    "code_system": None,
                    "search_basis": None,
                    "covered_lists": [],
                    "external_constants": [],
                    "exceptions": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        yield cdir

TECH_ARTIFACTS = {
    "rule_set_selector_spec": "ruleset_selector_spec.json",
    "field_schema_version": "field_schema.json",
    "constraint_schema_version": "constraint_schema.json",
    "precision_profile_version": "precision_profile.json",
    "architecture_decision_version": "architecture_decision.json",
    "competitiveness_classification": "competitiveness_classification.json",
    "input_protocol_schema": "input_protocol_schema.json",
}

CLASSIFICATION_ROLES = (
    "OPTIMIZABLE", "FIXED", "NON_COMPETITIVE", "PASS_THROUGH", "CONTRACT_DEFINED",
)

STUB_COVERED = {
    "source_list": "BOQ",
    "unit_work_scope": ["000001 配电工程"],
    "default_role": "OPTIMIZABLE",
    "basis": "stub——分部分项清单内缺省即可竞争",
}

STUB_EXCEPTION = {
    "item_id": "030404017001",
    "unit_work": "000001 配电工程",
    "item_name": "配电箱",
    "source_list": "BOQ",
    "pricing_role": "PASS_THROUGH",
    "evidence": "stub——「其中:暂估价」列非空",
}

STUB_EXTERNAL = {
    "fee": "安全文明施工费",
    "given_as": "LUMP_SUM",
    "treatment": "NON_COMPETITIVE",
    "basis": "stub——招标文件给定固定值",
}


def _stub_table(**overrides) -> dict:
    """一份**声明齐备**的项目级分类表（例外与外部常量均为空，即合法结论）。"""
    payload = {
        "project_id": "STUB-001",
        "code_system": "GB/T50500-2024",
        "search_basis": "分部分项清单「其中:暂估价」列非空",
        "covered_lists": [dict(STUB_COVERED)],
        "external_constants": [],
        "exceptions": [],
    }
    payload.update(overrides)
    return payload


def _phase0_spec() -> dict:
    """从**真实注册表**取 phase_0 规格，避免测试与配置各写一份而漂移。"""
    real = json.loads((config_dir() / GATE0_REGISTRY).read_text(encoding="utf-8"))
    return {"phase_0": real["phase_0"]}


def _stub_config(root: Path) -> None:
    """为正向测试构造一套可冻结的最小制品集（不含 freeze_blocker）。"""
    for path in TECH_ARTIFACTS.values():
        (root / path).write_text(
            json.dumps({"schema_id": path}, ensure_ascii=False), encoding="utf-8"
        )
    (root / PROJECT_CLASSIFICATION_TABLE).write_text(
        json.dumps(_stub_table(), ensure_ascii=False), encoding="utf-8",
    )


def _stub_registry() -> dict:
    gate_0a = {
        key: {"kind": "versioned", "artifact_path": path,
              "version": None, "hash": None, "frozen_at": None}
        for key, path in TECH_ARTIFACTS.items()
    }
    gate_0a["adjustment_scope"] = {"kind": "enum", "allowed": ["FULL", "SEGMENT"]}
    registry = {"gate_0a": gate_0a, "gate_0b": {}}
    registry.update(_phase0_spec())
    return registry


class RepresentationGuardTest(unittest.TestCase):
    """断言 1：未定态必须是 key 缺失。"""

    def test_absent_key_passes(self):
        self.assertIs(guard_representation({}).status, Status.PASS)

    def test_null_value_fails(self):
        item = guard_representation({"adjustment_scope": None})
        self.assertIs(item.status, Status.FAIL)
        self.assertIn("null", item.reason)

    def test_non_enum_string_fails(self):
        for bad in ("未定", "UNDETERMINED", "PENDING"):
            item = guard_representation({"adjustment_scope": bad})
            self.assertIs(item.status, Status.FAIL, bad)
            self.assertIn("熔断点被绕过", item.reason)

    def test_valid_enum_passes(self):
        for good in ("FULL", "SEGMENT"):
            self.assertIs(
                guard_representation({"adjustment_scope": good}).status, Status.PASS
            )


class Gate0aTest(unittest.TestCase):
    def test_positive_path_passes_when_everything_frozen(self):
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            _stub_config(cdir)
            registry = _stub_registry()
            for key in TECH_ARTIFACTS:
                freeze_record(registry, "gate_0a", key, cdir)
            report = check_gate_0a(registry, cdir, {"adjustment_scope": "FULL"})
            self.assertIs(report.status, Status.PASS, [i.to_dict() for i in report.items])

    def test_undetermined_scope_does_not_block_0a_but_blocks_phase_0(self):
        """选择项取值未定：Gate 0a 仍 PASS（机制就绪），Phase 0 输入门 BLOCKED。

        这是对早前版本的修正：把「机制是否就绪」与「取值是否已定」拆到
        两个时点判定。取值未定不该阻塞 WP1/WP2/WP3 —— 那两层被要求
        同时实现 FULL / SEGMENT 两条分支，选择只决定哪条生效。
        """
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            _stub_config(cdir)
            registry = _stub_registry()
            for key in TECH_ARTIFACTS:
                freeze_record(registry, "gate_0a", key, cdir)
            report = check_gate_0a(registry, cdir, {})  # key 缺失
            self.assertIs(
                report.status, Status.PASS, [i.to_dict() for i in report.items]
            )
            release = next(i for i in report.items if i.item == "release_scope")
            self.assertIn("WP1 数据层", release.reason)

            # 同一份选择：Phase 0 输入门必须熔断
            phase0 = check_phase0_inputs(registry, {}, cdir)
            self.assertIs(phase0.status, Status.BLOCKED)
            self.assertIn("adjustment_scope", {i.item for i in phase0.blockers})

    def test_conflicting_scope_blocks_both_phases(self):
        """配置冲突（2013 项目落值 FULL）在两个时点下都必须 BLOCKED。"""
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            _stub_config(cdir)
            registry = _stub_registry()
            for key in TECH_ARTIFACTS:
                freeze_record(registry, "gate_0a", key, cdir)
            selection = {"rule_set_id": "GB50500-2013", "adjustment_scope": "FULL"}
            self.assertIs(check_gate_0a(registry, cdir, selection).status, Status.BLOCKED)
            self.assertIs(
                check_phase0_inputs(registry, selection, cdir).status, Status.BLOCKED
            )

    def test_release_list_excludes_t00_10b(self):
        """断言 3：放行清单不含 T00-10B（依赖 WP1 的 T01-00B 产出）。"""
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            _stub_config(cdir)
            registry = _stub_registry()
            for key in TECH_ARTIFACTS:
                freeze_record(registry, "gate_0a", key, cdir)
            report = check_gate_0a(registry, cdir, {"adjustment_scope": "SEGMENT"})
            release = next(i for i in report.items if i.item == "release_scope")
            self.assertIn("T00-10B", release.reason)
            self.assertEqual(GATE_0A_RELEASE_EXCLUSIONS[0][0], "T00-10B")

    def test_real_config_0a_passes_and_phase0_blocks_on_project_inputs(self):
        """真实仓库现状：Gate 0a 8/8 通过，阻塞全部落在 Phase 0 输入门。

        这是对早前版本的修正。早前 ``competitiveness_classification`` 直接把
        「逐项分类表」当 Gate 0a 制品，于是**任一具体项目的清单数据未就绪**
        都会阻塞解析器/配置层/判定层的开发。修正后 T00-06 拆成两层：

        * Gate 0a 判据 = 分类**规则书**（角色集合 + 启发式 + 覆盖范围），
          跨项目复用 → 已冻结即通过；
        * Phase 0 输入门判据 = **逐项落值表**，随项目而异 → 空表即熔断。

        两处均与仓库实时状态解耦：选择项显式关闭项目落值文件
        （``use_project_selection=False``）；分类表注入**空壳**（key 在、
        标量为空）——断言的是「未声明即熔断」这一**行为**，而不是某个
        时点恰好成立的**数据**。
        """
        cdir = config_dir()
        registry = load_registry(cdir / GATE0_REGISTRY)
        selection = select_rule_set(
            contract_date="2026-03-01", use_project_selection=False
        ).to_dict()

        report = check_gate_0a(registry, cdir, selection)
        self.assertIs(
            report.status, Status.PASS, [i.to_dict() for i in report.items]
        )
        self.assertNotIn("competitiveness_classification", {i.item for i in report.blockers})

        # 项目级输入未就位（空壳分类表 + 未落值选择项）→ Phase 0 输入门熔断
        with _config_with_empty_classification_table() as cdir_empty:
            phase0 = check_phase0_inputs(registry, selection, cdir_empty)
        self.assertIs(phase0.status, Status.BLOCKED)
        blocked = {i.item for i in phase0.blockers}
        self.assertIn("adjustment_scope", blocked)
        self.assertIn("project_classification_table", blocked)


class ProjectInputArtifactTest(unittest.TestCase):
    """断言 2 的第二类判据：项目级分类声明（**声明式就绪**，不是「表里有没有行」）。

    2026-09-16 改：原判据是 ``len(rows) >= 1``，会把「本标段无例外项」这个
    **结论**误判成「没做」。新判据区分两件事——
    「key 存在且为 []」（已核查、结论为空）与「key 缺失」（根本没声明）。
    """

    def _registry(self, **spec_overrides) -> dict:
        registry = _phase0_spec()
        spec = registry["phase_0"]["project_classification_table"]
        spec.update(spec_overrides)
        return registry

    def _write(self, cdir: Path, payload) -> None:
        (cdir / PROJECT_CLASSIFICATION_TABLE).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def _check(self, payload, **spec_overrides):
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            self._write(cdir, payload)
            return check_project_input_artifacts(self._registry(**spec_overrides), cdir)[0]

    # ---------------------------------------------------- 声明齐备 → PASS
    def test_declaration_with_empty_exceptions_passes(self):
        """**本轮新增语义**：例外为空是合法结论，不得判 BLOCKED。"""
        item = self._check(_stub_table())
        self.assertIs(item.status, Status.PASS, item.to_dict())
        self.assertEqual(item.actual["exceptions"], 0)
        self.assertIn("结论", item.reason)

    def test_empty_exceptions_never_reported_as_empty_table(self):
        """反向断言：不得再出现「表为空」这类把它当没做的措辞。"""
        item = self._check(_stub_table())
        self.assertNotIn("表为空", item.reason)
        self.assertNotIn("rows=", item.reason)

    def test_exceptions_and_external_constants_may_be_populated(self):
        item = self._check(
            _stub_table(exceptions=[dict(STUB_EXCEPTION)],
                        external_constants=[dict(STUB_EXTERNAL)])
        )
        self.assertIs(item.status, Status.PASS, item.to_dict())
        self.assertEqual(item.actual["exceptions"], 1)
        self.assertEqual(item.actual["external_constants"], 1)

    # ------------------------------------------- key 缺失 ≠ 空列表 → BLOCKED
    def test_missing_exceptions_key_blocks_while_empty_list_passes(self):
        """核心判据：key 缺失与空列表在机器上必须可区分。"""
        ok = self._check(_stub_table(exceptions=[]))
        self.assertIs(ok.status, Status.PASS)

        table = _stub_table()
        del table["exceptions"]
        item = self._check(table)
        self.assertIs(item.status, Status.BLOCKED)
        self.assertIn("key 缺失与空列表语义不同", item.reason)

    def test_missing_external_constants_key_blocks(self):
        table = _stub_table()
        del table["external_constants"]
        item = self._check(table)
        self.assertIs(item.status, Status.BLOCKED)
        self.assertIn("external_constants", item.reason)

    def test_list_field_of_wrong_type_blocks(self):
        item = self._check(_stub_table(covered_lists={"source_list": "BOQ"}))
        self.assertIs(item.status, Status.BLOCKED)
        self.assertIn("须为列表", item.reason)

    # ------------------------------------------------------ 标量声明 → BLOCKED
    def test_missing_scalar_declaration_blocks(self):
        for field in ("project_id", "code_system", "search_basis"):
            with self.subTest(field=field):
                item = self._check(_stub_table(**{field: None}))
                self.assertIs(item.status, Status.BLOCKED)
                self.assertIn(field, item.actual)

    def test_illegal_code_system_blocks(self):
        item = self._check(_stub_table(code_system="GBT50500-2024"))
        self.assertIs(item.status, Status.BLOCKED)
        self.assertIn("code_system", item.reason)

    # ------------------------------------------------------- 覆盖声明 → BLOCKED
    def test_empty_covered_lists_blocks(self):
        item = self._check(_stub_table(covered_lists=[]))
        self.assertIs(item.status, Status.BLOCKED)
        self.assertIn("covered_lists 为空", item.reason)

    def test_covered_entry_requires_basis_and_legal_default_role(self):
        for bad in ({**STUB_COVERED, "basis": ""},
                    {**STUB_COVERED, "default_role": "CHEAP"},
                    {**STUB_COVERED, "source_list": "SOMEWHERE"}):
            with self.subTest(bad=bad):
                item = self._check(_stub_table(covered_lists=[bad]))
                self.assertIs(item.status, Status.BLOCKED)
                self.assertIn("覆盖声明不合格", item.reason)

    # --------------------------------------------------------- 例外行 → BLOCKED
    def test_illegal_exception_role_blocks(self):
        item = self._check(
            _stub_table(exceptions=[{**STUB_EXCEPTION, "pricing_role": "CHEAP"}])
        )
        self.assertIs(item.status, Status.BLOCKED)
        self.assertTrue(item.actual[0]["problems"][0].startswith("pricing_role="))

    def test_exception_missing_field_blocks(self):
        row = {k: v for k, v in STUB_EXCEPTION.items() if k != "unit_work"}
        item = self._check(_stub_table(exceptions=[row]))
        self.assertIs(item.status, Status.BLOCKED)
        self.assertIn("unit_work 缺失", item.actual[0]["problems"])

    def test_exception_row_key_is_not_droppable(self):
        """例外行必须带 evidence —— 「无依据的例外」不构成声明。"""
        row = {k: v for k, v in STUB_EXCEPTION.items() if k != "evidence"}
        item = self._check(_stub_table(exceptions=[row]))
        self.assertIs(item.status, Status.BLOCKED)
        self.assertIn("evidence 缺失", item.actual[0]["problems"])

    # --------------------------------------------- 汇总性外生常量 → BLOCKED
    def test_external_constant_needs_treatment_and_basis(self):
        for bad in ({**STUB_EXTERNAL, "treatment": "CHEAP"},
                    {k: v for k, v in STUB_EXTERNAL.items() if k != "basis"}):
            with self.subTest(bad=bad):
                item = self._check(_stub_table(external_constants=[bad]))
                self.assertIs(item.status, Status.BLOCKED)
                self.assertIn("汇总性外生常量", item.reason)

    # ------------------------------------------------------------ 其他
    def test_missing_file_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = check_project_input_artifacts(self._registry(), Path(tmp))[0]
            self.assertIs(item.status, Status.BLOCKED)
            self.assertIn("缺失", item.reason)

    def test_undeclared_registry_blocks_not_vacuous(self):
        """注册表没声明 = 没有判据，不能当空真通过。"""
        with tempfile.TemporaryDirectory() as tmp:
            items = check_project_input_artifacts({}, Path(tmp))
            self.assertIs(items[0].status, Status.BLOCKED)
            self.assertIn("空真", items[0].reason)


class Gate0bTest(unittest.TestCase):
    def test_real_config_blocked_on_all_items(self):
        cdir = config_dir()
        registry = load_registry(cdir / GATE0_REGISTRY)
        report = check_gate_0b(registry, cdir)
        self.assertIs(report.status, Status.BLOCKED)
        blocked = {i.item for i in report.blockers}
        # **不写死具体清单**：哪些制品已冻结会随推进变化（cost_basis_spec /
        # cost_assumption_spec 已于 2026-09-17 冻结），断言的应是**机制**——
        # 注册表里 version 仍为 null 的制品必须出现在阻塞项中，一个都不能漏。
        # 未冻结的制品必须出现在阻塞项中，一个都不能漏。
        # 2026-09-17 起 5 项制品全部冻结，故 unfrozen 为空是**正常状态**——
        # 但这条机制断言仍须生效，否则「未冻结却不阻塞」将无人发现。
        unfrozen = {k for k, spec in (registry.get("gate_0b") or {}).items()
                    if isinstance(spec, dict) and spec.get("kind") == "versioned"
                    and not spec.get("hash")}
        for field in unfrozen:
            self.assertIn(field, blocked, f"{field} 未冻结却未阻塞")
        # approvals 未签署 → 必须阻塞（当前真实仓库状态）
        self.assertIn("approvals", blocked)

    def _env(self, tmp: Path, responsibility: dict | None = None,
             signed: dict | None = None) -> dict:
        """造一个最小 Gate 0b：两份真实存在的制品 + approvals 块。

        制品必须真实存在且 hash 正确——否则被测的就不是审批判据，
        而是 hash 绑定判据了（两件事分开测）。
        """
        (tmp / "card.json").write_text('{"kind": "card"}', encoding="utf-8")
        (tmp / "cost.json").write_text('{"kind": "cost"}', encoding="utf-8")
        rec = {
            name: {
                "kind": "versioned", "artifact_path": f"{name}.json",
                "version": compute_artifact_hash(tmp / f"{name}.json"),
                "hash": compute_artifact_hash(tmp / f"{name}.json"),
                "frozen_at": "2026-01-01T00:00:00+00:00",
            }
            for name in ("card", "cost")
        }
        rec["approvals"] = {
            "kind": "approvals",
            "roles": list(GATE_0B_APPROVAL_ROLES),
            "responsibility": responsibility if responsibility is not None else {
                role: {"artifacts": ["card.json"]} for role in GATE_0B_APPROVAL_ROLES
            },
            "signed": signed if signed is not None else {},
        }
        return {"gate_0b": rec}

    def _approvals(self, registry: dict, cdir: Path) -> CheckItem:
        report = check_gate_0b(registry, cdir)
        return next(i for i in report.items if i.item == "approvals")

    def test_single_checkbox_cannot_freeze_business_caliber(self):
        """v3.2 的 all_required_approvals=true 可被一人勾选通过——本版必须拦住。

        旧格式（只有 hash、无署名、不指向具体制品）在新判据下同样不成立：
        它正是「签一个与任何制品都无关的字符串」的形态。
        """
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            registry = self._env(
                cdir, signed={"合同": {"hash": "sha256:" + "a" * 12}})
            approvals = self._approvals(registry, cdir)
            self.assertIs(approvals.status, Status.BLOCKED)
            self.assertIn("未签署", approvals.reason)
            self.assertIn("未署名", approvals.reason)

    def test_full_approvals_pass(self):
        """四角色各签署其责任制品 → PASS。"""
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            registry = self._env(cdir)
            h = compute_artifact_hash(cdir / "card.json")
            registry["gate_0b"]["approvals"]["signed"] = {
                role: {"by": "user", "artifacts": {"card.json": h},
                       "signed_at": "2026-09-17T10:00:00+08:00"}
                for role in GATE_0B_APPROVAL_ROLES
            }
            approvals = self._approvals(registry, cdir)
            self.assertIs(approvals.status, Status.PASS, approvals.reason)
            self.assertIn("逐角色签署", approvals.reason)

    def test_signing_wrong_artifact_is_blocked(self):
        """签非责任制品 = 签一个模糊 hash，与打勾无异 → BLOCKED。"""
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            resp = {role: {"artifacts": ["card.json"]} for role in GATE_0B_APPROVAL_ROLES}
            registry = self._env(cdir, responsibility=resp)
            h = compute_artifact_hash(cdir / "card.json")
            registry["gate_0b"]["approvals"]["signed"] = {
                role: {"by": "user", "artifacts": {"card.json": h}}
                for role in GATE_0B_APPROVAL_ROLES
            }
            # 合同角色改签 cost.json —— 不是它的责任制品
            registry["gate_0b"]["approvals"]["signed"]["合同"] = {
                "by": "user", "artifacts": {"cost.json": h}}
            approvals = self._approvals(registry, cdir)
            self.assertIs(approvals.status, Status.BLOCKED)
            self.assertIn("未签署责任制品", approvals.reason)

    def test_signature_voided_when_artifact_changes(self):
        """制品在签署后被改动 → 签名自动作废（这是逐角色签 hash 的全部意义）。"""
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            registry = self._env(cdir)
            stale = compute_artifact_hash(cdir / "card.json")
            registry["gate_0b"]["approvals"]["signed"] = {
                role: {"by": "user", "artifacts": {"card.json": stale}}
                for role in GATE_0B_APPROVAL_ROLES
            }
            # 制品被改（签署之后）：制品记录与文件都改了，签名 hash 停在旧值
            (cdir / "card.json").write_text('{"kind": "card", "tampered": 1}',
                                           encoding="utf-8")
            fresh = compute_artifact_hash(cdir / "card.json")
            self.assertNotEqual(stale, fresh)
            registry["gate_0b"]["card"]["hash"] = fresh
            registry["gate_0b"]["card"]["version"] = fresh
            approvals = self._approvals(registry, cdir)
            self.assertIs(approvals.status, Status.BLOCKED)
            self.assertIn("签名已失效", approvals.reason)

    def test_not_covered_is_warn_not_blocked(self):
        """显式声明「本角色无人承担」是真话，不是假审批 → WARN，不阻塞。"""
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            registry = self._env(cdir)
            h = compute_artifact_hash(cdir / "card.json")
            registry["gate_0b"]["approvals"]["signed"] = {
                role: {"by": "user", "artifacts": {"card.json": h}}
                for role in GATE_0B_APPROVAL_ROLES
            }
            registry["gate_0b"]["approvals"]["signed"]["法务"] = {
                "status": "NOT_COVERED",
                "reason": "本项目无专职法务，合规风险由本人知悉并承担"}
            approvals = self._approvals(registry, cdir)
            self.assertIs(approvals.status, Status.WARN, approvals.reason)
            self.assertIn("风险敞口", approvals.reason)

    def test_not_covered_without_reason_is_blocked(self):
        """「无人负责」本身是断言，不给理由 = 没说 → BLOCKED。"""
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            registry = self._env(cdir)
            h = compute_artifact_hash(cdir / "card.json")
            registry["gate_0b"]["approvals"]["signed"] = {
                role: {"by": "user", "artifacts": {"card.json": h}}
                for role in GATE_0B_APPROVAL_ROLES
            }
            registry["gate_0b"]["approvals"]["signed"]["法务"] = {
                "status": "NOT_COVERED"}
            approvals = self._approvals(registry, cdir)
            self.assertIs(approvals.status, Status.BLOCKED)
            self.assertIn("未给理由", approvals.reason)

    def test_contract_review_missing_is_blocked(self):
        """规则卡缺 contract_review = 用「文件没改」冒充「条款已核对」→ BLOCKED。"""
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            (cdir / "card.json").write_text('{"no_review": true}', encoding="utf-8")
            registry = {"gate_0b": {
                "contract_ruleset_version": {
                    "kind": "versioned", "artifact_path": "card.json",
                    "version": "sha256:" + "a" * 12, "hash": "sha256:" + "a" * 12,
                    "frozen_at": "2026-01-01T00:00:00+00:00",
                }
            }}
            report = check_gate_0b(registry, cdir)
            item = next(i for i in report.items if i.item == "contract_review")
            self.assertIs(item.status, Status.BLOCKED)
            self.assertIn("contract_review", item.reason)

    def test_contract_review_not_reviewed_blocks(self):
        """status=NOT_REVIEWED 时 Gate 0b 不得通过。"""
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            (cdir / "card.json").write_text(json.dumps({
                "contract_review": {"status": "NOT_REVIEWED", "declared_by": "user"}
            }), encoding="utf-8")
            registry = {"gate_0b": {
                "contract_ruleset_version": {
                    "kind": "versioned", "artifact_path": "card.json",
                    "version": "sha256:" + "a" * 12, "hash": "sha256:" + "a" * 12,
                    "frozen_at": "2026-01-01T00:00:00+00:00",
                }
            }}
            report = check_gate_0b(registry, cdir)
            item = next(i for i in report.items if i.item == "contract_review")
            self.assertIs(item.status, Status.BLOCKED)


class Assertion5Test(unittest.TestCase):
    def test_vacuous_pass_when_phase1_not_built(self):
        self.assertIs(assertion_5_sequence(None, None).status, Status.PASS)

    def test_fail_when_phase1_built_before_gate_0b(self):
        item = assertion_5_sequence("2026-06-01T00:00:00", "2026-05-01T00:00:00")
        self.assertIs(item.status, Status.FAIL)
        self.assertIn("作废", item.reason)

    def test_fail_when_gate_0b_never_passed_but_phase1_built(self):
        item = assertion_5_sequence(None, "2026-05-01T00:00:00")
        self.assertIs(item.status, Status.FAIL)

    def test_pass_when_ordered_correctly(self):
        item = assertion_5_sequence("2026-04-01T00:00:00", "2026-05-01T00:00:00")
        self.assertIs(item.status, Status.PASS)


class Assertion6Test(unittest.TestCase):
    def test_real_config_has_no_forbidden_defaults(self):
        report = assertion_6_config_zero_defaults(config_dir())
        self.assertIs(report.status, Status.PASS, [i.to_dict() for i in report.items])

    def test_detects_forbidden_default_in_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            (cdir / "field_schema.json").write_text(
                json.dumps(
                    {
                        "fields": [
                            {"name": "q1_point", "default": 100.0},
                            {"name": "adjustment_scope", "default": "FULL"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            report = assertion_6_config_zero_defaults(cdir)
            self.assertIs(report.status, Status.FAIL)
            scan = next(i for i in report.items if i.item == "zero_default_scan")
            self.assertEqual(len(scan.actual), 2)

    def test_null_default_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            (cdir / "field_schema.json").write_text(
                json.dumps(
                    {"fields": [{"name": "q1_point", "default": None}]}, ensure_ascii=False
                ),
                encoding="utf-8",
            )
            self.assertIs(
                assertion_6_config_zero_defaults(cdir).status, Status.PASS
            )

    def test_wp4_build_is_hard_gated(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = {"gate_0b": {}}
            gate_0b = check_gate_0b(registry, Path(tmp))
            self.assertIs(gate_0b.status, Status.BLOCKED)
            self.assertIs(assert_wp4_build_allowed(gate_0b).status, Status.BLOCKED)


class EndToEndTest(unittest.TestCase):
    def test_evaluate_gate_0_real_repo_state(self):
        cdir = config_dir()
        registry = load_registry(cdir / GATE0_REGISTRY)
        selection = select_rule_set(
            contract_date="2026-03-01", use_project_selection=False
        ).to_dict()
        # 分类表注入空壳：断言的是「未声明即熔断」的行为，不耦合实时落值
        # （2026-09-16 真实表已落值后，直读真实 config 的断言全部过期）。
        with _config_with_empty_classification_table() as cdir_empty:
            registry_empty = load_registry(cdir_empty / GATE0_REGISTRY)
            report = evaluate_gate_0(registry_empty, cdir_empty, selection)
        # 机制层已冻结 → Gate 0a 放行 WP1/WP2/WP3
        self.assertEqual(report["summary"]["gate_0a"], "PASS")
        # 数据层未就位 → Phase 0 仍熔断（含 adjustment_scope 与逐项分类表）
        self.assertEqual(report["summary"]["phase_0_input_gate"], "BLOCKED")
        self.assertEqual(report["summary"]["phase_0"], "BLOCKED")
        self.assertEqual(report["summary"]["wp4_solver_layer"], "BLOCKED")
        phase0_blocked = {
            i["item"] for i in report["phase_0_input_gate"]["items"]
            if i["status"] in ("BLOCKED", "FAIL")
        }
        self.assertEqual(
            phase0_blocked, {"adjustment_scope", "project_classification_table"}
        )
        # advisories 仍须存在（可能为空）——"已冻结"不得被误读为"已完备"
        # 早前 T00-06 的 freeze_blocker 是"分类表依赖真实清单"，随机制/数据
        # 两层拆分一并消除：规则书自身已完备，数据缺口改由 Phase 0 输入门表达。
        self.assertIsInstance(report["advisories"], list)

    def test_evaluate_gate_0_real_classification_table_passes(self):
        """真实分类表（已落值）应使 project_classification_table 判 PASS。

        与上一用例互补：空壳 → BLOCKED，落值 → PASS。落值内容随项目演进，
        但「落值后判 PASS」这一行为判据必须恒真。
        """
        cdir = config_dir()
        registry = load_registry(cdir / GATE0_REGISTRY)
        selection = select_rule_set(
            contract_date="2026-03-01", use_project_selection=False
        ).to_dict()
        report = evaluate_gate_0(registry, cdir, selection)
        items = {
            i["item"]: i["status"] for i in report["phase_0_input_gate"]["items"]
        }
        self.assertEqual(items.get("project_classification_table"), "PASS")


class AdvisoryTest(unittest.TestCase):
    def test_self_declared_blocker_is_surfaced_not_swallowed(self):
        """制品自声明未完成时必须被显式暴露，而不是被当成已冻结静默通过。"""
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            (cdir / "field_schema.json").write_text(
                json.dumps({"freeze_blocker": "尚待合同条款核对"}, ensure_ascii=False),
                encoding="utf-8",
            )
            registry = {
                "gate_0a": {
                    "field_schema_version": {
                        "kind": "versioned", "artifact_path": "field_schema.json",
                        "version": None, "hash": None, "frozen_at": None,
                    }
                },
                "gate_0b": {},
            }
            from bidpricing.artifact import advisories

            advs = advisories(registry, cdir)
            self.assertEqual(len(advs), 1)
            self.assertEqual(advs[0]["kind"], "freeze_blocker")
            self.assertIn("合同条款核对", advs[0]["text"])

    def test_blocker_refuses_freezing(self):
        """freeze_blocker 非空时必须拒绝写 hash——防止未完成制品被当成已通过。"""
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            (cdir / "field_schema.json").write_text(
                json.dumps({"freeze_blocker": "未完成"}, ensure_ascii=False),
                encoding="utf-8",
            )
            registry = {
                "gate_0a": {
                    "field_schema_version": {
                        "kind": "versioned", "artifact_path": "field_schema.json",
                        "version": None, "hash": None, "frozen_at": None,
                    }
                }
            }
            from bidpricing.artifact import ArtifactNotFreezable

            with self.assertRaises(ArtifactNotFreezable):
                freeze_record(registry, "gate_0a", "field_schema_version", cdir)


if __name__ == "__main__":
    unittest.main()
