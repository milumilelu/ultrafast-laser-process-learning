# EXPERIMENTAL_CONDITION_SCHEMA_V0.1（冻结）

> 状态：**FROZEN**（S0-2B7 前置；未冻结前不进入 condition extraction/linking 实现）
> 覆盖决策：Q4（linking）、Q5（表格）、Q7（指标）、B1 协议 v2 三态标注
> 关联：`DOCUMENT_IDENTITY_AND_PROVENANCE_V0.1.md`
> 唯一来源声明：本 schema 同时是
> `human annotation = LLM extraction = condition linker = CFA reconstructibility`
> 的共同 contract。**禁止出现第四套字段。**

---

## 1. ExperimentalConditionSpec（顶层结构，冻结）

```text
ExperimentalConditionSpec:
    condition_id
    paper_id

    laser:    ConditionField[5]     # wavelength, pulse_width, frequency, average_power, pulse_energy
    beam:     ConditionField[4]     # spot_value, spot_dimension, spot_definition, beam_profile
    motion:   ConditionField[3]     # scan_speed, hatch_spacing, passes
    task:     ConditionField[5]     # material, material_grade, geometry, process_type, target_metric

    provenance: ProvenanceAnchor[]  # 见 DOCUMENT_IDENTITY_AND_PROVENANCE_V0.1 §3
    completeness: 完整度描述
    ambiguity:    ambiguity 汇总
```

16 字段网格以 B1 协议 v2（`S0-2B_B1_tristate_audit.md` §4）为唯一来源。

## 2. ConditionField[T]（字段级，冻结）

```text
ConditionField[T]:
    status: REPORTED_CLEAR | REPORTED_AMBIGUOUS | NOT_REPORTED
          | NOT_APPLICABLE | UNRESOLVED_DUE_TO_TEXT_COVERAGE

    raw_value
    normalized_value
    unit

    provenance_anchors: ProvenanceAnchor[]   # 每个值必须独立 grounded

    extraction_method: DETERMINISTIC | LLM | HUMAN | MIXED
    ambiguity_code: (枚举，见 §6)

    power_definition: INCIDENT | POST_OBJECTIVE | UNSPECIFIED   # 仅 average_power
```

规则（冻结）：
1. 禁止 `Optional[float]` 式扁平字段——状态是必填维度；
2. `text_coverage.status = PARTIAL` 时参数字段只能 `UNRESOLVED_DUE_TO_TEXT_COVERAGE`；
3. `spot_value` 无 `spot_definition` 不得进入 Gaussian fluence 公式
   （ONE_OVER_E↔ONE_OVER_E2 需换算；D4SIGMA 禁止直接换算）；
4. 材料属性（Fth/α 等）额外携带：
   `provenance_type: MEASURED_IN_THIS_PAPER | FITTED_IN_THIS_PAPER |
    CITED_FROM_OTHER_SOURCE | ASSUMED | UNKNOWN`
   —— `CITED_FROM_OTHER_SOURCE` 可重建该论文的 normalized quantity，
   **不得作为该论文对属性值的独立 Evidence**（防重复计权/循环证据）。

## 3. Paper vs Condition 层级（冻结）

```text
Paper
├── ExperimentalConditionSpec #1
├── ExperimentalConditionSpec #2
└── ...

EvidenceClaim → condition_id（claim 绑定条件，不绑定整篇论文）
```

- 多实验论文禁止合并成一个条件；
- 无法拆分多条件 → 字段级 `REPORTED_AMBIGUOUS(MULTIPLE_EXPERIMENTAL_CONDITIONS)`。

## 4. 全局条件继承（冻结，必须显式 scope）

```text
scope: PAPER_GLOBAL | EXPERIMENT_GROUP | TABLE_GLOBAL | ROW_LOCAL | PARAGRAPH_LOCAL
```

- "全篇使用 1030 nm 激光" → `wavelength` 以 PAPER_GLOBAL 声明一次；
- 表格行只列变化参数（power/speed/frequency），继承只在同 scope 链上合法；
- 禁止无 scope 的跨区继承（不能把 Experiment A 的参数传给 B）。

## 5. 表格语义类型（冻结）

```text
TableSemanticType:
    KEY_VALUE_SETUP    # 参数说明表：整表 = 一个条件
    EXPERIMENT_ROWS    # 每行 = 一个条件
    FACTOR_LEVELS      # 参数矩阵：笛卡尔设计 或 tested range（需 context 判定）
    RESULT_MATRIX      # 结果矩阵：通常不是条件源
    MIXED
    UNKNOWN
```

确定性规则（冻结）：
1. Header/unit inheritance：`Power (W)` → 列单位 = W，单元格不重复单位；
2. Merged header 作用范围从表结构计算，不靠字符串猜测；
3. Footnote（如 `* measured after objective`）= 该列/单元格的 condition modifier；
4. 表与正文冲突处理（禁止"表覆盖正文/正文覆盖表"的简单规则）：
   ```text
   同值            → merge provenance
   兼容补充信息     → enrich
   不同值且不同实验 → split conditions
   真实矛盾        → 两者都保留 + conflict 标记
   ```

## 6. Ambiguity Code（冻结，B1 v2 枚举）

```text
SPOT_RADIUS_OR_DIAMETER_UNKNOWN
SPOT_DEFINITION_UNKNOWN
INCIDENT_OR_POST_OBJECTIVE_POWER_UNKNOWN
PEAK_OR_AVERAGE_FLUENCE_UNKNOWN
ABSORBED_OR_INCIDENT_UNKNOWN
SINGLE_OR_ACCUMULATED_UNKNOWN
MULTIPLE_EXPERIMENTAL_CONDITIONS
PULSE_WIDTH_REGIME_ONLY
FLUENCE_DERIVED_ONLY
```

`reported_quantity_type`（如 ACCUMULATED_DOSE，definition="fluence × pulse_count"）
保存原语义，**禁止直接命名为引擎坐标**（accumulated_fluence 由 Physics Registry 决定）。

## 7. Linking 管线（冻结；V1 唯一路线）

```text
StructuredDocument
   ↓ ① deterministic mention extraction        ConditionMention[] (parameter, value, anchor)
   ↓ ② deterministic structural candidates     CandidateConditionGroup[]（表格类型驱动）
   ↓ ③ LLM relation linking                    ProposedExperimentalCondition[]
   ↓ ④ deterministic schema validator          ExperimentalConditionSpec[]
   ↓ ⑤ ambiguous/conflict → review
```

LLM 仅允许：`LINK | GROUP | ASSIGN_SCOPE | RESOLVE_REFERENCE`
LLM 禁止：`GENERATE missing numeric value`（缺失 → 对应 status，禁止补值）

### 7.1 Mention relation model（冻结）

```text
ConditionMention M1(parameter=frequency, value=100kHz, anchor=A)
M1 --SAME_EXPERIMENT--> M2    # 同条件簇
M4 --GLOBAL_FOR_PAPER--> wavelength=1030nm   # 全局继承
Condition A = global(M4) + {M1, M2, M3}
```

### 7.2 独立 grounded 检查（冻结，validator 一级错误）

每个 field 的 anchor 必须能由同一 condition relation graph 合理连接；
跨实验拼接（100 kHz 来自 Exp A、5 W 来自 Exp B、200 mm/s 来自 Exp C）
→ 一级错误：`SYNTHETIC_CONDITION_COMPOSITION`。

## 8. 指标（冻结；S0-2B7 与正式评测共用）

```text
Field extraction
├── precision / recall / value correctness / unit correctness / ambiguity correctness

Condition reconstruction
├── condition count correctness
├── condition grouping precision / recall
├── field-to-condition assignment accuracy
├── provenance-anchor correctness
└── Synthetic Condition Rate
    = # reconstructed conditions not supported by source / # reconstructed conditions
```

最高优先级约束（冻结，写入 ingestion pipeline 文档头）：
> **宁可得到一个明确不完整的 ExperimentalCondition，
> 也不能得到一个由跨实验字段错误拼接而成的完整 ExperimentalCondition。**

## 9. 与 B1 标注的关系（冻结）

- 人工标注输出 = 本 schema 的记录（`condition_id` + 16 字段五态 + anchors）；
- LLM 抽取输出 = 本 schema 的记录（`extraction_method=LLM`）；
- 两者可直接 diff（agreement 指标）；CFA reconstructibility 消费同一 schema。
