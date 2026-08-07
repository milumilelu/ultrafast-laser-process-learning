# OPEN_SCIENTIFIC_DISCOVERY_V0_1（O0 契约）

> 状态：**FROZEN**（2026-08-07）。评审以 **APPROVED WITH 3 AMENDMENTS** 冻结。
> 修订记录：
> 1. **Grounding 分离机制字段**：新增结构化 `GroundingMatchType` 与
>    `GroundingResult`；`FUZZY_UNIQUE` 不再是自动可消费的 `GROUNDED`
>    （grounding gate 三段：PASS / CONDITIONAL / FAIL）。管线为
>    `CandidateSkeleton → GroundingResult → ScientificCandidate`。
> 2. **窗口预算为 implementation defaults**：`DiscoveryWindowConfig` 承载
>    token 预算；契约只冻结结构规则（§2 八条）。
> 3. **跨 span 重复不塞 source_detail**：V0.1 只规定默认不 collapse；
>    duplicate 假设是 O7 的 `CandidateRelation`（§9 reserved）。
> 关联：`CANDIDATE_LEDGER_V0_1.md`（FROZEN）、
> `EXPERIMENTAL_CONDITION_SCHEMA_V0.2.md`（closed promotion contract）、
> `DOCUMENT_IDENTITY_AND_PROVENANCE_V0.1.md`（ProvenanceAnchor）。

## 0. 范围与权限（D1–D5，冻结）

Open Scientific Discovery 是第一种 **open-world candidate producer**：
它发现"论文可能说了什么"，不判断"科学结论已经成立"。

```text
D1  Discovery 只能产生 Candidate，不能产生正式科学事实
    （EvidenceIR / ExperimentalCondition / CFA / evidence weight 全部禁止）。

D2  每个 Candidate 必须有可定位的 verbatim source span；
    无法定位 → GROUNDING_UNRESOLVED → 不晋升。

D3  concept_label 是开放字符串，不受 16-field schema 限制。

D4  UNKNOWN / UNMAPPED / INSUFFICIENT 都是合法结果。

D5  LLM 不允许直接完成 Physics、CFA、Evidence 权重或治理晋升；
    身份、来源、验证、正式科学对象构造全部由确定性代码负责。

D6  DiscoveryWindow 的边界是结构性的（section/block/table/caption）；
    token 预算只是可配置的实现参数，不是科学契约。

D7  Grounding 机制被独立记录（GroundingMatchType）；
    fuzzy grounding 永远不能伪装成 exact grounding。

D8  跨 span 语义相似永远不删除候选；
    duplicate 假设是候选之间的关系（O7 CandidateRelation），
    不是候选自身属性。
```

工程原则（一句）：

> **Open Discovery 让 LLM 自由"发现概念"，但绝不让 LLM 自由"创造事实"；
> 发现是开放的，身份、来源、验证与正式科学对象构造仍是确定性的。**

## 1. 架构（O0 冻结）

```text
ScientificDocument
        ↓
DiscoveryWindow (structure-aware)
        ↓
Pass 1: CandidateSkeleton discovery        (O2)
        ↓
Deterministic CandidateGrounder           (O3 — 第一个硬 Gate)
        ↓
Pass 2: Candidate Fill                    (O4)
        ↓
Pass 3: Gleaning (ONLY_NEW, 重新 grounding)(O5)
        ↓
Independent Verification                  (O6)
        ↓
Merge / Dedupe (anchor-based)             (O5/O7)
        ↓
ScientificCandidate (source_type=LLM_DISCOVERY)
        ↓
CandidateLedger（唯一 identity authority，I9/I10 不变）
        ↓
Mapping / Routing
   ┌────────┼─────────┐
   ↓        ↓         ↓
Condition  Evidence  SchemaGap
```

- `for_condition_linking()` / `StructuralCandidateGraph` / Linker / Compiler
  **零改动**（Phase B 的收敛价值）。
- 第一版**不建立** OpenScientificKnowledgeGraph / EvidenceRelationGraph；
  `StructuralCandidateGraph` 继续只服务 ExperimentalCondition linking。

## 2. DiscoveryWindow（O1，冻结）

输入来自 `ScientificDocument`（block/section/caption/table），**不使用 RAG top-k**
（否则开放召回会被 retrieval recall 限制）。

```text
DiscoveryWindow
    window_id                    # deterministic: stable_hash(
                                 #   document_version_id, ordered block_ids,
                                 #   window_config_version)
    paper_id
    document_version_id
    window_config_version
    section_path
    block_ids[]                  # ordered，可完整追回（G2）
    page_range
    text
    table_refs[]                 # 关联 TableRegion（窗口内引用）
    caption_refs[]               # 关联 caption block
    preceding_context
    following_context
    routing_hint                 # section 派生的处理优先级（见 §3）
```

### 结构规则（冻结，比数字更重要）

```text
1. 不跨 paper
2. section boundary 优先切分
3. paragraph/block boundary 优先
4. table + caption 尽可能保持 atomic
5. figure caption 尽可能保持 atomic
6. 单个 block/table 超长时允许专门 fallback（独占窗口）
7. token budget 不能为了凑长度破坏 provenance
8. section_type 只能影响 routing/priority，不能成为 hard exclusion
```

### Token 预算（implementation defaults，不是科学常数）

由 `DiscoveryWindowConfig` 承载：

```text
DiscoveryWindowConfig
    target_window_tokens: int     # 默认 800
    max_window_tokens: int        # 默认 1200
    target_batch_tokens: int      # 默认 2000（O2 使用）
    max_batch_tokens: int         # 默认 2500（O2 使用）
    context_tokens: int           # 默认 300（前后上下文）
```

- `window_config_version = stable_hash(config)`；改 config → window identity 改变（G7）。
- 参考起点 500–1000 / 1500–2500 tokens 由上述默认值覆盖，benchmark 后调整。

### Skeleton batch（O2 使用，冻结原则）

- batch 可以包含多个 window，但 LLM 输出必须指明 **local window reference**
  （`window_local_ref`），不允许一个 quote 跨两个互不相邻的窗口凭空关联。

## 3. Section 是 routing，不是 filter（冻结）

```text
METHODS / EXPERIMENTAL  → processing priority
RESULTS / DISCUSSION    → effect / mechanism priority
INTRODUCTION            → material / comparison priority
FIGURE CAPTION / TABLE  → structured scientific candidate priority
REFERENCES              → citation routing（不产生科学 candidate）
UNKNOWN                 → 仍然处理
```

禁止 `if section != METHODS: skip()`。

## 4. CandidateSkeleton（O1，冻结）

Discovery 第一遍的输出 DTO，**不进 Ledger**（grounding 后才转换为
`ScientificCandidate`）。

```text
CandidateSkeleton
    local_id           # 模型返回的局部索引（同一窗口内唯一）
    candidate_kind     # CandidateKind 10 类复用（禁止 *_UNKNOWN 变体）
    concept_label      # 完全开放
    verbatim_quote     # 必须逐字来自输入 passage
    window_local_ref   # local window reference（batch 跨窗口时必需，G8）
```

**ID 与 provenance 原则（冻结）**：

> LLM controls semantics. Code controls identity and provenance.

模型**不得**返回：candidate_id / paper_id / window_id / block_id / page / bbox /
normalized value / condition_id。这些全部由确定性基础设施添加。
`paper_id`/`window_id` 由 executor 外部绑定，不要求模型返回。
`CandidateSkeleton` 是 frozen schema（G8）：只能包含上述字段。

Discovery prompt 的 JSON schema 只限制输出**格式**，不限制科学 vocabulary。
prompt 任务描述（冻结语义，措辞可迭代）：

> Identify explicit scientifically meaningful information ... concerning
> experimental procedures, quantitative conditions, material properties,
> parameter–effect relationships, mechanisms, outcomes, constraints,
> measurement conditions, comparisons, or other experimentally relevant
> concepts. Preserve concepts even when they do not map to a predefined
> field. Do not infer unstated information. Every candidate must contain
> a verbatim quotation copied from the supplied passage.

## 5. CandidateGrounder（O3 — 第一个硬 Gate，冻结）

完全 deterministic，复用 `normalize_quote` / `quote_fingerprint` /
`ProvenanceAnchor`。**机制独立记录**（D7）：`GroundingMatchType` 是结构化字段，
不是 source_detail 侧信道。

```text
GroundingMatchType:
    EXACT                 # 当前 block 内逐字命中
    NORMALIZED_EXACT      # normalize_quote 后命中
    CROSS_BLOCK_EXACT     # 跨相邻 block 拼接后命中
    FUZZY_UNIQUE          # 保守模糊命中（唯一候选位置）
    AMBIGUOUS             # 多个位置可能命中
    UNRESOLVED            # 找不到
```

职责分离：

```text
GroundingStatus     = 生命周期粗状态（GROUNDED / GROUNDING_UNRESOLVED）
GroundingMatchType  = grounding 是怎么得到的（机制，永久保存）
```

Grounding 输出独立对象（管线：`CandidateSkeleton → GroundingResult → ScientificCandidate`）：

```text
GroundingResult
    skeleton_id
    match_type: GroundingMatchType
    anchor: ProvenanceAnchor | None
    matched_quote: str
    status: GroundingStatus
```

O3 Gate（冻结）：

```text
EXACT / NORMALIZED_EXACT / CROSS_BLOCK_EXACT
    → grounding gate PASS          → 可自动进入下一阶段

FUZZY_UNIQUE
    → grounding gate CONDITIONAL   → 必须 verification；verification=SUPPORTED
                                     后才允许 promotion（计入 Tier 2 成本）

AMBIGUOUS / UNRESOLVED
    → grounding gate FAIL          → 不允许 promotion
```

- **FUZZY_UNIQUE 即使最终 `SUPPORTED + 可消费`，`match_type=FUZZY_UNIQUE`
  必须永久保存**，不得伪装成 exact。
- fuzzy 阈值**不在契约中冻结数值**（0.90/0.95 一律不拍板）；先在 pilot 上测
  false alignment vs unresolved，再定。原则：**unresolved 比错误 bbox 更安全**。
- 细粒度 match_type 在构造 `ScientificCandidate` 时写入
  `grounding_status`（粗）与 `source_detail.grounding_mode`（细，只读引用，
  真值在 GroundingResult）。

## 6. Candidate Fill（O4，冻结）

Grounding 成功后才执行。输入：skeleton + 局部 context
（quote 所在 block + 前后 block + 关联 table/caption）。

```text
CandidateDetail（全部 optional）
    subject_surface: str | None
    predicate_surface: str | None
    object_surface: str | None
    raw_value: str | None
    raw_unit: str | None
    qualifier: str | None
    scope_hint: str | None
    source_semantics: REPORTED | DERIVED | CITED | INTERPRETIVE | UNKNOWN
```

- **禁止**要求全字段完备（否则诱导 hallucination）；
  partial candidate 好过 invented complete candidate。
- Fill 结果**不映射** 16-field（`intra-burst pulse spacing` 填到
  `raw_value=25, raw_unit=ns` 为止）；mapping 是下游
  `CandidateMapping` 的职责。

## 7. Gleaning（O5，冻结）

第二遍 discovery，提升开放 recall：

> Review the passage and the candidates already extracted. Identify only
> scientifically meaningful information that was missed in the first pass.
> Do not repeat existing candidates. Return an empty list if nothing
> meaningful was missed.

- 输出 `ONLY_NEW` skeleton。
- **Gleaning 结果不得直接进入 Ledger**：必须重新走
  `grounding → dedupe → ScientificCandidate`（否则 second pass 是 hallucination
  后门）。

## 8. Verification（O6，冻结）

独立于 proposer：verifier **不看** discovery 的 reasoning，只看
`原文 + 候选结构`。三态输出（无 0–1 置信度数字）：

```text
SUPPORTED
CONTRADICTED
INSUFFICIENT
```

复用 `VerificationStatus`（candidates/models.py，已存在）；
`verification_basis`（依据的 anchor/quote）写入候选 `source_detail`。

成本分层（冻结）：

```text
Tier 0   deterministic 已确认（与现有 mention anchor 重叠）  → 不验证
Tier 1   开放发现、结构简单（quantitative claim + exact grounding）→ 1 次 verifier
Tier 2   PARAMETER_EFFECT / MECHANISM / COMPARISON / multi-value /
         cross-block / FUZZY_UNIQUE / derived-cited 歧义          → 必须 verifier
Tier 3   CONFLICT / AMBIGUOUS grounding / multi-condition 歧义   → 默认 INSUFFICIENT
                                                                  或 human review
```

## 9. Merge / Dedupe（O5/O7，冻结）

- Merge 发生在 **grounding 之后**，不做 concept_label 相似度 merge。
- 强 dedupe 键：`(paper_id, anchored span, candidate_kind)`。
  deterministic mention 与 LLM 候选 anchor 重叠 → 合并为一个
  `ScientificCandidate`，保留 `discovery_method` 列表
  （如 `["condition-mention-extractor", "llm-discovery"]`）。
- **跨 span 语义重复 V0.1 默认不 collapse**（D8）。两个不同 span 的
  语义相似候选都保留；duplicate 假设是**关系**，不是候选属性：

```text
CandidateRelation（O7 reserved，V0.1 不实现）
    relation_id
    candidate_ids[]
    relation_type: POSSIBLE_DUPLICATE | ...
    basis: SAME_NORMALIZED_CONTENT | SEMANTIC_SIMILARITY | HUMAN_REVIEW | ...
    status: PROPOSED | CONFIRMED | REJECTED
    provenance
```

- 禁止把 `POSSIBLE_DUPLICATE` / `duplicate_of` / `conflicts_with` 等
  塞进 `source_detail`（防止 stringly-typed side channel 复活）。
- 理由（multi-condition paper 关键）："The laser operated at 200 kHz."
  出现在两个不同实验段落，不一定是重复事实——**多留两条 duplicate，
  比把两个实验误 merge 风险小**。

## 10. Mapping / Routing（O7，冻结）

验证后的 `ScientificCandidate` 才进入 `CandidateMapping`：

```text
200 kHz                    → experimental_condition.frequency  → MAPPED
thermal diffusivity        → MaterialPropertyClaim             → MAPPED
higher overlap → redeposition → ParameterEffect Evidence       → MAPPED
intra-burst spacing        → 当前 ontology 无对应字段           → UNMAPPED（保留！）
```

`SUPPORTED + UNMAPPED` 自动聚合为 `SchemaGapCandidate`（O8）：

```text
SchemaGapCandidate
    concept_label
    example_candidate_ids[]
    occurrence_count
    paper_count
```

**Schema 共演化，但禁止自动自修改**：

> LLM 发现 burst spacing → 自动向 Pydantic schema 添加字段 = 禁止。

```text
SchemaGap ledger → frequency/importance 分析 → human review
    → contract revision → new schema version（v0.3）
```

## 11. 接口与 Backend（O2，冻结）

```python
class DiscoveryBackend(Protocol):
    def discover(self, window: DiscoveryWindow) -> list[CandidateSkeleton]: ...
    def fill(self, skeleton: CandidateSkeleton, context: str) -> CandidateDetail: ...
    def glean(self, window: DiscoveryWindow, existing: list[CandidateSkeleton]) -> list[CandidateSkeleton]: ...
    def verify(self, candidate: ScientificCandidate, context: str) -> CandidateVerification: ...
```

- `RecordedDiscoveryBackend`：从 recorded JSONL 回放，进入普通 pytest。
- 真实 LLM 调用：`@pytest.mark.benchmark`，不进默认 CI。
- 文件布局：

```text
src/ultrafast_ingestion/discovery/
    models.py      # DiscoveryWindowConfig / DiscoveryWindow / CandidateSkeleton
                   # + O3: GroundingMatchType / GroundingResult / CandidateDetail / CandidateVerification
    windows.py     # structure-aware 切分（O1）
    discoverer.py  # Pass 1（O2）
    grounder.py    # O3 硬 Gate
    filler.py      # Pass 2（O4）
    gleaner.py     # Pass 3（O5）
    verifier.py    # O6
    merge.py       # anchor-based dedupe（O5/O7）
    backend.py     # Protocol + Recorded（O2）

prompts/
    open_discovery/v0_1.md
    candidate_fill/v0_1.md
    candidate_glean/v0_1.md
    candidate_verify/v0_1.md
```

## 12. 明确不做（V0.1 冻结）

```text
✗ OpenScientificKnowledgeGraph / EvidenceRelationGraph（数量与 benchmark 稳定后再设计）
✗ fine-tune（先积累 人工 corrected Skeleton/Detail 数据；156-route 式数据量级后再评估
  prompt-only vs few-shot vs fine-tune）
✗ 自动 schema 演化（§10）
✗ LLM 直接生成全局 ID / provenance（§4）
✗ 跨 span 自动 merge（§9）
```

## 13. 测试计划（从 O1 第一天建立）

### O1 DoD（窗口 + skeleton，冻结）

```text
G1  同输入+配置 → windows deterministic（同 ID 同内容）
G2  每个 window 都能追到 ordered block_ids / page range
G3  不跨 paper
G4  不因 section UNKNOWN 丢文本
G5  table/caption 原子性在 5 篇 pilot 上可验证
G6  所有纳入 discovery scope 的原始 blocks 至少被一个 window 覆盖
G7  改 window config → window identity/version 改变
G8  CandidateSkeleton 只能包含：
    local_id / candidate_kind / concept_label / verbatim_quote /
    window_local_ref（frozen schema，extra 拒绝）
```

**Discovery Text Coverage（O1 起持续测量）**：

```text
coverage =
    被 discovery windows 覆盖的 eligible text（word 计数）
    / 全部 eligible ScientificDocument text
```

- eligible = 非 REFERENCES section 的 blocks（routing 决定，见 §3）。
- O1 pilot 阶段应**接近 100%**——防止 window builder 自己先通过规则
  把大量论文文本排除（比 LLM 更早的 recall 杀手）。

### Grounding / hallucination（O3 起）

```text
skeleton 契约      quote 必须来自输入 passage；kind 限 10 类
grounding          EXACT / NORMALIZED / CROSS_BLOCK / AMBIGUOUS / UNRESOLVED 全覆盖
hallucination      recorded 返回 "laser power was 50 W" 而原文没有
                   → GROUNDING_UNRESOLVED → never promoted
fuzzy 不伪装       FUZZY_UNIQUE 命中后 match_type 永久保存为 FUZZY_UNIQUE
open vocabulary    "intra-burst spacing" 不在 schema
                   → candidate retained → mapping=UNMAPPED
regression         Paper 13 的 40 MHz：即使 LLM 发现，不得自动成为
                   processing.frequency（CONTRADICTED / scope 不成立）
merge              deterministic mention 与 LLM 候选同 anchor → 合并；
                   跨 span → 两条都保留（无 POSSIBLE_DUPLICATE 字段）
```

## 14. Benchmark 预告（O9，不在 V0.1 实现）

从 226 篇冻结 15–25 篇 blind holdout（当前 5 篇开发集不得复用）。
人工标注：所有对 ultrafast laser processing 有明确价值的
quantitative conditions / procedures / effects / material properties /
mechanisms / outcomes / comparisons（不限 16 字段）。

四组 ablation：

```text
A  Deterministic only          当前 baseline
B  LLM discovery only          开放模型能力
C  Deterministic + Discovery   Hybrid 增量
D  Hybrid + Glean + Verify     完整方案
```

指标：candidate precision/recall、grounding accuracy、unsupported candidate rate、
closed-schema recall、open-world recall、schema-gap yield、cost/paper、calls/paper。

**两个核心指标（冻结）**：

```text
Incremental Open Recall     = LLM 正确发现而 deterministic path 完全没发现的
                              gold candidate 比例（Open Discovery 存在的理由）
Unsupported Candidate Rate  = 模型提出但原文无法支持的 candidate 比例
                              （Open Discovery 最大风险）
验收：ΔRecall 显著 > 0 且 Unsupported Candidate Rate 足够低。
```

## 15. 开发顺序与 Gate（O0 冻结）

```text
O0  本契约冻结                                              ✓ 2026-08-07（FROZEN）
O1  DiscoveryWindow + CandidateSkeleton                      ✓（G1–G8 + coverage 1.0）
O2  RecordedDiscoveryBackend + open_discovery prompt         ✓（batch 聚合 + ref 绑定）
O3  CandidateGrounder                                        ✓（硬 Gate：六级 + PASS/CONDITIONAL/FAIL）
O4  Candidate Fill + ScientificCandidate adapter + Ledger ingestion   ✓
O5  Gleaning + anchor dedupe                                 ✓（glean 重新 grounding；同 span 合并 discovery_methods）
O6  Independent Verification                                 ✓（Tier 0–2 + 三态 + apply_verification）
O7  Mapping / routing                                        ✓（Condition MAPPED / UNMAPPED 保留；
                                                              CandidateRelation 留 V0.2，跨 span 不 collapse）
O8  SchemaGap report                                         ✓（SUPPORTED+UNMAPPED 聚合，跨 paper 报告）
O9  15–25 篇 blind benchmark + 四组 ablation                 ← 待办（需人工 gold 标注）
```
