# CFA V2.0 BUG-FIX CONTRACT（③）

> 状态：**签署**（2026-08-07）。
> 范围纪律：**只修两处确定性语义 bug，不借机扩算法、不调整 facet aggregation、
> 不改 metadata normalization、不改校准。**
> 依据：`artifacts/cfa_holdout/HOLDOUT_VALIDATION_RESULTS.md`（v1.1 holdout 判定）。

## 0. 版本堆栈变化

```text
CFA version:             uncalibrated-cfa-v2.0（= v1.1 + 两处 bug-fix）
BASE:                    v1.1 frozen stack（CFA_V1_1_EVALUATION_CANDIDATE_FREEZE.md）
仅修改：
  ① reconstructibility coordinate 判定（V2-1）
  ② 值形状语义：POINT / RANGE / SET / SWEEP（V2-2）
```

## 1. V2-1：Dependency-aware reconstructibility

**错误**（v1.1，`src/ultrafast_reconstructibility/coordinates.py:96-102`）：

```text
peak_fluence_J_m2 / areal_energy_J_m2
→ 无条件 RECONSTRUCTIBLE（即使 value=None、依赖全缺）
```

**修复**：统一回冻结 P1（Formula Registry 权威）——所有 coordinate
（含 J_m2 别名）必须满足：

```text
RECONSTRUCTIBLE
  ⟺ 依赖链真实满足：
     (a) 论文直接报告该坐标（REPORTED_CLEAR 的 point 值），或
     (b) get_formula(coordinate).required_inputs 全部可得
         ∧ compute_chain 成功
         ∧ missing_inputs == ∅
否则 → 依赖链真实状态（NOT_REPORTED / AMBIGUOUS / DEPENDENCY_MISSING /
        TEXT_COVERAGE_BLOCKED），绝无 coordinate-specific bypass。
```

J_m2 坐标为 Formula Registry 公式的**别名**，走同一条 compute_chain。

**全局 invariant test（V2-G2）**：

```text
对每个注册坐标：
  status == RECONSTRUCTIBLE
  ⇒ (直接报告 point 值) ∨ (compute_chain 成功 ∧ missing_inputs == ∅)
```

此后任何坐标出现类似 shortcut 都会被测试拦下。

## 2. V2-2：RANGE / SET / SWEEP ≠ POINT

**错误**（v1.1）：`0.2–25 MHz` → 取 `0.2 MHz` → `pulse_interval` 变确定值
→ COMPARABLE → InteractionState PARTIAL（3 个 H3 failure 的共同根因）。

**修复**：值形状显式语义，至少：

```text
POINT       frequency = 200 kHz
RANGE       frequency = 0.2–25 MHz
SET/SWEEP   frequency = {10, 100, 1000} kHz
```

- 禁止以 `range.lower`（或首值）作为代表值调用公式。
- RANGE 坐标确定性变换（如 `T = 1/f` ⇒ `T ∈ [1/f_high, 1/f_low]`），
  本版允许保守简化：
  - source coordinate shape = RANGE/SET/SWEEP（或来源含范围词）
    → 该坐标不得 AVAILABLE，标记 AMBIGUOUS（blocking: 值形状非 point）；
  - 因而 Interaction comparison 至多 AMBIGUOUS/PARTIAL，**绝不伪装
    COMPARABLE**（V2-G3、V2-G4）。

## 3. v2 准入测试（V2-G1..G5）

```text
V2-G1  B1-25 severe = 0（回归）
V2-G2  任何 dependency-missing coordinate 不得 RECONSTRUCTIBLE（invariant）
V2-G3  RANGE/LIST/SWEEP 不得静默降格为 point（值形状测试）
V2-G4  unverified / range-derived coordinate 不得提供确定性
       InteractionState positive evidence
V2-G5  v1.1 已正确的 Material / Task / metadata 行为不回退
       （B1-25 五 facet 逐项对比，除两 bug 相关外 status 不变）
```

## 4. 回归与验证（原 13 篇语义降级）

```text
B1-25 regression                    → V2-G1/G5 准入
former 13-paper（v2 diagnostic）    → 预期：
                                      H3 failures 3 → 0
                                      H5 bug 分歧 5 → 0
                                      severe 保持 0
                                      表述固定为 "v2 regression on former
                                      v1.1 holdout"，不得称独立验证
```

> **2026-08-07 结果**：全部准入 PASS（见 `artifacts/cfa_holdout/
> V2_REGRESSION_RESULTS.md`）。H3 bug 部分 3→0、H5 bug 分歧 5→0、
> severe=0、B1-25 无回退。残余差异 3 类（burst 定义歧义 269fe3；
> 主值被 RANGE mention 吞并 + 表格噪音 CONFLICT + facet_summary 取首报告
> 导致的保守方向 UNKNOWN），全部根因清晰、非本次两 bug、登记 v2.1+。

## 5. v2 独立验证（新 unseen holdout）

- 10–15 篇未见论文，独立于 B1-25 与旧 13 篇。
- 选择标准**先于运行冻结**；结果出来前：不看预测、不改规则、不改
  metadata normalization、不改 range policy、不改 facet aggregation。
- 人工三层标注 → 新 H1–H5 判定 → 全部通过才可称：

> **Uncalibrated CFA v2 has passed independent scientific validation.**

### 5.1 新 holdout 选择标准（2026-08-07 冻结，内容事实只读，不跑管道）

```text
池：
  A = literature_metadata/gold/annotations.jsonl 覆盖的论文（质量保证）
  B = 无 metadata 的加工论文（H2 覆盖，上限 3 篇）
排除（仅文件名/metadata 内容事实）：
  - B1-25（25 篇）与旧 13 篇 holdout
  - 文件名含 CJK（中文论文）
  - 非加工关键词：x-ray / synchrotron / lens / optics / photodetector /
    plasma / hygrothermal / thermal cycling / thermal residual / bonding
  - metadata: laser_type ∈ {CO2, ns, nanosecond}；process = non_laser_reference
分层（材料族优先多样性，glass 上限 3）：
  - 材料族尽量覆盖 sic / diamond / cfrp / glass / metal / polymer / ceramic
  - 任务：drilling / micromachining / cutting / surface_texturing / 其他
  - 激光：fs / ps 均覆盖；含 ≥1 篇无 metadata（H2）
规模：12 篇（范围 10–15）
纪律：选择期间不运行任何预测；选定后冻结不再增删。
```

### 5.2 冻结记录（2026-08-07，选定后不增删）

```text
11 篇（范围 10–15 内），清单：artifacts/cfa_holdout/holdout_v2_frozen.json
  diamond ×5  全部 metadata micromachining（fs）：1aec7d / 34af64 / 4005b7 /
              bbe6d4 / dd2760
  glass   ×3  179b11（ultrashort-pulse 钻孔仿真）· 3262a7（激光微钻监测）·
              4ae395（ps 水辅助切割 —— ps 覆盖）
  no-meta ×3  3c0cf5（fs 烧蚀阈值，金属类）· 5b039f（fs 液相加工）·
              86ddae（fs 锗加工 —— H2 覆盖）
排除记录（内容事实）：CO2 激光（021689 文件名）、thermal cycling/residual
（6fc9a/f95ada）、filamentation 诊断（3c5bbd）、unknown-content diamond
（5c8c71/9c3ee6）、task2_*（目标 fixture 来源，不作独立证据）、全部 CJK。
池约束（登记）：metadata gold 池中 sic/metal/polymer/ceramic 已耗尽或为
零、cfrp 仅剩被排除论文 → 材料多样性受池限制，diamond 占比高为固有分布。
验证：与 B1-25 及旧 13 篇零重叠（脚本校验）；未运行任何预测。
标注模板：artifacts/cfa_holdout/gold_holdout_v2_level1_2_3.jsonl（空槽）
PDF：artifacts/cfa_holdout/papers_v2/
```

## 6. Calibration Feasibility Gate（推迟）

- 正式 D1–D4 Gate 在 v2 独立验证通过之后。
- 当前**允许并行**：D1–D4 数据资产盘点（inventory：target tasks 数、
  transfer outcomes 数、outer-split 可行性、样本量下 calibrator 复杂度上限）。
- **禁止**：fit calibrator、选择 calibration mapping、比较 calibrated scores、
  根据旧 13 篇结果设计 calibration 函数。
