"""T01-02C Golden Dataset 生成脚本 —— 运行一次、制品提交、版本锁定。

用法::

    PYTHONPATH=src python tools/make_golden.py          # 默认 golden-v1 / 种子 20260916
    PYTHONPATH=src python tools/make_golden.py --version golden-v2 --seed 42

改用例/改期望 → 改 ``src/bidpricing/io/golden.py`` 后**重跑本脚本**，
manifest_hash 随期望内容自动更新；**禁止手改 manifest.json**。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from bidpricing.io.golden import GOLDEN_SEED, GOLDEN_VERSION, generate_golden  # noqa: E402

OUT = REPO / "tests" / "data" / "golden"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", default=GOLDEN_VERSION)
    ap.add_argument("--seed", type=int, default=GOLDEN_SEED)
    args = ap.parse_args()

    target = OUT / args.version
    manifest = generate_golden(target, version=args.version, seed=args.seed)
    print(f"Golden Dataset {args.version}（seed={args.seed}）→ {target}")
    for c in manifest["cases"]:
        print(f"  [{c['category']}|{c['kind']:8}] {c['case_id']}: {c['desc']}  expect={c['expect']}")
    print(f" manifest_hash = {manifest['manifest_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
