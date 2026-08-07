# B1 人工标注手册（Level 2/3）

> 配套：`make_label_template.py`（生成模板）、`validate_gold.py`（校验）、
> 协议 `B1_CHECKPOINT_V0_1.md`。本手册解决"怎么判断"。

## 0. 流程

```text
1. 准备论文清单（17→25 篇，每行一个 archive 文件名）
2. python benchmarks/cfa_confusion/make_label_template.py --papers list.txt
3. 逐篇：打开 archive 中对应 PDF，按本手册判断，编辑 gold_level2_level3.jsonl
4. python benchmarks/cfa_confusion/validate_gold.py gold_level2_level3.jsonl
5. 标注完成后跑 audit（run_seed5.py 扩展 + audit.audit_report）
```

**独立性**：判断只依据论文 PDF + 已知 target 定义，不要看系统预测。

## 1. Target 定义（固定）

```text
target = SiC / fs / rectangular_groove / depth_um（demo 任务）
设备：power 未知、spot=5μm 未验证
```

## 2. Level 2：坐标可用性（per paper，基于主要加工条件）

对每个坐标，判断"这篇论文能否重建出该物理坐标"：

| 状态 | 判定 |
|---|---|
| `AVAILABLE` | 论文报告了该坐标的全部输入（单位明确） |
| `NOT_REPORTED` | 论文有对应参数节但没报告必需字段 |
| `TEXT_COVERAGE_BLOCKED` | PDF 文本缺失/无法读取，无法判断（≠ 没报告！） |
| `AMBIGUOUS` | 必需字段报告了但冲突/双体制/歧义 |
| `DEPENDENCY_MISSING` | 论文字段够，但坐标需要设备/材料属性（Fth、热扩散系数） |
| `NOT_APPLICABLE` | 该坐标对论文过程无意义 |
| `UNKNOWN` | 其他无法判断 |

坐标依赖速查（输入来自 Formula Registry）：

```text
pulse_interval       需要 frequency
pulse_spacing        需要 scan_speed + frequency
pulse_energy         需要 average_power + frequency
line_energy          需要 average_power + scan_speed
areal_energy         需要 power + passes + speed + hatch
peak_fluence         需要 pulse_energy（或直接报告 fluence）+ spot 尺寸
pulse_overlap        需要 pulse_spacing + spot
hatch_overlap        需要 hatch_spacing + spot
pulses_per_spot      需要 spot + frequency + speed
normalized_fluence   需要 peak_fluence + 阈值 Fth（论文自测或引用都算，但
                      仅"引用文献值"且未确认 → 建议 DEPENDENCY_MISSING 或 AMBIGUOUS）
thermal_accumulation  需要 frequency + spot + 热扩散系数
```

要点：
- 论文**直接报告 fluence**（如 "10–50 J/cm²"）→ `peak_fluence = AVAILABLE`（无需再算）。
- spot 报告了"直径 15 µm @1/e" → 视为可用（1/e vs 1/e² 定义差异记 AMBIGUOUS
  或 AVAILABLE+notes，取决于是否影响比较）。
- 多个加工条件（如 Paper 11 两种样品、13 双体制）→ 按**主要加工条件**判断；
  条件间冲突 → 相关坐标 AMBIGUOUS。

## 3. Level 3：五 facet

```text
Material           论文材料 vs target SiC：
                    同为 SiC → KNOWN；不同（Diamond/CFRP/玻璃）→ MISMATCH；
                    论文材料不明 → UNKNOWN
Task               laser_type(论文 fs/ps vs fs) + process_type + geometry + target_metric
                    全匹配 → KNOWN；有维度缺信息 → PARTIAL；明确不同 → MISMATCH
InteractionState   Level 2 中至少一个坐标 AVAILABLE 且 target 侧可算 → PARTIAL；
                    全部不可比 → UNKNOWN；全可比 → KNOWN
Reconstructibility 论文坐标可重建程度：有可重建 → PARTIAL；全部可重建 → KNOWN；
                    全部无法判断 → UNKNOWN
Reachability        target 侧（SiC fs 设备）能提供多少坐标：
                    已知 power 缺失、spot 未验证 → 通常 PARTIAL（interval/spacing 可达）
```

Material/Task 是"证据对目标的匹配关系"；Interaction/Reconstructibility 看论文；
Reachability 看目标设备（固定答案，除非你认为 demo 设备另有能力——请注明）。

## 4. 常见陷阱

```text
1. "参数没抽到" ≠ "论文没报告"：先确认 PDF 文本是否完整（TEXT_COVERAGE_BLOCKED）
2. 发射波长（ZPL/PL）不是加工波长：Paper 11/13 的 1132/1038nm 等是缺陷发射
3. 设备型号数字不是参数：ZHL-25W-272+ 的 "25W" 是放大器型号
4. ODMR/测量系统的频率不是加工频率：40 MHz supercontinuum 是寿命测量
5. "up to 1 MHz" 是能力描述：如无法确认实际使用 → AMBIGUOUS 或 NOT_REPORTED
6. Fth 引用他人文献 → 不当作论文测量值
```

## 5. 交付

- 完成全部论文 + `validate_gold.py` 无 errors（`--require-complete` 可强制全填）
- 之后运行 `benchmarks/cfa_confusion/run_seed5.py`（扩展清单）→
  `audit.audit_report(human, system)` 出三层 confusion 报告
