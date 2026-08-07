# T2_VERTICAL_SLICE_V0_1（M5.5 Demo V2 集成契约）

> 状态：**FROZEN**（2026-08-07）。目标：第一次端到端验证
> "目标数据建模 + 文献知识读取 + 科学证据结构化 + E2P 编译 + 治理 +
> evidence-assisted optimization" 是**一个能工作的科研系统**。
> 关联：`OPEN_SCIENTIFIC_DISCOVERY_V0_1.md`、`CANDIDATE_LEDGER_V0_1.md`、
> `CONTRACT_V2_FREEZE.md`（E2P/BO 治理）。

## 0. Demo 定位（冻结）

```text
Demo V1  Vanilla Topic2                已具备（BO + prior_ablation 已闭环）
Demo V2  Topic2 + E2P                  ← 本契约（目标）
Demo V3  Topic2 + E2P + CFA            后续（CFA 不在本 Demo 前置）
```

- **CFA 不阻塞 Demo**：Demo 输出 `CFA status = NOT_YET_CALIBRATED` +
  facet descriptor（material / interaction_state / task /
  reconstructibility / reachability，未实现 facet = UNKNOWN）。
- **不输出"最优参数"**：E2P 只产 prior（GovernedPriorArtifact），
  推荐由 BO 给出。
- **offline replay**：无真实实验；使用既有 CSV + pilot 文献，完全可复现。

## 1. 目标任务（冻结）

```text
material      = SiC
laser_type    = fs
geometry      = rectangular_groove
target        = depth_um（BO objective_metric）
dataset       = data/test_fixture/topic2_experiments_v1.csv（synthetic fixture，
                契约匹配；真实数据链（data/processed/unified_experiments.csv）
                作为后续扩展）
literature    = pilot 5 篇（04/10/11/13/Flat-top）
```

## 2. 六区域 → artifact 映射（冻结）

| # | 区域 | 产出对象 |
|---|---|---|
| 1 | Target Task | task_spec + dataset profile |
| 2 | Process Learning | `ProcessLearningResult`（selected_model / feature view / CV metrics / important params / prediction+uncertainty interface） |
| 3 | Literature Evidence | `ScientificDocument` + `CandidateLedger` + `EvidenceIR`（EvidenceBundle + 审计 meta） |
| 4 | E2P Prior | `GovernedPriorArtifact`（approval_ids / evidence_ids / source_trace / content_hash / verification） |
| 5 | BO | Vanilla 与 Evidence-assisted 两臂的 `recommended_parameters` / predictions / acquisition / candidate ranking |
| 6 | Audit | bo_run_id / evidence ids / artifact hash / model version / feature view / audit_trace（BO 原生） |

## 3. 主链（冻结）

```text
CSV ──────────► BOSample[] ──► Process Learning（Group-CV × RAW/HYBRID）
                                        │ selected model
                                        ▼
PDF ─► ScientificDocument ─► CandidateLedger ─► EvidenceClaim[]
                                        │ (mapping + review)
                                        ▼
                              EvidenceIR（EvidenceBundle.accepted）
                                        │
                              approved priors ─► compile_from_approved_priors
                                        ▼
                              GovernedPriorArtifact
                                        │
            ┌───────────────────────────┴──────────────┐
            ▼                                           ▼
    Branch A: Vanilla BO                    Branch B: Evidence-assisted BO
```

- 参数映射（canonical → machine_bounds 键，冻结）：

```text
frequency → frequency_kHz
pulse_width → pulse_width_ps
scan_speed → scan_speed_mm_s
hatch_spacing → hatch_spacing_um
passes → passes
```

- Feature views：`RAW`（5 原始参数）与 `HYBRID`（RAW + 不依赖 laser power 的
  物理特征：pulse_interval / pulse_spacing / pulse_overlap / pulses_per_spot）。
  `pulse_energy`/`fluence` 等依赖 power 的坐标在 Demo 中 **blocked 并报告
  unavailable**（dependency-aware：unknown 只阻塞依赖它的计算，不阻塞系统）。
- spot_radius_um = 5.0（设备属性假设，`source_trace` 标记为 demo assumption，
  不冒充已确认的 canonical 值）。

## 4. 治理简化（显式声明，不冒充生产流程）

```text
EvidenceClaim.review_status = "approved"   # Demo auto-approve；
                                            # 生产必须保持 False（契约 §e2p）
approval_verifier           = demo approval repo（approval_id 白名单）
GovernedPriorArtifact.verification = repository_verified（走 verifier 路径）
```

## 5. EvidenceIR 定义（冻结）

```text
EvidenceIR = EvidenceBundle（candidates / accepted / rejected /
             applicability_results）+ 审计 meta：
             paper_count / claim_count / accepted_count /
             provenance（paper_id → quote_fingerprint 列表）
```

- claim 来源：CONDITION_MENTION / TABLE_CELL 候选（MAPPED 到参数）；
  semantic_role = "experimental_condition"（实际使用条件，不是推荐最优）；
  claim_type = "range_preference"。
- Open Discovery 候选为可选增强（`--with-discovery`，默认 off；
  Demo 主链 deterministic，可复现）。

## 6. 验收（冻结）

```text
G1  Branch A/B 均产出完整 BO result（bo_run_id / recommended_parameters /
    predictions / acquisition / audit_trace）
G2  Branch B 的 governed_prior 字段非空，且内容哈希与
    compile_from_approved_priors 输出一致
G3  GovernedPriorArtifact.evidence_ids 全部可追溯回 EvidenceIR claims
G4  EvidenceIR.accepted ⊆ claims 且全部通过 applicability（transfer_class ≠ none）
G5  ProcessLearningResult 含 selected_model + CV metrics + feature view 选择
G6  Demo 无 LLM 依赖、无网络依赖，可离线重复运行（recorded/确定性路径）
```

## 7. 文件布局（冻结）

```text
docs/contracts/T2_VERTICAL_SLICE_V0_1.md   本契约
demo/t2_slice/adapters.py                  CSV→BOSample / ledger→claims / claims→priors
demo/t2_slice/pipeline.py                  run_vertical_slice（六区域编排）
scripts/demo_t2_vertical_slice.py          CLI runner
tests/test_t2_vertical_slice.py            unit（合成 ledger + CSV）+ pilot（5 篇）
```

## 8. Demo V3 集成 Gate（FROZEN，2026-08-07）

M6–M9 主链插回 vertical slice。范围严格控制（集成验证，非科学有效性证明）：

```text
SourcePhysicsReadiness + TargetPhysicsReadiness
        ↓
CanonicalInteractionState（M8）
        ↓
assess_all()（M9）
        ↓
真实 UncalibratedCFAReport（挂到 result["cfa"]）
```

**CFA 是 audit/assessment 输出，绝不改变 prior weight**：

```text
Demo V2: Evidence → Governed Prior → BO
Demo V3: Evidence → CFA report
                  ↘ Governed Prior → BO   （并行，不融合）
```

- uncalibrated heuristic ≠ probability；数值 prior multiplier 等
  EvidenceBelief/fusion contract 冻结后才允许。
- target 侧 profile：spot_radius_um=5.0 **UNVERIFIED**（M7 事实）；
  power 缺失（M7 事实）→ peak_fluence 等坐标在 CFA 中不 COMPARABLE。
- 验收（集成 Gate）：

```text
V3-G1  calibration_status == NOT_YET_CALIBRATED
V3-G2  全输出无 probability/confidence/transfer 伪校准字段
V3-G3  power 缺失 → peak_fluence 永不 COMPARABLE（无静默降级）
V3-G4  spot UNVERIFIED → overlap 族仅 UNVERIFIED/warning，不作有效匹配证据
V3-G5  prior_applied_evidence 保持 M5.5 行为（CFA 不破坏 E2P→BO 链）
```

附带修复：Layer 2 classify 的 capability 词边界 bug（"rated" 子串误匹配
"operated"）——已修复并重建 Phase B 等价性 fixture 基线
（capture=post-classify-word-boundary-fix；旧基线在 git 历史）。
