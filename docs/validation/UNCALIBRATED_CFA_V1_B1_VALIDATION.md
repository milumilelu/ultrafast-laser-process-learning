# UNCALIBRATED_CFA_V1_B1_VALIDATION（冻结的 baseline checkpoint）

> 状态：**FROZEN**（2026-08-07）。本文件是 **baseline validation**，
> 一经冻结不可改写。
> 配套数据：`benchmarks/cfa_confusion/results/b1_25_audit.json`。

## 0. 身份声明（最重要）

```text
Validation dataset:  B1 25-paper audit（artifacts/b1_annotation/）
Baseline version:    uncalibrated-cfa-v1
冻结日期:            2026-08-07
```

**从冻结时刻起，B1-25 正式成为 development/diagnostic set。**
任何针对本报告发现的缺口（Material/Task metadata、InteractionState
conservatism）所做的修改，都不允许再以 B1-25 作为独立 test set
报告泛化性能。未来 CFA v1.1+ 的独立验证需要新的未见 holdout。

## 1. 冻结指标

```text
severe              0
conservative_miss  19
information_gap     0
consistent         69
```

Per-facet matrix（冻结）：

```text
Material           KNOWN/KNOWN 3 | MISMATCH/MISMATCH 2 | MISMATCH/UNKNOWN 19 | UNKNOWN/UNKNOWN 1
Task               MISMATCH/PARTIAL 25
InteractionState   PARTIAL/PARTIAL 11 | PARTIAL/UNKNOWN 11 | UNKNOWN/UNKNOWN 3
Reconstructibility PARTIAL/PARTIAL 24 | UNKNOWN/PARTIAL 1
Reachability       PARTIAL/PARTIAL 25
```

## 2. 冻结结论

### 结论 1：Safety property validated

```text
Unknown ≠ Mismatch 落实：
severe = 0 —— 系统从不在证据不足时做出 MISMATCH 负判断。
```

这是 CFA V1 最值得保护的成果。后续所有"提高覆盖率"的修改，
**必须以不破坏 severe = 0 为第一回归约束**。

### 结论 2：Reconstructibility validated

```text
M6 坐标重建语义与人工判断一致：24/25（Reconstructibility facet）
Reachability 全一致：25/25
```

### 结论 3：Known limitations discovered（不是性能差）

```text
A. Material metadata under-specified
   conservative_miss 19 = 人工 MISMATCH（对 SiC target 的异质材料）
   vs 系统 UNKNOWN（系统无材料信息，拒绝推断）
   → 安全行为与信息缺口并存

B. Task metadata under-specified
   MISMATCH/PARTIAL 25 —— 人工可见 laser/process/geometry 不匹配，
   系统仅有 material 维度（evidence_scope 缺 laser_type/process_type/
   geometry_type）

C. InteractionState conservative
   PARTIAL/UNKNOWN 11 —— 系统无可比坐标（原因分类见
   INTERACTION_STATE_CONSERVATISM_AUDIT.md）
```

**正确解读 conservative_miss=19**：

```text
Evidence metadata unavailable
→ CFA refuses to infer mismatch
```

这是设计意图（Unknown ≠ Mismatch），不是缺陷；真正缺陷是
**evidence metadata 没有进入 CFA**（Material/Task facet 的输入缺口）。

## 3. 版本纪律（冻结）

```text
uncalibrated-cfa-v1   = 当前已验证 baseline（本文件冻结的行为）
uncalibrated-cfa-v1.1 = 补 metadata 输入 + InteractionState 修复后的版本
```

- v1.1 的 B1-25 结果只能报告为：
  `development-set regression: known gaps resolved / not resolved`
- 禁止报告 `v1.1 accuracy improved from X to Y` 作为独立性能证据。
- 发布 v1.1 前保留一批未参与规则调整的 **CFA validation holdout**
  （10–15 篇）用于泛化验证。

## 4. 追溯

```text
审计运行：benchmarks/cfa_confusion/run_b1_audit.py
人工标注：artifacts/b1_annotation/gold_level2_level3_completed.jsonl（25 篇）
系统预测：25 篇（5 篇种子 evidence_material 来自 Level-1 标注；
          20 篇新材料 = None，系统不猜）
audit 结果：benchmarks/cfa_confusion/results/b1_25_audit.json
```
