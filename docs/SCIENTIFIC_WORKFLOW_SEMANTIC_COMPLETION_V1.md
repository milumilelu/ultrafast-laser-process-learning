# Scientific Workflow Semantic Completion V1 — 执行文件

> 状态：DRAFT — 待审查后冻结
> 日期：2026-08-08
> 基线：`main` @ `6a0e7b2`（含 Frontend V3 与 Backend Semantic Gates 16 tests）
> 核心理念：当前已跑通的是「给我机器参数 + 给我 Evidence + 给我 calibration observations，我能算到 ToolpathPlan」；本里程碑的目标是「给我一个科研任务，系统自己识别资源缺口、检索论文、LLM 精读、形成可信先验、校准物理模型、再规划路径」。

---

## 一、目标与唯一验收约束

本里程碑**不做**：

- 不继续 Frontend F4/F5 视觉美化
- 不重新造 LLM Reader（复用 `ScientificCorpusBuilder` + `ScientificAnalysisService`）
- 不新建第二套 workflow（`ScientificAnalysisJob` 不作为平行 orchestration）

**唯一验收约束（强制，高于一切 Gate）**：

> 验收只能通过**前端**进行：前端设置任务（含设备档案、数据范围、目标）→ 前端触发运行（分阶段 checkpoint）→ 前端输出验收结果（每个科学产物的数值与链路）。
> **测试期间不得手动接入任何中间过程**——禁止向 `task_spec` 注入 `evidence_ir` / `machine_profile` / `calibration_observations` / `empirical_kernel`，禁止绕过主链调用独立 scientific job 接口。

---

## 二、现状基线（已逐条核实，引用为证据）

| # | 断点 | 证据（file:line） |
|---|---|---|
| E1 | `equipment` 表只有 `equipment_id/laser_id/machine_id` 三列 | `packages/process_data/repository.py`；实跑 capability report 中 `actual_power_W/beam_radius_um/wavelength_nm` 恒 MISSING |
| E2 | capability 机器输入只来自 `task_spec.machine_profile/device_properties/process_parameters`，前端无录入界面 | `packages/scientific_computation/capability.py:93-95`；`TaskForm.tsx` |
| E3 | Agent 已有 EquipmentProfile schema v2（10 个 required 物理字段）与 API，V3 前端断开、主链不消费 | `src/ultrafast_app/api/routers/equipment.py:8-116` |
| E4 | `_agent_spot_diameter_um()` 读「当前激活设备」，非不可变 revision → 无法 replay | `apps/topic2_backend/application/service.py` |
| K1 | QueryPlan 生成后实际取证据仍为 evidence 表全量 + agent candidates（scope 级，非逐 KR） | `service.py:1164-1300`；`_evidence_for_scope` `service.py:1507-1552` |
| K2 | `document_parse / candidate_discovery / condition_reconstruction` 明确「暂未执行」 | `service.py:1244-1245` |
| K3 | 旧 RAG converter 仅五工艺参数，`laser_power_W` 等丢弃 | `src/ultrafast_knowledge/rag/evidence_converter.py:34,150` |
| K4 | Evidence validator 限定 `CORE_PARAMETER_NAMES` 五工艺参数 → 与 typed E2P drift | `packages/process_contracts/schemas.py:10,115,252` |
| K5 | LLM 精读服务存在但主链零调用 | `src/ultrafast_knowledge/corpus/builder.py:54`；`scientific_analysis/service.py`；`scientific_pipeline.py` |
| G1 | `LocalRemovalModelFactory.reconstructed` 静默 defaults（F_th=1.0, S=1.0, δ=1.0, α=0.02, thermal=0.0, radius=10μm） | `local_removal.py:131-155` |
| G2 | Planning `peak_fluence` 兜底 `threshold × 2` | `planning.py:88-92` |
| G3 | capability 无条件声明 F0/F1/F2，无 runnable 概念 | `capability.py:295-320` |
| G4 | 前端「继续」不传 stages → 后端全跑；Overview 用 artifact 存在性判断 Planning 就绪 | `service.py:237`；`OverviewSection.tsx:68-73` |
| G5 | `evaluate_observation` 只记 update_triggers intents，无真实闭环执行 | `service.py:2240-2328` |
| G6 | `ProcessCorrectionInterface.residual_model_ref=None`，无 corrected model 真实化 | `packages/scientific_computation/contracts.py:383-397` |
| G7 | E2P Core 的 Fusion / Uncertainty / Dynamic Trust 未接主链（prior 大量 `uncertainty: UNKNOWN`） | `packages/e2p/application/typed_prior_compiler.py` |
| B9 | B9 acceptance 注入 task_spec 后验证计算链 → 实为 vertical slice，且不符合前端 E2E 约束 | `tests/test_physics_to_planning_v1.py`（`_task()`） |

---

## 三、架构数据流覆盖矩阵（唯一验收对象）

下图即本里程碑唯一验收架构。每一行 = 一个节点；「P」列标注落地计划；验收只通过前端（见 §12）。

```text
TARGET TASK
  ├─ Geometry / Objective / Machine
  ▼
Scientific Capability Preflight
  ├─ Data State
  ├─ Physics Readiness
  └─ Missing Knowledge
  ▼
KnowledgeRequirement[]
  ▼
Existing Knowledge Coverage
  ▼
Scientific Knowledge Acquisition
  ├─ Requirement-driven Literature Retrieval
  ├─ PDF → ScientificDocument
  ├─ Deterministic + LLM Discovery
  ├─ CandidateLedger
  └─ Source Conditions → EvidenceIR
  ├─ Reconstructibility
  └─ E2P Core（Applicability/Quality · Fusion/Uncertainty · Dynamic Trust）
  ▼
PriorObjects（ParameterPrior / MechanismModelPrior / PlanningPrior）
  ▼
Scientific Computation（Physics Mapping · Parameter ID · Model Runtime）
  ▼
LocalRemovalModel → Stateful 2.5D Simulator → Virtual Laser Tool
  ▼
Process Learning（physics prediction / residual ML → corrected model）
  ▼
Toolpath Planner（Target Geometry + Machine Bounds）→ ToolpathPlan
  ▼
Predicted Morphology → Experiment → Measured Morphology
  ├─ Parameter Update
  ├─ Residual Model Update
  └─ E2P Trust Update → ↺
```

| 架构节点 | 现状（已核实） | 落地计划 | 前端验收点 |
|---|---|---|---|
| TARGET TASK（Geometry/Objective/Machine） | TaskForm draft → TaskScope ✓ | P1.2 拆 Dataset/Execution 双区 | 任务页显示两区选择 |
| Scientific Capability Preflight | `capability.py` ✓ 但 supported/runnable 不分 | P0.4 | Capability 页：runnable fidelities + blockers |
| Data State | `assess_data` → DataProfile/TargetPhysicsReadiness ✓ | — | Overview Data 卡 |
| Physics Readiness | `TargetCoordinateEvaluator` ✓ | — | Capability 派生物理状态 |
| Missing Knowledge | `recommended_requirements` ✓ | P3（四分类） | Capability Requirements 表 |
| KnowledgeRequirement[] | `analyze_knowledge_requirements` ✓ | — | Knowledge 页需求列表 |
| Existing Knowledge Coverage | `satisfy_requirements` 确定性覆盖 ✓ | — | 需求满足状态 |
| Requirement-driven Literature Retrieval | ❌ `_evidence_for_scope` 全量读 | P2.2 | Knowledge 页：逐 KR 检索事件 |
| PDF → ScientificDocument | ❌ document_parse 未执行 | P2.2/2.4 | 文献来源展示 |
| Deterministic + LLM Discovery | ❌ 服务存在未接入（K5） | P2.3 | LLM reading events（逐 KR） |
| CandidateLedger | ❌ | P2.4 | 候选账本 artifact |
| Source Conditions → EvidenceIR | ⚠️ 旧 Evidence 并集 | P2.1/2.4 | Evidence 列表（canonical roles） |
| Reconstructibility | 模块存在未接入 | P2.4 | Evidence Inspector tab |
| E2P Core：Applicability/Quality | ⚠️ 编译器未接 applicability refs | P2.5 | Prior 卡：applicability_refs |
| E2P Core：Fusion/Uncertainty | ⚠️ uncertainty 缺省 | P2.6 | Prior 卡：uncertainty 有来源 |
| E2P Core：Dynamic Trust | ❌ | P2.6 + P6 | Observation 后 trust 更新可见 |
| PriorObjects 三型 | ✓ typed prior 编译 | P2.5 上游打通 | Knowledge/Calibration Prior 视图 |
| Physics Mapping | ✓ `canonicalization.py` | — | Canonical 状态表 |
| Parameter ID | ✓ `identification.py` | P4 深化 | Calibration Fit/Identifiability |
| Model Runtime | ✓ mechanism registry + resolver | P4 | Registry 表 |
| LocalRemovalModel | ✓ 但 silent defaults | P0.2 | Model 卡（source=calibrated/prior，非 default） |
| Stateful 2.5D Simulator | ✓ F0-F2 | — | Simulation 指标（F4 UI 后置） |
| Virtual Laser Tool | ⚠️ simulator-in-the-loop（planning.py） | — | Planning 候选 |
| Process Learning（physics prediction / residual ML → corrected model） | ⚠️ `ProcessCorrectionInterface` residual=None（G6） | **P5** | 修正模型 artifact（residual 状态如实） |
| Toolpath Planner + Machine Bounds | ✓ 但 fallback（G2） | P0.3 | Planning 页候选 + 状态 |
| ToolpathPlan | ✓ 状态需重做 | P0.3 | Planning 卡：RECOMMENDED_EXECUTABLE / PROVISIONAL / BLOCKED |
| Predicted Morphology | ✓ simulation artifact | — | Simulation 数值（F4 UI） |
| Experiment → Measured Morphology | ⚠️ `evaluate_observation` intent-only（G5） | **P6** | Observation 录入 → 状态更新 |
| Parameter Update | ❌ | P6 | 重新标定可执行 |
| Residual Model Update | ❌ | P6 | residual 训练/更新接口 |
| E2P Trust Update | ❌ | P6 | trust 变化可见 |

---

## 四、P0 — Scientific Execution Gating（最高优先级）

- **P0.1** 前端 checkpoint 真停：`createOrContinueRun` 默认 stages 显式为 checkpoint 前缀；Normal「开始」只到 `assess_capability`；Developer Mode 才允许 Run all
- **P0.2** Research 模式禁 silent defaults：`LocalRemovalModelFactory` 加 `allow_provisional_defaults=False`（缺参抛 `BlockedError` + 缺参列表）；`planning.py` 删 `threshold×2` 兜底，`peak_fluence` 必须来自 canonical state 或显式参数
- **P0.3** `PlanStatus` 重做：`RECOMMENDED_EXECUTABLE / PROVISIONAL_SIMULATION_ONLY / BLOCKED / NOT_RUN`；探索模式需显式选择
- **P0.4** Capability 拆 `supported_fidelity`（算法能力）与 `runnable_fidelities`（当前任务可运行级别，逐 fidelity dependency + blocker）
- **P0.5** 前端 readiness 一律消费后端状态字段（删除 `if (plan) KNOWN` 逻辑）

验收：FLOW-B1/B2/B3（前端路径执行，见 §12）

## 五、P1 — Equipment Canonicalization

- **P1.1** contract 冻结：`EquipmentProfile / EquipmentProfileRevision / MachineProfileSnapshot / EquipmentIdentityMap`，每物理字段独立 verification（MEASURED / MANUFACTURER_SPEC / ESTIMATED / UNVERIFIED），schema 以 agent v2 为基线（`equipment.py:100-116`）
- **P1.2** Task 拆两概念：`DatasetScope.equipment_key`（历史数据来源）+ `ExecutionContext.equipment_profile_ref`（目标设备 revision）
- **P1.3** `create_application_run` 冻结 `MachineProfileSnapshot`（run 级 artifact），capability/canonicalization/calibration 只读 snapshot；删除 `_agent_spot_diameter_um` 读活配置
- **P1.4** 前端恢复设备管理（`/resources/equipment` 列表/详情/revisions；字段级验证状态）与 Task 双区选择；Capability 缺失输入直链设备档案

验收：EQUIP-B1/B2/B3

## 六、P2 — Requirement-driven Knowledge Chain（含 E2P Core 完整化）

- **P2.1** Evidence contract 去五参数限制：支持物理参数（F_th / incubation_S / delta_eff / …）与 canonical roles（THRESHOLD / FORMULA / MECHANISM_MODEL / MATERIAL_PROPERTY / PATH_STRATEGY）；旧 `CORE_PARAMETER_NAMES` 仅限 legacy 路径
- **P2.2** 逐 KR 真检索：`QueryPlan → ScientificCorpusBuilder`（RAG + in-paper context expansion）；`_evidence_for_scope` 退出 canonical 检索；`/e2p/evidence-candidates`（`rag_evidence_to_topic2`）仅 exploratory/legacy
- **P2.3** LLM 精读接入：`prepare_knowledge` 下 RequirementResolutionOperation 子操作 → `ScientificAnalysisService`（Map/Validate/Coverage/Reduce/Critic），**未配置 LLM 时显式 BLOCKED，不 mock**；state/events/artifacts 投影到当前 ApplicationRun
- **P2.4** `CandidateLedger → SourceConditions → EvidenceIR` 真实化（复用 `ScientificDocument / CandidateLedger / Condition Compiler / Reconstructibility`），替换「暂未执行」WARNING
- **P2.5** `compile_typed_priors` 接收 `ApplicabilityReport` refs（prior 携带 applicability_refs）
- **P2.6** E2P Core 完整化：EvidenceBelief → Fusion → Uncertainty（来自 applicability/belief，不再缺省 UNKNOWN）；Dynamic Trust 最小实现（trust update 由 P6 Observation 驱动）

验收：KNOW-B1..B5

## 七、P3 — Requirement Resolution Loop

- 逐 KR 循环：existing → retrieve → read → evaluate → satisfy；未满足 `↺ next source` 或按 stop reason 停止
- stop reason：`SATISFIED / PARTIALLY_SATISFIED / UNRESOLVED_NO_EVIDENCE / BUDGET_EXHAUSTED / BLOCKED_MISSING_SOURCE / CONFLICT_REQUIRES_REVIEW`
- ScientificNeed 四分类：`RESOURCE_INPUT → P1 设备通道` / `SCIENTIFIC_KNOWLEDGE → RAG+LLM` / `CALIBRATION_OBSERVATION → 实验` / `DATA_REQUIREMENT → 数据`；仅 SCIENTIFIC_KNOWLEDGE 进 RAG

## 八、P4 — Physics Calibration Gate（深化）

- Registry 由 active mechanism dependency 驱动任意参数；不可辨识 → abstain / PRIOR / MISSING（沿用机制注册表 + resolver）
- calibration 输入仅来自：设备 snapshot 测量 + 目标观测 + ParameterPrior + MechanismModelPrior

## 九、P5 — Process Learning 真实化（新）

- `ProcessCorrectionInterface` 落地：physics prediction（simulator 输出）为基线；residual-capable 接口真实可用（V1 至少：residual 模型可训练/更新或如实 BLOCKED，禁止 `residual_model_ref=None` 冒充可用）
- corrected model 作为 planning 的输入可选链（physics-only 为默认，residual 存在时标注）
- 验收：前端 Process Learning 卡展示 physics prediction 与 residual 状态（真实字段，非占位）

## 十、P6 — Observation 闭环（新）

- `evaluate_observation` 从 intent-only 升级为真实闭环：录入 Measured Morphology 后依次触发：
  1. **Parameter Update**：追加观测 → 重新标定（可执行路径）
  2. **Residual Model Update**：residual 训练/增量更新（或如实 BLOCKED）
  3. **E2P Trust Update**：Dynamic Trust 最小实现（trust 状态变化可见）
- 观测来源标记（experimental / synthetic）严格保留；synthetic 不得触发独立验证语义
- 验收：前端 Observation 录入后三更新状态可见（P6 随 P0/P5 落地）

## 十一、P7 — Simulation / Planning UI

- 满足 required state READY 且 machine bounds resolved 才展示 executable 结果；F4/F5 视觉在 P0-P2 通过后启动

---

## 十二、验收方式（唯一：前端 E2E）

**固定场景 `SCENARIO_E2E_V1`**（全部通过前端完成，禁止任何中间注入）：

```text
Task：SiC · 浅 2.5D 目标（rectangular pocket）· depth 目标
Dataset scope：EQ-REAL（真实加工数据 real_machining_data）
Execution equipment：前端创建设备档案（wavelength / actual power / spot radius，
                     字段级 verification）→ 选为 execution revision
```

**执行路径（前端操作，每步产出后端 artifact 且页面可核对数值）**：

```text
前端建任务 → 前端建设备档案 → Phase A 运行到 Capability（STOP）
→ 补设备缺失输入（若能力报告列出）→ Phase B 知识计划（KR 确认）
→ Phase C 知识获取（逐 KR：检索事件 → 选论文 → LLM reading events →
  CandidateLedger → SourceConditions → EvidenceIR → Applicability）
→ Phase D 标定（Registry / Identifiability / Calibration）
→ Phase E 仿真（LocalRemovalModel → F0/F1/F2 → 指标）
→ Phase F 规划（候选 → ToolpathPlan，status=RECOMMENDED_EXECUTABLE）
→ 输出验收：各页面数值 ↔ 后端 artifact 逐项一致（UI value == artifact value）
```

**约束**：

1. 不得向 `task_spec` 注入 `evidence_ir / machine_profile / calibration_observations / empirical_kernel`
2. 不得调用独立 scientific job 接口绕过主链
3. 中途必须真实经过每一个架构节点（§3 矩阵），缺任一步即 FAIL
4. LLM 为前置条件：未配置时 Phase C 显式 BLOCKED 并如实报告，不得用 mock 冒充
5. 执行方式：Playwright 自动化（新增 devDependency）或手动按清单操作；验收记录 = 每页面数值 + artifact id 对照表

**Gates**（在场景内判定）：

- **FLOW-B1**「开始」只执行到 `assess_capability`；**FLOW-B2** 缺 actual power 时 `calibrate_physics=BLOCKED`、`plan_process=NOT_RUN`；**FLOW-B3** 无显式探索模式时不得产生 RECOMMENDED_EXECUTABLE
- **EQUIP-B1** 设备档案含波长/实际功率/光斑/频率与速度边界且字段级验证；**EQUIP-B2** Task 绑 revision、Run 冻结 snapshot 且重放一致；**EQUIP-B3** `EQ-REAL` 与 `EQP-xxx` 明确分离
- **KNOW-B1** 每个 KR 的 QueryPlan 被真实检索消费（事件级）；**KNOW-B2** ≥1 真实 paper 走完 RAG→CorpusPack→LLM reading；**KNOW-B3** 产出 CandidateLedger+SourceCondition+EvidenceIR（非 RAG chunk→range 直通）；**KNOW-B4** ApplicabilityReport ref 传入 E2P compiler；**KNOW-B5** Fth 需求仅 THRESHOLD 证据可满足
- **OBS-B1** 录入 Measured Morphology 后 Parameter Update 可执行（重标定）；**OBS-B2** Residual 更新如实（训练或 BLOCKED）；**OBS-B3** E2P Trust 状态变化可见
- **E2E-B1/B2/B3** 场景无注入、机器输入来自设备解析、全链真实走通 → 通过后 B9 改名「Vertical Slice Acceptance」，本场景才叫 **Full Physics-to-Planning Scientific Workflow Acceptance**

---

## 十三、保留 / 不动的资产

计算内核（identification / simulator / planning / canonicalization）、E2P typed prior 编译器与 conflict 逻辑、机制注册表 + 参数 resolver、前端 V3 架构（artifact-driven / TanStack Query / 状态命名空间 / Workspace）、Git 历史。

## 十四、DoD

1. 前端 E2E 场景（§12）全链真实走通，各节点数值与后端 artifact 一致
2. FLOW / EQUIP / KNOW / OBS / E2E 全部 Gate PASS
3. 无任何中间注入路径参与验收
4. 全量回归 `pytest tests -q`（当前 495 passed）+ lint-imports + ruff + 相关 mypy 不降级
5. 前端不再出现「缺 actual power 但 Planning 就绪」矛盾态

## 十五、执行顺序

```text
1. P0（Gating）        —— 阻断矛盾态，建立 checkpoint 真停
2. P1（Equipment）     —— snapshot 冻结，资源输入真实化
3. P2（Knowledge）     —— 知识链真实接入（LLM 未配置显式 BLOCKED）
4. P5（Process Learning）+ P6（Observation 闭环）
5. P3（Resolution Loop）、P4（Calibration 深化）
6. P7（Simulation/Planning UI）
7. 前端 E2E 验收场景落地 → 全量验收
```
