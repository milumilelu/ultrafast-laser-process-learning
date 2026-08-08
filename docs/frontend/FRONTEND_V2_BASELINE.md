# Frontend V2 Baseline（UI-0 冻结基线）

> 状态：FROZEN（topic2-demo-v1.1）
> 冻结提交：`9e31a46` / `topic2-demo-v1`（及 `d634ef7`、`629f24c` release hardening）
> 本文记录 V2 重构开始前的前端/后端契约与行为基线，用于 UI-0 冻结与回归对照。

---

## 1. 基线路由清单（重构前）

| 路由 | 页面 | 用途 |
|---|---|---|
| `/` | HomePage | 首页/概览 |
| `/task` | TaskPage | 工艺任务（Task Context 编辑） |
| `/identification` | IdentificationPage | 参数辨识 V2（raw/physics/hybrid） |
| `/modeling` | ModelingPage | 工艺建模（E2P Policy → 训练比较 → 人工覆盖） |
| `/optimization` | OptimizationPage | 工艺优化（GP-UCB Vanilla / E2P prior） |
| `/database` | DatabasePage | 工艺数据库（实验数据管理） |
| `/runs` | RunsPage | 运行记录 |

## 2. 基线 Store 契约

### 2.1 taskContextStore（persist: `topic2-task-context`）
- `context: TaskContextState`：taskContextId / version（正式修改必须 +1）/ materialId / materialGrade / laserType / equipmentId（Agent 设备档案）/ datasetEquipmentId（Topic2 实验设备）/ processType / processParams / objective / targetMetrics / deviceProperties / datasetId / selectedModelId / createdAt / updatedAt
- `update(patch)`：自动 `version += 1`
- 兼容迁移 `migrateLegacyContext`：geometryType → processType；targetMetrics → objective；equipmentId 前缀 `EQ-` → datasetEquipmentId

### 2.2 scienceStore（非持久）
- modelPolicy / training / optimization / evidence（EvidenceCompileResult）
- ragEvidence + ragEvidenceMeta（RAG 检索候选）
- scientificPack（CorpusPack → KnowledgePack → 验证）
- analysisJob + analysisJobPolling（异步科学分析 Job）
- experiments / dataProfile（当前 scope）
- recentRuns
- selectedModelId / selectionMode（system | manual）

### 2.3 agentStore（非持久）
- status（idle/thinking/calling_tool/waiting_backend/completed/needs_confirmation/degraded/error）
- sessionId / degraded / messages / proposals（AgentProposal: update_task|select_model|run_modeling|run_optimization|use_evidence）
- 流式：startAssistantMessage / appendAssistantContent / finishAssistantMessage
- 幂等键：client_message_id（stream 中断 fallback 防重复执行）

### 2.4 pageContextStore
- page / activeRunId / activeModelId / quickActions

## 3. 基线 API 契约（前端 client）

### 3.1 topic2Api（`/api/v1`）
health / materials / equipment / experiments / statistics / scope-capability / getParameterIdentification / compileEvidence / modelPolicy / trainModels / models / getModel / recommend / getOptimization / listRuns / getRun / saveTaskContext

### 3.2 agentApi（`/agent-api`，同源代理）
health / llmConfig / llmProviders / saveLlmConfig / saveLlmApiKey / testLlm / evidenceCandidates / buildCorpus / analyzeCorpus / createAnalysisJob / getAnalysisJob / listAnalysisRuns / validateKnowledge / runIdentificationV2 / createSession / chat / streamChat（NDJSON）/ listEquipmentProfiles / getEquipmentProfile / createEquipmentProfile / activateEquipmentProfile / machineBounds / profileMachineBounds

### 3.3 关键响应形状
- `OptimizationResult`：run_id / recommendation_id / recommended_parameters / vanilla_recommended_parameters / recommendation_changed_by_evidence / prediction{mean,std} / acquisition{normalized_ucb,log_prior,lambda_t,score} / machine_bounds / prior_spec / governed_prior_artifact
- `ModelTrainingResult`：run_id / model_id / selected_model / validation_metrics / comparison / cv_strategy
- `EvidenceCompileResult`：version / candidates / accepted / rejected / applicability_results / prior_spec

## 4. 基线后端端点（Topic2 Backend `apps/topic2_backend`）

- `GET /api/v1/health | /materials | /equipment | /scope-capability | /experiments | /models | /database/statistics | /runs | /runs/{id}`
- `POST /api/v1/experiments/import | /parameter-identification/run | /models/train | /models/evaluate | /e2p/evidence/compile | /e2p/prepare | /e2p/model-policy | /optimization/recommend | /process-observations | /process-workflows/commands`
- `PUT /api/v1/experiments/{id} | /task-contexts/{id}/versions/{v}`
- `GET /api/v1/parameter-identification/{run_id} | /optimization/{run_id} | /e2p/runs/{run_id} | /task-contexts/{id} | /process-observations | /process-workflows/{workflow_id}`
- 同源代理：`/agent-api/{path:path}` → AGENT_PROXY_TARGET（默认 `http://127.0.0.1:8011`）
- 静态托管：`apps/topic2_frontend/dist`

## 5. 基线行为事实（回归对照）

1. Agent 为增强层：离线只降级侧栏，不阻塞 Task / Identification / Modeling / Optimization / Audit。
2. 正式科学结果全部来自后端；前端不实现 Physics / CFA / Prior / BO 算法。
3. GovernedPriorArtifact 只由后端 `e2p_prepare` 签发（review 实时校验，fails closed）；前端拿到 artifact 才能跑 evidence-assisted BO，否则 Vanilla。
4. 未取得 governed artifact 时 OptimizationPage 显示 Vanilla 结果，但响应含 `vanilla_recommended_parameters` 对照。
5. Task Context 每次正式修改 version+1；Agent 始终绑定 id+version。
6. 设备光学/材料属性只从设备档案读取（`spot_definition === '1/e2'` 才推导半径），Scientific/RAG 输出不直接写入设备档案。
7. 参数辨识 V2（agentApi.runIdentificationV2）：raw/physics/hybrid + 双排名 + feature_build（unavailable 如实显示）。
8. 旧版 ScientificAnalysisProgress 为专用模型（仅 agent 分析 Job），无通用 WorkflowEvent。
9. 未知状态（UNKNOWN/UNVERIFIED/BLOCKED）在现有 UI 中以灰色/黄色展示，无概率化渲染；CFA 无概率字段。

## 6. 已冻结科学语义（不改动）

- M6–M9（Reconstructibility / Target Readiness / Canonicalization / Uncalibrated CFA）语义与 `docs/contracts/*` 一致。
- E2P：compile_evidence → prior_spec → GovernedPriorArtifact（repository_verified + 实时 approval 复核）。
- BO：GP-UCB + soft prior；`recommend_with_soft_prior` 输出 vanilla 对照点。
- 前端禁止复制 scientific algorithms（`ultrafast_physics` 等绝不移入浏览器）。

## 7. 已知缺口（V2 需补齐，见 TOPIC2_FRONTEND_V2_DEVELOPMENT_TASK.md）

- 无 `docs/frontend/` 目录（本文为起点）。
- 无 Application Run API / WorkflowEvent / Artifact Query API（BE-1..BE-5 建议新增）。
- Agent 为固定右侧 380px 面板，无 Drawer / Activity Timeline / Audit References 分栏。
- 无 `/application`、`/evidence`、`/demo`、`/resources/*` 路由。
- Vanilla / Evidence-assisted 对照由单接口内嵌，无并列展示端点。
