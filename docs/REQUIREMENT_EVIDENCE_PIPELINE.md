# Requirement Compiler 与科学证据管线

## 正式主链

```text
TaskSpec
  → ScientificDependencyGraph / ModelCapability registry
  → QuantityValue / DecisionVariable 严格规范化
  → RequirementCompiler（递归依赖闭包，不执行模型）
  → RequirementSet
  → 离线 PDF → ScientificDocument / SemanticBlock 持久化
  → Paper Index + Global Block Index 候选并集
  → 候选论文内 Block Index evidence-window retrieval
  → Requirement × Paper 独立结构化 LLM Map
  → 数值/单位/原文引用机械校验
  → 通过校验的正证据写入 structured_scientific_knowledge
  → 条件感知的跨论文 Reduce（FOUND / CONFLICT / INSUFFICIENT / NOT_FOUND）
  → NOT_FOUND / INSUFFICIENT → CalibrationRequirement
```

旧的 `requirement type → intent → section 前缀 → 单篇批量知识抽取` 不再是应用主链。

## Requirement 分类

编译器输出：

- `RESOURCE_REQUIREMENT`：设备或任务必须提供；
- `KNOWLEDGE_REQUIREMENT`：文献可提供，必要时转实验标定；
- `CALIBRATION_REQUIREMENT`：必须标定；
- `DATA_REQUIREMENT`：需要实验/数据集；
- `DERIVABLE`：依赖满足后由已注册能力确定性推导；
- `SATISFIED`：任务或设备上下文已经给出。

模型依赖只在 `ultrafast_requirements.graph` 的 `ModelCapability` 中声明。若同一量有多个
provider，调用方必须显式选择，编译器不会猜测。

`QuantityValue` 必须同时声明 `quantity / value / unit / source`；禁止
`{"frequency_kHz": 100}` 这类裸数值。别名与单位由确定性代码规范化，例如
`100 kHz → 100000 Hz`、`1000 mm/s → 1 m/s`。优化任务必须提供至少一个带上下界、
步长和可选可行域的 `DecisionVariable`；预测任务禁止混入决策变量。

## 证据边界

`SemanticBlock` 保留 `paper_id / document_version_id / page / section / block_id /
bbox / 前后块 / table、figure、equation 关系`，不按固定字符数截断。`text` 是不可改写的
原文，`retrieval_text` 是加入论文、章节与实验上下文后的检索表示，两者严格分离。

在线分析只查询持久化的 Paper/Block 双索引，不重新解析 PDF。两个索引均使用 BM25、
dense LSA、RRF 与确定性 rerank；Global Block Index 可召回摘要未写目标量的论文。

LLM 每次只处理一篇论文中的一个 Requirement，输出 `FOUND / NOT_FOUND / CONFLICT`、值或范围、
原文单位、条件、语义角色、`source_block_refs`、原文短引和置信度。确定性校验只负责：

- 引用的 block 是否真实位于本次 evidence windows；
- 数值是否出现在被引原文；
- 单位是否可解析且量纲匹配；
- 原文短引是否逐字存在；
- `FOUND / NOT_FOUND / CONFLICT` 的结构是否自洽。

`validation_state=validated` 只表示抽取结果通过上述机械校验，不表示证据已通过治理、
适用性审核或可直接成为 E2P prior。

这里没有 Evidence Cache。机械校验通过的 `FOUND` 结果进入结构化科学知识库，后续按
quantity 与适用条件参与跨论文聚合。`governance_status` 只作为最终用户结果中的提醒：
它不限制 Paper/Block 召回、LLM 抽取、知识库查询或跨论文 Reduce。

## 离线建库

```powershell
.venv\Scripts\python.exe scripts\build_scientific_indexes.py `
  --pdf-root artifacts\b1_annotation\papers
```

该命令一次性持久化 `ScientificDocument / SemanticBlock`，随后原子更新 Paper Index 与
Block Index 的版本。新增文献后重新运行即可；在线 Requirement 分析不接收 PDF 路径。

## API

```text
POST /api/v1/requirements/compile
POST /api/v1/scientific-evidence/analyze
POST /api/v1/scientific-analysis/jobs
GET  /api/v1/scientific-analysis/jobs/{job_id}
```

编译请求示例：

```json
{
  "task_spec": {
    "target": "depth_um",
    "task_type": "prediction",
    "material": "SiC",
    "laser_type": "fs",
    "wavelength_nm": 1030
  },
  "available_quantities": [
    {"quantity": "laser_power_W", "value": 20, "unit": "W", "source": "task"},
    {"quantity": "frequency_kHz", "value": 200, "unit": "kHz", "source": "task"},
    {"quantity": "scan_speed_mm_s", "value": 1000, "unit": "mm/s", "source": "task"}
  ]
}
```

## 验证

```powershell
.venv\Scripts\python.exe -m pytest -q `
  tests\test_requirement_compiler.py `
  tests\test_cross_paper_aggregation.py `
  tests\test_scientific_analysis_queue.py `
  tests\test_real_requirement_evidence_pipeline.py
```

真实文献测试离线导入仓库中的 4 篇原始 PDF（1 篇 diamond、3 篇 SiC），验证双索引、
Global Block fallback、金刚石烧蚀阈值 `3.0 J/cm2` 的逐论文抽取、知识入库、跨论文聚合、
校准回退与 block 级溯源。当前固定金标用例的 Paper Recall@3、Evidence Block Recall@8、
MRR、数值抽取 Precision/Recall、单位正确率、条件绑定正确率与 Source Attribution Accuracy
均为 1.0，负例 False-Satisfied Rate 为 0。固定 LLM
响应只记录对真实原文的抽取结果；测试不伪造论文正文，也不依赖外部模型服务。

另有真实模型验收：

```powershell
$env:DEEPSEEK_API_KEY = "<secret>"
.venv\Scripts\python.exe scripts\run_live_evidence_acceptance.py
```

2026-08-09 的 DeepSeek V4 Flash 实际调用结果与限制见
`docs/validation/DEEPSEEK_V4_FLASH_EVIDENCE_ACCEPTANCE_20260809.md`。固定响应测试用于日常
确定性 CI，不能替代这项真实模型验收。
