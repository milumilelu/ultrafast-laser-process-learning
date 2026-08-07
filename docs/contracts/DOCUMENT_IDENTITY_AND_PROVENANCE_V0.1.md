# DOCUMENT_IDENTITY_AND_PROVENANCE_V0.1（冻结）

> 状态：**FROZEN**（S0-2B7 前置；未冻结前不进入 parser implementation）
> 覆盖决策：主计划 V2 系列讨论 Q1（三层存储）、Q3（ID 稳定/身份）、Q9（gold 对齐）
> 关联：`EXPERIMENTAL_CONDITION_SCHEMA_V0.1.md`（条件层）、`CONTRACT_V2_FREEZE.md`（任务层）

---

## 1. 三层存储职责（冻结，禁止双真源）

```text
第一层  原 PDF archive
        data/literature_archive/<sha256>_<paper_id>.pdf
        = Source of Record（不可变事实来源；sha256 归档）

第二层  ScientificDocument artifact（全保真 parser 输出）
        artifacts/scientific_documents/<paper_id>/<document_version_id>.json
        = Canonical Parsed Representation
        含：pages / blocks / paragraphs / sections / tables / figures / captions /
            bbox / reading_order / native|OCR source / parser metadata

第三层  关系表投影（现有 literature_section / literature_chunk 等，不废弃）
        = Derived Query Projections（可重建，必须携带 document_version_id）
```

原则（冻结）：
1. `paper_id` 由 PDF identity 决定（archive sha256 派生），**跨 parser 永久稳定**；
2. JSON 可以重新生成数据库投影；**数据库投影不得反向成为 ScientificDocument 的第二真源**；
3. 任何投影表行必须带 `document_version_id`，禁止无版本投影。

## 2. ID 体系（冻结）

### 2.1 Stable IDs（跨 parser 不变）
```text
paper_id              # 由 PDF archive sha256 派生
```

### 2.2 Version ID（随解析变化）
```text
document_version_id = stable_hash(
    paper_id, parser_name, parser_version, parser_config_hash, schema_version
)
```

### 2.3 Representation IDs（version-local，允许随版本改变）
```text
section_id    = hash(document_version_id + structural_path + ordinal)
block_id      = hash(document_version_id + page_index + bbox_normalized)
paragraph_id  = hash(document_version_id + section_id + paragraph_ordinal)
table_id      = hash(document_version_id + table_ordinal)
chunk_id      = hash(document_version_id + normalized_content)
```

禁止：
- 要求新 parser 生成与旧 parser 相同的 chunk_id（不现实）；
- 给 chunk_id / section_id 赋予"科学实体永久身份"职责。

## 3. ProvenanceAnchor（冻结；S0-2D 起为唯一正式定位器）

```text
ProvenanceAnchor:
    paper_id
    document_version_id

    pdf_page_index          # 0-based
    printed_page_label      # 页眉标注页（如 "p. 5 of 23"）

    bbox                    # [x0,y0,x1,y1] 页面坐标
    normalized_quote        # 归一化引用文本
    quote_fingerprint       # 归一化哈希

    section_path
    block_id

    char_start              # optional convenience（representation-local 定位器）
    char_end                # optional convenience
```

优先级（冻结）：
```text
PDF page + bbox + quote fingerprint
    >  section_path + block_id
    >  char offset（仅 representation-local，禁止跨版本使用）
```

## 4. 旧 ID 的 lineage remap（冻结；S0-2D work package D2）

```text
provenance_remap:
    old_document_version_id
    old_section_id / old_chunk_id / old_span

    new_document_version_id
    new_block_id / new_chunk_id / new_span

    mapping_method: PAGE_BBOX | QUOTE_EXACT | QUOTE_FUZZY | TEXT_SIMILARITY | MANUAL | UNRESOLVED
    mapping_score
    mapping_status
```

原则（冻结）：
1. 旧 provenance **不覆盖、不静默更新**；通过 lineage 显式指向新版 representation；
2. UNRESOLVED 是合法终态；禁止"找最像的一段然后当成功"；
3. remap 结果可审计（mapping_method + score 全量记录）。

## 5. Gold 对齐策略（冻结）

```text
旧 203 篇标注      gold_version = legacy_v1   （不批量重写，保持只读）
新标注            annotation_schema_version = cfa_condition_v0.1（anchor 优先）
                  anchor = paper_id + pdf_page + quote + bbox(if available)
                  legacy evidence_span 保留为 legacy locator
对齐              legacy annotation --alignment engine--> new provenance anchor
                  失败 = ALIGNMENT_UNRESOLVED（合法终态）
```

## 6. Parser 版本化与投影重建（冻结）

1. parser 变更（代码/配置/schema）→ 新 `document_version_id`，旧 artifact 保留；
2. 投影重建 = 读 artifact JSON → 重建第三层表；全程可重复（deterministic）；
3. RAG 索引重建独立于投影（index rebuild 是派生流程，不是源）。

## 7. 冻结范围与变更流程

- 本文件为 v0.1，变更走 contract bump（v0.1 → v0.2），附迁移说明；
- 与 `EXPERIMENTAL_CONDITION_SCHEMA_V0.1.md` 同步升级；
- B7-0 之后、parser 实现之前必须确认本文档无歧义。
