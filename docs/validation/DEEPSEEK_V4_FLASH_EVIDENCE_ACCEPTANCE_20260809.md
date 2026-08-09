# DeepSeek V4 Flash 真实证据抽取验收（2026-08-09）

## 结论

在 4 篇仓库原始 PDF 上，使用 DeepSeek 官方 OpenAI-compatible API 与
`deepseek-v4-flash` 完成 8 次真实抽取调用：4 次 diamond 烧蚀阈值正例任务，4 次
不存在材料常数的负例任务。所有供应商 request ID 均存在，共消耗 34,282 tokens。

本次验收通过，但仅证明该固定小规模用例，不构成模型泛化能力声明。

## 输入与主结果

- 目标：`ablation_threshold_J_m2`；条件：`material=diamond, laser_type=fs`。
- 正确论文：`04_arxiv_2502.16530.pdf`。
- 干扰论文：3 篇 SiC 文献。
- 正例聚合：`FOUND, 3.0 J/cm2`，机械校验通过，block 来源可追溯。
- 三篇干扰论文：均为 `NOT_FOUND`。
- 负例聚合：`NOT_FOUND`，并生成 `CalibrationRequirement` 回退。
- 结构化知识库：仅写入条件完整且机械校验通过的 diamond 正证据。
- 治理状态：仅在最终输出中提示 `unreviewed`，未限制检索、抽取或 Reduce。

## 指标

| 指标 | 结果 |
|---|---:|
| Paper Recall@3 | 1.0 |
| Evidence Block Recall@8 | 1.0 |
| Paper MRR | 1.0 |
| Numerical Extraction Precision | 1.0 |
| Numerical Extraction Recall | 1.0 |
| Unit Accuracy | 1.0 |
| Condition Linkage Accuracy | 1.0 |
| Source Attribution Accuracy | 1.0 |
| False-Satisfied Rate | 0.0 |

## 实时测试发现并修复的问题

首次真实调用中，模型曾把一篇 SiC 论文的 `7 J/cm2` 错标成 diamond Requirement 的
`FOUND`。跨论文 Reduce 因缺失 material 条件而没有使用它，但旧机械校验仍允许该条进入
结构化知识库。这是不合格的。

随后增加两层约束并重新真实调用：

1. Evidence Window 明确携带论文 title/metadata 作为不可引用的条件上下文；
2. `FOUND.conditions` 必须覆盖并匹配全部 `Requirement.conditions`，论文 metadata 也不得
   与 Requirement 冲突。

复测后三篇 SiC 文献均为 `NOT_FOUND`，且知识库只写入 diamond 正证据。

## 可复现命令

```powershell
$env:DEEPSEEK_API_KEY = "<secret>"
.venv\Scripts\python.exe scripts\run_live_evidence_acceptance.py `
  --output artifacts\real_llm_evidence_acceptance\deepseek_v4_flash_20260809.json
```

脚本只从环境变量读取密钥。报告仅保存 provider request ID、模型与 token usage，不保存
密钥、Authorization、prompt 或完整 API 响应。

机器可读报告：
`artifacts/real_llm_evidence_acceptance/deepseek_v4_flash_20260809.json`。

## 边界

当前仅覆盖一个正科学量、一个构造负例和 4 篇文献。正式主链仍需扩大到独立 unseen
论文集，并覆盖 incubation coefficient、penetration depth、range/table evidence、冲突值和
条件缺失等用例。
