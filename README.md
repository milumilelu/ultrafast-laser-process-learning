# Ultrafast Laser Process Learning Kernel

主计划 V2 的正式仓库（Brownfield 迁移内核）。

- 文档与决策：`docs/`（契约冻结见 `docs/contracts/CONTRACT_V2_FREEZE.md`）
- 包边界由 `lint-imports`（import-linter）强制

## Current milestone：Topic 2 Demo（课题二端到端展示版）

```text
Tag:  topic2-demo-v1.1（正式阶段展示冻结版；topic2-demo-v1 = R1-R16 首次全 PASS 的历史里程碑）
CFA:  Uncalibrated CFA（uncalibrated-cfa-v2.0），NOT_YET_CALIBRATED，无概率输出
```

### 演示命令（固定 Demo Scenario 01：SiC / depth_um / 固定 CSV / 5 篇 pilot / seed 42）

```bash
.venv\Scripts\python scripts\demo_t2_vertical_slice.py   # 端到端跑通（确定性）
.venv\Scripts\python scripts\demo_report.py              # 生成自包含 HTML 报告
# 浏览器打开 outputs\topic2_demo_report.html（10 步故事线 + 回溯）
```

演示场景与展示纪律：`docs/validation/DEMO_SCENARIO_01.md`；
Release Gate：`docs/validation/DEMO_RELEASE_CHECKLIST.md`（R1–R17 全 PASS）。

### 科学状态（如实声明）

```text
B1-25（dev set）：severe=0（无 Unknown→Mismatch 转换）——仅 diagnostic 表述，
                 不构成泛化性能声明。
旧 13 篇 holdout（v2 diagnostic）：H3/H5 两处确定性语义 bug 已修复（V2-1
                 依赖感知重建 / V2-2 RANGE≠POINT），H3 bug 3→0、H5 bug 5→0。
新 11 篇 unseen holdout（v2 independent）：H1/H2 PASS；H3/H5 未过（根因：
                 facet 聚合语义 / 表格提取 / review-sweep 文档语义，登记
                 artifacts/cfa_holdout/V2_INDEPENDENT_VALIDATION.md）。
结论：当前不声明 "CFA v2 已通过独立科学验证"；demo 展示只承诺
                 KNOWN/PARTIAL/UNKNOWN/MISMATCH + warnings + NOT_YET_CALIBRATED。
```

### 已知限制（详见 `docs/KNOWN_GAPS.md`，已按 RESOLVED / PARTIALLY_RESOLVED / POST_DEMO 重签）

- POST_DEMO：facet_summary 聚合语义（多条件取首报告）、表格提取 gap、
  review/sweep 条件选择、Calibrated CFA、Dynamic Trust、Open Discovery
  blind benchmark、Agent UI。
- PARTIALLY_RESOLVED：Material/Task metadata 覆盖（gold 缺口 2 处登记）。

## 当前包

```text
src/
├── process_contracts/        # 契约（TaskScope 等）
├── ultrafast_shared/         # 共享基础设施（units/config/db）
├── ultrafast_domain/         # 领域模型（leaf）
├── ultrafast_physics/        # 物理特征引擎 + Formula Registry（leaf）
├── ultrafast_ingestion/      # PDF 解析 → mention → candidate ledger → condition 编译
├── ultrafast_reconstructibility/  # M6 Source 侧依赖重建（五类未知区分）
├── ultrafast_interaction/    # M8 CanonicalInteractionState / Target readiness
├── ultrafast_cfa/            # M9 Uncalibrated CFA（五 facet，无概率）
├── ultrafast_e2p/            # 证据适用性/编译 → GovernedPriorArtifact
├── ultrafast_bo/             # 治理化 GP-UCB（vanilla / evidence-assisted）
├── ultrafast_knowledge/      # 知识治理（证据审核路径）
├── ultrafast_memory/         # 迁移自旧仓库（db/ids/config）
└── ultrafast_integrations/   # 存储/集成
demo/t2_slice/                # 垂直切片编排 + 文献资源解析（RF-2）
apps/topic2_backend/          # FastAPI（独立 repository 路径，非演示主链）
```

## 安装与验证

```bash
# 注意：系统 python 是 Windows Store 占位符，需用旧仓库 venv 的 python 建 venv：
# "C:\Users\RZF\Desktop\博士课题资料\ultrafast agent\.venv\Scripts\python.exe" -m venv .venv
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv\Scripts\python -c "import ultrafast_cfa, ultrafast_e2p, ultrafast_bo, ultrafast_ingestion, ultrafast_interaction, ultrafast_reconstructibility, ultrafast_physics"
.venv\Scripts\python -m pytest tests -q        # fast + pilot（111 pilot 需文献归档）
lint-imports
```

Release-scope 类型/风格检查（RF-8）：

```bash
.venv\Scripts\python -m mypy src/ultrafast_ingestion src/ultrafast_cfa src/ultrafast_interaction src/ultrafast_reconstructibility demo/t2_slice --ignore-missing-imports
.venv\Scripts\python -m ruff check src/ultrafast_ingestion src/ultrafast_cfa src/ultrafast_interaction src/ultrafast_reconstructibility src/ultrafast_physics src/ultrafast_e2p src/ultrafast_bo demo
```

依赖版本已按旧环境锁定（PyPI 直连在此网络环境会超时，见 docs/KNOWN_GAPS.md GAP-09/10）。
