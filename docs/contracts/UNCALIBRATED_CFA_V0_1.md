# UNCALIBRATED_CFA_V0_1（M9 契约）

> 状态：**FROZEN**（2026-08-07）。
> 目标：faceted applicability（五 facet）第一次可运行；**无任何概率声明**。
> 关联：`CANONICAL_PHYSICS_V0_1.md`（M8）、`SOURCE_RECONSTRUCTIBILITY_V0_1.md`（M6）、
> `TARGET_PHYSICS_READINESS_V0_1.md`（M7）。

## 0. 硬规则（冻结）

```text
1. 无 probability / confidence / transfer 数字——任何地方都不输出。
2. Unknown != Mismatch：缺值 -> UNKNOWN/partial，永不判 MISMATCH。
3. UNVERIFIED 坐标不进入比较（compare_canonical 的 UNVERIFIED 透传，
   Interaction-State facet 只统计 COMPARABLE / INCOMPARABLE）。
4. calibration_status = "NOT_YET_CALIBRATED"（固定值）。
```

## 1. 五 facet（冻结）

```text
Material            material_source vs material_target
                    KNOWN（相等）/ MISMATCH（明确不等）/ UNKNOWN（缺值）
Task                laser_type / process_type / geometry_type / target_metric
                    每维 match|unknown|mismatch；facet 状态：
                    任一 mismatch -> MISMATCH；有 unknown -> PARTIAL；全 match -> KNOWN
InteractionState    每坐标 COMPARABLE / UNVERIFIED / INCOMPARABLE
                    全可比 -> KNOWN；部分 -> PARTIAL；全不可比 -> UNKNOWN
Reconstructibility  source 侧 AVAILABLE 坐标数 / 总数（KNOWN/PARTIAL/UNKNOWN）
Reachability        target 侧 AVAILABLE 坐标数 / 总数（KNOWN/PARTIAL/UNKNOWN）
```

## 2. 输出（冻结）

```text
UncalibratedCFAReport
    version: uncalibrated-cfa-v1
    calibration_status: NOT_YET_CALIBRATED
    evidence_claim_id
    facets[5]
    warnings[]（UNKNOWN 非 mismatch 提示 + 未验证坐标清单）
```

## 3. 消费边界（冻结）

- Reconstructibility / Reachability 是 readiness 投影，不是加权分数。
- InteractionState 的 UNVERIFIED 坐标由 warnings 列出，CFA 下游不得消费。
- 单篇 evidence 可以是部分 facet KNOWN 部分 UNKNOWN——faceted 设计不允许
  "缺 fluence → CFA 整体失败"。

## 4. 验收（冻结）

```text
G1  五 facet 齐备且形状稳定（测试）
G2  全报告无概率/置信度/transfer 字段（测试强制）
G3  material 缺值 -> UNKNOWN 而非 MISMATCH（测试）
G4  unverified 坐标在 facet 中标记且 warning（测试）
G5  Tier A 坐标双侧 AVAILABLE -> InteractionState 至少 PARTIAL（测试）
```

## 5. B1-25 验证附录（FROZEN 2026-08-07）

```text
Validation dataset:  B1 25-paper audit（冻结为 diagnostic/dev set）
Baseline version:    uncalibrated-cfa-v1
severe = 0 / conservative_miss = 19 / information_gap = 0 / consistent = 69
```

- 完整报告：`docs/validation/UNCALIBRATED_CFA_V1_B1_VALIDATION.md`。
- **B1-25 从冻结时刻起不得作为 v1.1+ 的独立 test set**。
- 版本纪律：v1（baseline）→ v1.1（metadata 输入 + InteractionState 修复，
  五 facet 不变）；v1.1 对 B1-25 只报 dev regression，不报泛化指标。
- 安全性质回归约束：severe = 0 不可被任何覆盖率改进破坏。
- 发布 v1.1 前保留 CFA validation holdout（10–15 篇未见样本）。

## 6. v1.1 dev regression（FROZEN 2026-08-07，development set only）

```text
version: uncalibrated-cfa-v1.1
改动:    ③A EvidenceMetadata → Material/Task（metadata gold 输入）
         ③B-G InteractionState 汇总修复（全部条件而非第一个）
         材料族规范化（HPSI 4H-SiC / 4H-SiC → sic 等）
结果（B1-25 dev）:
    severe              0          （保持，第一回归约束 ✓）
    conservative_miss   2          （仅 2 篇无 metadata）
    consistent         114         （baseline 69 → 114）
    Material           KNOWN/KNOWN 3 | MISMATCH/MISMATCH 19 | MISMATCH/UNKNOWN 2 | UNKNOWN/UNKNOWN 1
    Task               MISMATCH/MISMATCH 22 | MISMATCH/PARTIAL 3
    InteractionState   PARTIAL/PARTIAL 19 | PARTIAL/UNKNOWN 3 | UNKNOWN/PARTIAL 2 | UNKNOWN/UNKNOWN 1
    Reconstructibility PARTIAL/PARTIAL 24 | UNKNOWN/PARTIAL 1
    Reachability       PARTIAL/PARTIAL 25
```

剩余已知缺口（dev，未修，按 ③B 结论需逐篇证据后处理）：

```text
A1  3 篇源坐标缺失（PARTIAL/UNKNOWN）：56485b/a8b139/5eba6f6a
    —— mention/条件覆盖需逐篇核对（提取漏检 vs 报告形态）
A2  2 篇无 metadata（MISMATCH/UNKNOWN）：ae1e95/fa290122
    —— conservative miss（安全方向）
A3  InteractionState UNKNOWN/PARTIAL 2：同 A1 根因
```

数据：`benchmarks/cfa_confusion/results/b1_25_dev_v11.json`。
根因分析：`docs/validation/INTERACTION_STATE_CONSERVATISM_AUDIT.md`。
此结果**不构成** v1.1 的泛化证据；独立验证需新的未见 holdout。

## 7. A1 修复登记（2026-08-07，dev）

人工核对（`artifacts/b1_annotation/a1_review/`）三篇 verdict：

```text
56485b9e  COMPILER_SINGLETON  → resolved
a8b139    EXTRACTION_MISS（表格） → 已登记
5eba6f6a  EXTRACTION_MISS（表格） → 已登记
```

### 已修复

```text
1. COMPILER_SINGLETON（56485b9e）
   paper_level_spec()：paper 级字段聚合（PROCESS_CONTEXT 优先、
   UNCLEAR 兜底、测量语境排除、冲突保留），predictor 以
   per-condition ∪ paper-level 的最高判定汇总。
   结果：56485b9e InteractionState UNKNOWN → PARTIAL

2. detect.py 表格检测（EXTRACTION_MISS 部分修复）
   caption 窗口内的紧凑数值 heading 块纳入行块判定
   （section_builder 把行号开头表格误标 heading）。
   影响：区域检测 0→1（a8b139）/0→8（5eba6f6a）；
   图/条件行为不变（新增区域无 cells，等价性测试保持）。
```

### 已登记（单元格级解析，独立工程）

```text
a8b139  Table 3-4：频率 1000/500/50 Hz 在实验表（行号开头、数值列
        无单位跟随）→ detect 已识别区域，但 classify 单元格解析
        不支持"表头行分离 + 数值行无 label/unit"结构 → 无 cell。
5eba6f6a Table 7：P/v/dh/spot 同为表头分离结构。
修复路径：表头-列映射的表格 cell 解析（独立任务，登记 GAP）。
```

### 表格 GAP 细化（2026-08-07 二轮）

```text
已交付：
  - detect：heading 化行块纳入（section_builder 行号误判）✓ 等价性保持
  - classify：header-column fallback（表头块在 region 内时按列映射）✓
  - paper_level_spec 纳入 TABLE_CELL 候选 ✓（链路完整性）

仍为 GAP（登记）：
  - 跨块表头（表头与数据行相隔 >10 块、多表共享表头）：detect 的
    header 候选收集曾破坏 Paper 11 等价性（used 归属竞争）→ 已回退。
    需表头-表格归属建模（架构级），独立任务。
  - Table 7 类表头缺失（表头文本在 PDF 中分散/无 caption 关联）。

影响：a8b139/5eba6f6a 的 frequency/speed/hatch 仍无法从表格进入
paper 级评估（InteractionState PARTIAL/UNKNOWN 2 篇保留，dev 记录）。
```

A1 修复后的 v1.1 dev（B1-25）：

```text
consistent         114（含修复前同值，56485b9e 归位 PARTIAL）
InteractionState   PARTIAL/PARTIAL 20 | PARTIAL/UNKNOWN 2（a8b139/5eba6f6a）
severe             0（保持）
```
