"""确定性校验与 primary 字段计算（validator）。

角色只允许枚举内值（非法→unknown）；页码越界→去页码（unknown）；unknown 不进入 primary。
"""

from __future__ import annotations

from ultrafast_knowledge.literature.extraction.schemas import (
    MaterialRole,
    PaperMetadata,
    ProcessRole,
)

PRIMARY_MATERIAL_ROLES = frozenset(
    {
        MaterialRole.PRIMARY_WORKPIECE,
        MaterialRole.SUBSTRATE,
        MaterialRole.COATING,
        MaterialRole.REINFORCEMENT,
    }
)


def validate_mentions(metadata: PaperMetadata, *, page_count: int) -> list[str]:
    warnings: list[str] = []
    for mention in [*metadata.material_mentions, *metadata.process_mentions]:
        if mention.page is not None and not (1 <= mention.page <= max(1, page_count)):
            warnings.append(f"mention page {mention.page} out of range (1..{page_count}); page cleared")
            mention.page = None
        if not mention.raw_text.strip():
            warnings.append("mention with empty raw_text dropped")
    metadata.material_mentions = [m for m in metadata.material_mentions if m.raw_text.strip()]
    metadata.process_mentions = [m for m in metadata.process_mentions if m.raw_text.strip()]
    return warnings


def compute_primary_fields(metadata: PaperMetadata) -> None:
    primary: list[str] = []
    for mention in metadata.material_mentions:
        if mention.role in PRIMARY_MATERIAL_ROLES and mention.canonical_material_id not in primary:
            primary.append(mention.canonical_material_id)
    metadata.primary_material = primary
    primary_process = ""
    for mention in metadata.process_mentions:
        if mention.role == ProcessRole.PRIMARY_PROCESS:
            primary_process = mention.canonical_process_id
            break
    metadata.primary_process = primary_process
    metadata.primary_material_grade = {
        canonical: grade
        for canonical, grade in metadata.primary_material_grade.items()
        if canonical in primary
    }


def finalize(metadata: PaperMetadata, *, page_count: int) -> PaperMetadata:
    warnings = validate_mentions(metadata, page_count=page_count)
    compute_primary_fields(metadata)
    if not metadata.primary_material and any(
        m.role != MaterialRole.UNKNOWN for m in metadata.material_mentions
    ):
        warnings.append("material mentions exist but none has a primary role; primary_material stays unknown")
    metadata.warnings.extend(warnings)
    return metadata
