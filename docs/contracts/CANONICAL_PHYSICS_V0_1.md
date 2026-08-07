# CANONICAL_PHYSICS_V0_1（M8 契约）

> 状态：**FROZEN**（2026-08-07）。
> 关联：`SOURCE_RECONSTRUCTIBILITY_V0_1.md`（M6）、
> `TARGET_PHYSICS_READINESS_V0_1.md`（M7）、`UNCALIBRATED_CFA_V0_1.md`（M9）、
> `CONTRACT_V2_FREEZE.md`（Formula Registry）。

## 0. 原则（冻结）

> CanonicalInteractionState 不是"尽量算满"，而是在已验证输入与公式依赖
> 约束下，诚实表示哪些 canonical coordinates 真正成立。

- 坐标 namespace 与 Formula Registry 完全一致（无新坐标）。
- 每个坐标携带：value / unit / formula_id / formula_version /
  input_provenance / availability_status / reason。
- 统一 availability 语义（Source/Target 归一，M9 只消费它）：

```text
AVAILABLE / UNVERIFIED / AMBIGUOUS / NOT_REPORTED /
TEXT_COVERAGE_BLOCKED / DEPENDENCY_MISSING / UNAVAILABLE
```

## 1. 对象（冻结）

```text
CanonicalInteractionState
    side: source | target
    condition_id / paper_id
    coordinates: {coordinate -> CanonicalCoordinate}

CanonicalCoordinate
    availability / value / unit / formula_id / formula_version /
    approximate / input_provenance[] / reason
```

映射（冻结）：

```text
Source RECONSTRUCTIBLE              -> AVAILABLE
Source AMBIGUOUS                    -> AMBIGUOUS
Source NOT_REPORTED / COVERAGE_BLOCKED / DEPENDENCY_MISSING -> 同名
Target AVAILABLE                    -> AVAILABLE
Target AVAILABLE_WITH_UNVERIFIED_ASSUMPTION -> UNVERIFIED（CFA 不消费）
Target BLOCKED                      -> UNAVAILABLE
```

## 2. compare_canonical（M9 输入，冻结）

```text
双侧 AVAILABLE      -> COMPARABLE
任一侧 UNVERIFIED   -> UNVERIFIED（reason=unverified_on_one_side）
其余               -> INCOMPARABLE（reason 必填）
缺失于任一侧        -> INCOMPARABLE（reason=missing_on_one_side）
```

Unknown 永远不是 Mismatch。

## 3. rollout policy（Tier，冻结）

```text
M8.1  Tier A  canonical：pulse_interval / pulse_spacing（双侧可独立建立）
M8.2  Tier B  conditional：pulse_overlap / hatch_overlap / pulses_per_spot /
      peak_fluence（spot verified -> AVAILABLE；unverified -> UNVERIFIED）
M8.3  Tier C  governed：normalized_fluence（Fth 治理化前一律 DEPENDENCY_MISSING）
```

## 4. 验收（冻结）

```text
G1  Tier A 坐标在双侧 AVAILABLE 时 COMPARABLE（测试）
G2  unverified target 坐标永不 COMPARABLE（测试）
G3  无自写公式（只消费 Formula Registry / M6/M7 评估器）
G4  输出无概率/置信度字段
```
