"""把现存 JSON 方案与方案组幂等归库到 SQLite（迁移脚本）。

用法（仓库根，即 bid-pricing/ 下）：
    set PYTHONPATH=src
    python tools/migrate_to_sqlite.py           # 用默认库 .sqlite/quote.db
    python tools/migrate_to_sqlite.py -d xxx.db # 指定目标库
    python tools/migrate_to_sqlite.py --archive-source   # 成功后归档源树

幂等：plan 按 plan_id、plan_group 按 group_id upsert，可安全重跑。

**为什么提供 --archive-source**：import_json_tree 是 force upsert——幂等
重跑会把「库中已删除的方案 / 已取消的定稿」按 JSON 旧值**复活**（连定稿
锁也一并绕过）。JSON 树与库并存期间它是第二真相源；迁移确认成功后应把
源树归档（重命名为 ``<目录>.migrated-<时间戳>.bak``），让库成为唯一真相。
默认不开：归档会移动用户数据，须显式选择。
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

from bidpricing import project_store, sqlite_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把 JSON 方案树归库到 SQLite")
    parser.add_argument("-d", "--db", default=None,
                        help="目标库路径；缺省用默认库")
    parser.add_argument("-s", "--source", default=None,
                        help="源 JSON 根目录；缺省用默认 outputs/projects")
    parser.add_argument("--archive-source", action="store_true",
                        help="迁移成功后把源 JSON 树重命名为 <目录>.migrated-<时间戳>.bak"
                             "（防幂等重跑复活库中已删数据；库成为唯一真相源）")
    args = parser.parse_args(argv)

    db = Path(args.db) if args.db else None
    source = Path(args.source) if args.source else None
    plans, groups = sqlite_store.import_json_tree(source_dir=source, db=db)
    print(f"导入方案 {plans} 个、方案组 {groups} 个"
          f" -> {sqlite_store.resolve_db_path(db)}")

    if args.archive_source:
        src = Path(source) if source is not None else project_store.PROJECTS_DIR
        if not src.exists() or not any(src.iterdir()):
            print(f"源目录为空或不存在，跳过归档：{src}")
            return 0
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dst = src.with_name(f"{src.name}.migrated-{stamp}.bak")
        shutil.move(str(src), str(dst))
        print(f"源 JSON 树已归档：{src} -> {dst}")
        print("此后库是唯一真相源；如需回迁请先人工确认 bak 内容。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
