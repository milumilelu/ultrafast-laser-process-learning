# Physics-to-Planning V1 最终验收

> 验收日期：2026-08-08  
> 验收范围：任务说明书 Gate B0–B9、F1–F6。

## 结论

```text
Overall: PASS
Backend gates:  B0–B9 ALL PASS
Frontend gates: F1–F6 ALL PASS
Backend regression: 479 passed, 111 deselected
Frontend regression: 92 passed
Import boundaries: 12 kept, 0 broken
```

## 主链交付

```text
Task
→ ScientificCapabilityReport
→ KnowledgeRequirementSet
→ RetrievalQueryPlan / EvidenceSet
→ ParameterPrior / MechanismModelPrior / PlanningPreferencePrior
→ CalibrationResult / IdentifiabilityReport
→ LocalRemovalModel
→ MorphologySimulationResult
→ ToolpathPlan
```

ApplicationRun 使用十个 canonical stages：

```text
prepare_task → assess_capability → assess_data → baseline_learning
→ analyze_knowledge_requirements → prepare_knowledge → satisfy_requirements
→ calibrate_physics → establish_process_model → plan_process
```

分段 checkpoint 在同一 `application_run_id` 上续跑；前端只读取后端 artifacts，
不重算 Capability、E2P prior、物理标定、形貌仿真或路径规划。

## Gate 结果

| Gate | 结果 | 核心证据 |
|---|---|---|
| B0–B9 | PASS | 独立验收脚本逐 Gate 检查 typed contracts、能力预检、证据/先验、参数辨识、F0–F2 仿真、去除模型、路径规划和完整 lineage |
| F1 | PASS | Capability、Knowledge、Calibration、Simulation、Planning 五个 artifact 工作区均直接消费后端 payload |
| F2 | PASS | `MISSING`、`IDENTIFIABLE`、`WEAKLY_IDENTIFIABLE`、`NOT_IDENTIFIABLE` 等科学状态有显式语义与视觉区分 |
| F3 | PASS | canonical stage 树、checkpoint 续跑、同一 run ID、新事件游标和同 run artifact 刷新均有回归测试 |
| F4 | PASS | UI 明示 geometry 是 soft transfer prior，不是 hard filter；文献先验、目标域拟合和机器/数据输入分区展示 |
| F5 | PASS | 审计 DAG 仅由真实 events 构造，展示十阶段及 artifact lineage |
| F6 | PASS | Developer Mode 展示 artifact ID、schema version、input refs、provenance、reason codes 与 raw payload |

## 自动化验证

```powershell
.venv\Scripts\python.exe scripts\run_topic2_acceptance.py
# Overall PASS; B0–B9 ALL PASS

.venv\Scripts\python.exe -m pytest -q
# 479 passed, 111 deselected

.venv\Scripts\lint-imports.exe --no-cache
# 12 kept, 0 broken

.venv\Scripts\python.exe -m mypy packages\scientific_computation `
  packages\scientific_retrieval packages\process_contracts\prior_objects.py `
  packages\e2p\domain\prior_objects.py `
  packages\e2p\application\typed_prior_compiler.py `
  --ignore-missing-imports --explicit-package-bases
# Success: no issues found in 13 source files

cd apps\topic2_frontend
npm test -- --run
# 13 files, 92 tests passed
npm run typecheck
# PASS
npm run build
# PASS
```

新增科学模块、E2P typed-prior 编译器、验收脚本和相应测试通过 Ruff；主服务新增代码的
import/无效忽略标记检查通过。主服务既有的宽异常捕获策略不在本次重构范围内。

## 真实前后端联调证据

使用隔离临时数据库，通过真实 FastAPI 与生产构建前端完成浏览器 E2E；不是 mock：

| 项目 | 后端 artifact 值 | UI 值 |
|---|---:|---:|
| ApplicationRun | `app-04934cb4a5d34d64961ba9f422bc707f` | 同一 run |
| Capability | `PARTIAL` | `PARTIAL` |
| 标定 RMSE | `4.883708861602826` | `4.884` |
| thermal diffusivity | `estimate=null` | `当前数据不可辨识` |
| 仿真 fidelity | `F2_DEFOCUS_RECURSION` | `F2_DEFOCUS_RECURSION` |
| 形貌 RMSE | `3.7685320215608495` | `3.769` |
| 路径族 | `CROSS_HATCH` | `CROSS_HATCH` |
| 加工时间 | `0.01015` | `0.01` |

联调生成并在 Developer Mode 核对：

- `MorphologySimulationResult-9ee75f4480886c20`
- `ToolpathPlan-ce368f408dd09a45`
- 十个 canonical stage 的实际事件与 artifact refs
- schema version、provenance、reason codes 和 raw payload

## 科学披露

- 验收观测明确标记为 `SYNTHETIC_TEST_FIXTURE`，不构成真实实验验证。
- 当前数据只能支持 effective calibration；thermal diffusivity 不可辨识时保持空值，未伪造估计。
- `CalibrationResult.validation_data_refs` 为空；拟合数据未冒充独立验证集。
- 几何相似性只生成 soft planning preference，未改写机器硬边界。
- Uncalibrated CFA 仍为 `NOT_YET_CALIBRATED`，不输出 transfer probability。
- F0 仅为 deterministic baseline；主链规划采用 F2 状态递推模拟。
- 运行中仅出现 Starlette 弃用提示和 sklearn 收敛告警；均未导致 Gate 或测试失败。
- 一次全量回归中的 legacy web-bootstrap 测试遇到瞬时 SQLite `database is locked`；该测试随即
  单独复跑通过，随后完整套件再次运行并以 479 passed 结束。未通过隐藏失败来签发验收。
