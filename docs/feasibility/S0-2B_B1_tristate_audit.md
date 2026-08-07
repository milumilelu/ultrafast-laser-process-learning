# S0-2B B1 — Tri-State Physical-Field Audit（协议 v2，QC 冻结版）

> v1 发布于 6660e33。v2 根据 B1 Protocol QC 修正：text coverage 独立状态、
> NOT_REPORTED 与语料截断分离、条件级（condition-level）对象、spot schema 冻结、
> reported quantity definition、材料属性 provenance 分离。

## 1. 论文级：TextCoverageStatus（每篇必填，独立于字段标注）

```text
text_coverage:
    status: COMPLETE | PARTIAL | UNKNOWN
    missing_sections: [experimental_setup, methods, supplementary, ...]
```

- COMPLETE = 读到全部页，实验参数节在档；
- PARTIAL = 文本转储缺节（或疑似缺页）；
- UNKNOWN = 未获原文。

字段状态与 text coverage 的关系（强制规则）：
```text
status=COMPLETE 时允许: REPORTED_CLEAR / REPORTED_AMBIGUOUS / NOT_REPORTED / NOT_APPLICABLE
status=PARTIAL  时参数类字段只能: UNRESOLVED_DUE_TO_TEXT_COVERAGE（不得标 NOT_REPORTED）
                导航类字段（material/process/target 等可见字段）仍可标 REPORTED_CLEAR
```

统计口径由此拆分为：
```text
intrinsic reconstructibility      = REPORTED_CLEAR 占比（仅 COMPLETE 论文）
corpus-observation completeness   = COMPLETE 论文占比（含 UNRESOLVED 的稀释）
```

## 2. 条件级：ExperimentalConditionSpec（冻结）

```
Paper
├── experimental_conditions[0].condition_id     # cond-01, cond-02, ...
│       fields:  16 字段网格（§4）
│       extra_reported: 原文报告的附加量（含 reported_quantity_type）
├── experimental_conditions[1] ...
└── notes
```

- 一篇论文多组条件（不同波长/脉宽/材料）→ 多个 condition，禁止合并；
- Evidence claim 未来通过 `condition_id` 关联；Paper-level 只做聚合；
- 无法拆分多条件时 → `MULTIPLE_EXPERIMENTAL_CONDITIONS`（REPORTED_AMBIGUOUS 语义）。

## 3. 字段状态（五态，冻结）

```text
REPORTED_CLEAR                     值+单位+定义可解析
REPORTED_AMBIGUOUS                 有报告但语义歧义（ambiguity_reason 必填）
NOT_REPORTED                       仅 COMPLETE 文本下允许
NOT_APPLICABLE                     该实验设计下无意义
UNRESOLVED_DUE_TO_TEXT_COVERAGE    文本不完整导致无法判定（PARTIAL 时参数字段必用）
```

Ambiguity Reason 枚举（v2 冻结）：
```
SPOT_RADIUS_OR_DIAMETER_UNKNOWN / SPOT_DEFINITION_UNKNOWN /
INCIDENT_OR_POST_OBJECTIVE_POWER_UNKNOWN / PEAK_OR_AVERAGE_FLUENCE_UNKNOWN /
ABSORBED_OR_INCIDENT_UNKNOWN / SINGLE_OR_ACCUMULATED_UNKNOWN /
MULTIPLE_EXPERIMENTAL_CONDITIONS / PULSE_WIDTH_REGIME_ONLY / FLUENCE_DERIVED_ONLY
```

## 4. 字段网格 v2（冻结）

### Laser 组
| 字段 | 说明 |
|---|---|
| wavelength | nm |
| pulse_width | 值+unit；regime-only → REPORTED_AMBIGUOUS(PULSE_WIDTH_REGIME_ONLY) |
| frequency | Hz/kHz/MHz |
| average_power | 附 power_definition: INCIDENT/POST_OBJECTIVE/UNSPECIFIED |
| pulse_energy | mJ/µJ |

### Beam 组（spot schema 冻结）
```text
spot_value, spot_unit
spot_dimension:  RADIUS | DIAMETER | UNKNOWN
spot_definition: ONE_OVER_E | ONE_OVER_E2 | FWHM | D4SIGMA | OTHER | UNSPECIFIED
beam_profile:    GAUSSIAN | TOP_HAT | OTHER | UNSPECIFIED
```
规则：`spot_value` 无 `spot_definition` 不得进入 Gaussian fluence 公式（ONE_OVER_E 与
ONE_OVER_E2 需换算，D4SIGMA 禁止直接换算）。

### Motion 组
scan_speed / hatch_spacing / passes（多脉冲站点实验 → NOT_APPLICABLE + note）。

### Task 组
material / material_grade / geometry / process_type / target_metric。

## 5. Reported Quantity Type（冻结）

原文报告的衍生量必须保存原语义，禁止直接映射为引擎坐标名：
```text
extra_reported[].reported_quantity_type:  ACCUMULATED_DOSE | FLUENCE | THRESHOLD | ...
extra_reported[].definition:              "fluence × pulse_count" 等原文定义
```
Physics Registry 再决定是否规范化（如 ACCUMULATED_DOSE → accumulated_fluence），
不同论文的 "dose/accumulated fluence/total fluence/energy dose" 定义可能不同，先保定义。

## 6. 材料属性 provenance（冻结）

```text
ablation_threshold / thermal_diffusivity 等:
    provenance_type:
        MEASURED_IN_THIS_PAPER
        FITTED_IN_THIS_PAPER
        CITED_FROM_OTHER_SOURCE      # 可重建该论文的 normalized quantity
        ASSUMED
        UNKNOWN
```
`CITED_FROM_OTHER_SOURCE` 不得作为该论文对属性值的独立 Evidence（防 MaterialState
重复计权/循环证据，对应 V2 §10 self_dependency 原则）。

## 7. 阅读规则（QC 修正）

- 必须读取全文**所有页**（文本转储为每页一长行，禁止只看行首截断）；
- 参数表（Table: Laser parameters）优先于正文提及；
- 每字段记录 `evidence`（页号 + 原文短语）。

## 8. v2 输出文件

- `S0-2B_B1_annotations_v2.jsonl` —— 论文×条件×字段五态标注
- `S0-2B_B1_QC.md` —— v1/v2 一致性对照 + 7 项出口检查 + UNCERTAIN 裁决
