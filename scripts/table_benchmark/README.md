# Table Extraction Benchmark

Four PDF table extraction schemes are compared on real ultrafast-laser papers
from `data/literature_archive/`:

1. PyMuPDF `find_tables()` (+ `strategy="text"` fallback, no parameter tuning)
2. Docling + TableFormer (ACCURATE)
3. PaddleOCR PP-StructureV3 (local, CPU)
4. Camelot 2.0 `flavor="ml"`

This benchmark deliberately does **not** touch `src/ultrafast_ingestion/` or
`src/ultrafast_knowledge/`, and does not implement any fallback architecture.

## Layout

```
scripts/table_benchmark/
├── README.md
├── common.py               stdlib-only shared helpers
├── benchmark_cases.json    case registry (derived from gold/*.json)
├── gold/*.json             hand-annotated gold tables (source of truth)
├── run_pymupdf.py          adapter 1
├── run_docling.py          adapter 2
├── run_paddleocr.py        adapter 3
├── run_camelot.py          adapter 4
├── run_all.py              orchestrator (4 venvs -> evaluate)
├── evaluate.py             metrics + review + summary
└── results/                per-tool outputs, summary.json/csv, REPORT.md
```

## Environments

Each scheme uses an independent virtual environment to avoid dependency
conflicts (PyTorch / PaddlePaddle / OpenCV):

| Tool      | venv                  |
|-----------|-----------------------|
| PyMuPDF   | `.venv-table-pymupdf` |
| Docling   | `.venv-table-docling` |
| PaddleOCR | `.venv-table-paddle`  |
| Camelot   | `.venv-table-camelot` |

Install:

```bash
.venv-table-pymupdf/Scripts/python -m pip install "pymupdf==1.28.2"
.venv-table-docling/Scripts/python -m pip install "docling"
.venv-table-paddle/Scripts/python -m pip install paddlepaddle==3.2.2 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/   # 本机 Python 3.12 实测 3.2.2
.venv-table-paddle/Scripts/python -m pip install "paddleocr[doc-parser]"
"%LOCALAPPDATA%\Temp\cv\Scripts\python" -m pip install "camelot-py[ml]"   # Windows 中文长路径无法解包 torch，用短路径 venv
```

PaddleOCR additionally uses PyMuPDF only to render the target page to PNG at a
fixed DPI (300) before inference:

```bash
.venv-table-paddle/Scripts/python -m pip install "pymupdf==1.28.2"
```

## Run

```bash
python scripts/table_benchmark/run_all.py
```

or step by step:

```bash
.venv-table-pymupdf/Scripts/python scripts/table_benchmark/run_pymupdf.py
.venv-table-docling/Scripts/python scripts/table_benchmark/run_docling.py
.venv-table-paddle/Scripts/python scripts/table_benchmark/run_paddleocr.py
.venv-table-camelot/Scripts/python scripts/table_benchmark/run_camelot.py
python scripts/table_benchmark/evaluate.py
```

Each adapter writes a unified result JSON per case plus `_raw.json` with the
tool's original output, `env.json` (python/package/device/OS) and
`pip_freeze.txt` into `results/<tool>/`.

## Metrics

| Metric | Definition |
|--------|------------|
| Table Recall | detected / total gold tables |
| Shape Accuracy | exact row & column counts (cell-evaluable cases) |
| Cell Accuracy | normalized cell exact match on aligned rows |
| Numeric Accuracy | ordered numeric-token match on gold numeric cells |
| Header-Value Accuracy | value remains under the same column/row header |
| Cold Start | elapsed time of the first (model-loading) case |
| Mean Page Time | mean elapsed time of warm cases |

Normalization is deliberately conservative (whitespace folding, mu/micro and
unicode minus only). No unit conversion, rounding, or LLM repair.

## Outputs

- `results/summary.json` — full metrics + per-category + diagnostics
- `results/summary.csv` — one row per tool
- `results/diagnostics.json` — per-case per-tool diagnostic
- `results/review/<case_id>/` — source page PNG + gold + per-tool JSON
- `REPORT.md` — final benchmark report

## 本机实测注意事项

- Camelot 实际运行环境为 `%LOCALAPPDATA%\Temp\cv`（camelot-py 2.0.0）：仓库内
  `.venv-table-camelot` 因 Windows 中文长路径无法解包 torch 而残缺，未使用。
  通过 `run_all.py` 的 `TABLE_BENCH_VENV_CAMELOT` 环境变量覆盖。
- Camelot ml 依赖 HF 模型（table-transformer-detection / structure-recognition-v1.1-all /
  timm resnet18.a1_in1k），本机已离线缓存；运行需
  `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`。
- PaddleOCR 本机实际安装 paddlepaddle 3.2.2（CPU），并需
  `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True` 跳过模型源检查。
- PaddleOCR 页面渲染 PNG 以 `case_id` 命名（长文件名会导致 PyMuPDF 无法打开）。
