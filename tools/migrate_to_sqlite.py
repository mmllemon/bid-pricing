"""把现存 JSON 方案与方案组幂等归库到 SQLite（迁移脚本）。

用法（仓库根，即 bid-pricing/ 下）：
    set PYTHONPATH=src
    python tools/migrate_to_sqlite.py           # 用默认库 .sqlite/quote.db
    python tools/migrate_to_sqlite.py -d xxx.db # 指定目标库

幂等：plan 按 plan_id、plan_group 按 group_id upsert，可安全重跑。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bidpricing import sqlite_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把 JSON 方案树归库到 SQLite")
    parser.add_argument("-d", "--db", default=None,
                        help="目标库路径；缺省用默认库")
    parser.add_argument("-s", "--source", default=None,
                        help="源 JSON 根目录；缺省用默认 outputs/projects")
    args = parser.parse_args(argv)

    db = Path(args.db) if args.db else None
    source = Path(args.source) if args.source else None
    plans, groups = sqlite_store.import_json_tree(source_dir=source, db=db)
    print(f"导入方案 {plans} 个、方案组 {groups} 个"
          f" -> {sqlite_store.resolve_db_path(db)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())