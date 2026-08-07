# Development Set（开发集，冻结）

- 来源：pilot2（2026-08-05T130649Z，27 篇分层采样，27/27 `extracted_with_llm`）
- 定位：**开发集**，用于管道调试与 prompt/策略迭代；**不得**用其回归结果作为独立测试结论
- 文件：
  - `dev_ids.txt`：27 篇 paper_id（固定）
  - `pilot2_predictions.jsonl`：raw baseline 预测（未经任何折叠/后处理）
  - `pilot2_manifest.json`：当时 manifest（注意：pilot2 运行于未提交代码，
    其 manifest 仅作诊断用途；严格可复现实验见 runner v2 的 manifest 约定）
- 注意：pilot2 的 27 篇与后续修复后的回归**同批**——回归结果只用于"改前/改后"对照，
  不代表对未查看测试集的泛化结论
