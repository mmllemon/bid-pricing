# ADR-0031: 不可行诊断——两遍设计与删除过滤器近似

- 状态：Accepted
- 日期：2026-09-18
- 关联任务：T03-06（路线 v3.2.1，Gate 2）
- 关联决策：ADR-0023（九值状态域/三态分列）、ADR-0029（SKIP 不参与最严竞争）、
  ADR-0004（未定态语义）、model_v0.3_R2 §6.3（放弃投标判据表）

## 背景

路线 T03-06 要求：输出 `constraint_id / blocking / conflicting_set /
suggested_relaxation`；**求解器无 IIS**（HiGHS 经 PuLP 不暴露 IIS）时实现
最小冲突集近似或逐项关闭诊断。T03-03（ADR-0030）已产出结构化可行性证书，
μ 未落值等挂账在预检层可见化；T04-02E 将把本模块与 LP/MILP 求解流对接。

## 决策

### D1 两遍设计：结构冲突（参数级）与删除过滤器（旋钮级）分开

- **Pass A（纯算术，无需预言机）**：两层穷举——总价层
  （P_min=Σ merged_lower·q0 vs B；P_max vs B 上界侧）与逐项箱层
  （max(L_i, floor_i, lb_C5) > U_i）。产出**带数额**的参数级放松建议。
  覆盖面固定两层，不取决于被测数据（规则⑧）。
- **Pass B（需预言机）**：对 `constraint_schema.toggleable=true` 的软约束
  （C6..C13）逐个关闭（单关→成对关，至 max_conflict_size=2 阶），
  可行域恢复非空 ⇒ blocking、冲突集=被关闭集合。这是 IIS 的**删除过滤器
  近似**——找到的是「对可行性的必要成员」，不是完整 IIS，文案必须如此自述。

### D2 硬约束不得整条关闭（DG-05）

C1..C5（toggleable=false）只能**参数级放松**（Pass A），不得进入删除过滤器——
关闭 C1 等于放弃投标总价锁定，不是诊断是改题。旋钮域以 constraint_schema
的 toggleable 标志为**唯一权威**，本层不自造清单。

### D3 预言机三态 + EC-7 精化

`oracle(instance) -> FEASIBLE | INFEASIBLE | UNKNOWN` 三态不得合并
（ADR-0023 同族）。内置 phase1 预言机的关键精化：`solve_phase1` 对
EC-7 失败（已证空域：箱倒置 / B<P_min / B>P_max）返回 **BLOCKED** 而非
INFEASIBLE——直接映射会把「已证不可行」吞成「可行性未知」。故先跑
`check_exactness`：

- **仅 EC-7 被否定且 status=FAIL**（EC-1..EC-6 全过）⇒ INFEASIBLE（已证）；
- **EC-7 status=BLOCKED（B 缺失）** ⇒ UNKNOWN——「没给 B」不是「B 定得太低」
  （ADR-0004/0002 同族，首版实现踩中，测试钉住）；
- EC-1..EC-6 任一否定 ⇒ UNKNOWN（适用域外，不猜测）。

### D4 UNKNOWN 不参与「恢复可行」判定

关掉旋钮后从 UNKNOWN 变 FEASIBLE ⇒ blocking 成立；仍 UNKNOWN ⇒ 无结论。
全 UNKNOWN 且无结构冲突、无冲突集 ⇒ DG-01 BLOCKED（不可行未证亦未排除）。
把 UNKNOWN 当 INFEASIBLE 就是把「没算出来」当「算出来了不可行」。

### D5 建议动作唯一来源 = §6.3 判据表

`suggested_relaxation` 的动作语义只从 model_v0.3_R2 §6.3 映射
（GIVE_UP_OR_REESTIMATE / APPROVAL_THETA / DECISION_CASHFLOW / RAISE_PSTAR /
SUPPLEMENT_EVIDENCE），不发明新动作；§6.3 是建议不是法律否决（§8.1）。
能量化的必须量化：金额由本模块从原始量（q0/L/U/cap/floor/B）重算，
不得抄预言机返回的 reason 文案（规则⑥跨来源）。

### D6 最小性与阶数诚实

- 已找到冲突集的**真超集**不再报告（DG-03）；
- ≤2 阶截断内未找到 ⇒ WARN「无 ≤2 阶冲突集」——**截断是搜索边界不是
  存在性证明**，不得宣称无冲突（DG-07）；
- 冲突集顺序确定化（内部排序）：`load_toggleable_ids` 返回 frozenset，
  迭代序不定，不排序则同一实例两次运行输出不同。

### D7 基线即可行 ⇒ 如实 PASS，不硬找冲突

聚合沿用跨层不变量：SKIP 不参与最严竞争、空判据集 ⇒ BLOCKED
（ADR-0029）。诊断结论是「判据聚合」（诊断质量），与「实例可行性」
分开自述。

## 后果

- T04-02E 接口已就位：`oracle` 为注入点，LP/MILP 预言机
  （backend UNAVAILABLE⇒UNKNOWN）可直接插入，Pass B 无需改动。
- 首版 oracle 曾把 EC-7 FAIL 吞成 UNKNOWN（冒烟暴露），EC-7 精化后
  low-B 场景基线正确判 INFEASIBLE——冒烟先于测试再次纠错实现。
- 编辑工具「报告成功未落盘」本任务再现 2 次（oracle 精化、测试夹具），
  均靠 grep 核验拦截；重要修改后必须核验落盘。

## 验证

- 30 项区分性测试（全量 1007 → 1037，双环境绿）。
- 注入验证：错误冲突集（超集）⇒ DG-03 FAIL；blocking 缺建议 ⇒ DG-04 FAIL；
  硬约束进过滤器 ⇒ DG-05 FAIL；B 缺失 ⇒ UNKNOWN 非 INFEASIBLE。
- CLI `diagnose`（--probe / --instance / --json）：simple 探针 PASS；
  低 B 实例端到端给出 C1-B 冲突 + 数额 + §6.3 动作。
