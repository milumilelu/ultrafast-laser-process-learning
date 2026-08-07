# CANDIDATE_LEDGER_V0_1（Phase A 旁路 Ledger + Phase B 消费中枢）

> 状态：**FROZEN**（v0.1，2026-08-07）。
> 变更清单：Phase A 评审后移除 `CandidateSourceType.UNASSIGNED_MENTION`
> （unassigned 是 promotion 维度，不是 source 维度，见 §1.1）；新增
> Phase B 规范（§8）与不变式 I9–I12（§5）。
> 关联：`EXPERIMENTAL_CONDITION_SCHEMA_V0.2.md`（promotion contract）、
> `DOCUMENT_IDENTITY_AND_PROVENANCE_V0.1.md`（ProvenanceAnchor）。

## 0. 范围与原则

Phase A（本契约版本）：**Passive Ledger**。现有 Layer 1–4 管线输入接口**完全不变**，
Ledger 作为旁路聚合产物验证"信息保全层"能力。Phase B（ledger-backed consumption）
另行契约。

核心原则（冻结）：

1. **Candidate 是"发现到的信息"，不是"已确认的科学事实"。**
2. 禁止单维模糊状态（如 `status = VALID/REJECTED`）。状态按四个正交维度拆分：
   `grounding_status` / `mapping_status` / `verification_status` / `promotion_status`。
3. **open 是 discovery；closed 是 promotion contract。**
   `CandidateKind` 只是 routing taxonomy（10 类宽分类），不是知识 ontology；
   开放性由 `concept_label: str` 承载。
4. **Candidate ID 是 representation identity，不是科学真值 identity。**
   `document_version_id`/parser 变化后 candidate_id 允许变化；跨版本 lineage 走
   现有 `ProvenanceAnchor`，不制造"永远稳定"的 ID。
5. **lossless-first，semantic filtering later。** REJECTED / AMBIGUOUS / UNMAPPED
   全部保留，只是各维度状态不同。
6. `to_canonical_dict()` 是 stable hash 与 artifact persistence 的**唯一** canonical
   serialization；`model_dump()` 仅是实现工具，不是仓库契约。

## 1. 四个问题的答案（Identity / Provenance / Lifecycle / Mapping）

### 1.1 Candidate identity

```text
candidate_id = stable_hash(
    document_version_id,
    source_type.value,
    source_locator,
    normalized_raw_content,     # normalize_quote(raw_statement)
)
```

| source_type | source_locator |
|---|---|
| CONDITION_MENTION / REJECTED_CONDITION_MENTION | `block_id:char_start:char_end`（mention anchor） |
| TABLE_CELL | `block_id:row:<row_index>:<parameter>:<value>[:<value2>]` |

- `stable_hash` 复用 `ultrafast_ingestion.models.provenance.stable_hash`。
- 同一 (span) 只允许产生一个候选：dedup key = `(source_locator, source_type)`。
- **UNASSIGNED 不是 source 维度**：unassigned mention 是已接受 mention 的
  lifecycle 状态（`promotion_status`），不产生第二个候选，否则违反
  "every accepted mention → exactly one ledger candidate"。
  `CandidateSourceType` 不包含 `UNASSIGNED_MENTION` 值。

### 1.2 Candidate provenance

- 每个候选携带 `provenance_anchors: list[ProvenanceAnchor]`（V0.1 恰好 1 个）。
- mention 候选：直接复用 `ConditionMention.anchor`。
- table cell 候选：由 cell 文本构造 `ProvenanceAnchor.build`（无 char 级偏移；
  raw_text 全文指纹可定位）。
- 所有 V0.1 候选均为确定性来源 → `grounding_status = GROUNDED`。
  `GROUNDING_UNRESOLVED` 预留给 V0.2 LLM verbatim quote 定位失败。
- `source_detail` 是恢复源对象的唯一锚点：必须包含 `parameter`（原始
  infer_parameter 结果，REJECTED 候选的 open concept 在 `concept_label`）、
  `mention_id`、`values`、`normalized_unit`、`value_type`、`context_class`、
  `acceptance_status`、`rejection_reason`。恢复 roundtrip 与源对象全等（Phase B 强制）。

### 1.3 Candidate lifecycle（四维状态，全部冻结）

```text
grounding_status:      GROUNDED | GROUNDING_UNRESOLVED | NOT_RUN
mapping_status:        MAPPED | UNMAPPED | AMBIGUOUS | NOT_APPLICABLE   (在 CandidateMapping)
verification_status:   NOT_RUN | SUPPORTED | CONTRADICTED | INSUFFICIENT
promotion_status:      PROMOTED | NOT_PROMOTED | BLOCKED
```

V0.1 填充规则：

| 来源 | grounding | verification | promotion | promotion_reason |
|---|---|---|---|---|
| ACCEPTED mention，已进条件 | GROUNDED | NOT_RUN | PROMOTED | `condition_id`（promotion_ref） |
| ACCEPTED mention，unassigned | GROUNDED | NOT_RUN | NOT_PROMOTED | `unassigned_after_linking` |
| AMBIGUOUS_CONTEXT mention | GROUNDED | NOT_RUN | NOT_PROMOTED | `ambiguous_context` |
| REJECTED_CONTEXT mention | GROUNDED | NOT_RUN | NOT_PROMOTED | `rejected_context` |
| TABLE_CELL | GROUNDED | NOT_RUN | NOT_PROMOTED | `cell_not_promoted`（Phase B 前 cell 不进 condition） |
| （无 compile_result 时） | GROUNDED | NOT_RUN | NOT_PROMOTED | `no_compilation` |

V0.1 不做 verification（`NOT_RUN`）。`CandidateVerification` / `CandidateConflict`
对象在 §4 定义字段网格，V0.2 实现。

### 1.4 Candidate → downstream mapping

- V0.1 每个候选恰好 1 条 `CandidateMapping`，`target_namespace = "experimental_condition"`。
- mapping 由 acceptance_status + parameter 决定：

| 来源 | status | target_field |
|---|---|---|
| ACCEPTED mention | MAPPED | mention.parameter |
| AMBIGUOUS_CONTEXT mention | AMBIGUOUS | mention.parameter |
| REJECTED_CONTEXT mention | NOT_APPLICABLE | None |
| TABLE_CELL | MAPPED | cell.parameter |

- 反例（1132 nm ZPL）：`mapping(experimental_condition, processing_laser_wavelength)
  = NOT_APPLICABLE`，其科学内容由 `concept_label`（开放标签，见 §2.3）保留，
  不从 ledger 消失。

## 2. 对象模型（V0.1 冻结）

### 2.1 ScientificCandidate

```text
candidate_id: str
paper_id: str
document_version_id: str

candidate_kind: CandidateKind          # 10 类宽分类，见 §3.1
concept_label: str                     # 开放标签；known 时 = parameter id
raw_statement: str                     # verbatim 原文（mention.raw_text / cell.raw_text）
raw_value: str | None                  # V0.1 确定性路径填 None（数值在 source_detail）；LLM 路径填原文
raw_unit: str | None                   # 同上（V0.1 填 None）

source_type: CandidateSourceType
source_ref: str                        # mention_id / legacy cell key（audit 对照用）
source_locator: str                    # §1.1
source_detail: dict[str, Any]          # 无损附加：status/value_type/values/unit/
                                       # context_class/rejection_reason/table 元数据等

provenance_anchors: list[ProvenanceAnchor]
grounding_status: GroundingStatus
verification_status: VerificationStatus
promotion_status: PromotionStatus
promotion_reason: str = ""
promotion_ref: str = ""                # condition_id 等

discovery_method: str                  # "condition-mention-extractor" | "table-cell-parser"
discovery_version: str
```

`ScientificCandidate` 不承载后续过程状态（不演化成 God object）；后续状态走
`CandidateMapping` / `CandidateVerification` / `CandidateConflict`。

### 2.2 CandidateMapping（V0.1 实现）

```text
candidate_id: str
target_namespace: str                  # V0.1 仅 "experimental_condition"
target_field: str | None               # parameter id
status: MappingStatus
```

### 2.3 concept_label 派生规则（冻结）

| source_detail.context_class / 来源 | concept_label |
|---|---|
| ACCEPTED / AMBIGUOUS（有 parameter） | parameter id |
| EMISSION_WAVELENGTH | `emission/ZPL wavelength` |
| EQUIPMENT_MODEL | `equipment model specification` |
| CAPABILITY_SPEC | `capability/system specification` |
| TABLE_CELL | cell.parameter |
| 其他 REJECTED_CONTEXT | `rejected-context quantity` |

### 2.4 CandidateLedger（aggregate）

```text
CandidateLedger:
    ledger_version_id                 # stable_hash("candidate-ledger", paper_id, document_version_id, SCHEMA_VERSION)
    paper_id
    document_version_id
    schema_version: "candidate-ledger-v0.1"
    candidates: list[ScientificCandidate]
    mappings: list[CandidateMapping]
    metrics: dict[str, int]           # 按 source_type / mapping_status / candidate_kind / promotion_status 计数
```

Artifact：`write_artifact(out_dir)` → `out_dir/<paper_id>/<ledger_version_id>.json`，
JSON 序列化与 `ScientificDocument` 一致（`ensure_ascii=False, indent=1, sort_keys=True`）。

### 2.5 RESERVED（V0.2，本版只定义字段网格，不实现）

```text
CandidateVerification:
    candidate_id
    verification_status              # SUPPORTED | CONTRADICTED | INSUFFICIENT | NOT_RUN
    verifier                         # 如 "verification-llm-v0.1"
    verification_version
    supporting_provenance[]          # verifier 依据的 anchor

CandidateConflict:
    candidate_ids[]
    conflict_type                    # ROLE | VALUE | SCOPE ...
    resolution_status                # OPEN | RESOLVED | WONT_FIX
```

## 3. 枚举（冻结）

### 3.1 CandidateKind —— 只做 routing，不承担开放性

```text
QUANTITY
PROCEDURE
PARAMETER_EFFECT
MATERIAL_PROPERTY
MECHANISM
OUTCOME
CONSTRAINT
COMPARISON
MEASUREMENT
OTHER
```

- **禁止** `*_UNKNOWN` 变体。`UNKNOWN` 描述的是 mapping 状态，不是科学对象类型。
  例如 "intra-burst spacing"：
  `candidate_kind = QUANTITY`，`concept_label = "intra-burst spacing"`，
  将来 `mapping(target=burst_pulse_spacing) = MAPPED` 或保持 UNMAPPED。
- V0.1 确定性路径全部产 `QUANTITY`（mention/cell 均带数值），其余 9 类由
  V0.2 LLM 发现路径填充。

### 3.2 CandidateSourceType

```text
CONDITION_MENTION
TABLE_CELL
REJECTED_CONDITION_MENTION
LLM_DISCOVERY             # V0.2
HUMAN                     # V0.2
```

- 无 `UNASSIGNED_MENTION`：unassigned 是 lifecycle（promotion），不是 source。
- 每个 mention（任意 acceptance status）恰好映射一个候选：
  `REJECTED_CONTEXT → REJECTED_CONDITION_MENTION`，其余 → `CONDITION_MENTION`。

## 4. Phase A 接入与 DoD（冻结）

```text
ConditionMention
TableCell
REJECTED_CONTEXT mention
unassigned_mentions (compile_result)
        ↓
CandidateLedger adapters（candidates/ledger.py）
        ↓
CandidateLedger artifact（旁路，不改 Layer 3/4 输入）
```

DoD：

1. 现有 Layer 1–4 行为完全不变；现有测试全部保持绿色。
2. 已有信息没有因 Ledger 丢失（§5 集合完整性不变式全过）。
3. pseudo cell ID（`graph/builder._cell_key` 的 `"cell:..."`）在 ledger 中被正式
   `candidate_id` 替代；`source_ref` 保留 legacy key 供 Phase B 删除前对照。
   graph 内部 key 本版不动（Phase B 再删）。
4. `candidate_id` 确定性：同输入同 ID；canonical dict roundtrip 等值。

## 5. 集合完整性不变式（测试强制）

```text
I1  every ACCEPTED mention           → exactly one ledger candidate
I2  every REJECTED_CONTEXT mention   → exactly one ledger candidate
I3  every AMBIGUOUS_CONTEXT mention  → exactly one ledger candidate
I4  every unassigned mention         → 其候选可追溯（promotion_status=NOT_PROMOTED,
                                        reason=unassigned_after_linking）
I5  every graph 使用的 cell key      → 存在对应 TABLE_CELL 候选（source_ref 可反查）
I6  candidate_id 确定性             → 相同输入两次构建，ID 与 canonical dict 相等
I7  roundtrip                       → to_canonical_dict → model_validate → 全等
I8  禁止合成数值                     → candidate 不新增任何不在输入 mention/cell 中的数值
I9  Ledger 是唯一 candidate identity authority
                                    → 所有下游节点 id 必须来自 ledger 身份函数
I10 下游不得发明合成身份              → graph/linker 任何 mention/cell 节点 id 都在 ledger 内
I11 下游过滤不删除 ledger 候选        → view 是 routing，不是 deletion；ledger 恒保持全量
I12 Layer 4 输出行为等价             → 迁移后 conditions/unassigned/synthetic rate 与迁移前语义一致
```

## 5.1 Phase A → Phase B 迁移等价性（冻结）

- 迁移前以一次性捕获脚本生成 `tests/fixtures/phase_b_legacy_graph_*.json` 与
  `phase_b_legacy_compile_*.json`（5 篇 pilot）。
- `tests/test_phase_b_equivalence.py` 将 ledger-backed 管线输出归一化到
  source-identity 空间（mention → mention_id；cell → legacy key），与快照
  逐项比较：node set、roles、edge set（type/rule/strength/block_ids/table_id/row/quote）、
  conditions（role/scope/mention identities/fields）、unassigned、
  synthetic_condition_count。
- 归一化以 `source_detail.parameter` + `legacy_cell_key` 为锚点，任何解析器
  或规则变更使快照失配时测试必须显式失败（不允许静默改 fixture）。

## 6. 实现文件（A2–A5）

```text
src/ultrafast_ingestion/candidates/
    __init__.py
    models.py       # enums + ScientificCandidate + CandidateMapping + CandidateLedger
    mapping.py      # mapping 派生规则（§1.4 / §2.2）
    ledger.py       # build_ledger(document, mentions, regions, compile_result) + identity + artifact
```

## 7. 测试计划（A6）

```text
test_candidate_stable_hash.py
test_candidate_canonical_serialization.py
test_condition_mention_adapter.py
test_rejected_mention_preservation.py
test_unassigned_mention_preservation.py
test_table_cell_candidate_identity.py
test_candidate_ledger_roundtrip.py
（pilot 完整性测试并入 test_condition_ledger_pilot.py，pytest.mark.pilot）
```

## 8. Phase B：Ledger 作为 graph/linker 的正式消费入口（冻结）

```text
ConditionMention / TableCell / REJECTED / (V0.2: LLM Discovery / Human)
        ↓
 CandidateLedger            ← 唯一 candidate identity authority (I9)
        ↓
 ConditionLinkView         ← routing view（for_condition_linking）
        ↓
 StructuralCandidateGraph
        ↓
 LLM Linker（candidate_id）
        ↓
 Validator / Compiler
        ↓
 ExperimentalConditionSpec[]（契约不变）
```

### 8.1 B1 — Ledger-backed identity

- Table cell 节点 id = `candidate_id_for_cell(document, cell)`（ledger 身份函数）。
- 删除 `graph/builder._cell_key` 字符串身份 hack（I10 终结）。
- `candidates/ledger.legacy_cell_key` 仅保留作 audit 对照与等价性归一化锚点。

### 8.2 B2 — Ledger-backed graph

- `build_candidate_graph(document, view)`，view = `ledger.for_condition_linking(document, regions)`。
- view 语义（routing，不删数据，I11）：
  - `mentions`：全部 CONDITION_MENTION 候选（含 REJECTED，注册为 REJECTED 角色节点、
    不产生任何边——与迁移前 node set 语义一致）；
  - `eligible_mention_ids`：mapping MAPPED/AMBIGUOUS（供消费方路由）；
  - `cell_nodes`：仅 KEY_VALUE_SETUP / EXPERIMENT_ROWS / COMPARISON_TABLE 的 cell
    （迁移前 R1–R4 的边来源）；FACTOR_LEVELS / RESULT_MATRIX / MIXED / UNKNOWN 的
    cell 留在 ledger，不进 graph；
  - `regions`：R1–R4 的结构语义来源。
- ConditionMention 对象由 ledger 无损恢复（`source_detail` 增补 `parameter`；
  恢复 roundtrip 必须与原对象全等，pilot 测试强制）。
- graph 节点 key = candidate_id；`ConditionMention.mention_id` 保留在对象内与
  ledger `source_ref` 中作 lineage。

### 8.3 B3 — Ledger-backed linker/compiler

- `run_recorded` 的 mention_spec 解析返回 graph key（candidate_id）。
- validator 的 roles 查询按 graph key 进行。
- compiler 逻辑零改动（所有 key 一致化后自然工作）；`ExperimentalConditionSpec`
  契约与 schema 输出不变（mention_ids 字段承载 candidate_id）。

### 8.4 Phase B DoD

1. I9–I12 全过；`test_phase_b_equivalence.py` 对 5 篇 pilot 全部通过。
2. 现有 Layer 4 pilot 测试（更新为 candidate_id 后）保持绿色。
3. `_cell_key` 从 builder 删除；graph 内不再出现 `"cell:"` 前缀节点 id。
4. ledger artifact 保持 Phase A 语义不变（candidate_id 不变——identity 不依赖
   source_detail 内容变化）。

### 8.5 Open Discovery 接入方式（V0.2 预告）

```text
ScientificDocument → Open Discovery → CandidateSkeleton → Grounding
        → ScientificCandidate（source_type=LLM_DISCOVERY）→ CandidateLedger
```

Open Discovery 只生产 candidate；下游消费（view/graph/linker）不再感知来源差异。
