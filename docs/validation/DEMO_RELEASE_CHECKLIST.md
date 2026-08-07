# TOPIC 2 DEMO RELEASE CHECKLIST（M10 Gate）

> 目标版本：**topic2-demo-v1**（Uncalibrated CFA v2.0 演示版）
> 执行日期：2026-08-07。全部 Gate 通过后 tag。
> 演示场景：`docs/validation/DEMO_SCENARIO_01.md`（固定）。
> 复现命令：`python scripts/demo_t2_vertical_slice.py --output outputs/t2_slice_run.json`

## R1–R6 工程 Gate

| Gate | 内容 | 命令 | 结果 |
|---|---|---|---|
| R1 | clean install | `pip install -e .` + 全包 clean import | **PASS** |
| R2 | fast tests | `pytest tests -q` | **PASS**（446 passed, 111 deselected） |
| R3 | pilot tests | `pytest tests -m pilot -q` | **PASS**（111 passed） |
| R4 | import-linter | `lint-imports` | **PASS**（10 kept, 0 broken） |
| R5 | mypy（CI 范围） | `mypy src/ultrafast_ingestion --ignore-missing-imports` | **PASS**（44 files clean） |
| R6 | ruff | CI 范围 + 触碰代码（demo/reconstructibility/cfa/interaction/physics/benchmarks） | **PASS** |

## R7–R16 语义 Gate（证据来自 `outputs/t2_slice_run.json`，固定 seed 42）

| Gate | 内容 | 证据 | 结果 |
|---|---|---|---|
| R7 | process learning 端到端 | view=RAW model=RSM，18 samples，Group-CV 完成 | **PASS** |
| R8 | 文献证据可追溯 paper/page | claims 带 `source.block_id`（如 `04_arxiv_2502.16530.pdf:p0:b25`）+ quote + candidate_id；ledger_version_ids 5 个 | **PASS** |
| R9 | Source/Target readiness 报告 | `cfa.target_physics_readiness`（available/blocked/unverified 计数）+ 每 report Reconstructibility | **PASS** |
| R10 | CFA 报告 NOT_YET_CALIBRATED | `cfa.calibration_status` + `audit.cfa_status` | **PASS** |
| R11 | Unknown 不静默转 Mismatch | B1-25 severe=0；v1.1 holdout severe=0；v2 regression severe=0；H2 违例 0（2c0e83 无 metadata → UNKNOWN） | **PASS** |
| R12 | unverified physics 不静默消费 | V2-1/V2-2 修复 + `test_demo_v3`（peak_fluence 永非 COMPARABLE；spot UNVERIFIED → overlap 族永非 COMPARABLE + warnings） | **PASS** |
| R13 | GovernedPriorArtifact 可追溯 evidence IDs | 16 个 claim 级 approval_ids + content_hash `025112440d90c059` + audit_trace `repository_verified` | **PASS** |
| R14 | assisted BO 报告 prior_applied=true | `prior_applied_evidence.assisted_search_prior_applied=True`，prior_guidance=`e2p_soft_prior_v1`，acquisition score 0.999（prior 真实修改 acquisition） | **PASS** |
| R15 | vanilla BO 报告 prior_applied=false | `vanilla_search_prior_applied=False`，acquisition prior_guidance=null，score 0.732 | **PASS** |
| R16 | fixed seed/config 可重放 | 同命令重跑两次：仅 `bo_run_id`（运行标识）不同，全部科学载荷逐字节一致（推荐参数/acquisition/哈希/facets） | **PASS** |

## 展示纪律（随 release 固化）

```text
√ 表述：Uncalibrated CFA；facet ∈ {KNOWN, PARTIAL, UNKNOWN, MISMATCH} + warnings
√ calibration_status 恒为 NOT_YET_CALIBRATED
× 禁止：transfer probability / confidence 类输出（测试断言无泄漏）
× 禁止：把 B1-25 表述为独立泛化性能（只能作 diagnostic audit 表述）
√ 推荐参数并列展示 + acquisition 分数对照 + audit_trace 回溯
```

## OUT OF SCOPE（登记，进入 post-demo research track）

```text
× Calibrated CFA probability        × Dynamic Trust
× Cross-equipment transfer claim    × Open-world 226 篇全量验证
× Automatic schema evolution        × Fine-tuned 科学抽取模型
× Full Agent execution UI           × 全部论文 OCR 再摄取
× 材料属性/Fth 全治理覆盖           × transfer outcomes 学习证据权重
× 表格提取 gap 修复（A1 2 篇已登记根因）
```

## 冻结版本依赖

```text
CFA:            uncalibrated-cfa-v2.0（V2-1 dependency-aware + V2-2 RANGE 语义）
B1-25:          development/diagnostic set（severe=0）
旧 13 篇 holdout: v2 diagnostic set（H3 bug 3→0 / H5 bug 5→0）
新 11 篇 holdout: v2 independent validation（等人工标注）
Calibration:    未开始（D1-D4 inventory 已完成：outcome 仅 18 点）
```

## 结论

**R1–R16 全部 PASS → 允许 tag `topic2-demo-v1`。**
