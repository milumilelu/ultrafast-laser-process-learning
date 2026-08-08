# CFA V2 INDEPENDENT VALIDATION（新 11 篇 unseen holdout，H1–H5）

> 状态：**验证完成（未通过）**（2026-08-07）。
> 这是 v2 的独立验证（新 11 篇未参与任何规则调整）；不得与
> "v2 regression on former v1.1 holdout" 混淆。
> 结果存档：`benchmarks/cfa_confusion/results/holdout_v2_audit.json`
> gold：`artifacts/cfa_holdout/gold_holdout_v2_level1_2_3_completed.jsonl`（人工三层标注）

## 1. Gate 判定

| Gate | 判定 | 证据 |
|---|---|---|
| **H1** severe = 0 | **PASS** | severe=0；无任何 Unknown→Mismatch 转换 |
| **H2** 缺失 metadata 不转 Mismatch | **PASS** | 3c0cf5、86ddae（无 metadata）→ Material UNKNOWN（未编造）；0 违例 |
| **H3** unverified 坐标不贡献正证据 | **未过** | 2 违例：dd2760（综述）、179b11（扫频验证）→ 系统 PARTIAL vs gold UNKNOWN |
| **H4** metadata 识别 explicit mismatch | **CHECK** | Material 8/9（1 miss = gold metadata 覆盖缺口）、Task 9/9 |
| **H5** Reconstructibility 一致性 | **未过** | 4/11 = 0.364；7 处分歧全为系统 UNKNOWN vs gold PARTIAL（保守方向） |

## 2. 逐 facet

```text
Material            consistent 8/11；cons_miss 3（3c0cf5/86ddae no-meta、5b039b metadata.material_id 空）→ 全保守
Task                consistent 9/11；2 保守 PARTIAL（no-meta 两篇）
InteractionState    consistent 8/11；2 过乐观（dd2760/179b11）、1 保守（34af64）
Reconstructibility  consistent 4/11；7 分歧全保守方向（系统少报 AVAILABLE）
Reachability        consistent 11/11
```

## 3. 分歧根因（全部为第三类机制，与 V2-1/V2-2 无关）

1. **facet_summary 首报告语义（冻结行为）**——H5 主因。
   1aec7d/34af64/bbe6d4/4ae395/5b039b：系统 L2 聚合**实际有 AVAILABLE**
   坐标（如 1aec7d 的 pulse_energy/pulse_interval/pulse_spacing/line_energy
   全 AVAILABLE），但 Reconstructibility facet 取**第一个编译条件**的状态
   → UNKNOWN；gold 按"主加工条件"判断 → PARTIAL。与 v2 regression §3.2.3
   登记一致（已知冻结聚合语义）。
2. **review / sweep 文档语义**——H3 两处违例。
   - dd2760（综述）：系统 L2 **全 AMBIGUOUS**（V2-2 正常工作的直接证据），
     但个别被引用实验条件有 point 值（如某引用条件 200 kHz）→ 该条件
     pulse_interval COMPARABLE → InteractionState PARTIAL；gold 按综述
     无单一加工条件 → UNKNOWN。
   - 179b11（仿真+验证）：模型参数实验用 1 kHz point 条件 → COMPARABLE；
     gold 按验证段扫频（1–100 kHz）→ UNKNOWN。
3. **表格提取缺口（已登记）**——3262a7（ns excimer 微钻，参数在表格）。
4. **gold 标注自洽性 1 处**：86ddae L2 无任何 AVAILABLE 但
   Reconstructibility 标 PARTIAL（人工标注不一致；validate_gold 不检查
   facet-L2 一致性——建议 post-demo 补该校验）。

## 4. 安全方向证据（对 demo 展示仍然成立）

- severe=0：11 篇零反向风险；无编造 Material/Task。
- H2：无 metadata 论文保持 UNKNOWN。
- V2-2 修复在综述论文上得到压力验证：dd2760 全范围/全扫描参数 → 系统
  产出 **13/13 坐标 AMBIGUOUS**，零 point 伪装。
- H4：Task 9/9；Material 唯一 miss 是 gold metadata 自身的 material_id 空
  （5b039b，保守方向）。
- Reachability 11/11。

## 5. 结论（按契约 §5 判定）

```text
H1/H2 PASS，H3/H4/H5 未达字面标准
→ 不能声明 "Uncalibrated CFA v2 has passed independent scientific validation"
→ 登记为 v2 结论；demo release（topic2-demo-v1）不受影响：
   展示纪律本就不承诺 H 门通过，只承诺如实呈现 KNOWN/PARTIAL/UNKNOWN/
   MISMATCH + warnings + NOT_YET_CALIBRATED（本验证恰好证明该呈现诚实）
```

## 6. Post-demo track 优先级（据此修订）

```text
P1  facet_summary 聚合语义（H5 主因）：非 InteractionState facet 也需
    跨条件汇总（任一条件 PARTIAL → PARTIAL），或明确定义"主加工条件"。
P2  表格提取（H3/H5 次因）：sc04 系列表格参数未抽取（3262a7 等）。
P3  review/sweep 文档语义（H3）：文档类型（review）与参数扫描（sweep）
    的 condition 选择规则。
P4  gold 校验器补 facet-L2 一致性检查（86ddae 类标注错误防回归）。
```
