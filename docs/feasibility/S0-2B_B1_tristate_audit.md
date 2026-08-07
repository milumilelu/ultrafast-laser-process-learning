# S0-2B B1 — Tri-State Physical-Field Audit（协议与首批标注）

> 目的：回答"目标相关论文到底报告了多少足以建立 SourceConditionSpec 的物理条件"。
> 方法：人工读原文（`work/texts/` 全文 txt 转储，必要时回原 PDF）逐字段三/四态标注。
> 状态：协议冻结 + 首批 3 篇示例标注；其余 14 篇列入工作表。

## 1. 标注状态定义（四态）

| 状态 | 含义 |
|---|---|
| REPORTED_CLEAR | 原文明确报告，值+单位+定义可解析，可直接进入 SourceConditionSpec |
| REPORTED_AMBIGUOUS | 原文报告但物理语义有歧义（见 ambiguity 表） |
| NOT_REPORTED | 读完全文未报告（或文本转储不完整，标注 NOT_REPORTED+note 区分） |
| NOT_APPLICABLE | 该 Evidence 类型/实验设计下本字段无意义（如单线扫描无 hatch） |

每个 REPORTED_CLEAR 记录：`raw_value, unit, normalized_value, evidence_span(页), definition`
每个 REPORTED_AMBIGUOUS 记录：`ambiguity_reason`

## 2. Ambiguity Reason 枚举（冻结）

```
SPOT_RADIUS_OR_DIAMETER_UNKNOWN
SPOT_DEFINITION_UNKNOWN            (1/e vs 1/e2 vs FWHM vs D4σ)
INCIDENT_OR_POST_OBJECTIVE_POWER_UNKNOWN
PEAK_OR_AVERAGE_FLUENCE_UNKNOWN
ABSORBED_OR_INCIDENT_UNKNOWN
SINGLE_OR_ACCUMULATED_UNKNOWN
MULTIPLE_EXPERIMENTAL_CONDITIONS   (多组条件未分离，无法对应单一 SourceConditionSpec)
PULSE_WIDTH_REGIME_ONLY            (只说 ps/fs 无具体值)
FLUENCE_DERIVED_ONLY               (只有剂量/能量组合量，单脉冲量需推导)
```

## 3. 字段网格（16 字段，四组）

| 组 | 字段 | 备注 |
|---|---|---|
| Laser | wavelength, pulse_width, frequency, average_power, pulse_energy | power 区分 incident/post-objective（注在 definition） |
| Beam | spot_size, spot_size_type, beam_profile | spot_size_type: DIAMETER/RADIUS+definition；profile: GAUSSIAN/FLAT_TOP/UNKNOWN |
| Motion | scan_speed, hatch_spacing, passes | passes 对多脉冲站点实验标 NOT_APPLICABLE+note |
| Task | material, material_grade, geometry, process_type, target_metric | 供 Task facet 与分层 |

## 4. 首批示例标注（3 篇，协议示范）

见 `S0-2B_B1_annotations.jsonl`。要点：

- **04_arxiv_2502.16530**（Diamond，30-fs 光烧蚀加工）：报告率最高的目标论文。
  wavelength 800nm CLEAR / pulse_width 30fs CLEAR / frequency 1kHz CLEAR /
  pulse_energy 0.8mJ CLEAR / spot ≈15μm CLEAR（**definition=1/e 强度直径**，与物理引擎
  w0(1/e²) 需换算系数，计入 definition 而非 ambiguity）/ beam_profile NOT_REPORTED
  （未声明高斯，仅"beam profiler 测量"）/ scan_speed NOT_REPORTED（提及平移速度但未给值）/
  hatch NOT_APPLICABLE（单线道）/ passes NOT_APPLICABLE（用脉冲数 n=100–10000 站点替代；
  **同时报告 accumulated dose = fluence×n（1–500 kJ/cm²），REPORTED_CLEAR**）/
  material CVD type-Ib <100> 200ppmN CLEAR / 目标 Ra+MRR CLEAR /
  烧蚀阈值 ~3 J/cm² 为引文值（非实测）→ 阈值 NOT_REPORTED(实测)，cited 值记录。
- **Flat-top picosecond laser texturing of CFRP**：fluence 2.3–7.0 J/cm² CLEAR /
  beam_profile FLAT_TOP CLEAR / pulse_width PULSE_WIDTH_REGIME_ONLY(AMBIGUOUS) /
  wavelength/frequency/power/spot_size/scan_speed/hatch 在**现有文本转储中未出现**
  （NOT_REPORTED+note"转储可能不完整，需回 PDF 确认"）。
- **10_arxiv_2411.18093**（4H-SiC ps 垂直切片）：material 4H-SiC(6寸,多焦点) CLEAR /
  process slicing(CLEAR) / **全部 Laser/Beam/Motion 字段 NOT_REPORTED（文本转储不含
  实验参数节，需回原 PDF）**——转储不完整是当前 B1 的主要操作约束。

## 5. B1 发现（进入 B2 schema 决策的输入）

1. **文本转储不完整**：work/texts 对部分论文只有引言/方法片段（SiC 切片论文完全缺失
   实验参数节）——B1 必须对每篇标注 "text coverage" 状态（COMPLETE / PARTIAL / MISSING），
   PARTIAL 需回原 PDF，否则 NOT_REPORTED 不可信。
2. **报道模式倾向**：实验性加工论文普遍报告 wavelength/pulse_width/frequency/pulse_energy/
   fluence/spot（Diamond 论文 6/6）；扫描类论文的 scan_speed/hatch 报告率需更多样本。
3. **spot definition 是最高频的潜在歧义**：Diamond 论文明确 1/e，但多数论文只说
   "spot diameter" 不定义——B2 必须把 spot_size_type+definition 作为结构字段。
4. **accumulated dose（fluence×n）在烧蚀论文中是常见报告量**（Diamond 论文）——
   对应物理引擎的 accumulated_fluence 坐标，建议 B2 把它纳入 Laser 组字段。

## 6. 工作表（剩余 14 篇 TARGET_RELEVANT + 11 篇 UNCERTAIN 候选）

- TARGET_RELEVANT 余 14：03_arxiv_2605.26251 / 13_arxiv_2411.18868 / 21_arxiv_2507.14047 /
  22_arxiv_1806.05412 / 23_arxiv_1701.05885 / 24_arxiv_1705.10285 / 29_arxiv_1711.09140 /
  30_arxiv_1605.01854 / 5c1d8afec21906f9 / 60e5539a0877178d / a2cd5a8236cbbccc(中文) /
  eaf23bb875dc2f05(中文) / Polarization dependence of laser interaction with carbon fibers and CFRP /
  (04 与 Flat-top 已标)
- UNCERTAIN 待读（读后决定相关性与条件）：11 篇（含 CFRP/Ti 钻孔策略、Bessel 金刚石等）
- 每篇输出同 schema 的 annotation 记录 + text_coverage + notes

## 7. B1 出口标准

- 全部 TARGET_RELEVANT（17 篇）完成四态标注（含 text_coverage 判定）；
- 产出 §8 报告率矩阵；
- 未达到 20–25 篇时从 UNCERTAIN 晋升补充。
