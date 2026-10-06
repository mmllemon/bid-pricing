"""真实样本（仓外文件）的版本守卫 —— 供测试用例复用。

**要拦的事故**：``test_io_boq`` / ``test_io_clean`` 的冒烟用例对着
``../真实案件示例/`` 下的 xlsx 断言行数与编码分布，而那份文件**不在版本控制内**。
它已经被替换过一次（84 行版 → 83 行版），于是三条断言以 ``83 != 84`` 的形式炸掉：
失败信息指向断言，真正的根因却是「样本换了版本」——看日志的人会去查解析器，
而解析器是对的。

原有守卫只判 ``path.exists()``：文件**在、但换了一版**时既不跳过、也不解释，
成了「假回归」。本模块改用 T01-05 的导入登记表
（``imports/<project>/import_registry_<side>.json``）做基准复算，把
「样本已被替换」变成一条**把话说清楚的跳过**，与「文件不在本机」同等对待——
真实文件用例不得耦合项目实时状态（`test_io_boq` 头部声明的同源原则）。

两条口径：

* **被替换 → skipTest**，不判 FAIL。样本是外部输入，不是本仓的代码事实；
  把它判成回归会让「测试挂了」与「样本换了」永远分不清。
* **未登记 → 不拦**。没有比对基准时守卫无从判定，「跳过校验」比「假装通过」诚实，
  也比「把机制性缺口报成测试失败」有用。

局限（如实标注）：只对**已登记**的 (project, side) 有效。目前
``xiyong_l_district`` 只登记了 ``cap`` 与 ``cost`` 两侧，``bid`` 侧未登记，
故报价侧样本仍无版本守卫——须先 ``import-register`` 才有基准。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from bidpricing.io.import_registry import verify_import

#: 真实样本所属项目（与 imports/ 下的登记目录同名）
PROJECT_ID = "xiyong_l_district"

_REPO_ROOT = Path(__file__).resolve().parents[1]


def require_registered_sample(
    path: Path,
    side: str,
    *,
    project_id: str = PROJECT_ID,
) -> None:
    """确认样本存在且与该 (project, side) 最新登记指纹一致，否则跳过当前用例/整个用例类。

    用 ``raise unittest.SkipTest`` 而不是 ``case.skipTest(...)``：后者是实例方法，
    在 ``setUpClass`` 里只拿得到类（``cls.skipTest`` 是未绑定函数，会 TypeError）。
    抛 ``SkipTest`` 在两种上下文都成立——``setUpClass`` 里抛＝整个类跳过，
    用例方法里抛＝该用例跳过。调用点因此不必区分自己站在哪一侧。
    """
    if not path.exists():
        raise unittest.SkipTest(f"真实样本文件不在本机：{path}")

    result = verify_import(path, project_id, side, _REPO_ROOT)
    if result.status == "PASS":
        return

    if "未登记导入" in result.reason:
        # 无比对基准 → 守卫无从判定。不拦（见模块 docstring 第二条口径）。
        return

    raise unittest.SkipTest(
        "真实样本已被替换，跳过（既不假通过，也不误报成回归）："
        f"{result.reason}"
    )
