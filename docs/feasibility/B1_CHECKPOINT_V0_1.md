# B1 CHECKPOINT V0_1（M6/M9 科学有效性 checkpoint 协议）

> 状态：**FROZEN**（2026-08-07）。
> 目标：用人工标注验证 M6 reconstructibility、M8 canonical coordinates、
> M9 CFA facets 的科学语义——把 extraction benchmark 升级为
> scientific validity benchmark。
> 关联：`SOURCE_RECONSTRUCTIBILITY_V0_1.md`、`CANONICAL_PHYSICS_V0_1.md`、
> `UNCALIBRATED_CFA_V0_1.md`、`S0-2B_B1_annotations.jsonl`（已有 Level 1 标注）。

## 0. 三层对照（冻结）

```text
Level 1 — Extraction validity
    字段级：field/value/unit/scope 是否正确
    人工输入：S0-2B_B1_annotations.jsonl（5 篇已有）+ 扩标至 17→25 篇

Level 2 — Reconstruction validity
    坐标级：哪些 physics coordinates 应该 AVAILABLE / BLOCKED
    人工输入：按协议 §2 标注（或由 Level 1 字段状态确定性推导）

Level 3 — CFA validity
    facet 级：Material / Task / Interaction / Reconstructibility / Reachability
    人工输入：按协议 §3 标注
```

## 1. 系统侧预测（冻结）

`benchmarks/cfa_confusion/system_predictor.py` 对每篇论文输出：

```text
Level 1: 字段状态（系统 M6 字段分类）
Level 2: canonical coordinate availability（M8 source_state）
Level 3: CFA facets（M9 assess_all，target=SiC fs depth_um demo 任务）
```

- target 固定为 demo 任务（SiC / fs / rectangular_groove / depth_um）——
  B1 材料多样时 Material facet 的 MISMATCH 是**预期正确行为**，
  正是要验证的。
- 论文清单：先跑已有 5 篇标注（种子）；17→25 篇扩标后跑全量。

## 2. 人工标注格式（Level 2/3，冻结）

```json
{
  "paper_id": "04_arxiv_2502.16530.pdf",
  "target_task": "sic_fs_depth",
  "level2_coordinates": {
    "pulse_interval": "AVAILABLE",
    "pulse_spacing": "NOT_REPORTED",
    "peak_fluence": "AVAILABLE",
    "pulse_overlap": "UNKNOWN",
    "normalized_fluence": "DEPENDENCY_MISSING"
  },
  "level3_facets": {
    "Material": "MISMATCH",
    "Task": "KNOWN",
    "InteractionState": "PARTIAL",
    "Reconstructibility": "PARTIAL",
    "Reachability": "PARTIAL"
  },
  "notes": ""
}
```

人工坐标状态词表（与系统一致）：AVAILABLE / UNKNOWN / NOT_REPORTED /
AMBIGUOUS / DEPENDENCY_MISSING / TEXT_COVERAGE_BLOCKED / NOT_APPLICABLE。

## 3. CFA facet confusion audit（冻结）

不是传统 accuracy；按语义分类：

```text
Human UNKNOWN & System UNKNOWN        ✓ 一致
Human UNKNOWN & System MISMATCH       severe error（证据不足时负判断）
Human MISMATCH & System UNKNOWN       conservative miss（保守但安全）
Human MATCH   & System UNKNOWN        information/reconstruction gap
Human X       & System X              一致（含 KNOWN/PARTIAL）
```

Level 1 额外关注：

```text
Human REPORTED  & System NOT_REPORTED      → 提取漏检（FN）
Human NOT_REPORTED & System REPORTED       → 提取误报（FP）
Human REPORTED_AMBIGUOUS & System REPORTED_CLEAR → 歧义被静默消解（severe）
```

## 4. 输出（冻结）

```text
benchmarks/cfa_confusion/
    system_predictor.py    系统预测（paper → 三层）
    audit.py               confusion 分析
    results/seed5.json     种子 5 篇报告（跑通即产出）
    gold_level2_level3.jsonl  人工标注落点（扩标进行时填充）
```

## 5. 验收（冻结）

```text
G1  种子 5 篇（已有 Level 1 标注）可跑通三层对照
G2  severe error（Human UNKNOWN vs System MISMATCH）计数为 0 或逐条说明
G3  系统 MISMATCH 全部有 Material/Task 维度的明确依据（可审计）
G4  扩标清单 17→25 篇冻结后系统预测可一键重跑
G5  confusion 输出无概率/置信度字段
```
