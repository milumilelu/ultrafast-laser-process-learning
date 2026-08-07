# CFA V1.1 HOLDOUT VALIDATION RESULTS（H1–H5 Gate 判定）

> 状态：**评估完成**（2026-08-07）。13 篇独立 holdout × 三层人工 gold
> vs 冻结 CFA v1.1（`CFA_V1_1_EVALUATION_CANDIDATE_FREEZE.md`）。
> 结果存档：`benchmarks/cfa_confusion/results/holdout_audit.json`
> （含逐篇 prediction + audit + gates）。

## 1. 总体

```
gold 13 篇 / predicted 13 篇（8-hex 前缀匹配归档 PDF）
severe = 0          （H1：首要不对称风险指标）
conservative_miss = 1（Material：2c0e83 无 metadata → 系统 UNKNOWN，保守方向）
information_gap  = 0
consistent       = 53 / 65（五 facet 合计）
```

逐 facet：

| facet | severe | cons_miss | gap | consistent |
|---|---|---|---|---|
| Material | 0 | 1 | 0 | 12/13 |
| Task | 0 | 0 | 0 | 10/13 |
| InteractionState | 0 | 0 | 0 | 10/13 |
| Reconstructibility | 0 | 0 | 0 | 8/13 |
| Reachability | 0 | 0 | 0 | 13/13 |

## 2. Gate 判定

| Gate | 判定 | 证据 |
|---|---|---|
| **H1** severe = 0 | **PASS** | severe=0，无反向风险 |
| **H2** 缺失 metadata 不转 Mismatch | **PASS** | 2c0e83（无 metadata）：Material UNKNOWN（未编造）、Task PARTIAL（保守）；0 违例 |
| **H3** unverified 坐标不贡献 InteractionState 正证据 | **CHECK（未过）** | 3 篇 gold=UNKNOWN 被系统顶为 PARTIAL：f613aa / 1b61e6 / 269fe3 |
| **H4** metadata 可用时识别 explicit mismatch | **CHECK** | Material 10/10（100%）；Task 10/12（83%，2 篇为 metadata gold 缺 process_type，系统保守 PARTIAL，未编造） |
| **H5** Reconstructibility 与 gold 一致性 | **CHECK（未过）** | 8/13 = 0.615；5 篇 gold=UNKNOWN 被系统顶为 PARTIAL |

## 3. 分歧根因（均为 frozen 代码行为，本轮不得修复）

1. **`peak_fluence_J_m2` / `areal_energy_J_m2` 无条件 AVAILABLE**
   - `src/ultrafast_reconstructibility/coordinates.py:96-102`：即使输入缺失
     （value=None）也返回 `RECONSTRUCTIBLE`。
   - 后果：每篇论文 Reconstructibility 恒有 ≥2 个 AVAILABLE → 恒 PARTIAL；
     7fe49（机械钻孔、全 NOT_APPLICABLE）也不例外。这是 H5 全部 5 个分歧
     的根因。
2. **范围值端点被当确定值**
   - f613aa（0.2–25 MHz）、1b61e6（1–1000 Hz）、269fe3（GHz burst）的
     `pulse_interval` 被编译器按 REPORTED_CLEAR 取首值 → AVAILABLE →
     COMPARABLE → InteractionState PARTIAL；gold 判 AMBIGUOUS → UNKNOWN。
   - 这是 H3 全部 3 个分歧的根因（`RECONSTRUCTIBLE` 对范围端点的确证性问题）。

其余 10/13 篇 InteractionState 一致（含 31cf79/7fe49/da1887/7a03b9 正确保持
UNKNOWN），未发现"材料/任务编造性正判定"。

## 4. v1.1 结论（登记）

- v1.1 在不安全方向上表现正确：severe=0、无编造 mismatch、无 metadata 猜测。
- v1.1 存在两个已定位的过乐观缺陷（§3），全部为 **UNKNOWN→PARTIAL** 单方向
  漂移（安全方向但违反 H3/H5 的字面判定）。
- 按冻结协议 §4：**未完全通过 → 登记为 v1.1 结论，进入 v2 迭代**，
  holdout 保持独立（13 篇不再参与任何规则调整）。

## 6. 版本纪律修正（2026-08-07，方法论重要修正）

原 13 篇对 **v1.1** 是独立 holdout；但 v2 修复过程已以这 13 篇为诊断依据
（§3 两缺陷由此发现），因此：

```text
B1-25              → v1.1 development set
13-paper holdout   → v1.1 independent validation set
                  → 发现 v2 bugs 后：v2 diagnostic/regression set
新 unseen holdout  → v2 independent validation（冻结中）
```

后续任何表述不得再称这 13 篇为"v2 独立验证"；对它们的运行一律记为
**v2 regression on former v1.1 holdout**。v2 独立验证必须使用新的未见样本。

## 7. 关于"calibration 可修"的结论性否定

§3 两缺陷**不是** PARTIAL 边界校准问题，而是上游确定性语义错误：

- V2-1：依赖缺失仍标 RECONSTRUCTIBLE → reconstructibility correctness bug；
  校准器若吸收它，学到的将是"补偿上游实现 bug"，参数无科学含义。
- V2-2：RANGE/SWEEP 被降格为 point → representation bug（range ≠ point
  observation）；同理不可交给校准。

结论：**calibration 只负责 transfer uncertainty，不承担修 bug 职责。**
Calibration Feasibility Gate 必须推迟到 v2 独立验证通过之后；当前只允许
并行做 D1–D4 数据资产盘点（inventory），禁止 fit calibrator / 设计
calibration mapping。
