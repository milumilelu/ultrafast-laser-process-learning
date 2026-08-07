# S0-2B B1 — Multi-Condition Reference Annotation（11 / 13）

> 目的：验证 `EXPERIMENTAL_CONDITION_SCHEMA_V0.1` 能否表达复杂论文；固定 multi-condition
> linker ground truth（先于 parser 实现，防止实现反向污染 gold）。
> 机器可读版本：`S0-2B_B1_REFERENCE_11_13.jsonl`
> 人工统计：见 §3（expected_condition_count / expected_field_assignments）

---

## 1. 六问回答

### Paper 11（11_arxiv_2404.09906，SiC 光致发光，fs 辐照）

1. **可确定的 experimental conditions 数**：**4 个**（2 加工 + 2 表征）；**加工条件 = 2**：
   - C01 石墨烯样品写入（§III）：1030 nm / 383 fs / 频率 AMBIGUOUS / 2.4 µm@1/e²（计算值，空气中）/ NA 0.4 / 线偏振 / 60–520 nJ 扫参
   - C02 原始样品写入（§IV）：同激光同光学，**100 kHz 显式** / 60–1850 nJ 扫参
   - C03/C04 = CLSM1（737.19 nm Ti:Sa，4.3 K）与 CLSM2（785 nm CW + <100 ps 超连续）**表征条件**（process_type=characterization，不进入 CFA 加工条件集）
2. **只能部分重建的 condition**：C01（频率无法确定：系统规格同时给 "repetition rate 10 kHz" 与 "up to 1 MHz capability"——写入频率与系统能力未分离，标 LINKAGE 歧义，不猜）
3. **全局继承字段**：wavelength=1030nm、pulse_width=383fs、spot=2.4µm@1/e²、光学（NA 0.4 + 线偏振）→ 由 C01、C02 共享（GLOBAL_TO_EXPERIMENTS）
4. **不能证明同实验的字段**：C01 频率（10 kHz vs 1 MHz 能力）与 C02 频率（100 kHz）——分属不同实验组，MUTUALLY_EXCLUSIVE
5. **表格—正文冲突**：Table I 是**对比表**（KEY_VALUE_SETUP 型，含 Ref19/Ref33 前作参数），非本论文全部条件——正文条件（1030nm/383fs）与表内 "This work" 行一致，无冲突；但**表内 Ref 行不得进入本论文条件集**（scope=COMPARISON）
6. **无法消解的双体制**：无（双"样品"而非双体制；频率歧义在 C01 内为字段级 LINKAGE_AMBIGUOUS）

### Paper 13（13_arxiv_2411.18868，SiC 近红外发光中心写入）

1. **condition 数**：**4 个**（**加工 = 1** + 表征 3）：
   - C01 激光写入：515 nm / 230 fs / **200 kHz** / NA 0.90（100×）/ 点阵 5 µm 间距 / **2 与 4 µm 两个深度层** / 2–445 nJ 能量扫参 / N 掺杂 4H-SiC（1e19 cm⁻³，SiCrysta）
   - C02 RT/低温共聚焦（976 nm CW）；C03 寿命测量（**800 nm / 40 MHz** 超连续）；C04 自旋控制（914 nm CW + 微波）
2. **只能部分重建**：C01 无 spot 尺寸（只给 NA）——beam 组仅 NA 可算，spot 缺失不补
3. **全局继承**：515nm/230fs/200kHz/NA0.9/材料 → C01 内全局（PAPER_GLOBAL 加工条件）
4. **不能证明同实验的字段**：**200 kHz（写入）vs 40 MHz（寿命测量）**——不同系统不同角色，MUTUALLY_EXCLUSIVE，**禁止融合**（本 reference 的核心测试点）
5. **表格—正文冲突**：**存在**——写入能量范围正文 "2 nJ/pulse to 445 nJ/pulse" vs 成像节 "450 nJ to 22 nJ"（22–450）：两值并存保留，标 TABLE_TEXT_CONFLICT，不裁决
6. **无法消解的双体制**：**无**（40 MHz 非写入体制；写入只有 200 kHz 一个体制）

## 2. Mention Relation Graph（ground truth，linker 直接对照）

见 JSONL `relations` 段。要点：
- Paper 11：M1/M2/M3/M4（波长/脉宽/光斑/光学）--GLOBAL_TO_EXPERIMENTS--> C01+C02；M5(10kHz) --SAME_EXPERIMENT--> C01（LINKAGE_AMBIGUOUS）；M6(100kHz) --> C02；M5 与 M6 MUTUALLY_EXCLUSIVE
- Paper 13：M7(200kHz) 与 M8(40MHz) **MUTUALLY_EXCLUSIVE**（写入 vs 表征）；M9("25W"=ZHL-25W-272+ 放大器型号) 与 M10（发光中心 ZPL 发射波长 1132/1038/1241 nm 等）= **NOT_A_PROCESS_PARAMETER**——两类假 mention 测试点

## 3. 人工统计（parser/linker 输出对照基准）

| paper | expected_condition_count | expected_processing_conditions | expected_field_assignments |
|---|---:|---:|---:|
| 11 | 4 | 2 | 24 |
| 13 | 4 | 1 | 15 |

Condition Assignment Matrix（linker 必须能输出的格式，示例节选）：
```
Paper 13:
mention\cond   C01(writing)  C02(976nm)  C03(800/40MHz)  C04(914nm)
515nm 230fs        1            0            0              0
200kHz             1            0            0              0
40MHz              0            0            1              0
25W(model)         0            0            0              0   <- 必须拒绝
```

## 4. Schema 发现（v0.1 需 v0.2 修订项，冻结前确认）

| # | 发现 | 建议 |
|---|---|---|
| F1 | **ConditionField 是标量，无法表达 factor-level sweep**（11: 60–520 nJ；13: 2–445 nJ 能量扫参、2&4µm 双深度） | v0.2 增加 `sweep` 子结构（FACTOR_LEVELS / RANGE / EXPLICIT_LIST），value 支持 multi-value |
| F2 | 表征条件（CLSM/寿命/自旋）与加工条件并存，CFA 只消费加工条件 | v0.2 增加 `condition.role: PROCESSING \| MEASUREMENT \| COMPARISON`（已在本次标注中使用，待正式化） |
| F3 | 假 mention 高发源：发射波长（ZPL）、设备型号（ZHL-25W-272+）、系统能力规格（"up to 1 MHz"） | deterministic mention 抽取必须带 parameter-context 校验；这两篇是 precision 测试点 |
| F4 | 表—正文数值冲突（13: 2–445 vs 22–450）要求双方保留 | v0.2 冲突保留语义已在标注中使用（conflicts 段），需进 schema |
| F5 | 系统规格与使用频率未分离（11 的 10 kHz vs 1 MHz） | 字段级 LINKAGE_AMBIGUOUS 表达已足够，无需改 schema |

**结论**：v0.1 schema 能承载两篇复杂论文的全部结构与关系（F1/F2 需 v0.2 小修，不阻塞
B7 linker 设计——linker 直接按本 reference 的关系图开发）。**reference 已冻结，parser
不得影响其内容。**
