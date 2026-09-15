"""验收闸门的机械判据实现（路线 §7）。"""

from .gate0 import (
    GATE_0A_RELEASES,
    GATE_0A_RELEASE_EXCLUSIONS,
    GATE_0B_APPROVAL_ROLES,
    NO_DEFAULT_FIELD_PREFIXES,
    assert_wp4_build_allowed,
    assertion_5_sequence,
    assertion_6_config_zero_defaults,
    check_gate_0a,
    check_gate_0b,
    evaluate_gate_0,
    guard_representation,
)

__all__ = [
    "GATE_0A_RELEASES",
    "GATE_0A_RELEASE_EXCLUSIONS",
    "GATE_0B_APPROVAL_ROLES",
    "NO_DEFAULT_FIELD_PREFIXES",
    "assert_wp4_build_allowed",
    "assertion_5_sequence",
    "assertion_6_config_zero_defaults",
    "check_gate_0a",
    "check_gate_0b",
    "evaluate_gate_0",
    "guard_representation",
]
