# A1 核对工作包（source-coordinate missing，3 篇）

> 来源：`INTERACTION_STATE_CONSERVATISM_AUDIT.md` 类别 A。
> 任务：逐篇确认"人工标注 AVAILABLE 的坐标，论文是否真的报告了必需字段"，
> 并分类根因（提取漏检 / 条件编译丢失 / 论文报告形态）。

## 内容

```text
papers/                  3 篇 PDF（核对对象）
review_context.json      系统抽取 vs 人工标注对照
                          （mentions 全量 / 编译条件字段 / human_level2_available / notes）
```

## 初步根因（系统侧已自动分析，需人工用 PDF 复核）

### 1. 56485b9e（强化玻璃内部孔）—— 条件编译 singleton 丢失

```text
系统已抽取（ACCEPTED）：
    frequency 100 kHz（p2:b20）、scan_speed 30 mm/s（p2:b24）
    wavelength / pulse_width / average_power
编译条件字段只有：pulse_width / wavelength / average_power
    → frequency/scan_speed 作为孤立 mention 未构成条件（singleton 语义）
    → source 侧缺这两个字段 → pulse_interval/pulse_spacing 不可重建
```

**核对问题**：确认 PDF p2 中 100 kHz 与 30 mm/s 确实是加工参数
（与 pulse_width/wavelength 同属加工条件）。

**预期根因**：M6 条件编译的 singleton 语义（孤立 mention 不建条件）——
修复方向：SourceConditionSpec 支持 paper 级字段聚合（全部 ACCEPTED mention
的字段并集），不依赖条件编译。

### 2. a8b139（热障涂层镍基合金钻削）—— 无频率 mention

```text
系统抽取参数：average_power / length / magnification / pitch / spot_size
    → 无 frequency（无 kHz/MHz mention）
人工标注 AVAILABLE：pulse_interval（需要 frequency）、pulses_per_spot（需 frequency）
```

**核对问题**：
- PDF 是否报告了重复频率（如 "500 kHz"/"MHz"）？若有 → **提取漏检**（Layer 2 修复）
- 若没有 → 人工 AVAILABLE 的依据是什么（如从其他参数推导）？→ 记录为
  "坐标定义差异"（人工用了系统不消费的推导路径）

### 3. 5eba6f6a（CFRP 激光表面改性）—— 无 scan_speed/frequency mention

```text
系统抽取：fluence / na / pitch / wavelength / pulse_width / average_power / ...
    → 无 scan_speed、无 frequency、无 hatch_spacing
人工标注 AVAILABLE：line_energy（需 power+speed）、areal_energy（需 power+speed+hatch）、hatch_overlap
```

**核对问题**：
- PDF 是否报告扫描速度/频率/线间距？若有 → **提取漏检**（Layer 2 修复）
- 若论文只有 fluence 类报告（无 speed）→ 人工 AVAILABLE 依据？→ 坐标定义差异

## 输出

核对完成后在 `review_context.json` 每篇追加：

```json
{
  "paper_id": "...",
  "human_verdict": "EXTRACTION_MISS | COMPILER_SINGLETON | REPORTING_FORM | COORDINATE_DEFINITION_DIFF",
  "pdf_evidence": "p5: repetition rate of 500 kHz",
  "notes": ""
}
```

分类后按契约 UNCALIBRATED_CFA_V0_1 §6 的 A1 登记更新修复计划。
