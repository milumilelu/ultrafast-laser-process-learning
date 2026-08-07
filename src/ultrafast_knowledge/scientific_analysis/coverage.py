"""Coverage Planner（文档第十一、十二节）。

- RAG 输出 Primary + Reserve 两级；先精读 Primary，coverage 足够即停；
- coverage 类别跟踪：laser_conditions / spot_size / fluence_relation /
  threshold / thermal_property / mechanism 等；
- 缺失类别 → Targeted RAG 提示（精确检索，不做泛搜）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ultrafast_knowledge.corpus.schemas import CorpusSource, EvidenceCorpusPack
from ultrafast_knowledge.scientific_analysis.schemas import SourceScientificAnalysis

# coverage 类别 → 判定函数（从 Source 分析中检查是否覆盖）
COVERAGE_CATEGORIES: dict[str, str] = {
    "laser_conditions": "experimental_conditions",
    "parameter_relations": "parameter_effects",
    "material_properties": "material_properties",
    "threshold": "thresholds",
    "formulas": "formulas",
    "mechanisms": "mechanisms",
    "reported_optima": "reported_optima",
}

# 类别 → Targeted RAG 检索提示（文档第十二节）
CATEGORY_SEARCH_HINTS: dict[str, tuple[str, ...]] = {
    "threshold": ("ablation threshold", "threshold fluence", "incubation"),
    "material_properties": ("thermal diffusivity", "absorptance", "bandgap", "heat capacity"),
    "spot_size": ("spot size", "beam waist", "diameter", "1/e2", "focus"),
    "thermal_property": ("thermal diffusivity", "heat accumulation", "thermal conductivity"),
    "laser_conditions": ("wavelength", "pulse duration", "repetition rate", "power"),
    "mechanisms": ("mechanism", "heat accumulation", "multiphoton", "plasma"),
    "reported_optima": ("optimal", "optimum", "best parameters"),
    "formulas": ("formula", "equation", "fluence", "overlap"),
    "parameter_relations": ("effect", "influence", "dependence", "relation"),
}


@dataclass(slots=True)
class CoverageReport:
    covered: dict[str, int] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    search_hints: dict[str, list[str]] = field(default_factory=dict)

    @property
    def coverage_ratio(self) -> float:
        total = len(COVERAGE_CATEGORIES)
        return len(self.covered) / total if total else 0.0

    def sufficient(self, threshold: float = 0.6) -> bool:
        return self.coverage_ratio >= threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "covered": self.covered,
            "missing": self.missing,
            "search_hints": self.search_hints,
            "coverage_ratio": self.coverage_ratio,
            "sufficient": self.sufficient(),
        }


class CoveragePlanner:
    """从 Source 分析结果统计 coverage，决定是否启用 Reserve / Targeted RAG。"""

    def __init__(self, *, sufficient_threshold: float = 0.6):
        self.sufficient_threshold = sufficient_threshold

    def assess(
        self,
        analyses: list[SourceScientificAnalysis],
    ) -> CoverageReport:
        report = CoverageReport()
        for category, attribute in COVERAGE_CATEGORIES.items():
            count = sum(len(getattr(analysis, attribute)) for analysis in analyses)
            if count > 0:
                report.covered[category] = count
            else:
                report.missing.append(category)
                report.search_hints[category] = list(
                    CATEGORY_SEARCH_HINTS.get(category, ())
                )
        return report

    def select_primary(
        self,
        pack: EvidenceCorpusPack,
        primary_count: int = 6,
    ) -> list[CorpusSource]:
        """Primary：检索分数最高的前 N 个 Source（Reserve 为其余）。"""
        scored = sorted(
            pack.sources,
            key=lambda source: max(
                (section.retrieval_score or 0.0 for section in source.sections),
                default=0.0,
            ),
            reverse=True,
        )
        return scored[:primary_count]

    def reserve_sources(
        self,
        pack: EvidenceCorpusPack,
        primary_count: int = 6,
    ) -> list[CorpusSource]:
        scored = sorted(
            pack.sources,
            key=lambda source: max(
                (section.retrieval_score or 0.0 for section in source.sections),
                default=0.0,
            ),
            reverse=True,
        )
        return scored[primary_count:]

    def targeted_rag_queries(self, report: CoverageReport) -> list[str]:
        """缺失类别 → Targeted RAG 查询（文档第九、十二节）。"""
        queries = []
        for category in report.missing:
            hints = report.search_hints.get(category, ())
            if hints:
                queries.append(" ".join(hints))
        return queries
