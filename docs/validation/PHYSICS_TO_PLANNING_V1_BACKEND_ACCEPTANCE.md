# Physics-to-Planning V1 独立后端验收

> 验收日期：2026-08-08  
> 验收范围：任务说明书 Gate B0–B9；不包含后续前端集成 Gate F1–F6。

## 结论

```text
Overall: PASS
B0–B9:  ALL PASS
Full regression: 479 passed, 111 deselected
Import boundaries: 12 kept, 0 broken
```

## 独立验收命令

```powershell
.venv\Scripts\python.exe scripts\run_topic2_acceptance.py
```

该命令通过真实 FastAPI `POST /api/v1/application-runs` 创建隔离的
ApplicationRun，检查幂等性、十阶段主链、typed artifacts 和完整 lineage。
机器、数据库和 artifact 目录均在临时目录中，不依赖 Agent、LLM 或网络。

机器可读报告生成于：

```text
outputs/physics_to_planning_v1_backend_acceptance.json
```

## Gate 结果

| Gate | 结果 | 核心证据 |
|---|---|---|
| B0 | PASS | 健康检查、ApplicationRun 幂等、十阶段完成、旧 Demo/replay 回归通过 |
| B1 | PASS | 规定的 typed contract 均有 schema version、enum、unit、input refs |
| B2 | PASS | Capability 独立输出 available/missing/identifiability/requirements |
| B3 | PASS | RetrievalQueryPlan 明确 `geometry_is_hard_filter=false` |
| B4 | PASS | EvidenceIR 可编译 Parameter/Mechanism/Planning typed priors；冲突分开保存 |
| B5 | PASS | 合成已知参数可恢复；terminal depth 不辨识 thermal diffusivity；prior refs 保留 |
| B6 | PASS | F0 固定 kernel、F1 incubation、F2 defocus recursion 均有确定性测试 |
| B7 | PASS | EMPIRICAL/RECONSTRUCTED/HYBRID 输出同一 LocalRemovalModel contract |
| B8 | PASS | RASTER/CROSS_HATCH 候选由 morphology error + machining time 选择 |
| B9 | PASS | Capability→Requirement→Evidence→Prior→Calibration→Model→Simulation→Plan 全链 artifact refs 存在 |

## 自动化验证

```powershell
.venv\Scripts\python.exe -m pytest tests\test_physics_to_planning_v1.py -q
# 16 passed

.venv\Scripts\python.exe -m pytest tests -q
# 479 passed, 111 deselected

.venv\Scripts\lint-imports.exe --no-cache
# 12 kept, 0 broken

.venv\Scripts\python.exe -m mypy packages\scientific_computation `
  packages\scientific_retrieval packages\process_contracts\prior_objects.py `
  packages\e2p\domain\prior_objects.py `
  packages\e2p\application\typed_prior_compiler.py `
  --ignore-missing-imports --explicit-package-bases
# Success: no issues found in 13 source files
```

## 科学披露

- 验收中的反演观测明确标记为 `SYNTHETIC_TEST_FIXTURE`，不是实验验证。
- 当前真实 CSV 只支持 effective calibration；不声称辨识真实 thermal diffusivity。
- `CalibrationResult.validation_data_refs` 为空；拟合数据没有被伪装成独立验证集。
- 文献 range 只产生软 planning preference，不转为机器硬边界。
- Uncalibrated CFA 仍为 `NOT_YET_CALIBRATED`，不输出 transfer probability。
- F0 是 deterministic baseline；新主链规划使用 F2 状态递推模拟。

## 前端集成状态

本后端 Gate 通过后已完成前端 F1–F6 集成。前端只读取并展示后端 artifacts，未重新实现
E2P、物理计算、Requirement、Simulation 或 ToolpathPlan 组合逻辑。完整结果见
`docs/validation/PHYSICS_TO_PLANNING_V1_FINAL_ACCEPTANCE.md`。
