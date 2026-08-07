# S0-2B7 — Structured Ingestion Feasibility Pilot（机制可行性）

> 定位：**mechanism feasibility pilot**，禁止报告提升幅度（样本不支持）。
> 前置：B7-0 解析器可用性 Gate（PASS，见 §1）；两份契约冻结（IDENTITY_V0.1 / CONDITION_V0.1）。

## 1. B7-0 Parser Availability Gate（结果）

| 候选 | 状态 | 证据 |
|---|---|---|
| A. existing parser | 可用 | 旧仓库 `section_parser` + `work/texts`（B1 已用） |
| B. PyMuPDF structured baseline | **PASS** | pymupdf 1.28.2 已装新仓库 venv（清华镜像）；冒烟：sc04_003 PDF 12 页，page1=23 / page5=26 个 text blocks 均带 bbox |
| C. Docling | PENDING | pip 镜像可装；HF model API 可达（200）；模型 artifacts 离线落盘需在 pilot 首日实测（`artifacts_path` 本地化） |
| D. GROBID | DECLINED-for-pilot | Java/Docker 服务；Windows/受限网络开销大；S0-2D 签 ADR 再议 |

DoD「existing + 1 structured parser」：**PASS**（A + B）。

## 2. Pilot 选篇（5 篇，故意覆盖 5 类，非随机）

| # | 类型 | 论文 | 状态 |
|---|---|---|---|
| 1 | clean single-condition | 04_arxiv_2502.16530（Diamond 30fs 烧蚀） | B1 已标（v2） |
| 2 | incomplete text coverage | 10_arxiv_2411.18093（4H-SiC ps 切片） | B1 已标（v2） |
| 3 | table-heavy | Flat-top picosecond laser texturing of CFRP | B1 已标（v2，Table I） |
| 4 | **multi-condition** | **11_arxiv_2404.09906**（SiC 光致发光：fs 230/250/383 + kHz 10/100 + MHz 1/4.5/70） | 待 B1 标注（linking 主测试） |
| 5 | ambiguous/conflicting | **13_arxiv_2411.18868**（双重复频率体制 200kHz vs 40MHz + 25W + 230fs，体制映射不明确） | 待 B1 标注 |

选型依据（文本扫描）：11_arxiv 三个脉宽+多频率体制；13_arxiv 双重复频率体制冲突。

## 3. 对比维度（冻结）

```text
结构:   section recovery / paragraph-block recovery / reading order
表格:   table recovery / TableSemanticType 判定 / header-unit 继承 / footnote modifier
溯源:   ProvenanceAnchor（page+bbox+quote）可映射回 PDF
字段:   field precision / recall / value+unit correctness
条件:   condition count / grouping P/R / assignment accuracy / Synthetic Condition Rate
ID:     document_version_id 稳定性 / chunk 重建 / gold remap 可行性（2 篇抽样）
```

## 4. DoD（全部达成才过 Gate B7）

```text
✓ parser 能离线执行（A+B 已验证；C 可选）
✓ structure 稳定产生（section/block/bbox）
✓ table 恢复到可消费形式（TableSemanticType + header 继承）
✓ provenance 映射回 PDF（page+bbox+quote）
✓ ID/version contract 可实现（document_version_id + 投影重建）
✓ condition schema 能承载结果（v0.1 冻结）
✓ multi-condition linking 不产生明显伪组合（11_arxiv 上 Synthetic Condition Rate 报告）
✓ gold remapping 技术上可行（2 篇抽样，UNRESOLVED 允许）
```

## 5. 执行产物

- `src/ultrafast_ingestion/`（experimental infrastructure；仅依赖 stdlib + parser adapters + core contracts；
  禁止依赖 ultrafast_knowledge/e2p/bo；是否永久保留由 S0-2D ADR 决定）
- pilot 报告 `docs/feasibility/S0-2B7_PILOT_REPORT.md`（通过后提交 Gate B7 判定）
