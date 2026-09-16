#!/usr/bin/env python
"""紧凑提取 xlsx 清单的键列（跳过项目特征长文本），用于快速核对结构。"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from xlsx_dump import _sheet_names, _shared_strings, read_sheet  # noqa: E402


def main() -> int:
    path = Path(sys.argv[1])
    want = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    with zipfile.ZipFile(path) as zf:
        sst = _shared_strings(zf)
        for i, (name, target) in enumerate(_sheet_names(zf), start=1):
            if want and i != want:
                continue
            rows = read_sheet(zf, target, sst, want_formula=True)
            print(f"\n{'=' * 72}\n## [{i}] {name}\n{'=' * 72}")
            for ri, row in enumerate(rows, start=1):
                if not any(c.strip() for c in row):
                    continue
                cols = [c.replace("\n", "⏎")[:26] for c in row]
                while cols and not cols[-1].strip():
                    cols.pop()
                print(f"r{ri:>3}| " + " ǀ ".join(cols))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
