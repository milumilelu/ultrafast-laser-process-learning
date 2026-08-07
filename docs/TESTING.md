# TESTING — 分层、oracle 与 CI 约定

## 1. 测试分层（pytest markers）

| marker | 何时跑 | 内容 |
|---|---|---|
| `unit`（默认） | 每次 commit/PR | 纯文本语境分类、规则对干扰、无外部 fixture |
| 无 marker 默认集 | 每次 commit/PR | 迁移回归（BO/Group-CV/soft-prior）、内核打包、契约 |
| `pilot` | 显式 `pytest -m pilot` | 5 篇 pilot PDF 的 DocumentStructure/mentions/语义 manifest |
| `benchmark` | 单独 job | mention extraction / 未来 condition linking 评估 |
| `slow` | 按需 | 长任务 |

默认 `pytest` = `-m "not pilot and not benchmark"`（快速、离线、自包含）。
CI 每次 push 跑默认集 + lint-imports + ruff；pilot 集在 CI 上因无归档自动 skip。

## 2. Oracle 原则

1. **Golden artifact ≠ 唯一 oracle**：`artifacts/scientific_documents/*.json` 用于
   debug/replay/inspection，测试**不逐字节 assert**；
2. **权威 oracle = 人工冻结的 semantic manifest**（`tests/fixtures/pilot_semantic_manifest.yaml`）：
   页数、必需 section、关键 quote+page anchor、必需图注、reading-order 单调性；
3. mention 层 oracle = `S0-2B_B1_REFERENCE_11_13.jsonl`（condition 级人工 reference）
   + 反例 fixtures（ZHL-25W-272+、ZPL 波长、ODMR 频率、V1 标签）。

## 3. 路径与网络纪律

- 测试代码**禁止绝对路径**；pilot 归档经 `ULTRAFAST_PILOT_ARCHIVE` env 或同级
  `ultrafast agent` 目录解析；缺失 → `pytest.skip`，**禁止静默 PASS**；
- **core suite 禁止联网**；CI 不装联网依赖（embedding local_files_only 同理）；
- 未来 parser adapter 若引入 `from_pretrained(...)` 必须显式标记 slow/benchmark。

## 4. LLM 测试纪律（Layer 4 起）

- CI 内绝不调用真实外部 LLM；
- 单元/CI 用 recorded response 或 fake linker；真实 LLM 归 benchmark job；
- linking 测试硬失败条件：`Synthetic Condition Count > 0`（跨实验拼接 = 一级错误，
  即使字段 individually 全对）。

## 5. 已登记的覆盖缺口（不设覆盖率阈值）

以 critical branch 覆盖为准：
`UNKNOWN / AMBIGUOUS_CONTEXT / REJECTED_CONTEXT / RANGE / LIST / COMPARISON /
MEASUREMENT / MUTUALLY_EXCLUSIVE / CONFLICT` —— 每类都有测试后再谈行覆盖率。
