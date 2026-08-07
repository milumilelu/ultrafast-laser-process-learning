# Frozen Baseline（2026-08-05，2026-08-06 修订）

- git commit（首版冻结）: `0973501`（feat(benchmark): complete corpus annotation - gold 203 papers）
- 2026-08-06 canonical 重命名：`AlSiC` → `SiCp/Al`（碳化硅颗粒增强铝基复合材料标准写法；
  语义等价，仅标识符规范化；`alsic` 等别名保留兼容旧数据/旧文本）
- gold SHA256（重命名后）: `D5A1683FDCBA26760E238616CAD9C0A1FDAE736335374B450CEE0EF205A64E06`
- 文件: `gold/annotations.jsonl`（203 篇，schema 0 errors）
- 首版冻结 SHA256（重命名前）: `7ACC67C5C2BDD8D1B01F6811F4F94146257A71FD0945EEDCA7E2E94D556EEFEF`

## 定位声明（2026-08-06 修订）

- 本文件名为 gold，但当前 203 篇标注主要由 **AI 语义裁决**产生，
  尚无独立人工盲审与标注者一致性数据——严格定位为 **AI 策展 silver benchmark**。
- 只有完成独立盲审（30~50 篇）、报告字段级错误率、双人一致性后，
  才可正式称"人工 gold 基线"。
- ontology 版本：**ontology-v1 / pre-v2**。Germanium / HexagonalBoronNitride /
  welding 等候选 canonical 在 v1 中**未启用**（相应论文标空/abstain）；
  v2 引入必须以消融实验对比本基线。

## 冻结范围

- gold 定义在 ontology-v2 评估与消融之前保持不可变；
- 新 canonical 只作为 ablation 分支讨论，不修改本文件；
- 评测/运行一律以本 SHA 对齐（runner 使用字节级 SHA256）。
