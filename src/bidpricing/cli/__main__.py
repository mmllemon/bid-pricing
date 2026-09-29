"""python -m bidpricing.cli 入口（原 cli.py 末尾 __main__ guard）。"""
from .main import main

if __name__ == "__main__":
    raise SystemExit(main())
