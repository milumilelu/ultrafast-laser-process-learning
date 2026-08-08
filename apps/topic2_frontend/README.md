# Physics-to-Planning V3 Scientific Workbench

> Frontend is an artifact-driven scientific workbench, not an independent workflow
> implementation. There is exactly one scientific truth: the backend ApplicationRun
> state and artifacts.

## 三条硬规则

1. **Frontend is an artifact-driven scientific workbench, not an independent workflow implementation.**
2. **There is exactly one scientific truth: backend ApplicationRun state and artifacts.**
3. **UI navigation follows Task → Capability → Knowledge → Calibration → Simulation → Planning, not legacy Identification → Modeling → Optimization.**

## 技术栈

- React 18 + TypeScript + Vite
- React Router 7（`/workspace` 工作台 + 六个一级入口）
- TanStack Query（server state；前端不维护业务真相 store）
- Zustand（仅 UI state：Developer Mode 等）
- Vitest + Testing Library

## 目录结构

```text
src/
├── app/          路由 / providers / query client
├── api/          薄 HTTP 层（DTO 校验、错误归一化；无科学逻辑）
├── domain/       状态命名空间 + 纯展示映射（view-model mappers）
├── features/
│   ├── workspace/     Overview + 续跑流程（create/continue 同 run）
│   ├── capability/    Execution Capability Graph + Input Resolver
│   ├── knowledge/     Requirement → QueryPlan → Evidence → Prior lineage
│   ├── calibration/   动态参数 Registry / Fit / Identifiability
│   └── runs/          Run Inspector（Flow / Artifacts / Events）
├── components/    layout / ui / scientific 展示组件
└── stores/        仅 Draft State（taskDrafts）与 UI State（developerMode）
```

## 状态命名空间（domain/status.ts）

三个严格分离的命名空间，类型系统禁止混用：

- `ExecutionStatus`: NOT_RUN / RUNNING / READY / BLOCKED / FAILED（执行能力，绝无 UNKNOWN）
- `ScientificStatus`: KNOWN / PARTIAL / UNKNOWN / MISMATCH（科学知识状态）
- `ParameterStatus`: MEASURED / DERIVED / PRIOR_ONLY / CALIBRATED / PROVISIONAL / NOT_IDENTIFIABLE / MISSING

## 开发

```bash
npm install
npm run dev        # 端口 5173，/api/v1 → 127.0.0.1:8010
npm test           # vitest run
npm run typecheck
npm run build
```

## 当前迭代状态（F0–F3）

| Phase | 内容 | 状态 |
|---|---|---|
| F0 | App shell / router / API client / server state / status 系统 / Developer Mode | DONE |
| F1 | Workspace + Overview（四卡 + Next Action）+ Capability（依赖图 / Input Resolver） | DONE |
| F2 | Knowledge（Requirement → QueryPlan → Evidence → Prior lineage + Inspector） | DONE |
| F3 | Calibration（动态参数 Registry / Fit / Identifiability） | DONE |
| F4 | Simulation 可视化（surface / height map / cross section / difference map） | 下一迭代 |
| F5 | Planning（candidate paths / simulator score / recommended ToolpathPlan） | 下一迭代 |
| F6 | Run Inspector（Flow / Artifacts / Events / Compare） | Flow/Artifacts/Events DONE，Compare 下一迭代 |
| F7 | Polish | 下一迭代 |

## 前端验收 Gate（FE-1..FE-10 对应测试）

- FE-2（前端无科学逻辑）→ `src/domain/__tests__/fe2_no_science.test.ts` 静态扫描
- FE-3（状态不混用）→ `src/domain/__tests__/status.test.ts`
- FE-4（blocker 依赖链）→ `src/domain/__tests__/capability.test.ts`
- FE-5（Knowledge lineage）→ `src/domain/__tests__/knowledge.test.ts`
- FE-6（动态参数数量）→ `src/domain/__tests__/calibration.test.ts` + `CalibrationSection.test.tsx`
- FE-10（resume 不创建第二个 run）→ `runFlow.test.ts` + `client.test.ts`
