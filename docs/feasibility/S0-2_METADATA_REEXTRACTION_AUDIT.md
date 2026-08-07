# S0-2A Existing Pilot Audit — 文献元数据重提取既有试点审阅

> 日期：2026-08-06　|　审阅对象：旧仓库 `ultrafast_laser_memory/benchmarks/literature_metadata/`
> 方法：只读审阅（未重新抽取、未修改任何既有资产）。所有数字均由既有资产重新计算得出。
> 目的：Gate C 决策输入 —— 决定 M4（Uncalibrated CFA）source 侧可计算坐标。

---

## 0. 结论摘要（Gate C 判定）

**Gate C 判定：C2 PASS_WITH_EXTENSION（带 C4 风险旗标）。**

- 既有 pilot **对 CFA 无直接证明力**：gold schema 不含频率/功率/速度/光斑/光束/道次等全部 11 个物理重建字段，无法测出这些字段的抽取性能（"recall 高但没标"假设成立）；
- 但 pipeline 结构（全文 sections 抽取 + page/section/span 级 provenance + manifest 审计）**可复用**，不需要换模型或重做 RAG；
- 需要补的验证（S0-2B，非换模型）：物理字段 gold 扩展、NOT_REPORTED vs MISSED 三态标注、ambiguity taxonomy、目标材料子集分层、40 篇人工盲审完成；
- **C4 风险旗标**：目标材料子集（SiC/CFRP/Diamond/SiCpAl/ZrO2）58 篇中仅 4 篇（6.9%）有 wavelength+pulse_width 标注——但这是**标注 abstain 率，不是原文报告率**；原文实际报告率未知，必须由 S0-2B 的小样本三态标注测定，在此之前不能收缩 CFA 坐标范围。

---

## 1. Gold 到底标了什么（问题 1）

`gold/annotations.jsonl`：203 篇，schema 字段：
`paper_id, title, is_review, primary_material[], material_grade{}, primary_process, laser_type, wavelength_nm, pulse_width{value,unit,evidence}, geometry, material_mentions[]{raw,canonical,role,page}, process_mentions[], evidence_page_primary_material, notes`

**CFA 需要但 gold schema 不存在的字段（实测 11/11 全部缺失）**：

| 字段 | in gold schema |
|---|---|
| frequency_kHz / average_power / pulse_energy / scan_speed / spot_size / spot_definition / beam_shape / hatch / passes / target_metric | **全部 False** |

已有字段的**标注非空率**（= 报告率上限，annotator 也可能漏标）：

| 字段 | 非空 | 占比 |
|---|---:|---:|
| primary_material | 159/203 | 78.3% |
| material_grade | 32/203 | 15.8% |
| primary_process | 147/203 | 72.4% |
| laser_type | 94/203 | 46.3% |
| **wavelength_nm** | **28/203** | **13.8%** |
| **pulse_width** | **24/203** | **11.8%** |
| geometry | 119/203 | 58.6% |

**判定**：gold 覆盖"材料/工艺/几何"导航层，物理重建层（能量/频率/速度/光斑）完全未覆盖。**扩 gold，不是换模型。**

## 2. 评估单位是什么（问题 2）

`scripts/evaluate_extraction.py` 实测：
- **单位 = 论文级**：material exact（集合相等）、multi-label P/R/F1（FP 无条件统计，含 abstain 论文乱报惩罚）、process/laser/grade/geometry accuracy（精确字符串相等，model abstain 按 miss）、wavelength ±2nm 容差、pulse_width value±5% + unit 精确匹配、evidence_page_accuracy（正确页含 primary mention）、每字段独立 abstention recall/precision、Wilson CI + 论文级 bootstrap。
- **缺失的评估维度**（CFA 需要）：presence recall（对不存在字段无法测）、value/unit 分离、condition linkage、ambiguity detection、provenance（page/span）准确性（现有只有 evidence_page 一个弱代理指标）。

**判定**：对导航层字段的评估设计是严谨的（FP 惩罚 + abstain 分离 + CI），但物理字段与 ambiguity 维度不存在。

## 3. Missing vs Extraction Failure（问题 3）

**现状态：无法分离。**
- gold 对物理字段没有三态机制（NOT_REPORTED / REPORTED_BUT_MISSED 均表现为空值）；
- 对已有字段，非空率（§1）是"报告率上限"，但没有独立核查确认 annotator 未漏标（silver 标注自证）；
- dev 预测质量（pilot2/130649Z，27 篇，deepseek-v4-flash）：wavelength accuracy 0.50（**MAE 25 nm**）、pulse_width 0.44、material_grade 0.375、material exact 0.68/F1 0.79。

**判定**：需要在 S0-2B 用三态标注（reported+correct / reported+missed / not_reported）的小样本重测，才能回答"是 pipeline 不行还是论文没报告"。

## 4. 物理语义 ambiguity（问题 4）

**现状态：完全未测。** 下列 ambiguity 维度在 gold schema、评估器、预测 schema 中均不存在：
`radius vs diameter / 1/e² vs FWHM vs unspecified / average power vs pulse energy / incident vs post-objective / peak vs average fluence / incident vs absorbed / single-pulse vs accumulated`
唯一非结构化的残留是 gold `notes` 字段（如 "FWHM = 50 fs" 的 evidence 串）。

**判定**：定义 ambiguity taxonomy + 标注项 = S0-2B benchmark extension，不能判 pilot 通过。

## 5. 按材料/场景分层（问题 5）

gold 材料分布：Glass 46 / NickelSuperalloy 31 / Diamond 24 / CFRP 24 / TBC 21 / FusedSilica 9 / **SiC 9** / Aluminum 7 / Silicon 5 / GlassCeramic 3 / Steel 2 / **SiCp/Al 2** / Copper 2 / Ti6Al4V 2 / Epoxy 1 / Sapphire 1。**ZrO2 = 0 篇。**

**目标材料子集（SiC/CFRP/Diamond/SiCp/Al/ZrO2）58 篇：仅 4 篇（6.9%）有 wavelength+pulse_width**（04_arxiv_2502.16530=800/30fs、07_arxiv_2401.02340=790/40fs、11_arxiv_2404.09906=1030/383fs、12_arxiv_2310.16315=1030/300fs——全部为 Diamond/SiC 加工论文）。

**重要发现——语料相关性污染**：58 篇中相当数量**不是激光加工论文**：
- CFRP 类含大量结构工程论文（"CFRP U-Wraps and Spike Anchors"、"CFRP-strengthened shear walls"、"Bond–Slip Relationship" 等 = 土木加固，epmc_* 系列多为胶接/老化/热循环）；
- Diamond 类含大量 X 射线光学仿真/表征论文（无激光工艺条件）；
- 结论：**"CFRP 24 篇"被非激光论文稀释**，真实可用的 target-relevant 激光工艺文献远少于名义数量；且现有 gold 的 laser_type 空值占比 53.7% 与这批论文有关。

**判定**：分层必须加"是否激光加工论文"过滤（`is_review` + laser_type + `usable_for` 语义），否则 stratum 指标无意义。

## 6. Full text vs chunk（问题 6）

**实测：pilot 与生产抽取都基于全文 sections，不是 RAG chunk。**
- runner 输入 = `work/texts/*.txt`（全文页面文本），LLM 输入 = 前 24 个 section × 1500 字符（~36K 字符截断）；
- 生产链路 `metadata_backfill.py` = `literature_section`（page 级 section）→ 抽取 → 再建 chunk 供 RAG；
- mentions 已携带 `page + section_id + section_type + evidence_span`（chunk 级 provenance 所需信息已在，chunk_id 关联可通过 section_id 建立）。

**架构建议（支持你的倾向）**：
```
claim provenance      = chunk/section 级（已有 evidence_span/page/section_id）
SourceConditionSpec   = paper 级聚合（条件可跨 section 合并）
```
风险点：生产 RAG 检索路径（query→chunk）若以 chunk 为单位喂给 LLM，条件分裂在多个 chunk 时可能丢失——**S0-2B 需用 2-3 篇条件分散的论文做 chunk vs 全文对照试验**才能定 C1 vs C3。

## 7. Leakage 检查（问题 7）

实测：
- **prompt 无 gold 泄漏**：`semantic_roles.py` ROLE_PROMPT 为静态系统提示，无 few-shot、无 gold 内容；manifest 记录 prompt_sha256 + git commit + worktree diff + 每篇文本 SHA（可追溯）。
- **dev/test 纪律存在但未执行完**：README 明确 dev=27（pilot2）仅用于调参、回归结果不作测试结论；**test=176 篇从未运行**；audit=40 篇 worksheet 已生成但**人工盲审字段全部空白（未完成）**。
- **silver 自证问题（最大泄漏源）**：gold 由同一 pipeline 家族（AI 策展）产生，预测与标注同源 → 现有数字只是 development score，113444Z→130649Z 的提升（material exact 0.41→0.68）是 dev 上的 prompt 迭代，不代表独立性能。
- gold 有两个版本（首版 7ACC67C5 → 重命名后 D5A1683）；113444Z 的 gold_sha256=5faa9f6 与 130649Z=7acc67c5 不同 → 早期 run 与当前 gold 不完全对齐（重命名影响 2 篇）。

**判定**：无 prompt 级泄漏；有"未完成人工盲审 + 未跑 test set + gold 同源"三处限制——**任何现有数字只能引用为 development score**。

## 8. Gate C 决策与 Source Computability 矩阵

### 8.1 当前数据下的 source 可计算性（实测）

| physics coordinate | 依赖字段 | 当前 gold 可算率 | 判定 |
|---|---|---|---|
| pulse_width regime | pulse_width | 11.8%（目标材料 6.9%） | 可算（粗） |
| wavelength | wavelength_nm | 13.8% | 可算 |
| pulse_interval | frequency | **0%（字段不存在）** | blocked |
| pulse_energy | power+frequency | 0% | blocked |
| peak_fluence | energy+spot | 0% | blocked |
| pulse_spacing | speed+frequency | 0% | blocked |
| N_eff / overlap | spot+frequency+speed | 0% | blocked |
| areal_energy | power+speed+hatch+passes | 0% | blocked |
| normalized_fluence | peak_fluence+Fth | 0% | blocked |

**Source computable ∩ Target computable 目前 ≈ 空**（target 侧另见 S0-3）。这不是"文献没报告"，而是"标注没标"——必须由 S0-2B 三态标注测定真实报告率。

### 8.2 四种出口的判定

```
C1 PASS_CHUNK          ✗ 不能判定（物理字段从未测过）
C2 PASS_WITH_EXTENSION ✓ 当前判定（pipeline 结构可复用，需补验证）
C3 REQUIRE_FULLTEXT   ? 待 S0-2B 的 chunk-vs-全文对照试验
C4 SCOPE_REDUCTION    ⚠ 风险旗标（6.9% 是标注 abstain 率，非报告率；不得据此收缩）
```

### 8.3 S0-2B 补验清单（只补真实缺口，不重新抽一轮）

| # | 补验项 | 范围 | 产出 |
|---|---|---|---|
| B1 | 物理字段三态标注小样本 | 15–25 篇 target-relevant 激光论文（SiC/CFRP/Diamond/SiCpAl，过滤非激光；ZrO2 待补文献） | NOT_REPORTED vs MISSED 表（§3） |
| B2 | gold schema 扩展定义 | 频率/功率(incident/post-objective 标记)/速度/光斑(diameter+definition)/beam/hatch/passes/fluence 类 + ambiguity 标志 | 扩展 schema 冻结 |
| B3 | chunk vs 全文对照 | 2–3 篇条件跨页/跨段论文 | C1 vs C3 判定 |
| B4 | 40 篇人工盲审完成 | audit/ 现有 worksheet（至少覆盖目标材料子集） | silver→gold 晋升（仅对盲审子集） |
| B5 | 语料相关性过滤 | `usable_for/not_usable_for` + laser 判定 | target stratum 纯净版 |
| B6 | 目标材料文献补采（ZrO2） | 与 S0-4 联动 | 语料缺口登记 |

**S0-2B 出口**：B1–B3 完成 → 更新本文件 8.1 矩阵 → Gate C 重新判定（C1/C2/C3/C4 之一）。
