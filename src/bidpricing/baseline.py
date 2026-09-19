"""Baseline 定义、复算与冻结（T05-00）。"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

SPEC_FILENAME = "baseline_spec.json"
METHODS = ("UNIFORM_DISCOUNT", "PREVIOUS_MANUAL", "COMPANY_CONVENTION")


class BaselineError(ValueError):
    pass


@dataclass(frozen=True)
class BaselineResult:
    method: str
    version: str
    prices: Mapping[str, float]
    fingerprint: str
    frozen: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"method": self.method, "version": self.version, "prices": dict(self.prices), "fingerprint": self.fingerprint, "frozen": self.frozen}


def load_baseline_spec(config_dir: Path | str = "config") -> dict[str, Any]:
    return json.loads((Path(config_dir) / SPEC_FILENAME).read_text(encoding="utf-8"))


def _fingerprint(method: str, version: str, prices: Mapping[str, float]) -> str:
    payload = {"method": method, "version": version, "prices": {k: prices[k] for k in sorted(prices)}}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_baseline(config: Mapping[str, Any], *, cap_by_id: Mapping[str, float] | None = None) -> BaselineResult:
    """按冻结配置构造基准报价；只允许一个方法，缺输入阻断。"""
    method = str(config.get("method", ""))
    if method not in METHODS:
        raise BaselineError(f"method 必须是 {METHODS!r}")
    if config.get("frozen") is not True:
        raise BaselineError("baseline 配置未冻结")
    version = str(config.get("version", ""))
    if not version:
        raise BaselineError("baseline version 缺失")
    if method == "UNIFORM_DISCOUNT":
        if cap_by_id is None or config.get("discount") is None:
            raise BaselineError("UNIFORM_DISCOUNT 缺少 cap_by_id 或 discount")
        discount = float(config["discount"])
        if not 0 <= discount <= 1:
            raise BaselineError("discount 必须在 [0,1] 内")
        prices = {str(k): float(v) * (1.0 - discount) for k, v in cap_by_id.items()}
    else:
        raw = config.get("price_by_id")
        if not isinstance(raw, Mapping) or not raw:
            raise BaselineError(f"{method} 缺少 price_by_id")
        prices = {str(k): float(v) for k, v in raw.items()}
    return BaselineResult(method, version, prices, _fingerprint(method, version, prices))


def compute_z_baseline(result: BaselineResult, contribution: Callable[[str, float], float]) -> float:
    """用外部唯一贡献函数复算 Z_baseline，避免在基准模块复制利润公式。"""
    return sum(float(contribution(item_id, price)) for item_id, price in result.prices.items())


def verify_frozen(result: BaselineResult, *, expected_fingerprint: str | None = None) -> bool:
    actual = _fingerprint(result.method, result.version, result.prices)
    return result.frozen and actual == result.fingerprint and (expected_fingerprint is None or actual == expected_fingerprint)
