# S0-2B7 — Mention False-Negative Audit（Layer 2 准入 Gate）

> 日期：2026-08-06　|　范围：5 篇 pilot 的 CFA-critical 期望 mention（人工 reference 冻结于
> `S0-2B_B1_REFERENCE_11_13.jsonl` / `S0-2B_B1_annotations_v2.jsonl`）
> 结论：**Mention Gate PASS**（G1–G4 全部满足）

---

## 1. 指标（人工 reference 37 项期望 vs 实际抽取）

| 指标 | 值 |
|---|---:|
| expected mentions（CFA-critical） | 37 |
| detected / OK | **37 / 37** |
| missed | **0** |
| misclassified | **0** |
| wrongly rejected | **0** |
| value-shape errors（RANGE/LIST/SCALAR） | **0** |
| **CFA-critical mention recall** | **100%（37/37）** |
| **wrong-rejection rate** | **0%** |

按字段覆盖：wavelength 8/8、pulse_width 4/4、frequency 6/6、pulse_energy 6/6、
fluence 3/3、accumulated_dose 1/1、spot_size 4/4、NA 2/2、scan_speed 1/1、
depth 1/1、pitch 1/1 —— 全部命中。

## 2. 审计发现与修复（四类漏检逐一处置）

| # | 漏检模式 | 根因 | 修复 |
|---|---|---|---|
| FN-1 | **kJ/cm² 累计剂量完全漏抽**（04: 1–500 kJ/cm²） | 单位表无 kJ/cm2 | units.py 增加 kJ/cm2 → accumulated_dose |
| FN-2 | **"2 nJ/pulse to 445 nJ/pulse" 被拆成两个 SCALAR** | (a) 双端单位区间模式缺失；(b) 区间跨 block 换行截断 | 新增 DUAL_UNIT_RANGE 模式 + 抽取时拼接下一 block 60 字符延续 |
| FN-3 | **参数表 "Label (unit) value" 全漏**（Flat-top Table I 6 项） | 模式要求"数值在单位前"；且 TABLE 正则第一行误用 r"" 未插值、`({_NUM})` 双重括号使 range 组错位 | 新增 TABLE_CELL 模式（已知 label 白名单过滤）+ 修复插值与分组 |
| FN-4 | **length 单位消歧失效**（15µm→length、5µm apart→length、2&4µm depths→length） | infer_parameter 对单候选单位提前返回，词表从未执行；且词序匹配而非最近词 | 最近词消歧（仅 length 族单位），position 传入 |
| FN-5 | **NA / M² / 放大倍数无法抽取**（无量纲） | 模式只有 value+unit | 新增无量纲模式（NA/M2/×放大）+ 哨兵单位 |
| FN-6 | **ODMR/自旋频率被当激光频率**（11: 4.5/70 MHz） | 无 spin 语境规则 | SPIN_FREQUENCY_WORDS 拒绝（zero field splitting/ODMR 等） |
| FN-7 | **"V1 and 70 MHz" 合并成假 LIST**（V1=缺陷标签） | 数值模式无开头 lookbehind | 所有模式加 `(?<![A-Za-z0-9])` |
| FN-8 | **capability 词无距离限制**（"up to 1 MHz"污染 90 字符外的 1030nm） | 窗口内任意出现即 AMBIGUOUS | capability 词需在 mention 60 字符内 |
| FN-9 | **上下文窗口未真正跨 block**（两侧被 block 边界截断） | win_start/win_end 按 block 文本截断 | 窗口改为跨 block 上下文切片 |

回归固化：`tests/test_condition_mentions_false_negative_regressions.py`（7 个永久 fixture：
跨 block 区间、depth/pitch、NA、kJ/cm2、表格单元、ODMR 拒绝、V1 假 LIST）。

## 3. Gate 判定

```
G1 无未解释的系统性漏检模式      PASS —— 37/37 全命中；9 类漏检全部定位根因并修复
G2 真参数被 REJECTED 为 0       PASS —— wrong-rejection rate = 0
G3 RANGE/LIST/SCALAR 表达正确   PASS —— 6 处 sweep（60-520/60-1850/2-445/22-450/2.3-7.0 nJ·J、
                                      1-500 kJ、2&4µm LIST）shape 全对
G4 parser/抽取问题分离登记       PASS —— 10 篇（SiC 切片）实验参数节在旧文本转储缺失属
                                      corpus 限制；本轮 PDF 解析已产出 45 条 mention
                                     （含红外体制暗示），text-coverage 判定属 parser 层
```

## 4. 仍登记的已知缺口（非 blocker，v0.2/Layer 3 处理）

| 缺口 | 说明 |
|---|---|
| cross-block 延续仅 60 字符 | 更长的跨块区间可能仍拆散；Layer 3 前按需加长 |
| 参数表语义类型（KEY_VALUE vs EXPERIMENT_ROWS vs FACTOR_LEVELS） | Layer 3 structural candidates 的输入，本层不做 |
| 表-正文冲突保留（F4）与 condition.role（F2） | 已在 schema v0.1 预留，Layer 3/4 实现 |
| 发射波长拒绝依赖最近词启发式 | 极端情形（发射词与 laser 等距）需人工复核；已登记 |

## 5. 产出

- 审计数据：`S0-2B7_PILOT_MENTION_AUDIT.jsonl`（5 篇 541 条 mention，含 page/provenance）
- 回归 fixtures：`tests/test_condition_mentions_false_negative_regressions.py`
- 5 篇 artifact JSON：`artifacts/scientific_documents/`（document_version_id 已随规则变更更新）

**Mention Gate 通过：可以进入 Layer 3 structural candidate edges。**
