"""Literature Metadata Enrichment（P0-A）：两层抽取的第一层。

Document Metadata Enrichment 产出：
- MaterialMention / ProcessMention（候选 + 语义角色 + canonical ID + 证据位置）
- PaperMetadata（primary_material / grade / primary_process / laser_type / …）

原则：允许 unknown，禁止猜。LLM 缺席时角色与 primary 字段保持 unknown（空），
不把规则候选冒认为语义事实。
"""

from __future__ import annotations

from enum import StrEnum

EXTRACTION_VERSION = "metadata-extractor-v2"


class MaterialRole(StrEnum):
    PRIMARY_WORKPIECE = "primary_workpiece"
    SUBSTRATE = "substrate"
    COATING = "coating"
    REINFORCEMENT = "reinforcement"
    COMPARISON_MATERIAL = "comparison_material"
    TOOL_MATERIAL = "tool_material"
    BACKGROUND_ONLY = "background_only"
    UNKNOWN = "unknown"


class ProcessRole(StrEnum):
    PRIMARY_PROCESS = "primary_process"
    PRETREATMENT = "pretreatment"
    POSTPROCESS = "postprocess"
    COMPARISON_PROCESS = "comparison_process"
    BACKGROUND_ONLY = "background_only"
    UNKNOWN = "unknown"


class ExtractionStatus(StrEnum):
    EXTRACTED_WITH_LLM = "extracted_with_llm"
    RULE_ONLY_ABSTAINED = "rule_only_abstained"
    FAILED = "failed"


MATERIAL_ROLES = frozenset(MaterialRole)
PROCESS_ROLES = frozenset(ProcessRole)

EXTRACTION_METHODS = frozenset({"rule", "llm", "llm_rule_fallback"})
EXTRACTION_STATUSES = frozenset(status.value for status in ExtractionStatus)
