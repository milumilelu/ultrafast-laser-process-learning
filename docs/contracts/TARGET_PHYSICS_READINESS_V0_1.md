# TARGET_PHYSICS_READINESS_V0_1（M7 契约）

> 状态：**FROZEN**（2026-08-07）。
> 目标：Target 侧（目标数据集/设备）的 physics readiness，与 Source 侧
> （`SOURCE_RECONSTRUCTIBILITY_V0_1`）严格对称，为 M8 canonicalization 与
> M9 CFA Interaction-State facet 提供相同 coordinate namespace 与相同的
> availability semantics。
> 关联：`SOURCE_RECONSTRUCTIBILITY_V0_1.md`（M6）、`CONTRACT_V2_FREEZE.md`。

## 0. 核心规则（冻结）

> **Unverified input cannot silently satisfy a physics dependency.**

```text
spot = 5 μm 存在于 equipment profile
≠
spot = 5 μm 已确认
```

profile 中未确认的值 → `UNVERIFIED`；消费它的坐标最多达到
`AVAILABLE_WITH_UNVERIFIED_ASSUMPTION`（readiness 记录，**正式 CFA 不消费**）；
缺失输入 → `BLOCKED`。

## 1. Target 侧"未知"语义（与 Source 对称但不同源，冻结）

```text
Source 侧:  NOT_REPORTED / REPORTED_AMBIGUOUS / TEXT_COVERAGE_BLOCKED /
            DEPENDENCY_MISSING

Target 侧:  MEASURED（数据集记录）
            VERIFIED_EQUIPMENT_PROPERTY（设备属性已确认）
            DERIVED（确定性推导，验证状态随来源传播）
            UNVERIFIED（profile 存在但真实性未确认——如 spot=5μm）
            MISSING（如 power：target CSV 无此列）
```

## 2. 对象（冻结）

### TargetInputFact

```text
input_name（physics engine input，如 frequency_Hz）
value / unit
source: DATASET | EQUIPMENT_PROFILE | DEVICE_PROPERTY | DERIVED
verification_status: MEASURED | VERIFIED_EQUIPMENT_PROPERTY | DERIVED |
                     UNVERIFIED | MISSING
field_name / provenance
```

### TargetConditionSpec

```text
input_facts[]（dataset 列 + equipment profile 的确定性投影）
dataset_name / equipment_profile_id
```

- dataset 列映射（冻结）：pulse_width_ps→pulse_width_s、frequency_kHz→frequency_Hz、
  scan_speed_mm_s→scan_speed_m_s、hatch_spacing_um→hatch_spacing_m、passes→passes、
  laser_power_W→laser_power_W（缺列→MISSING）。
- profile 映射：spot_radius_um→beam_radius_m（UNVERIFIED 传播）；
  spot_diameter_m = 2×beam_radius（确定性推导，状态传播）；
  ablation_threshold_J_m2 / thermal_diffusivity_m2_s 同族。

### TargetPhysicsReadinessReport

```text
verified_inputs[] / unverified_inputs[] / missing_inputs[]
available_coordinates[]                 # 全部输入 verified/measured
unverified_assumption_coordinates[]     # 含 UNVERIFIED 输入（CFA 不消费）
blocked_coordinates[] / blocking_dependencies[] / warnings[]
```

### TargetPhysicsReadiness（CFA/M8 projection）

```text
verified_input_count / unverified_input_count / missing_input_count
available_coordinate_count / unverified_assumption_coordinate_count /
blocked_coordinate_count
coordinate_status: {TargetCoordinateStatus -> 计数}
```

## 3. 已知 target 事实（本契约基线）

```text
power   → target CSV 缺失            → MISSING
spot    → profile 5 μm 存在但未确认   → UNVERIFIED
```

预期结果（不是承诺，是评估器的确定性输出）：
pulse_energy/line_energy/areal_energy/peak_fluence 被 power 阻塞；
pulse_overlap/hatch_overlap/pulses_per_spot 需 spot（UNVERIFIED 时
AVAILABLE_WITH_UNVERIFIED_ASSUMPTION 或 BLOCKED）。

## 4. 与 M8/M9 的衔接（冻结）

```text
M8 CanonicalInteractionState 只消费两侧 readiness 的可用坐标：
    Source  RECONSTRUCTIBLE ↔ Target  AVAILABLE（可比较）
    Source  RECONSTRUCTIBLE ↔ Target  AVAILABLE_WITH_UNVERIFIED_ASSUMPTION
            → unverified（CFA 不比较）
M9 CFA 不消费任何含 UNVERIFIED/UNRESOLVED 的坐标。
```

## 5. 验收（冻结）

```text
G1  power 缺失 → pulse_energy 等坐标 BLOCKED（测试）
G2  spot UNVERIFIED → 消费坐标永不为 AVAILABLE（测试）
G3  spot VERIFIED → 相关坐标 AVAILABLE（测试）
G4  同一输入两次评估确定性一致
G5  只调用 Formula Registry（P1；无自写公式）
G6  与 Source readiness 共享 coordinate namespace（pulse_interval 等）
```
