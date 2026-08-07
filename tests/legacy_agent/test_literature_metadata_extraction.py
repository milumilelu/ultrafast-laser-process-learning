from __future__ import annotations

import json

from ultrafast_knowledge.literature.extraction.candidates import (
    detect_geometry,
    detect_grades,
    detect_laser_type,
    detect_material_candidates,
    detect_process_candidates,
    detect_pulse_width,
    detect_wavelength,
)
from ultrafast_knowledge.literature.extraction.extractor import extract_paper_metadata
from ultrafast_knowledge.literature.extraction.schemas import (
    MaterialRole,
    PaperMetadata,
    ProcessRole,
)
from ultrafast_knowledge.literature.extraction.semantic_roles import (
    apply_llm_roles,
    extract_llm_fields,
)
from ultrafast_knowledge.literature.schemas import LiteratureSectionData


def _section(section_id: str, section_type: str, text: str, page: int = 1) -> LiteratureSectionData:
    return LiteratureSectionData(
        section_id=section_id,
        paper_id="paper-1",
        artifact_id=None,
        section_type=section_type,
        section_title="",
        page_start=page,
        page_end=page,
        text=text,
        text_hash=f"hash-{section_id}",
        parser_version="test",
    )


def test_material_candidates_rule_detection() -> None:
    sections = [
        _section("s1", "abstract", "Single crystal diamond refractive lenses were manufactured by femtosecond laser micromachining of diamond."),
        _section("s2", "introduction", "Silicon carbide and CFRP are also discussed for comparison."),
    ]
    materials = detect_material_candidates(sections)
    canonical_ids = {m.canonical_material_id for m in materials}
    assert "Diamond" in canonical_ids
    assert "SiC" in canonical_ids
    assert "CFRP" in canonical_ids
    diamond = next(m for m in materials if m.canonical_material_id == "Diamond")
    assert diamond.role == MaterialRole.UNKNOWN
    assert diamond.page == 1
    assert diamond.section_type == "abstract"
    assert diamond.evidence_span is not None
    assert diamond.raw_text


def test_material_candidates_multi_material_tbc() -> None:
    sections = [
        _section("s1", "abstract", "Laser drilling of thermal barrier coated nickel superalloy was studied."),
    ]
    canonical_ids = {m.canonical_material_id for m in detect_material_candidates(sections)}
    assert {"NickelSuperalloy", "TBC"} <= canonical_ids


def test_glass_ceramic_canonical_detection() -> None:
    sections = [_section("s1", "abstract", "微晶玻璃飞秒激光加工研究进展")]
    canonical_ids = {m.canonical_material_id for m in detect_material_candidates(sections)}
    assert "GlassCeramic" in canonical_ids
    assert "Glass" not in canonical_ids


def test_candidate_dedup_keeps_distinct_occurrences_on_same_page() -> None:
    sections = [
        _section("s1", "abstract", "Diamond was cut. Diamond was then polished.", page=3),
        _section("s2", "methods", "Diamond was mounted.", page=3),
    ]
    mentions = [
        mention
        for mention in detect_material_candidates(sections)
        if mention.canonical_material_id == "Diamond"
    ]
    assert len(mentions) == 3
    assert len({(item.section_id, item.evidence_span) for item in mentions}) == 3


def test_process_candidates() -> None:
    sections = [
        _section("s1", "abstract", "Internal scribing and mechanical breaking of glass sheets; wet etching as postprocess."),
    ]
    processes = {p.canonical_process_id for p in detect_process_candidates(sections)}
    assert "scribing" in processes
    assert "wet_etching" in processes
    assert "cutting" not in processes


def test_laser_wavelength_pulse_detection() -> None:
    text = "A Ti:Sapphire laser (lambda = 800 nm, FWHM = 50 fs, 10 kHz) was used."
    assert detect_laser_type(text) == "fs"
    assert detect_wavelength(text) is not None and detect_wavelength(text).value == 800.0
    assert detect_pulse_width(text) is not None and detect_pulse_width(text).unit == "fs"
    assert detect_laser_type("ultrafast laser processing") == ""
    assert detect_wavelength("no wavelength mentioned") is None


def test_grade_detection() -> None:
    text = "T300 laminates and Q345B steel plates were tested."
    grades = detect_grades(text)
    assert grades.get("CFRP") == "T300"
    assert grades.get("Steel") == "Q345B"


def test_geometry_detection() -> None:
    assert detect_geometry("through glass via (TGV) fabrication") == "circular_hole"
    assert detect_geometry("a compound refractive lens (CRL)") == "lens"
    assert detect_geometry("nothing special here") == ""


def test_no_llm_abstains_roles_and_primary() -> None:
    sections = [
        _section("s1", "abstract", "Diamond lenses made by femtosecond laser micromachining of diamond."),
    ]
    metadata = extract_paper_metadata("paper-1", sections, llm_client=None, page_count=1)
    assert metadata.extraction_status == "rule_only_abstained"
    assert metadata.primary_material == []
    assert metadata.primary_process == ""
    assert metadata.laser_type == "fs"
    assert all(m.role == MaterialRole.UNKNOWN for m in metadata.material_mentions)
    assert metadata.material_mentions


class _FakeClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def chat(self, messages: list[dict], **kwargs: object) -> dict:
        return {"content": json.dumps(self.payload, ensure_ascii=False)}


def test_llm_roles_assign_primary_fields() -> None:
    sections = [
        _section("s1", "abstract", "Single crystal diamond refractive lenses were manufactured by femtosecond laser micromachining."),
    ]
    client = _FakeClient(
        {
            "material_roles": {"0": "primary_workpiece"},
            "process_roles": {"M0": "primary_process"},
            "laser_type": "fs",
            "wavelength_nm": 1030,
            "pulse_width": {"value": 350, "unit": "fs", "evidence": "350 fs"},
            "material_grade": {"Diamond": "single crystal"},
            "geometry": "lens",
        }
    )
    metadata = extract_paper_metadata("paper-1", sections, llm_client=client, page_count=1)
    assert metadata.extraction_status == "extracted_with_llm"
    assert metadata.primary_material == ["Diamond"]
    assert metadata.primary_process == "micromachining"
    assert metadata.laser_type == "fs"
    assert metadata.wavelength_nm is not None and metadata.wavelength_nm.value == 1030.0
    assert metadata.pulse_width is not None and metadata.pulse_width.unit == "fs"
    assert metadata.primary_material_grade == {"Diamond": "single crystal"}
    assert metadata.geometry == "lens"
    assert metadata.material_mentions[0].role == MaterialRole.PRIMARY_WORKPIECE
    assert metadata.material_mentions[0].extraction_method == "llm"


def test_llm_invalid_role_falls_back_to_unknown() -> None:
    sections = [_section("s1", "abstract", "Diamond femtosecond laser micromachining of diamond.")]
    client = _FakeClient({"material_roles": {"0": "banana"}, "laser_type": "unknown"})
    metadata = extract_paper_metadata("paper-1", sections, llm_client=client, page_count=1)
    assert metadata.extraction_status == "rule_only_abstained"
    assert metadata.primary_material == []
    assert metadata.material_mentions[0].role == MaterialRole.UNKNOWN
    assert metadata.laser_type == "fs"
    assert any("schema violation" in warning for warning in metadata.warnings)


def test_llm_payload_missing_fields_abstains() -> None:
    from ultrafast_knowledge.literature.extraction.semantic_roles import _validate_llm_payload

    assert _validate_llm_payload({"foo": "bar"}, n_materials=1, n_processes=1) is not None
    assert _validate_llm_payload(
        {"material_roles": {"0": "primary_workpiece"}, "process_roles": {"M0": "primary_process"},
         "laser_type": "fs", "wavelength_nm": 1030, "pulse_width": None, "material_grade": {}, "geometry": "unknown"},
        n_materials=1, n_processes=1,
    ) is None
    assert _validate_llm_payload(
        {"material_roles": {"7": "primary_workpiece"}, "process_roles": {},
         "laser_type": "fs", "wavelength_nm": None, "pulse_width": None, "material_grade": {}, "geometry": "unknown"},
        n_materials=2, n_processes=0,
    ) is not None
    assert _validate_llm_payload(
        {"material_roles": {}, "process_roles": {}, "laser_type": "banana",
         "wavelength_nm": None, "pulse_width": None, "material_grade": {}, "geometry": "unknown"},
        n_materials=0, n_processes=0,
    ) is not None
    assert _validate_llm_payload(
        {"material_roles": {}, "process_roles": {}, "laser_type": "fs",
         "wavelength_nm": None, "pulse_width": {"value": 50}, "material_grade": {}, "geometry": "unknown"},
        n_materials=0, n_processes=0,
    ) is not None


def test_llm_garbage_payload_abstains() -> None:
    sections = [_section("s1", "abstract", "Diamond laser micromachining.")]
    client = _FakeClient("not json at all {broken")
    metadata = extract_paper_metadata("paper-1", sections, llm_client=client, page_count=1)
    assert metadata.extraction_status == "rule_only_abstained"
    assert any("failed after retries" in warning for warning in metadata.warnings)


def test_llm_comparison_role_excluded_from_primary() -> None:
    sections = [
        _section("s1", "abstract", "CFRP plates were cut; diamond tools and aluminum reference samples were also used."),
    ]
    payload = {
        "material_roles": {"0": "comparison_material", "1": "primary_workpiece", "2": "tool_material"},
        "process_roles": {"M0": "primary_process"},
        "laser_type": "unknown",
        "wavelength_nm": None,
        "pulse_width": None,
        "material_grade": {},
        "geometry": "unknown",
    }
    client = _FakeClient(payload)
    metadata = extract_paper_metadata("paper-1", sections, llm_client=client, page_count=1)
    assert metadata.primary_material == ["CFRP"]
    roles = metadata.mention_roles()
    assert roles.get("Diamond") == "tool_material"
    assert metadata.primary_material_grade == {}


def test_extract_llm_fields_normalization() -> None:
    fields = extract_llm_fields(
        {
            "laser_type": "ultrafast",
            "wavelength_nm": None,
            "pulse_width": {"value": "300", "unit": "ps", "evidence": "300 ps"},
            "material_grade": {"Steel": "Q345B", "X": None},
            "geometry": "unknown",
        }
    )
    assert fields["laser_type"] == ""
    assert fields["wavelength_nm"] is None
    assert fields["pulse_width"]["value"] == 300.0
    assert fields["material_grade"] == {"Steel": "Q345B"}
    assert fields["geometry"] == ""


def test_apply_llm_roles_unknown_process() -> None:
    from ultrafast_knowledge.literature.extraction.candidates import detect_process_candidates

    sections = [_section("s1", "abstract", "Femtosecond laser micromachining of diamond.")]
    processes = detect_process_candidates(sections)
    apply_llm_roles([], processes, {"process_roles": {"M0": "unknown"}})
    assert processes[0].role == ProcessRole.UNKNOWN
    assert processes[0].extraction_method == "rule"


def test_validator_page_out_of_range_cleared() -> None:
    sections = [_section("s1", "abstract", "Diamond machining.", page=9)]
    client = _FakeClient({"material_roles": {"0": "primary_workpiece"}, "laser_type": "fs"})
    metadata = extract_paper_metadata("paper-1", sections, llm_client=client, page_count=2)
    assert metadata.material_mentions[0].page is None
    assert any("out of range" in warning for warning in metadata.warnings)


def test_paper_metadata_as_dict() -> None:
    sections = [_section("s1", "abstract", "Diamond machining by femtosecond laser.")]
    metadata = extract_paper_metadata("paper-1", sections, llm_client=None, page_count=1)
    data = PaperMetadata.model_validate(metadata.as_dict())
    assert data.paper_id == "paper-1"
