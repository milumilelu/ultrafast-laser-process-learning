# Table Evidence Pipeline V1

## Frozen scope

- Native-text scientific tables: Camelot 2.0 ML.
- Image-only tables: persist an unresolved warning; no OCR fallback in V1.
- Cross-page tables: detect `POSSIBLE_CONTINUATION`, but do not merge until a
  dedicated cross-page Gold set shows zero false merges for `first_row`.
- Normalization is deterministic. An LLM must not repair table cells.

## Runtime contract

Install the optional table runtime with `.[tables]`. The validated benchmark
environment used `camelot-py==2.0.0`, Python 3.12.13, CPU, `torch==2.13.0`,
`torchvision==0.28.0`, `transformers==4.57.6`, and
`huggingface_hub==0.36.2`. The latter packages are recorded observations, not
project pins, because their compatibility must be validated in the chosen
deployment image before freezing them.

Preload these model families into the deployment cache:

- `table-transformer-detection`
- `structure-recognition-v1.1-all`
- `timm resnet18.a1_in1k`

Validated cache revisions are fixed and checked before every extraction:

```text
microsoft/table-transformer-detection
  2357cbe2b5a5d1c03e54f32764f06058933b65ab
microsoft/table-transformer-structure-recognition-v1.1-all
  7587a7ef111d9dcbf8ac695f1376ab7014340a0c
timm/resnet18.a1_in1k
  491b427b45c94c7fb0e78b5474cc919aff584bbf
```

Production must set both:

```text
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

When Camelot is installed in an isolated environment, also set
`TABLE_EXTRACTOR_PYTHON` to that environment's Python executable. The main
process then uses `CamelotWorkerTableExtractor` and exchanges JSON with a
minimal worker that has no dependency on Pydantic or the application package.

`CamelotMLTableExtractor` refuses extraction without offline mode. A failure is
recorded in paper metadata as `TABLE_EXTRACTION_FAILED`; native-text ingestion
continues so one optional extractor cannot invalidate the whole paper.

## Stored evidence

`scientific_table_store` is the lossless normalized source. The block index
contains deterministic projections:

- one table-summary block;
- one block per non-header row;
- stable links to the caption and table ID.

A table-row retrieval window contains only the caption, summary/header
projection, matched row, and at most one adjacent data row on each side.

## Cross-page acceptance gate

Build 5–10 real Gold cases covering repeated headers, missing repeated headers,
same-column adjacent tables, changed column counts, and page header/footer noise.
Report correct merge, false merge, missed merge, and duplicate-header rates for
`none`, `first_row`, and `column_count`. Automatic `first_row` stacking remains
disabled unless false merge rate is exactly zero on this gate.
