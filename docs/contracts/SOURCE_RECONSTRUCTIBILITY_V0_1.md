# SOURCE_RECONSTRUCTIBILITY_V0_1（M6 契约）

> 状态：**FROZEN**（2026-08-07）。
> 目标：回答"文献读取出的 condition 能否科学地重建成足够完整、可信的
> source state，并支撑 Physics Canonicalization / CFA"。
> 关联：`EXPERIMENTAL_CONDITION_SCHEMA_V0.2.md`（condition 契约）、
> `CONTRACT_V2_FREEZE.md`（physics 公式 registry）、
> `T2_VERTICAL_SLICE_V0_1.md`（M5.5 工程切片）。

## 0. 定位（冻结）

M5.5 已证明工程集成；M6 开始证明**科学有效性**：

```text
ScientificCandidate / ExperimentalConditionSpec
        ↓
SourceConditionSpec（physics-consumable 投影）
        ↓
Physics dependency evaluation（复用 Formula Registry，P1）
        ↓
SourceReconstructibilityReport / SourcePhysicsReadiness
```

## 1. 五种"不知道"必须分开（hard invariant）

```text
NOT_REPORTED                论文未报告该参数
TEXT_COVERAGE_BLOCKED       解析/文本覆盖不足，无法判定（≠ 论文没报告）
REPORTED_AMBIGUOUS          报告但歧义（冲突保留 / LINKAGE_AMBIGUOUS）
PHYSICS_DEPENDENCY_MISSING  字段齐全但物理依赖缺失（设备/材料属性，如 Fth）
NOT_APPLICABLE              该坐标对该条件无意义
```

- 历史教训（Paper 10 类全文 dump 不完整）："参数没抽到" 不得解释为
  "论文没报告"。coverage 状态来自**解析层审计**（M6-1 adapter 输入），
  不是从字段缺失反推。
- `REPORTED_AMBIGUOUS` 直接映射自 `ConditionField.status`：
  REPORTED_CLEAR → 明确；CONFLICT_PRESERVED / LINKAGE_AMBIGUOUS → 歧义。

## 2. SourceConditionSpec（M6-1，冻结）

```text
SourceConditionSpec
    condition_id
    paper_id
    document_version_id
    role / scope
    coverage_status: TEXT_COVERAGE_OK | TEXT_COVERAGE_PARTIAL | TEXT_COVERAGE_UNKNOWN
    fields: {parameter -> SourceField}
        SourceField:
            values: list[float]        # SI 无关，保持 condition 原值
            unit: str
            field_status: REPORTED_CLEAR | CONFLICT_PRESERVED | LINKAGE_AMBIGUOUS
            provenance_anchor_ids[]
```

- 由 `ExperimentalConditionSpec` 确定性投影（无新抽取、无新语义判断）。
- coverage_status 由解析层审计提供（pilot 5 篇当前 = TEXT_COVERAGE_OK；
  旧 dump 缺口场景由重解析后审计更新——机制保留，不硬编码）。

## 3. Physics dependency evaluation（M6-2，冻结）

- **禁止**自写 `if spot and energy: fluence = ...`（P1）。
- 唯一判据：`ultrafast_physics.registry.get_formula(id).required_inputs` +
  `PhysicsFeatureEngine.compute` 的 `missing_inputs`。
- condition canonical 参数 → 引擎输入名（确定性映射，冻结）：

```text
frequency → frequency_Hz         pulse_width → pulse_width_s
scan_speed → scan_speed_m_s      hatch_spacing → hatch_spacing_m
passes → passes                  pulse_energy → pulse_energy_J
average_power → laser_power_W    spot_size → spot_diameter_m
fluence → peak_fluence_J_m2（已报告坐标，直接可消费）
accumulated_dose → areal_energy_J_m2（已报告坐标）
```

- 单位换算由 engine 统一处理（`ultrafast_shared.units.convert`）。
- spot_size 为直径约定：`spot_diameter_m` 可直接提供；
  `beam_radius_m = d/2` 是确定性推导（feature_builder 既有约定）。
- 缺失输入归类：

```text
输入来自 condition 字段：
    字段存在且 REPORTED_CLEAR → 提供
    字段 CONFLICT_PRESERVED / LINKAGE_AMBIGUOUS → 该坐标 REPORTED_AMBIGUOUS
    字段缺失（coverage OK）→ NOT_REPORTED
    字段缺失（coverage PARTIAL/UNKNOWN）→ TEXT_COVERAGE_BLOCKED
输入是设备/材料属性（beam_radius / ablation_threshold / thermal_diffusivity）：
    → PHYSICS_DEPENDENCY_MISSING（source 侧永不提供设备属性）
```

## 4. 报告对象（M6-3，冻结）

### SourceReconstructibilityReport（per condition）

```text
paper_id / condition_id
reported_fields[]        # 明确报告
ambiguous_fields[]       # CONFLICT_PRESERVED / LINKAGE_AMBIGUOUS
missing_fields[]         # NOT_REPORTED（coverage OK 时）
coverage_blocked_fields[]  # TEXT_COVERAGE_BLOCKED
computable_physics_coordinates[]   # {coordinate, value, unit, formula_version, approximate}
blocked_physics_coordinates[]      # {coordinate, status, missing_inputs[]}
blocking_dependencies[]            # 阻塞的输入名（去重）
reconstructibility_status: FULL | PARTIAL | BLOCKED
warnings[]
```

### SourcePhysicsReadiness（Source 侧聚合，与未来 Target 对称）

```text
reported_field_count / ambiguous_field_count / missing_field_count
computable_coordinate_count / blocked_coordinate_count
coordinate_status: {CoordinateStatus -> 出现次数}   # 聚合语义（修订注：跨条件
                    # 聚合时按状态计数；per-condition 的坐标状态在 report 内）
reconstructible_conditions / total_conditions
```

## 5. M6 分步（冻结）

```text
M6-0  本契约
M6-1  ExperimentalConditionSpec → SourceConditionSpec adapter
M6-2  Physics dependency evaluator（Formula Registry 复用）
M6-3  SourceReconstructibilityReport / SourcePhysicsReadiness
M6-4  5 篇 pilot reference 验证（测试 + 统计）
M6-5  批量 audit runner（226 篇 archive 可跑；17/25 篇 B1 标注后统计）
M6-6  CFA V1 candidate physics coordinates 冻结（依 M6-4/5 统计）
```

## 6. 文件布局与包边界（冻结）

```text
src/ultrafast_reconstructibility/
    models.py        # 枚举 / SourceConditionSpec / Report / Readiness
    adapter.py       # ExperimentalConditionSpec → SourceConditionSpec
    coordinates.py   # dependency evaluator（P1：只问 Formula Registry）
    report.py        # per-condition report + 聚合
    batch.py         # M6-5 batch runner
```

- 新包加入 import-linter root_packages；`ultrafast_reconstructibility` 为
  leaf（禁止依赖 ultrafast_bo / ultrafast_domain / process_contracts）。
- 依赖方向：reconstructibility → physics / e2p / shared（均允许被依赖）。

## 6.1 M6-6：CFA V1 candidate physics coordinates（依 226 篇审计统计冻结）

226 篇审计（`outputs/m6_archive_audit.json`，1126 条件）坐标状态分布：

```text
RECONSTRUCTIBLE  2645   （pulse_interval / pulse_spacing 等无设备依赖坐标）
DEPENDENCY_MISSING 5731  （beam_radius / Fth / thermal_diffusivity 主导阻塞）
NOT_REPORTED      5201
AMBIGUOUS         1061
```

CFA V1 候选坐标集（冻结，校准后可调整）：

```text
Tier A（Source 可独立重建，无需设备属性）：
    pulse_interval / pulse_spacing
Tier B（需 spot 定义：source 报告 或 device profile 提供）：
    pulse_overlap / hatch_overlap / pulses_per_spot / peak_fluence
Tier C（需 governed 阈值 Fth，CFA 前不得直接比较）：
    normalized_fluence
```

- Tier C 坐标在 Fth 治理化之前一律 `DEPENDENCY_MISSING`，
  禁止用任意默认 Fth 计算（P0 原则延续）。
- M6-6 的最终冻结以 B1 17/25 篇标注统计复核后为准（本表为 226 篇初值）。

## 7. 验收（冻结）

```text
G1  五种"不知道"在字段与坐标两级均可区分（测试强制）
G2  M6-2 不包含任何自写公式（只调用 get_formula / engine.compute）
G3  Pilot 5 篇全部产出 report 与 readiness（无异常）
G4  Paper 13 双体制（200kHz/40MHz）：40MHz 坐标标注 REPORTED_AMBIGUOUS
    或 TEXT_COVERAGE_BLOCKED 之外的状态时须显式 warning（LINKAGE_AMBIGUOUS）
G5  batch runner 对 226 篇可离线运行（benchmark 标记）
G6  同一条件两次评估结果确定性一致
```
