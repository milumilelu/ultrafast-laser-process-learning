# INTERACTION_STATE_CONSERVATISM_AUDIT（③B root-cause 分析）

> 状态：**FROZEN**（2026-08-07）。基于 B1-25 baseline（v1）。
> 分析对象：11 篇 `Human PARTIAL / System UNKNOWN` 的 InteractionState 差异。

## 结论总览

```text
11 cases
├── G: predictor sampling bias      8 篇
└── A: source-coordinate missing    3 篇
（B/C/D/E/F/H 类在 B1-25 中未观察到）
```

## G 类：预测器抽样偏差（8 篇，真 bug，修 predictor 而非 CFA 内核）

`system_predictor._facet_summary` 只取 `reports[0]`（第一个编译条件），
而人工基于**主要加工条件**判断。8 篇论文的后续条件实际可产生
COMPARABLE 坐标：

```text
86dacaa…(glass 刻划)      cond1: PARTIAL(1)   ← 被 cond0 掩盖
8e8fcc…(冷却孔仿真)        cond1: PARTIAL(1)
ae1e95…(CFRP 表面处理)     cond3: PARTIAL(1)
fa290122…(发射率表面)      cond2/3: PARTIAL(1,1)
9f6aed…(玻璃陶瓷切割)      cond1: PARTIAL(1)
04(金刚石加工)             cond2: PARTIAL(1)
10(SiC 切片)               cond1/3: PARTIAL(1,2)
Flat-top(CFRP 织构)        cond1/2: PARTIAL(1,2)
```

**修复**：facet_summary 按"全部条件中 InteractionState 的最高判定"
（任一条件 PARTIAL → PARTIAL；全 UNKNOWN → UNKNOWN）汇总，
或明确采用"主要加工条件"（人工对齐的语义）。

## A 类：source-coordinate missing（3 篇，已核对，2026-08-07）

核对材料：`artifacts/b1_annotation/a1_review/`（review_context.json 系统抽取
对照 + review_context_reviewed.json 人工 PDF 复核 + papers/ 3 篇 PDF）。

```text
56485b9e…(强化玻璃内孔)     COMPILER_SINGLETON（已修复）
  PDF p3 Table 1：laser pulse frequency 100 kHz、average laser power 50 W、
  laser pitch 4–5 µm、pulse energy 140–200 µJ、cutting speed 10–30 mm/s。
  frequency/scan_speed 均为 ACCEPTED mention（100 kHz p2:b20、30 mm/s
  p2:b24），但未进入编译条件字段 → singleton 编译丢失，非提取漏检。
  → 修复：paper_level_spec 聚合（predictor 层 A1 fix，已生效）。

a8b139…(热障涂层镍基钻削)    EXTRACTION_MISS（登记为表格 GAP，demo 不做）
  PDF p5 Tables 3–4 明确报告 pulse Frequency 1000 / 500 / 50 Hz
  （斜孔 1000/500 Hz），并直接报告 Ton、Toff 与 'No of pulse'；
  系统无任何 frequency mention → 表格提取漏检。
  → 归类：表格提取 gap（freeze 记录"表格 GAP"），v0.2-demo 不修。

5eba6f6a…(CFRP 表面改性)     EXTRACTION_MISS（登记为表格 GAP，demo 不做）
  PDF p13 Table 7 明确报告 P=110–275 W、scanning speed v=1600–2400 mm/s、
  hatch distance dh=0.10–0.15 mm、spot ωz=677–1017 µm → 系统全部未抽取
  → 表格提取漏检。注意：本文为 ns fiber 激光（pulse_width 2022 ns），
  人工 AVAILABLE 标注含"用 v=(1-OLs)ωf 反推 f"的推导路径——系统不消费
  该路径（坐标定义差异成分已记录，主因仍是提取漏检）。
  → 归类：表格提取 gap，v0.2-demo 不修。
```

A 类结论：1 篇为编译层缺陷（已由 paper_level_spec 修复）；2 篇为表格
提取漏检（演示版明确 OUT OF SCOPE：Complete OCR re-ingestion / 表格
再提取）。3 篇均**不涉及 CFA 内核语义**，无需改变 facet 逻辑。

## 未观察到的类别（B1-25 无证据）

```text
B target blocked / C spot unverified / D power missing
    → 这些是 Target 侧系统性阻塞，在 25 篇中一致存在，但 11 篇差异
      的主因不是它们（target 固定，两侧一致）
E namespace mismatch / F formula too strict / H human 用额外坐标
    → 未成为 11 篇差异主因
```

## 后续约束

- G 类修复属于 predictor 层（不改 CFA 内核语义）。
- A 类修复属于 M6/mention 层，需逐篇证据确认后才动。
- 任何修复后的回归验证：B1-25 只作 dev set；severe=0 必须保持。
