# Open Discovery Benchmark（O9）

## 目的

回答核心问题：

> 枚举规则（deterministic path）到底漏掉了多少有科学价值的文本信息？
> Open Discovery 的增量 recall 是否显著 > 0，同时 Unsupported Candidate Rate 足够低？

## Gold 标注协议（人工，冻结前评审）

**标注任务**：对每篇 holdout 论文，标记所有对 ultrafast laser processing 建模/理解
有明确科学价值的 claims / quantities / conditions：

```text
QUANTITY / PROCEDURE / PARAMETER_EFFECT / MATERIAL_PROPERTY /
MECHANISM / OUTCOME / CONSTRAINT / COMPARISON / MEASUREMENT / OTHER
```

- **不限于 16-field**：`intra-burst pulse spacing` 这类开放概念必须标。
- 每个 gold 条目必须带 verbatim_quote + block_id + char offsets（能定位回 PDF）。
- 标注范围 = 全文（含 Results/Discussion；references 除外）。

**格式**（`benchmarks/open_discovery/gold/*.jsonl`，一行一条）：

```json
{"paper_id": "...pdf", "candidate_kind": "QUANTITY",
 "concept_label": "intra-burst pulse spacing",
 "verbatim_quote": "Eight pulses separated by 25 ns",
 "block_id": "...", "char_start": 123, "char_end": 152}
```

## Holdout 选择

- 从 226 PDF 冻结 **15–25 篇**，当前 5 篇 pilot 开发集**禁止复用**。
- 冻结后 `docs/contracts/` 记录 holdout 清单（评审通过前不公布给任何开发流程）。

## Ablation 与指标

```text
A  Deterministic only            = extract_mentions + table cells -> ledger
B  LLM discovery only            = discovery backend -> ledger
C  Deterministic + Discovery     = merge_into_ledger
D  Hybrid + Glean + Verify       = 完整管线（verification 后仅 SUPPORTED 计入）
```

指标（`metrics.py`）：

```text
deterministic_recall / hybrid_recall    span-overlap 匹配
incremental_open_recall                 ← 头号指标（LLM 独有 gold 比例）
unsupported_candidate_rate              ← 头号风险（grounding FAIL / CONTRADICTED）
```

运行：

```bash
python benchmarks/open_discovery/run_ablation.py \
  --gold benchmarks/open_discovery/gold/holdout.jsonl \
  --papers benchmarks/open_discovery/holdout_papers.txt \
  --artifacts artifacts/ledgers/
```

## 验收（冻结）

```text
G1  incremental_open_recall 显著 > 0（与 0 的差异需统计检验）
G2  unsupported_candidate_rate 足够低（阈值在 pilot 校准后冻结）
G3  hybrid_recall >= deterministic_recall（不得退步）
```
