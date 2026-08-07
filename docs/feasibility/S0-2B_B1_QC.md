# S0-2B B1 Protocol QC Gate — 报告

> 日期：2026-08-06　|　范围：仅既有 3 篇（protocol-development set，不计入正式 benchmark）
> 结论：**B1 Protocol QC PASS**（7 项出口全部满足，3 处结构性修正已固化到协议 v2）

---

## 1. 一致性重标（v1 vs v2，3 篇）

### 1.1 按字段状态对比

| paper | 字段 | v1 状态 | v2 状态 | 差异原因 |
|---|---|---|---|---|
| 04_arxiv_2502.16530 (Diamond) | 全部 16 字段 | — | 与 v1 一致 | 无实质差异；仅结构升级 |
| | spot_size | REPORTED_CLEAR | spot_value/spot_dimension/spot_definition 拆分 | 结构性拆分（有意变更） |
| | ablation_threshold | NOT_REPORTED_MEASURED | extra_reported THRESHOLD + provenance_type=CITED_FROM_OTHER_SOURCE | 结构升级 |
| | accumulated_dose | (extra) | reported_quantity_type=ACCUMULATED_DOSE + definition | 结构升级 |
| Flat-top CFRP | wavelength | **NOT_REPORTED** | **REPORTED_CLEAR (355 nm)** | **v1 阅读截断漏掉 Table I（p5）** |
| | pulse_width | REPORTED_AMBIGUOUS(regime only) | **REPORTED_CLEAR (10 ps)** | 同上 |
| | frequency | NOT_REPORTED | **REPORTED_CLEAR (1 MHz)** | 同上 |
| | spot_size | NOT_REPORTED | **REPORTED_CLEAR (19 μm DIAMETER, definition UNSPECIFIED→AMBIGUOUS)** | 同上 |
| | scan_speed | NOT_REPORTED | **REPORTED_CLEAR (1 m/s)** | 同上 |
| | beam_profile | REPORTED_CLEAR(FLAT_TOP) | REPORTED_CLEAR(TOP_HAT) | 语义同（枚举更名） |
| | average_power | NOT_REPORTED | NOT_REPORTED（Table I 确无功率列） | **确认是真缺失** |
| 10_arxiv_2411.18093 (SiC) | 全部 Laser/Beam/Motion | **NOT_REPORTED** | **UNRESOLVED_DUE_TO_TEXT_COVERAGE** | **结构性修正（v1 错误归因为"没报告"）** |
| | material/process/target | REPORTED_CLEAR | REPORTED_CLEAR | 一致 |

### 1.2 一致性汇总

- **值/单位层面**：v1 与 v2 在"已报告字段"上 0 处数值冲突（Diamond 全部字段一致）；
- **状态层面**：13 处状态差异，其中 6 处来自 CFRP 全文复读（阅读缺陷），7 处来自结构性升级；
- **阅读缺陷根因**：v1 只读每页行首 ~400 字符；v2 全文页扫描 + 参数表优先 → 协议 v2 §7 固化。

### 1.3 结论

同一标注者按 v2 协议重标，未产生"同协议下反复不定"的结构性歧义；差异全部可归因于
（a）阅读完整性协议化、（b）schema 结构升级。**协议已达到可放量条件。**

---

## 2. 七项出口检查

| # | 出口要求 | 状态 | 落点 |
|---|---|---|---|
| 1 | text coverage 独立状态 | PASS | 协议 v2 §1：TextCoverageStatus + missing_sections |
| 2 | NOT_REPORTED 与 corpus truncation 分开 | PASS | 新增 UNRESOLVED_DUE_TO_TEXT_COVERAGE；COMPLETE 才允许 NOT_REPORTED |
| 3 | 一篇论文多 ExperimentalConditionSpec | PASS | 协议 v2 §2：experimental_conditions[] + condition_id；claim→condition_id |
| 4 | spot schema 冻结 | PASS | spot_value/unit + spot_dimension + spot_definition + beam_profile（§4 Beam 组） |
| 5 | reported quantity definition 可保存 | PASS | reported_quantity_type + definition（§5）；ACCUMULATED_DOSE 不预命名为 accumulated_fluence |
| 6 | cited/measured 属性 provenance 分离 | PASS | provenance_type 五类（§6）；CITED_FROM_OTHER_SOURCE 不作独立 Evidence |
| 7 | 3 篇重标无结构性歧义 | PASS | §1.3 |

---

## 3. UNCERTAIN 11 篇轻量裁决（3 问：激光加工？目标相关工艺？含实验条件？）

| 论文 | 裁决 | 依据 |
|---|---|---|
| 06_arxiv_2406.12886 (Bessel 金刚石电极) | → TARGET_RELEVANT | fs Bessel 激光加工 |
| 07_arxiv_2401.02340 (Bessel 金刚石取向) | → TARGET_RELEVANT | fs 激光写入 |
| 11_arxiv_2404.09906 (SiC 光致发光) | → TARGET_RELEVANT | fs 辐照相互作用 |
| 12_arxiv_2310.16315 (SiC 相位调制探针) | → TARGET_RELEVANT | fs 相互作用研究 |
| 20_arxiv_1812.04284 (SiC 色心写入) | → TARGET_RELEVANT | fs 激光写入 |
| Concurrent Effect ... CFRP Single Lap | → TARGET_RELEVANT | CFRP 激光织构 |
| Polymer Composites 2024 Li | → TARGET_RELEVANT | CFRP 激光改性 |
| The effect of laser-texturing configurations | → TARGET_RELEVANT | CFRP 激光织构 |
| Ultrafast laser surface treatments (CFRP) | → TARGET_RELEVANT | CFRP 激光处理 |
| epmc_2025_bioinspired_microcavities | → TARGET_RELEVANT | CFRP 激光微腔织构 |
| palmieri_ijaa_2016 | → TARGET_RELEVANT | CFRP 激光烧蚀预处理 |
| 28_arxiv_1207.1981 (单晶单色器) | → IRRELEVANT | X 射线束线，非激光 |
| 1e1db7c47f124124 (X 射线探针光学模型) | → IRRELEVANT | 仿真 |
| 677e00e7c1eee09f (光栅干涉仪) | → IRRELEVANT | 同步辐射表征 |

**裁决后基准人口（B1 benchmark population）= 28 篇 TARGET_RELEVANT**（58→28，去重 2、
非激光 22、未定 2：CFRP/Ti 钻孔策略与 SiC 平面透镜，暂不进基准）。

---

## 4. QC 期间发现的流程缺陷（已修复）

1. **curation 脚本 ID 匹配 bug**：v1 用截断标题做 key，11 条晋升失败静默丢失 →
   v2 脚本多级匹配（精确→前缀→包含→标题包含，剥离扩展名）+ **未命中告警**；
2. **v1 阅读协议缺陷**：每页只读行首 → 协议 v2 §7（全页扫描 + 参数表优先）；
3. **B5 计数口径**：本轮将 TARGET_RELEVANT 从 17 修正为 **28**（前次 17 是匹配 bug 造成的低估）。

---

## 5. 放量计划（QC 后）

1. 剩余 **25 篇** TARGET_RELEVANT 按协议 v2 标注（每篇含 text_coverage + condition 拆分）；
2. 标注同时记录 "Fth/α 等属性" 的 provenance_type，为 S0-5 材料属性库积累；
3. 输出 §8 报告率矩阵（按 COMPLETE 子集计算 intrinsic reconstructibility）；
4. 2 篇残留 UNCERTAIN（CFRP/Ti 钻孔、SiC 平面透镜）回原文后裁决；
5. B6/S0-2C 语料补采（ZrO2/SiCp/Al）在 B2 schema 冻结后启动。
