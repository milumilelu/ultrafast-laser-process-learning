"""标注准备流水线（P0-A 第二阶段）：18:01 定时任务执行。

流程：
1. 从语料挑选代表性 PDF（按场景均衡，避开已标注的 10 篇）
2. 抽取前 6 页文本（带页码标记）→ work/texts/
3. 规则层预标注（Extractor V2 rule-only）→ work/drafts/annotations_round2_draft.jsonl
4. 生成标注工作单 work/annotation_worksheet.md（供人工/AI 逐篇裁决语义角色）

产出均为"草稿/工作台"，不修改 gold/annotations.jsonl。
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BENCH_ROOT = Path(__file__).resolve().parents[1]
MEMORY_ROOT = BENCH_ROOT.parents[1]
CORPUS_ROOT = MEMORY_ROOT / "超快智能体文献检索"
WORK_DIR = BENCH_ROOT / "work"
GOLD_PATH = BENCH_ROOT / "gold" / "annotations.jsonl"

DEFAULT_PER_SCENARIO = 3
MAX_PAGES = 6


def _load_gold_paper_ids() -> set[str]:
    if not GOLD_PATH.exists():
        return set()
    ids: set[str] = set()
    with GOLD_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                ids.add(json.loads(line)["paper_id"])
            except (json.JSONDecodeError, KeyError):
                pass
    return ids


def _scenario_dirs() -> list[Path]:
    if not CORPUS_ROOT.exists():
        return []
    return sorted(d for d in CORPUS_ROOT.iterdir() if d.is_dir() and d.name != "__pycache__")


def _pick_pdfs(gold_ids: set[str], per_scenario: int) -> list[Path]:
    picked: list[Path] = []
    for scenario in _scenario_dirs():
        pdfs = sorted(scenario.rglob("*.pdf"))
        candidates = [p for p in pdfs if p.name not in gold_ids]
        picked.extend(candidates[:per_scenario])
    return picked


def _extract_pages(pdf_path: Path) -> list[str]:
    import fitz  # type: ignore

    document = fitz.open(str(pdf_path))
    try:
        pages = []
        for index in range(min(MAX_PAGES, len(document))):
            text = " ".join(document[index].get_text("text").split())
            pages.append(f"[PAGE {index + 1}] {text}")
        return pages
    finally:
        document.close()


def _build_sections_from_pages(pages: list[str], paper_id: str) -> list[object]:
    from ultrafast_knowledge.literature.schemas import LiteratureSectionData

    sections = []
    for index, page in enumerate(pages, start=1):
        text = page.split("] ", 1)[1] if "] " in page else page
        sections.append(
            LiteratureSectionData(
                section_id=f"{paper_id}-page-{index}",
                paper_id=paper_id,
                artifact_id=None,
                section_type="page",
                section_title="",
                page_start=index,
                page_end=index,
                text=text,
                text_hash=f"h-{paper_id}-{index}",
                parser_version="annotation-prep",
            )
        )
    return sections


def _rule_draft(pdf_path: Path, pages: list[str]) -> dict:
    from ultrafast_knowledge.literature.extraction.extractor import extract_paper_metadata

    paper_id = pdf_path.name
    sections = _build_sections_from_pages(pages, paper_id)
    metadata = extract_paper_metadata(paper_id, sections, llm_client=None, page_count=len(pages))
    data = metadata.as_dict()
    return {
        "paper_id": paper_id,
        "title": pdf_path.stem,
        "is_review": None,
        "primary_material": data["primary_material"],
        "material_grade": data["primary_material_grade"],
        "primary_process": data["primary_process"],
        "laser_type": data["laser_type"],
        "wavelength_nm": (data["wavelength_nm"] or {}).get("value"),
        "pulse_width": data["pulse_width"],
        "geometry": data["geometry"],
        "material_mentions": data["material_mentions"],
        "process_mentions": data["process_mentions"],
        "evidence_page_primary_material": None,
        "notes": "rule-draft; roles unknown until semantic review",
        "rule_extraction_status": data["extraction_status"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare literature annotation worksheet")
    parser.add_argument("--per-scenario", type=int, default=DEFAULT_PER_SCENARIO)
    parser.add_argument("--limit", type=int, default=0, help="dry-run limit (0 = all)")
    args = parser.parse_args()

    gold_ids = _load_gold_paper_ids()
    pdfs = _pick_pdfs(gold_ids, args.per_scenario)
    if args.limit:
        pdfs = pdfs[: args.limit]
    if not pdfs:
        print(f"no PDFs selected (corpus={CORPUS_ROOT})")
        return

    texts_dir = WORK_DIR / "texts"
    drafts_dir = WORK_DIR / "drafts"
    texts_dir.mkdir(parents=True, exist_ok=True)
    drafts_dir.mkdir(parents=True, exist_ok=True)

    drafts: list[dict] = []
    worksheet: list[str] = []
    failed = 0
    for pdf in pdfs:
        rel = pdf.relative_to(CORPUS_ROOT)
        try:
            pages = _extract_pages(pdf)
            if not any(page.strip() for page in pages):
                raise RuntimeError("empty text extraction (likely scanned)")
            (texts_dir / f"{pdf.stem}.txt").write_text("\n\n".join(pages), encoding="utf-8")
            draft = _rule_draft(pdf, pages)
            draft["source_path"] = str(rel)
            drafts.append(draft)
            worksheet.append(f"## {pdf.name}\n- source: {rel}\n- laser: {draft['laser_type']} | wavelength: {draft['wavelength_nm']} | pulse: {draft['pulse_width']}")
            worksheet.append(f"- material candidates: {[m['canonical_material_id'] for m in draft['material_mentions']]}")
            worksheet.append(f"- process candidates: {[m['canonical_process_id'] for m in draft['process_mentions']]}")
            worksheet.append(f"- geometry: {draft['geometry']} | grades: {draft['material_grade']}\n")
        except Exception as exc:  # noqa: BLE001 — 单篇失败不阻断流水线
            failed += 1
            worksheet.append(f"## {pdf.name}\n- FAILED: {exc}\n")

    draft_path = drafts_dir / "annotations_round2_draft.jsonl"
    with draft_path.open("w", encoding="utf-8") as handle:
        for draft in drafts:
            handle.write(json.dumps(draft, ensure_ascii=False) + "\n")

    worksheet_path = WORK_DIR / "annotation_worksheet.md"
    worksheet_path.write_text("\n".join(worksheet), encoding="utf-8")

    summary = {
        "generated_at": None,
        "corpus_root": str(CORPUS_ROOT),
        "selected_pdfs": len(pdfs),
        "drafted": len(drafts),
        "failed": failed,
        "draft_path": str(draft_path),
        "worksheet_path": str(worksheet_path),
        "texts_dir": str(texts_dir),
        "existing_gold_papers": len(gold_ids),
    }
    from datetime import datetime, timezone

    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    (WORK_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
