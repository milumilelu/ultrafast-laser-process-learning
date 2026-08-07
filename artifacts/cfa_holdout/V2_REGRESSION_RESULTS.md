# CFA V2.0 REGRESSION ON FORMER V1.1 HOLDOUT（③④ 结果）

> 状态：**完成**（2026-08-07）。
> 表述纪律：以下全部为 **v2 regression on former v1.1 holdout**（13 篇已
> 降级为 v2 diagnostic set，不得称独立验证）。
> 运行方式：`run_holdout_audit.py`（冻结 v1.1 堆栈 + V2-1/V2-2 两处修复，
> 未改动任何 facet aggregation / metadata / canonicalization）。

## 1. 结果对照（v1.1 holdout → v2 regression）

```text
v1.1                    v2 regression           变化
severe = 0              severe = 0              ✓ 保持
H2 违例 0               H2 违例 0               ✓ 保持
H3 违例 3               H3 违例 1               3 → 1
H4 material 10/10       H4 material 10/10       ✓ 保持
H4 task 10/12           H4 task 10/12           ✓ 保持（metadata gold 缺口，非系统）
H5 consistent 8/13      H5 consistent 9/13      8 → 9
```

InteractionState 一致性 10/13 → **12/13**；Reconstructibility bug 分歧
5 → **0**。

## 2. 两处 bug 的修复证据（预期达成）

| 预期（contract §4） | 结果 |
|---|---|
| H3 failures 3 → 0（bug 引起） | **达成**：f613aa（0.2–25 MHz）、1b61e6（1–1000 Hz）→ `pulse_interval` AMBIGUOUS（REPORTED_NON_POINT）→ InteractionState UNKNOWN |
| H5 bug 分歧 5 → 0 | **达成**：31cf79 / 7fe49 / da1887 / 7a03b9 / f613aa 的 gold-UNKNOWN vs system-PARTIAL（J_m2 bypass 导致）全部消除，系统如实 UNKNOWN |
| severe 保持 0 | **达成** |

## 3. 残余差异（第三类机制，非本次两 bug，登记不入修复范围）

### 3.1 H3 残余 1 处：269fe3（GHz burst）

- 系统：某 condition 里 `frequency=200 kHz`（**point** 值）→ `pulse_interval`
  AVAILABLE → COMPARABLE → InteractionState PARTIAL。
- gold：`pulse_interval` AMBIGUOUS（burst 结构下"脉冲间隔"定义不唯一：
  burst 内 404 ps vs burst 间 5 µs）。
- 机制：**burst 定义歧义**（point 值但含义多义）——v1.1 同样 PARTIAL，
  v2 未引入、未改变。修复不在 V2-1/V2-2 范围内（不是 range 降格，是
  定义歧义）。登记为 v2.1+ 候选（burst 语义层）。

### 3.2 Reconstructibility 反向分歧 4 处（系统 UNKNOWN vs gold PARTIAL）

2a9940 / 0d101f / 1057b6 / 269fe3：gold PARTIAL（论文确实报告了主条件
值），系统 UNKNOWN。根因（均非本次两 bug）：

1. **主值被 RANGE mention 吞并**：0d101f 的 `3–33 µJ`（RANGE mention 含
   主值 33 µJ）→ 非 point → AMBIGUOUS；v1.1 里这些坐标靠 J_m2 bypass
   "凭空" AVAILABLE 掩盖了提取缺口，v2 移除 mask 后如实暴露。
2. **表格噪音造成 CONFLICT**：0d101f 多个 frequency 值（1 kHz / 5 Hz /
   100 Hz，其中 5 Hz、100 Hz 来自表格）→ 条件内 CONFLICT_PRESERVED。
3. **facet_summary 取首报告**：1057b6 存在含 520 kHz point 的干净
   condition（InteractionState 判定为 PARTIAL 与此一致），但
   Reconstructibility 取第一个报告（空条件）→ UNKNOWN——frozen 聚合
   语义（freeze 文档原样登记），非本次改动。

方向说明：全部为**保守方向**（少报 AVAILABLE），无 severe、无编造。

## 4. V2 准入测试判定

```text
V2-G1  B1-25 severe = 0                    PASS（本报告 §5）
V2-G2  dependency-missing 不得 RECONSTRUCTIBLE   PASS（test_v2g2_*，29 项
       reconstructibility 测试全绿；invariant 覆盖全部注册坐标）
V2-G3  RANGE/LIST/SWEEP 不降格 point       PASS（f613aa/1b61e6 修复；
       REPORTED_NON_POINT 阻断，含 J_m2 直接报告路径）
V2-G4  unverified/range 不提供正证据       PASS（残余 269fe3 为 burst
       定义歧义，登记 §3.1）
V2-G5  已正确行为不回退                    PASS（改动仅移除 AVAILABLE
       声明；Material/Task/Reachability 代码零改动，矩阵与 v1.1
       设计记录一致；全量测试 445 passed）
```

## 5. B1-25 回归（V2-G1/G5 证据）

```text
25 篇：severe = 0，consistent = 65，conservative_miss = 19（Material，
即 v1.1 已登记的 metadata 未覆盖保守行为），information_gap = 0
Material：KNOWN/KNOWN 3 · MISMATCH/MISMATCH 2 · MISMATCH/UNKNOWN 19 · UNKNOWN/UNKNOWN 1
Task：MISMATCH/PARTIAL 25（证据 scope 仅 material，四维全 unknown → PARTIAL）
InteractionState：PARTIAL/PARTIAL 19 · PARTIAL/UNKNOWN 3 · UNKNOWN/PARTIAL 2 · UNKNOWN/UNKNOWN 1
Reconstructibility：PARTIAL/PARTIAL 13 · PARTIAL/UNKNOWN 11 · UNKNOWN/UNKNOWN 1
Reachability：PARTIAL/PARTIAL 25
```

注：v1.1 的 B1-25 基线 JSON 未入库，V2-G5 以结构论证补足——两处修复只
可能**移除** AVAILABLE（J_m2 不再无条件、range 不再 point），
`compare_canonical` 只会丢 COMPARABLE，故 InteractionState/Reconstructibility
只可能 PARTIAL→UNKNOWN（修复方向）；Material/Task/Reachability 代码路径
未触碰。

## 6. 结论

- 两处确定性语义 bug 修复证据成立（H3 bug 部分 3→0，H5 bug 分歧 5→0，
  severe=0，B1-25 无回退）。
- 残余差异全部根因清晰、保守方向、非本次范围，登记为 v2.1+ 候选
  （burst 定义语义；主值被 RANGE 吞并的提取改进；facet_summary 聚合语义）。
- 按 contract：原 13 篇仅作 diagnostic/regression，**下一步冻结新 unseen
  holdout 做 v2 独立 H1–H5 验证**。
