# CFA V1.1 EVALUATION CANDIDATE FREEZE（② code freeze）

> 状态：**FROZEN**（2026-08-07）。
> 目的：冻结 v1.1 独立验证的候选版本。**holdout 选定后，下列任何
> 组件不得再修改**（否则 holdout 立即退化为第二个 development set）。

## 0. 版本堆栈（冻结）

```text
CFA version:             uncalibrated-cfa-v1.1
Ingestion stack:         pymupdf parser v0.1.0 + section_builder v1
Mention rules:           Layer 2（含 2026-08-07 rated 词边界修复）
Table semantics:         detect/classify（heading 行块纳入 + header-column fallback）
Ledger:                  candidate-ledger-v0.1（Phase A/B 冻结版）
Reconstructibility:      SOURCE_RECONSTRUCTIBILITY_V0_1（含 paper_level_spec，
                         PROCESS_CONTEXT 优先聚合）
Canonicalization:        CANONICAL_PHYSICS_V0_1（source/target state + compare）
Metadata:                EvidenceMetadata（literature_metadata gold 字段映射，
                         list/空值清洗，材料族规范化）
Facet logic:             UNCALIBRATED_CFA_V0_1（五 facet，Unknown != Mismatch，
                         severe=0 回归约束）
Aggregation:             per-condition ∪ paper-level 最高判定
```

## 1. 已知 dev 缺口（冻结记录，不得在本轮修复）

```text
A2  metadata 未覆盖 2 篇（ae1e95/fa290122）→ Material UNKNOWN（conservative）
表格 GAP  跨块表头解析（a8b139/5eba6f6a）→ 2 篇 InteractionState UNKNOWN
          （dev 记录，安全方向）
```

## 2. 验证协议（holdout）

```text
H1  severe = 0
H2  Unknown 不因 metadata 缺失被转换为 Mismatch
H3  unverified physics coordinate 不得贡献 Interaction-State positive evidence
H4  Material/Task explicit mismatch 在 metadata 可用时识别
H5  Reconstructibility 与人工 gold 保持高一致性
```

- 第一优先指标：**Severe Error Rate**（asymmetric-risk decision，
  不用普通 accuracy 做 Gate）。
- 三层 gold（Level 1 metadata/condition / Level 2 comparability /
  Level 3 facets）——系统错时能定位到层。

## 3. Holdout 纪律

```text
- 10–15 篇，未参与 B1-25 与任何规则调整
- 分层冻结：材料 × 任务 × source readiness × metadata 覆盖
- 覆盖决策边界：MISMATCH / UNKNOWN / PARTIAL / KNOWN 各情况
- 选定后写入 CFA_V1_1_HOLDOUT 契约，之后不增删
```

## 4. 下一阶段

```text
人工三层标注 → run_b1_audit 扩展（holdout 模式）→ H1–H5 判定
→ 若通过：Calibration Feasibility Gate（D1–D4）
→ 若未通过：登记为 v1.1 结论，进入 v2 迭代（holdout 保持独立）
```

> **2026-08-07 更新**：holdout H1–H5 判定完成（H1/H2 PASS，H3/H5 未过），
> 根因锁定为两处确定性语义 bug（`coordinates.py` J_m2 无条件 RECONSTRUCTIBLE
> bypass；RANGE/SWEEP 降格 point）。v1.1 结论与细节见
> `artifacts/cfa_holdout/HOLDOUT_VALIDATION_RESULTS.md`。
> 版本纪律：原 13 篇自发现 v2 bugs 起**降级为 v2 diagnostic/regression set**，
> 不再称"v2 独立验证"；v2 独立验证需新 unseen holdout。Calibration Feasibility
> Gate 推迟至 v2 独立验证通过后；期间仅允许 D1–D4 数据资产盘点并行。
