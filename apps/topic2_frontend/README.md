# Topic2 Web Frontend — Human-Agent-Scientific Workflow

面向超快激光加工工艺智能规划与设计的 Web 工作台（课题二科学计算平台 + 超快激光 Agent 智能交互层）。

> **UI 定义任务 → Agent 理解与编排 → Topic2 Backend 执行确定性科学计算 → 结果回到界面与 Agent → 人工决策。**

## 技术栈

- React 18 + TypeScript + Vite
- React Router（一级导航：首页 / 工艺任务 / 参数辨识 / 工艺建模 / 工艺优化 / 工艺数据库 / 运行记录）
- Zustand（TaskContext / PageContext / Agent 会话 / 科学结果独立状态）
- ECharts（参数重要性图表）
- Vitest + Testing Library（单元 / 组件测试）

## 目录结构

```text
src/
  api/            # API Adapter 层（topic2 / agent），业务组件禁止直接 fetch
  components/     # TaskContextBar / AgentSidebar / ProposalCard / 图表 / EvidencePanel / RunTracePanel …
  pages/          # 七个一级页面
  stores/         # taskContext(版本化) / pageContext / agent / science
  lib/            # canonical ID、格式化、DataProfile 计数、scope 映射、Proposal 应用
  config.ts       # VITE_ACCEPTANCE_MODE / VITE_TOPIC2_API_URL / VITE_AGENT_API_URL
```

## 启动

```bash
# 1. 启动 Topic2 Backend（端口 8010，包含 API 与静态前端）
cd <repo-root>
PYTHONPATH=. python -m uvicorn apps.topic2_backend.main:app --host 127.0.0.1 --port 8010

# 2.（可选）启动 Agent 服务（端口 8011）
cd ultrafast_laser_memory
.venv\Scripts\python -m uvicorn ultrafast_app.api.main:app --host 127.0.0.1 --port 8011

# 3. 前端开发模式（Vite，端口 5173，/api/v1 与 /agent-api 已配置代理）
cd apps/topic2_frontend
npm install
npm run dev

# 4. 生产构建（构建后由 Topic2 Backend 直接托管于 http://127.0.0.1:8010/）
npm run build
```

## 验收模式

```bash
npm run build -- --mode acceptance   # VITE_ACCEPTANCE_MODE=true
```

或提供环境变量：`VITE_ACCEPTANCE_MODE=true`。验收模式固定正式 Backend、隐藏实验性/调试入口，Agent 故障不影响课题二主流程。

## 配置

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `VITE_TOPIC2_API_URL` | `/api/v1`（同源代理 / 后端托管） | Topic2 Backend 基地址 |
| `VITE_AGENT_API_URL` | `/agent-api`（Vite 代理 → 8011） | Agent 服务基地址 |
| `VITE_ACCEPTANCE_MODE` | `false` | 验收模式开关 |

## 核心机制

- **Task Context**：全局唯一 ID + 版本号（v1→v2→…）。每次正式修改递增版本，Agent 每次执行绑定 `task_context_id` + `task_context_version`。
- **Canonical ID**：材料/激光/设备/加工任务/加工目标均使用 Canonical ID，界面仅映射显示标签。
- **设备管理**：任务页可选择设备型号并展示真实设备参数（波长/脉宽/功率/频率/光斑直径/扫描速度等），支持「新建设备」——通过 Agent 服务创建设备档案；优化页参数范围优先采用当前激活设备的机器边界（machine-bounds），无设备档案时退回数据范围。
- **加工任务**：矩形槽 / 圆孔 / 单线 / 自定义（自定义任务通过 Agent 对话说明），可设置槽宽、槽深、孔径、孔深、线宽、切深等任务参数并随 Task Context 提供给 Agent。
- **加工目标**：质量优先 / 效率优先 → 映射为科学计算目标（roughness_um 最小化 / depth_um 最大化），由 Topic2 Backend 执行。
- **Page Context**：页面与活动 Run/Model 自动注入 Agent 消息前缀。
- **Agent Proposal**：Agent 修改任务必须经 Proposal → 人工确认（Level 2）；执行级动作（Level 3）保持人工触发。
- **降级模式**：Agent / RAG / E2P 不可用时，参数辨识、建模、比较、人工模型选择、Vanilla 优化、数据库、运行记录全部可用。
- **数据真实性**：所有正式指标来自 Backend；前端不做任何验收指标计算与证据虚构。材料数据来源（合成夹具 / 真实加工数据）在界面明确标注。

## 测试

```bash
npm test            # 单元 + 组件测试（TaskContext 版本、Canonical ID、Adapter、格式化、状态机、组件）
npm run build       # tsc 严格类型检查 + 生产构建
```

## 对接对象

- Topic2 Backend：`GET /api/v1/{health,materials,equipment,experiments,database/statistics,runs}`、`POST /api/v1/{parameter-identification/run,models/train,e2p/model-policy,e2p/evidence/compile,optimization/recommend}` 等（详见 `docs/interface/topic2_api.md`）。
- Ultrafast Laser Agent：`POST /chat/sessions`、`POST /chat`（会话式问答 + thinking/tool/audit 状态展示）。

## 说明

- 运行记录（`GET /api/v1/runs`、`GET /api/v1/runs/{id}`）为前端新增的只读接口，不改动任何既有端点；Backend 端 CORS 与静态托管为纯增量配置。
- E2P Evidence：当前默认证据候选为空（由 RAG / Agent 提供），前端不虚构；`/e2p/evidence/compile` 返回的真实适用性结果会完整展示在 Evidence Panel。
