"""半自动文献检索辅助 v2（P0-A 语料补缺）。

能力：
  1. 生成 WoS / Scopus / CNKI 人工粘贴用检索式文件（付费库需人工）
  2. 调 Crossref（词袋，429 自动重试）/ OpenAlex（title.search 单/双词）检索元数据
  3. 多子查询自动合并去重；本地年份与关键词二次过滤
  4. 与现有 gold 比对（标题规范化 + DOI），标记 already_annotated / new
  5. 导出 candidates.jsonl（title/doi/year/abstract 摘要/container/url）

用法：
  python scripts/literature_search.py --tag alsic_bonding ^
      --queries "AlSiC laser; aluminum silicon carbide femtosecond laser; metal matrix composite laser bonding" ^
      --must "AlSiC|aluminum silicon carbide|aluminium silicon carbide|SiC particle|metal matrix composite" ^
      --openalex-terms "AlSiC; aluminum silicon carbide; silicon carbide laser" ^
      --years 2011-2026 --rows 30

输出：searches/<tag>_<ts>/{candidates.jsonl, search_queries.md}
人工流程：search_queries.md 在 WoS/Scopus/CNKI 粘贴检索 → 下载 PDF →
放入语料目录 → prepare_annotations.py 抽取 → 标注。
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BENCH_ROOT = Path(__file__).resolve().parents[1]
GOLD_PATH = BENCH_ROOT / "gold" / "annotations.jsonl"
SEARCH_DIR = BENCH_ROOT / "searches"

TITLE_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff]+")


def normalize_title(title: str) -> str:
    return TITLE_RE.sub(" ", (title or "").lower()).strip()


def normalize_doi(doi: str) -> str:
    value = (doi or "").strip().lower()
    return re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", value)


def load_gold() -> tuple[set[str], set[str]]:
    if not GOLD_PATH.exists():
        return set(), set()
    titles: set[str] = set()
    dois: set[str] = set()
    for line in GOLD_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        norm = normalize_title(record.get("title") or "")
        if norm:
            titles.add(norm)
        doi = normalize_doi(record.get("doi") or "")
        if doi:
            dois.add(doi)
    return titles, dois


def _http_json(url: str, timeout: int = 30, retries: int = 3) -> dict:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "ultrafast-laser-benchmark/1.0 (mailto:research@example.com)"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 — 限流/网络瞬时失败退避重试
            last_error = exc
            time.sleep(2 * (attempt + 1))
    raise last_error  # type: ignore[misc]


def search_crossref(query: str, rows: int, years: tuple[int, int]) -> list[dict]:
    params = {
        "query.bibliographic": query,
        "rows": str(rows),
        "filter": f"from-pub-date:{years[0]}-01-01,until-pub-date:{years[1]}-12-31",
        "select": "DOI,title,abstract,container-title,issued,URL",
    }
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
    try:
        data = _http_json(url)
    except Exception as exc:  # noqa: BLE001 — 单源失败降级
        print(f"  crossref error: {exc}")
        return []
    items = []
    for item in data.get("message", {}).get("items", []):
        issued = (item.get("issued") or {}).get("date-parts") or []
        year = str(issued[0][0]) if issued and issued[0] else ""
        items.append({
            "doi": normalize_doi(item.get("DOI") or ""),
            "title": " ".join(item.get("title") or [""]).strip(),
            "abstract": re.sub(r"<[^>]+>", " ", item.get("abstract") or "")[:800].strip(),
            "container": " ".join(item.get("container-title") or []),
            "year": year,
            "url": item.get("URL") or f"https://doi.org/{item.get('DOI')}",
            "source": "crossref",
        })
    return items


def _openalex_abstract(inverted: dict) -> str:
    if not inverted:
        return ""
    positions: list[tuple[int, str]] = []
    for word, indices in inverted.items():
        for index in indices:
            positions.append((index, word))
    return " ".join(word for _, word in sorted(positions))[:800]


def search_openalex(term: str, rows: int, years: tuple[int, int]) -> list[dict]:
    params = {
        "filter": f"title.search:{term}",
        "per-page": str(rows),
    }
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    try:
        data = _http_json(url)
    except Exception as exc:  # noqa: BLE001 — 单源失败降级
        print(f"  openalex error: {exc}")
        return []
    items = []
    for work in data.get("results", []):
        year = str(work.get("publication_year") or "")
        if not (years[0] <= int(year) <= years[1]) if year.isdigit() else False:
            continue
        doi = work.get("doi") or ""
        items.append({
            "doi": normalize_doi(doi),
            "title": (work.get("title") or "").strip(),
            "abstract": _openalex_abstract(work.get("abstract_inverted_index") or {}),
            "container": ((work.get("primary_location") or {}).get("source") or {}).get("display_name") or "",
            "year": year,
            "url": work.get("id") or "",
            "source": "openalex",
        })
    return items


def merge(items: list[dict]) -> list[dict]:
    by_key: dict[str, dict] = {}
    for item in items:
        key = item["doi"] or (normalize_title(item["title"]) + item["year"])
        by_key.setdefault(key, item)
    return list(by_key.values())


def filter_hits(items: list[dict], must_pattern: str | None, years: tuple[int, int]) -> list[dict]:
    pattern = re.compile(must_pattern, re.IGNORECASE) if must_pattern else None
    kept = []
    for item in items:
        year = item.get("year") or ""
        if year.isdigit() and not (years[0] <= int(year) <= years[1]):
            continue
        if pattern is None:
            kept.append(item)
            continue
        haystack = f"{item['title']} {item['abstract']}"
        if pattern.search(haystack):
            kept.append(item)
    return kept


def build_queries_md(queries: list[str], must: str | None, tag: str, years: tuple[int, int]) -> str:
    lines = [
        f"# 检索式（{tag}，{years[0]}-{years[1]}）",
        "",
        "## Web of Science / Scopus（人工粘贴，可加引号与 NOT）",
    ]
    for index, query in enumerate(queries, start=1):
        lines += [f"### 子查询 {index}", f"```text\n{query}\n```", ""]
    lines += [
        "## CNKI（中文另行输入，参考关键字）",
        "```text\n铝基碳化硅 飞秒激光 表面织构 胶接 剪切强度\n```",
        "",
        "## 提示",
        f"- 二次过滤正则: {must or '(无)'}",
        "- 下载 PDF 放入语料目录 → prepare_annotations.py 抽取 → 标注；",
        "- 与 candidates.jsonl 按 DOI/标题去重。",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Half-automatic literature search v2 (Crossref/OpenAlex)")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--queries", required=True, help="分号分隔的子查询（词袋）")
    parser.add_argument("--must", default=None, help="二次过滤正则（标题或摘要命中）")
    parser.add_argument("--openalex-terms", default="", help="分号分隔的 title.search 词（建议 1-2 词）")
    parser.add_argument("--years", default="2011-2026")
    parser.add_argument("--rows", type=int, default=30)
    parser.add_argument("--no-crossref", action="store_true")
    args = parser.parse_args()

    years = tuple(int(part) for part in args.years.split("-"))
    gold_titles, gold_dois = load_gold()
    queries = [q.strip() for q in args.queries.split(";") if q.strip()]
    openalex_terms = [t.strip() for t in args.openalex_terms.split(";") if t.strip()]

    items: list[dict] = []
    if not args.no_crossref:
        for index, query in enumerate(queries, start=1):
            print(f"[{index}/{len(queries)}] crossref: {query[:60]}")
            items += search_crossref(query, args.rows, years)
            time.sleep(1.0)
    for index, term in enumerate(openalex_terms, start=1):
        print(f"[openalex {index}/{len(openalex_terms)}] title.search: {term}")
        items += search_openalex(term, args.rows, years)
        time.sleep(0.6)

    items = merge(items)
    items = filter_hits(items, args.must, years)
    for item in items:
        already = normalize_title(item["title"]) in gold_titles or (item["doi"] and item["doi"] in gold_dois)
        item["status"] = "already_annotated" if already else "new"
    new_count = sum(1 for i in items if i["status"] == "new")

    out_dir = SEARCH_DIR / f"{args.tag}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "candidates.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in items) + "\n", encoding="utf-8"
    )
    (out_dir / "search_queries.md").write_text(
        build_queries_md(queries, args.must, args.tag, years), encoding="utf-8"
    )
    print(f"\n结果: {len(items)} 条（新 {new_count} / 已标注 {len(items) - new_count}）")
    print(f"输出: {out_dir}")
    for item in items[:20]:
        marker = "ALREADY" if item["status"] == "already_annotated" else "new   "
        print(f"  [{marker}] {item['year']} {item['title'][:66]}")
        print(f"          doi={item['doi'] or '-'} | {item['container'][:38]}")


if __name__ == "__main__":
    main()
