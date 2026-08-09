# Evidence → Prior V1：评审、计划与验收边界

## 评审结论

| 现有模块 | 结论 | V1 处理 |
| --- | --- | --- |
| 设备 profile、revision、快照 | 可用 | 保留；重写激活字段和有效功率规则 |
| 旧 TaskForm / ApplicationRun | 不可用 | 不进入 V1 |
| 物理模型 RequirementCompiler | 不适合作为 V1 主入口 | 改用目标特定的知识需求模板 |
| PDF → SemanticBlock、原文 provenance | 可用 | 直接复用 |
| Paper/Block 持久化双索引 | 可用 baseline | 直接复用 |
| 旧数值 RequirementEvidence | 不足 | 由多类型 EvidenceIR v2 取代 |
| CrossPaperAggregator | 仅适合直接匹配汇总 | 不作为 E2P 前置 gate |
| 旧 EvidenceClaim / E2P applicability | 不可直接用 | 由 EvidenceBelief 和逐维 transfer score 取代 |
| typed prior 的证据引用、冲突保留思想 | 可用 | 重建为 Parameter/Region/Preference/ModelStructure 四类软先验 |
| React、TanStack Query、基础 UI | 可用 | 保留技术底座，重写业务页面 |

核心断点是新文献管线与旧 E2P 没有正式契约，现有科学分析接口在
`requirement_set + evidence_run` 处终止，不能形成 EvidenceBelief 或 PriorObject。

## 实施计划

1. 定义 `TaskRequestV1`、目标特定 `KnowledgeRequirementV1`、多类型
   `EvidenceIRV2`、`EvidenceBelief` 和 typed `PriorObjectV2`。
2. 保留双索引检索；按 `Requirement × Paper` 独立调用 LLM，允许条件不完全
   匹配的证据进入 E2P，禁止跨论文拼接。
3. 对引文、block 引用、数字、单位做机械校验；仅校验通过的正证据写入
   `structured_scientific_knowledge_v2`。
4. 对材料、牌号、目标、波长、脉宽、条件完整度、机械校验和抽取可信度做
   可解释的逐维适用性评分。评分是确定性 transfer weight，不宣称为校准概率。
5. 逐条 evidence 生成 belief 和软 prior；互斥数值区间分别保留，禁止平均。
6. 提供单一 `POST /api/v1/evidence-prior/analyze`，并将前端收敛为设备、任务、
   文献证据、E2P 先验四个区块。
7. 治理状态不限制检索、抽取、知识入库或 E2P，只在最终结果 warnings 中提醒。
8. 以仓库真实 PDF 和真实 `deepseek-v4-flash` 完成端到端验收；mock 仅用于
   快速单元测试，不构成验收通过依据。

## 验收条件

- 设备 revision 被精确解析，且有效最大功率来源可追溯；
- 真实 PDF 进入持久化 Paper/Block 索引；
- 供应商返回模型与请求模型均为 `deepseek-v4-flash`；
- 至少一条 EvidenceIR 通过机械校验并写入结构化知识库；
- belief 只能引用校验通过的 EvidenceIR；
- 至少形成一个 typed prior；
- 未治理知识不被过滤，并在最终结果中出现明确提醒；
- 完整 Python、前端测试与生产构建通过。
