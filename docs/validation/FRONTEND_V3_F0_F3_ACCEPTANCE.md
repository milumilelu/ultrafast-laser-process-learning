# Frontend V3 验收（F0–F3 迭代）

> 验收日期：2026-08-08
> 迭代范围：任务说明书「删除旧前端、从零建立新前端」的 F0–F3；F4–F7 为下一迭代。
> 分支：`feat/frontend-v3-scientific-workbench`（基线 `main` @ `409d92b`）

## 结论

```text
Overall: PASS (F0–F3)
Frontend tests: 56 passed (10 files)
Typecheck: PASS
Build: PASS
Live API smoke: PASS (canonical 10-stage run + checkpoint resume + artifact shapes)
```

## 三条硬规则落地

1. **Frontend is an artifact-driven scientific workbench, not an independent workflow
   implementation.** — 全部科学数据来自 `useRunArtifacts`（backend artifacts）；无任何
   客户端科学计算（FE-2 静态扫描测试通过）。
2. **There is exactly one scientific truth: backend ApplicationRun state and artifacts.** —
   前端只有 server state（TanStack Query）+ UI state + Draft state（taskDrafts）。
3. **UI navigation follows Task → Capability → Knowledge → Calibration → Simulation →
   Planning** — 旧 Identification/Modeling/Optimization 路由已删除。

## 删除内容

- `src/pages/*`、`src/components/*`、`src/stores/*`、`src/lib/*` 旧业务层全部删除（无
  legacy/ 目录，Git 历史保留）。
- 旧 API 模块（topic2.ts / application.ts / agent.ts / types.ts）删除；仅保留
  `config.ts`（API base URL）并适配。

## 新结构

```text
src/
├── app/          router / providers / queryClient
├── api/          client.ts + runs/datasets/tasks（薄 HTTP 层）
├── domain/       status（三命名空间）/ stages / artifact / capability / knowledge / calibration
├── features/     workspace / capability / knowledge / calibration / runs
├── components/   layout / ui / scientific
└── stores/       ui.ts（developerMode）+ taskDrafts.ts（Draft State）
```

## 新增能力（对照任务说明书章节）

| 章节 | 实现 |
|---|---|
| §三 / §四 | 六入口导航 + Workspace 左侧为真实执行状态机的 workflow rail |
| §五 | Global Context Bar（Task/Material/Process/Target/Machine/Run + Research/Developer Mode） |
| §六 | Overview：目标 + 四张主卡（Capability/Knowledge/Physical Model/Planning）+ Recommended Next Action |
| §七-§九 | Capability：Execution Capability Graph（依赖传播，blocker 显示缺哪些输入）、Input Resolver（来源分类）、Identifiability、Requirements |
| §十-§十一 | Knowledge：Requirement 为中心 + QueryPlan（geometry hard filter 显式 NO）+ Evidence→Prior lineage + 5-tab Inspector |
| §十二-§十三 | Calibration：动态参数 Registry（数量由后端产物决定）、Fit（含 in-sample 声明）、Identifiability（NOT_IDENTIFIABLE 显示「当前数据不可辨识」） |
| §二十二 | Run Inspector：Flow（真实 events DAG）/ Artifacts / Events；Compare 下一迭代 |
| §三十二 | 「继续」为主控制：首次 createRun，之后 continueRun 同一 run（FE-10） |
| §三十八 FE-2 | `fe2_no_science.test.ts` 全仓扫描禁止客户端科学函数 |

## Live API 冒烟验证（真实 FastAPI，端口 8012，非 mock）

- POST `/application-runs`（research + task_spec）→ `physics-to-planning-application-v1`，
  十 canonical stages 全部 completed。
- 两段式 checkpoint：先跑 GAP 阶段，再 `continue` 剩余阶段 → 同 run、10 stages、
  events sequence 1..79 单调。
- GET `/artifacts/{id}` 返回 `{artifact_id, artifact_type, content:<snapshot>}` 嵌套结构；
  前端 `getArtifact` 按该真实契约解包（fixture 测试固化）。
- `/materials`、`/equipment`、`/experiments` 返回 `{items: [...]}` 包装；前端已按真实
  契约解包。
- ScientificCapabilityReport / PriorObjectSet / CalibrationResult / IdentifiabilityReport /
  LocalRemovalModel / MorphologySimulationResult / ToolpathPlan 的 content 字段与前端
  view-mapper 逐项核对一致。

## 与旧实现的主要契约差异（前端视角）

1. `GET /api/v1/artifacts/{id}` 返回嵌套 envelope（`content.content` 才是 payload）。
2. 数据集类端点返回 `{items: [...]}`。
3. 任务上下文仅 Draft State（localStorage），提交时写入 task_spec。

## 未实现（下一迭代 F4–F7，不阻塞本次交付）

- Simulation 四种可视化（3D / height map / difference map / cross section）
- Planning 页面（后端 ToolpathPlan artifact 已产出，前端直接消费）
- Run Compare
- 全局文献库 / Observation 闭环 UI
