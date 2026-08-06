# CONTRACT_V2_FREEZE

> 状态：**V2.0 冻结**（2026-08-06）
> 前置基线：`7-契约差异清单与冻结建议.md`（Contract Migration Baseline）
> 字段分类：
> - `[FROZEN]` 已冻结，任何修改须走契约变更流程（bump + migration 脚本）
> - `[PROVISIONAL_PENDING_SPRINT0]` 结构性冻结，具体取值/枚举成员由 S0-3 / S0-5 实测决定；决定前实现按本表占位，禁止臆造默认值
>
> 冻结范围说明：Q1–Q5 **直接冻结**（消除第三套契约与 EvidenceIR 硬冲突）；Q6–Q7 **部分冻结**（结构/规则冻结，取值待 S0-5/S0-3）。

---

## 0. 冻结状态总表

| # | 决策 | 状态 | 冻结内容 | 待验证项 |
|---|---|---|---|---|
| Q1 | TaskScope | 直接冻结 | 扩现有 `TaskScope`；禁止新建第三套 TaskContext；e2p 层保持投影 | — |
| Q2 | Evidence taxonomy | 直接冻结 | `semantic_role × claim_type` 双轴；role→CFA evaluator；claim_type→belief 编译 | — |
| Q3 | parameter namespace | 直接冻结 | raw / physics 分命名空间；physics 仅接受 Formula Registry 注册项 | — |
| Q4 | Evidence 三层 | 直接冻结 | candidate=治理存储 / e2p EvidenceIR=科学消费 / contracts=API 投影 | — |
| Q5 | extraction confidence | 直接冻结 | 与 prior/confidence 完全分离，命名与语义独立 | — |
| Q6 | MaterialState | 部分冻结 | 属性必带 condition/provenance/review、走治理链；V1 不建真值字典 | S0-5：V1 属性范围（候选 Fth + thermal_diffusivity） |
| Q7 | Equipment | 部分冻结 | 5 表为 persistence；不建重复 EquipmentProfile 表；支持 Unknown；未核实输入禁算 energy 坐标 | S0-3：spot=5.0 可信度、power range 等取值 |

---

## 1. Q1 — TaskScope v2

`[FROZEN]` 以 `packages/process_contracts/schemas.py:23` TaskScope 为唯一基座；e2p 层 dataclass 继续作为科学层投影（已有 `task_scope_to_e2p` 适配器保留）。

| 字段 | 类型/约束 | 分类 | 备注 |
|---|---|---|---|
| task_context_id / task_context_version | str / int≥1 | FROZEN | 保留现有版本化 |
| material, material_grade | str, str\|None | FROZEN | |
| laser_type | Literal["fs","ps"] | FROZEN | 三层均有，保留 |
| equipment_id, laser_id, machine_id | str | FROZEN | |
| geometry_type | str | FROZEN | 主计划"geometry"统一为 geometry_type |
| process_type | str \| None | FROZEN(新增) | 补齐 contracts 缺口（e2p 已有） |
| target_metric | str \| None | FROZEN(结构) | 放宽：不再 Literal 锁死；目标注册表初始成员 `{depth_um, roughness_um, Sa_um}` FROZEN，**新增成员 PROVISIONAL**（S0-3 后按数据确认） |
| optimization_direction | Literal["minimize","maximize"] \| None | FROZEN(结构) | 语义：逐 target 方向，由目标注册表提供；注册表内容 PROVISIONAL |
| controllable_parameters | list[str] | FROZEN(结构) | 默认派生 = machine_bounds keys；派生规则 FROZEN |
| measurement_definition | dict \| None | FROZEN(结构) | 引用/内联 measurement_device + method + roughness_type（从 ProcessQuality 上移语义）；ProcessQuality 字段保留 |
| process_parameters | dict | FROZEN | 保留 |
| device_properties | dict | PROVISIONAL_PENDING_SPRINT0 | 前端已有 4 键（ablationThresholdJcm2/spotDefinition/spotRadiusUm/thermalDiffusivityM2S）；键名改 snake_case + 与 MaterialState/Q7 对齐；**是否保留该 dict 或改引用，由 Q6/Q7 结构落地时定** |

契约规则（FROZEN）：`extra="forbid"` 保留；禁止新增第三套 TaskContext 类；DB `task_contexts.payload_json` 序列化 schema 随 contracts v2 升级，旧版本记录只读。

## 2. Q2 — Evidence taxonomy 双轴

`[FROZEN]` 双轴定义，evaluator/belief 分派各消费一轴。

**轴 1：semantic_role（证据是什么 → CFA evaluator 分派）**

```text
FORMULA / MATERIAL_PROPERTY / THRESHOLD / PARAMETER_EFFECT /
PARAMETER_RANGE / REPORTED_OPTIMUM / MECHANISM / EXPERIMENTAL_CONDITION
+ UNSPECIFIED（哨兵：拒绝进入 evaluator，不参与 CFA）
```

legacy 6 类映射（FROZEN，一次性映射表）：
```text
experimental_condition → EXPERIMENTAL_CONDITION
searched_range        → PARAMETER_RANGE
reported_optimum      → REPORTED_OPTIMUM
recommended_range     → REPORTED_OPTIMUM + {recommended: true} 标记
observed_relation     → PARAMETER_EFFECT
unspecified           → UNSPECIFIED
```

**轴 2：claim_type（怎么被消费 → belief 编译通道）**

```text
PARAMETER_DIRECTION / RANGE_PREFERENCE / RELATIVE_IMPORTANCE /
HISTORICAL_DATASET / HISTORICAL_MODEL / FUNCTIONAL_SHAPE
```
（沿用 contracts.EvidenceClaimType 6 类；**新增成员 PROVISIONAL_PENDING_SPRINT0**）

组合示例（FROZEN 语义）：
```text
semantic_role=PARAMETER_EFFECT + claim_type=PARAMETER_DIRECTION → PreferenceBelief
semantic_role=REPORTED_OPTIMUM + claim_type=RANGE_PREFERENCE  → RegionBelief
semantic_role=FORMULA + claim_type=FUNCTIONAL_SHAPE            → FeatureBelief 通道
```

## 3. Q3 — Parameter 命名空间

`[FROZEN]` 双命名空间；校验规则：

```text
RAW namespace:
  pulse_width_ps / frequency_kHz / hatch_spacing_um / passes / scan_speed_mm_s  (CORE_PARAMETER_NAMES)
  + laser_power_W          # 新加入 raw namespace；BO core controls 仍为 5 个（power 为条件参数，S0-3 确认数据可得性）

PHYSICS namespace:
  成员 = Formula Registry 注册的 formula_id（注册表即白名单）
  当前注册：pulse_energy / pulse_interval / pulse_spacing / line_energy / areal_energy /
           peak_fluence / pulse_overlap / hatch_overlap / pulses_per_spot /
           normalized_fluence / thermal_accumulation_number
  计划新增（PROVISIONAL_PENDING_SPRINT0）：accumulated_fluence、dose 分布描述符
```

规则（FROZEN）：
1. Evidence.parameter 必须属于两命名空间之一，否则校验拒绝；
2. physics 参数必须能在 Formula Registry 中找到 formula_id（**禁止 LLM 发明未注册特征**）；
3. 新增 physics 参数 = 版本化 Registry 变更，不是 schema 变更；
4. raw 参数的单位后缀规范（_ps/_kHz/_um/_mm_s/_W）保留，physics 参数用 SI 单位。

## 4. Q4 — Evidence 三层收敛

`[FROZEN]` 三层职责与映射（禁止第四套证据对象）：

| 层 | 对象 | 职责 | 关键字段/映射 |
|---|---|---|---|
| 治理存储 | `knowledge_candidate` 表（memory 库） | 证据生命周期、审核、准入 | candidate_id / paper_id / claim / parameter_json / condition_json / usable_for_json / not_usable_for_json / source_quality_score / review_status |
| 科学消费 | e2p `EvidenceClaim` → 扩展为 EvidenceIR 全字段 | CFA/E2P 算法输入 | 在现有字段上**新增**：parameter_scope、source_context(物理字段)、page、chunk_ids、extraction_confidence、validation_state |
| API 投影 | `contracts.Evidence` | wire 形状 | 保留现有字段；`parameter` 校验改按 Q3 双命名空间 |

映射键（FROZEN）：`paper_id`（candidate↔literature）、`candidate_id`（candidate↔EvidenceIR）、`evidence_id`（EvidenceIR↔contracts）。chunk 级关联通过 `literature_chunk.chunk_id`。

**EvidenceIR 字段冻结表（在 e2p EvidenceClaim 上扩展）：**

| 字段 | 分类 | 说明 |
|---|---|---|
| claim_id, claim_type, parameter, target, value, semantic_role | FROZEN | 现有字段，semantic_role 按 Q2 新 8 类 |
| scope（material/laser_type/geometry/equipment/target） | FROZEN | 保留 |
| source_context：material_grade, wavelength, pulse_width, equipment, geometry, process, target_metric | FROZEN(结构) | **数据来源固定为 literature_paper 元数据（重提取后复制），禁止在 evidence 层重新抽取**；取值 PROVISIONAL_PENDING_S0-2 |
| provenance：source_id, review_id + 新增 paper_id, page, chunk_ids | FROZEN(结构) | chunk_ids 填充规则 PROVISIONAL_PENDING_S0-2（traceability 出口） |
| extraction_confidence | FROZEN(结构) | 语义=LLM 抽取质量（0–1）；**与 prior 强度完全无关**；取值规则 PROVISIONAL |
| validation_state | FROZEN(结构) | lightweight validator 输出：`{PASSED, FAILED, NEEDS_REVIEW}`；具体规则 PROVISIONAL |
| review_status | FROZEN | 沿用 governance：pending/approved/rejected |

## 5. Q5 — extraction_confidence 与禁 confidence 的边界

`[FROZEN]` 三个命名永久分离，写入契约注释防回归：

```text
extraction_confidence    # 抽取质量（LLM 对自己的抽取可靠性的估计）→ 允许
source_quality_score     # 证据/来源质量 Q_i 的构成输入（确定性 provenance 计算）→ 允许
confidence / prior_mean / prior_std   # 未验证的数值先验强度 → 永久禁止（沿用 schemas.py:124 校验）
```

规则（FROZEN）：三者的计算/校验路径互不引用；任何 prior 强度字段进入证据对象必须带 `verification` 标记与审核溯源（沿用 GovernedPriorArtifact 门控）。

## 6. Q6 — MaterialState（部分冻结）

**FROZEN 部分：**
1. `MaterialPropertyClaim = EvidenceIR(semantic_role=MATERIAL_PROPERTY)`，走 extract → validate → review → approved 治理链；
2. 新表 `material_property`（结构冻结）：
   ```text
   material_id, property_name, value, unit, condition_json,
   source_id, provenance, review_status
   ```
3. `MaterialState` = resolver 构造的科学视图，**不是真值字典**：多条件属性禁止平均（如 SiC Fth 多值并存），resolver 按 wavelength/pulse_width/grade/measurement_definition 选择，冲突时返回 `conflicting`/`unavailable`；
4. 循环证据控制（FROZEN）：CFA 评估 E_i 时使用来自 E_i 自身的属性 → `facet_dependency_provenance.self_dependency=true`，仅参与 source state 重建，不计独立支持。

**PROVISIONAL_PENDING_S0-5：** V1 属性范围（候选：ablation_threshold + thermal_diffusivity）；condition 分辨率优先级规则；属性值的单位规范。

## 7. Q7 — Equipment（部分冻结）

**FROZEN 部分：**
1. persistence = 现有 5 表（equipment_profile / laser_source_config / optical_setup_config / motion_system_config / process_capability_config）；**禁止新建重复 EquipmentProfile 大表**；
2. 科学层组合视图 `EquipmentProfileView`（不落表）；
3. 新列（结构冻结，落地时机=契约 v2 迁移）：`optical_setup_config.beam_profile`、`optical_setup_config.spot_definition`（语义：1/e² / D4σ / other / unknown）；`laser_source_config.average_power_min/max_W` 补全为必填规范；
4. Unknown 语义（FROZEN）：字段级 `verification_status ∈ {verified, unverified, unknown}`；`unverified/unknown` ≠ 数值可用；**spot=5.0 在 verification 前禁止参与 peak_fluence / N_eff / normalized_fluence 计算**；
5. 可信来源顺序（FROZEN）：实测/标定 > 审核后人工档案 > 可靠历史记录 > Unknown；禁止从论文反推本机参数。

**PROVISIONAL_PENDING_S0-3：** 各档位的具体取值（spot 直径、power range、M²、NA、hatch range、scan speed range）与 verified/unverified 判定结果。

## 8. 变更控制与升级流程

1. FROZEN 字段变更：必须产出契约变更说明（原因/影响/回滚），bump 到 v2.x，并附带 DB migration 脚本；未完成前实现保持旧行为。
2. PROVISIONAL_PENDING_SPRINT0 项：由 S0-3/S0-5/S0-2 决策文档决定 → 升级为 FROZEN 或降级为"明确不可用"，不需要 schema bump，但须在决策文档留痕。
3. 本文件生效后，`7-契约差异清单.md` Q1–Q7 状态同步更新为"已冻结/部分冻结"。
4. 契约 v2 冻结后，DB 迁移按 `8-主计划V2.md` §11 顺序执行（contracts v2 先行，再改代码）。

## 9. 待 S0 试验解决的 PROVISIONAL 项汇总

| 项 | 所属 | 解决者 |
|---|---|---|
| target_metric 注册表新增成员 | Q1 | S0-3（数据覆盖） |
| optimization_direction 逐 target 内容 | Q1 | S0-3 |
| device_properties 键名与去留 | Q1/Q6/Q7 | S0-3/S0-5 |
| source_context 物理字段取值 | Q2/Q4 | S0-2（重提取出口 A/B/C） |
| chunk_ids 填充规则 | Q4 | S0-2 |
| extraction_confidence 取值规则 | Q4/Q5 | S0-2（recall/ambiguity 实测后定） |
| validation_state 判定规则 | Q4 | S0-2/S0-3 |
| MaterialState V1 属性范围 | Q6 | S0-5 |
| condition 分辨率优先级 | Q6 | S0-5 |
| Equipment 各档位取值与 verification | Q7 | S0-3 |
| physics 命名空间新增成员（accumulated_fluence 等） | Q3 | S0-3（Registry 变更走版本化） |
