# EXPERIMENTAL_CONDITION_SCHEMA_V0.2（冻结）

> 状态：**FROZEN**（v0.2，2026-08-06）。取代 v0.1 中 PROVISIONAL 项：F2（condition.role）与 F4（冲突保留）正式落地；F1（sweep/多值）与 F3（语境分类）已在实现中生效。
> 关联：`EXPERIMENTAL_CONDITION_SCHEMA_V0.1.md`（基础字段网格）、`DOCUMENT_IDENTITY_AND_PROVENANCE_V0.1.md`。

## v0.1 → v0.2 变更清单

| # | 变更 | 状态 |
|---|---|---|
| F1 | ConditionField 支持多值/sweep（`values: list[float]` + 字段级 status） | 已实现（mentions Layer 2 + compiler） |
| F2 | `condition.role: PROCESSING \| MEASUREMENT \| COMPARISON \| UNKNOWN` 正式字段 | **本版冻结** |
| F3 | 语境分类（acceptance_status / context_class） | 已实现（Layer 2） |
| F4 | 同参数冲突保留：`CONFLICT_PRESERVED`（禁止静默覆盖/取"更合理"值） | **本版冻结** |

## 1. ExperimentalConditionSpec（v0.2 冻结）

```text
ExperimentalConditionSpec:
    condition_id
    paper_id
    role: PROCESSING | MEASUREMENT | COMPARISON | UNKNOWN
    scope: PAPER_GLOBAL | EXPERIMENT_GROUP | TABLE_GLOBAL | ROW_LOCAL | PARAGRAPH_LOCAL
    mention_ids[]
    fields: { parameter -> ConditionField }
```

规则（冻结）：
1. role 由组件内 mention 角色判定：含 PROCESSING → PROCESSING；全 MEASUREMENT → MEASUREMENT；
   其余 UNKNOWN。COMPARISON 条件**只**由 COMPARISON_ONLY 边组成，永不进入 PROCESSING。
2. 全局继承（ASSIGN_SCOPE PAPER_GLOBAL）的 mention 作为字段附件进入每个 PROCESSING 条件，
   自身不构成条件。
3. 单例未分配 mention 进入 `unassigned_mentions`（合法终态；LINKAGE_AMBIGUOUS 表达）。

## 2. ConditionField（v0.2 冻结）

```text
ConditionField:
    parameter
    status: REPORTED_CLEAR | CONFLICT_PRESERVED | LINKAGE_AMBIGUOUS
    values: list[float]          # 多值/区间/扫参（F1）
    unit
    provenance_anchor_ids[]      # 每个值必须有输入 mention 溯源（检查 8）
    evidence_strength
```

- 同参数不同值 → `CONFLICT_PRESERVED`，两值并存（F4；13 的 2–445 vs 22–450 即此）；
- 不同单位并存 → CONFLICT_PRESERVED 且计入 synthetic 风险计数；
- **禁止**：编译器合成不在输入 mention 中的数值（检查 9，`UNGROUNDED_VALUE_GENERATION`）。

## 3. Linking 决策（v0.2 冻结）

```text
decision: LINK | SEPARATE | ASSIGN_SCOPE | ABSTAIN
evidence_strength: EXPLICIT | STRUCTURALLY_SUPPORTED | SEMANTICALLY_INFERRED
```

- LLM 输出 relation 级 proposal；condition_id 由确定性 compiler 生成；
- ABSTAIN 是合法且鼓励的决策（Paper 11 的 10 kHz vs 1 MHz 能力描述 → LINKAGE_AMBIGUOUS）；
- 权限：确定性硬约束 > LLM proposal > 弱结构提示。

## 4. Validator 硬约束（9 项，冻结）

见 `conditions/validator.py`：
UNKNOWN_MENTION / UNKNOWN_EDGE / REJECTED_MENTION_IN_CONDITION /
CONTRADICTS_HARD_STRUCTURAL_CONSTRAINT / COMPARISON_POLLUTION /
MEASUREMENT_POLLUTION / 冲突警示（不拒绝）/ MISSING_PROVENANCE /
UNGROUNDED_VALUE_GENERATION。

## 5. 指标（冻结）

- Synthetic Condition Rate（pilot 硬 Gate = 0）
- Unsupported Resolution Rate（reference 标 LINKAGE_AMBIGUOUS 却强行解析的比例；Paper 11 测）
- relation P/R、field-to-condition assignment P/R、condition-count accuracy、role accuracy、abstention correctness
