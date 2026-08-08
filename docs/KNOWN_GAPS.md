# KNOWN_GAPS / 已知差距与断链登记

> 更新：2026-08-07（topic2-demo-v1.1 Release Hardening，RF-5 重签）。
> 状态词汇：`RESOLVED` / `PARTIALLY_RESOLVED` / `KNOWN`（未影响发布主链）/
> `POST_DEMO`（明确进入 post-demo research track，演示版不做）。

## 演示版状态声明（先说结论）

```text
demo 主链（Target CSV → Process Learning → Literature/conditions →
EvidenceIR → E2P → GovernedPriorArtifact → Vanilla/Assisted BO，并行
Source/Target readiness → Canonical state → Uncalibrated CFA audit）：
连通，R1–R17 全 PASS（docs/validation/DEMO_RELEASE_CHECKLIST.md）。

科学状态：不声明 "CFA v2 已通过独立科学验证"。
新 11 篇 unseen holdout：H1/H2 PASS，H3/H5 未过
（artifacts/cfa_holdout/V2_INDEPENDENT_VALIDATION.md），
根因全部登记为 POST_DEMO。
```

## Gap 登记表（按演示版相关性重签）

| ID | 状态 | 描述 | 处置 |
|---|---|---|---|
| GAP-01 | **RESOLVED** | E2P prepare → GovernedPriorArtifact → BO 未形成真实完整链 | M5.5/V3 vertical slice 实测连通：`prior_applied_evidence` + audit_trace（repository_verified + evidence_ids）证明 governed prior 真实进入 BO |
| GAP-02 | POST_DEMO | 前端参数辨识页走 Agent 侧 identification-v2，与后端 /parameter-identification/run 双轨 | 统一到 ultrafast_learning（非演示主链） |
| GAP-03 | **PARTIALLY_RESOLVED** | 真实 CSV 无功率列 / spot=5.0 未核实 / process_capability_config 空 | Target Physics Readiness（M7）完成并展示：spot=5.0 µm 显式 UNVERIFIED，功率相关坐标如实阻塞（NOT_APPLICABLE/DEPENDENCY_MISSING），不静默消费 |
| GAP-04 | **RESOLVED（登记为 POST_DEMO 的扩展项）** | 文献元数据不可重建（wavelength 0/226 等） | S0-2B 三态标注完成；演示版使用人工 gold 的 subset（metadata-gold 分层）；全量 226 篇开放世界验证属 POST_DEMO |
| GAP-05 | POST_DEMO | 旧 `src/acquisition.py` 与 ultrafast_bo UCB 双 acquisition 并存 | 旧仓库退役时清除 |
| GAP-06 | **PARTIALLY_RESOLVED** | `ultrafast_knowledge` 依赖 memory/integrations 非干净可分离包 | 独立 re-home 工作流（POST_DEMO）；演示主链不依赖 ultrafast_knowledge |
| GAP-07 | **RESOLVED** | prior_artifact 原为 sys.path 注入垫片 | 新仓库直接内置 canonical 实现（迁移自 packages/e2p） |
| GAP-08 | KNOWN | 系统 python 为 Windows Store 占位符 | 文档化；建议安装正式 Python 3.12 |
| GAP-09 | KNOWN | PyPI 直连超时 | README 已记录国内镜像 |
| GAP-10 | KNOWN | 依赖版本锁定 | 保持锁定，升级走单独 PR |
| GAP-11 | POST_DEMO | facet_summary 聚合语义：非 InteractionState facet 取首条件状态（H5 未过主因） | P1：跨条件汇总或显式"主加工条件" |
| GAP-12 | POST_DEMO | 表格提取 gap：sc04 系列表格参数未抽取（H3/H5 次因） | P2：表格再提取（演示版 OUT OF SCOPE） |
| GAP-13 | POST_DEMO | review/sweep 文档条件选择语义（H3 未过次因） | P3：文档类型（review）与参数扫描条件选择规则 |
| GAP-14 | POST_DEMO | Calibrated CFA / Dynamic Trust / Open Discovery blind benchmark / Agent UI | post-demo research track（M10 已冻结范围） |
| GAP-15 | PARTIALLY_RESOLVED | Material/Task metadata gold 覆盖缺口（如 5b039b material_id 空） | 保守方向（系统如实 UNKNOWN）；补 gold 为数据治理项 |

## S0-2 相关重大发现（旧仓库既有资产，勿重复造）

`ultrafast_laser_memory/benchmarks/literature_metadata/` 已存在：
- `gold/annotations.jsonl`（203 篇 AI 策展 silver 标注）
- `dev/pilot2_manifest.json` + `pilot2_predictions.jsonl`（已跑 pilot）
- `runs/20260805T112820Z|113444Z|130649Z/`（已跑评估 + predictions）
- `scripts/run_llm_benchmark.py` / `evaluate_extraction.py` / `prepare_annotations.py`
- `work/texts/`：100+ 篇全文 txt（含 task2_*、sc04_*、diamond/CFRP/SiC 相关）
- `audit/audit_worksheet.md`：40 篇人工盲审工作表（字段空白，未完成）

**S0-2A 完整审阅结论见 `docs/feasibility/S0-2_METADATA_REEXTRACTION_AUDIT.md`（Gate C=C2 PASS_WITH_EXTENSION）。**

## 2026-08-07 迁移记录（legacy runtime 迁入后新增）

- MIG-01: `tests/legacy_agent/test_builder_builds_real_corpus_for_sic` 与
  `test_build_corpus_api_endpoint` 依赖 RAG 索引就绪（raw_hit_count>0）；
  新仓库尚无索引，待数据/索引构建后恢复（POST_DEMO）。
- MIG-02: `test_web_bootstrap_has_no_implicit_mock_source` 单独运行通过，
  全量运行时受测试顺序/全局状态污染（旧仓库环境隐藏依赖），测试隔离待优化。
