# ADR-0037：方案持久化从 JSON 文件迁移到 SQLite（库为唯一真相）

- 状态：已采纳
- 日期：2026-09-22
- 关联：ADR-0006（声明式就绪而非行数）、ADR-0003（状态快照自动派生）、
  H-012（多用户目录隔离）、ADR-0035（成本税口径）

## 背景

方案、方案组、审计此前全部落在**文件型 JSON**（`project_store.py` /
`group_store.py`）。痛点：写非原子（崩溃可能半写文件）、并发写冲突、复杂查询/历史
跟踪困难、JSON 与导出 Excel 之间的一致性只能靠约定。同批决策的候选是 Postgres/MySQL
（过度）、Redis（不符查询需求）、SQLite（内嵌、零运维、事务 + SQL、单写者足够）——
选定 **SQLite**。

## 决策

**D1（库为唯一真相，一行一方案）** 方案持久化中心落到 `src/bidpricing/sqlite_store.py`。
一个方案 = `plan` 表一行：元数据提**真列**（`target_total/fixed_pretax/vat_rate/
surtax_rate/ratio_min/ratio_max` 可取可查），大嵌套块（`params/all_items/preview/result`）
作为 **JSON 文本列**。文件层 `project_store.save_plan` 等**不再承担读写入口**（保留
`_safe_folder` 等纯工具）。

**D2（PPPT 四表）** `plan`、`plan_group`（方案组）、`plan_slot`（组×策略槽位）、
`audit_log`（审计）四张表。**建组与组槽写在同一事务**（`create_group`/`upsert_slot`），
天然原子，替代原文件直接覆盖写。审计写入 `append_audit`，读取 `list_audit`。

**D3（按用户一库一文件）** 库路径沿用 `PROJECTS_DIR` 的按用户重定向模型——
`outputs/projects/<用户>/.sqlite/quote.db`。`resolve_db_path()` 在调用时从
`PROJECTS_DIR` 动态解析，**不得在模块定义时绑定**（否则用户隔离失效，与 H-012 同纪律）。
`api/app.py` 启动时 `sqlite_store.PROJECTS_DIR = user_scope(...)` 即落到对应用户库。
开启 WAL。

**D4（一次性种子迁移，启动时幂等归库）** 由 `tools/migrate_to_sqlite.py`（CLI）与
`sqlite_store.import_json_tree()`（幂等 upsert）把现存 JSON 树归库。`api/app.py`
启动时**仅当本用户库文件尚不存在**才触发导入——既完成冷迁移，又避免每次重启把已在
库中删除的方案从遗留 JSON 里「复活」。此后库为唯一真相，旧 JSON 只读保留、不再写。

**D5（补全 get/set/业务闭环函数）** 在单表读写之外补齐
`delete_plan / mark_finalized / find_plan_by_strategy / find_group_by_plan_id /
copy_group / delete_group`，语义与文件版对齐。重点不变量：`mark_finalized` 保证
**同一项目只保留一份已定稿方案**；`copy_group` 深拷贝出独立方案行（`is_copy=1`）；
`delete_group(keep_plans=False)` 级联删除槽位方案。

## 影响

- `api/app.py` 持久化入口全部改走 `sqlite_store`；业务事件（optimize / overview
  save/delete/finalize）从文件 `log_event` 改走 `append_audit` 入库；HTTP 访问日志
  中间件仍走文件 JSONL（避免逐请求刷库产生递归）。
- 新增 `GET /api/audit/list` 审计读取端点（`limit/action/user` 过滤）。
- 新增 `tests/test_sqlite_store.py`（12 项）覆盖单表/组/审计/迁移幂等/新增函数。
- 仓库地图与 `docs/PROJECT_HANDOFF.md` 同步更新。

## 验证

- 冒烟脚本：迁移幂等、槽位摘要、按策略查找、单项目单定稿、整组复制、删除及级联。
  `import app` 成功，真实按用户库已建并导入（leema：14 方案 / 12 组）。
- 全量回归通（迁移后 **1551 项**含新增 12 项，全部通过）。
- `/api/audit/list` 返回 `{"status":"PASS","audit":[...]}`。

## 遗留

1. 旧 JSON 文件保留在盘上但**不再写入**。用于历史核对或手动重新归库
   （`tools/migrate_to_sqlite.py`）；如需回退文件层，把 `app.py` 持久化入口指回
   `project_store` 即可，但会丢失库内新写入。
2. **前端界面实测一次完整链路**（导入→测算→方案组/复制/定稿→审计→导出）尚待做，
   作为本 ADR 落地后的收尾验证（见 `docs/PROJECT_HANDOFF.md`）。