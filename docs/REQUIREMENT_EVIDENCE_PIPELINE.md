# Requirement Compiler 与科学证据管线

## 正式主链

```text
TaskSpec
  → ScientificDependencyGraph / ModelCapability registry
  → RequirementCompiler（递归依赖闭包，不执行模型）
  → RequirementSet
  → 论文级 metadata retrieval
  → PDF → ScientificDocument → SemanticBlock
  → 论文内 evidence-window retrieval
  → 每个 Requirement 一次结构化 LLM 抽取
  → 数值/单位/原文引用确定性校验
  → requirement-scoped EvidenceIR
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

## 证据边界

`SemanticBlock` 保留 `paper_id / document_version_id / page / section / block_id /
bbox / 前后块 / table、figure、equation 关系`，不按固定字符数截断。

LLM 每次只处理一个 Requirement，输出 `FOUND / NOT_FOUND / CONFLICT`、值或范围、
原文单位、条件、语义角色、`source_block_refs`、原文短引和置信度。确定性校验只负责：

- 引用的 block 是否真实位于本次 evidence windows；
- 数值是否出现在被引原文；
- 单位是否可解析且量纲匹配；
- 原文短引是否逐字存在；
- `FOUND / NOT_FOUND / CONFLICT` 的结构是否自洽。

`validation_state=validated` 只表示抽取结果通过上述机械校验，不表示证据已通过治理、
适用性审核或可直接成为 E2P prior。

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
    "material": "SiC",
    "laser_type": "fs",
    "wavelength_nm": 1030
  },
  "available_quantities": {
    "laser_power_W": 20,
    "frequency_Hz": 200000,
    "scan_speed_m_s": 1.0
  }
}
```

## 验证

```powershell
.venv\Scripts\python.exe -m pytest -q `
  tests\test_requirement_compiler.py `
  tests\test_real_requirement_evidence_pipeline.py
```

真实文献测试直接解析仓库原始 PDF
`artifacts/b1_annotation/papers/04_arxiv_2502.16530.pdf`，验证论文级检索、语义块检索、
金刚石烧蚀阈值 `3.0 J/cm2` 的 requirement-specific 抽取与 block 级溯源。测试中的 LLM
响应是对该真实论文的固定记录，CI 不伪造论文正文，也不依赖外部模型服务。
