# B1 标注工作包

25 篇论文（5 篇种子 + 20 篇补充，材料均衡覆盖）+ Level 2/3 标注模板。

## 内容

```text
papers/                      25 篇 PDF（按 archive 文件名命名）
papers.txt                   论文清单（模板生成输入）
gold_level2_level3.jsonl     标注模板（13 坐标 × 5 facet，全部空槽待填）
```

## 材料覆盖（均衡）

```text
种子（已有 Level 1 材料标注）：
    Diamond（04）、CFRP（Flat-top）、SiC ×3（10/11/13）

补充 20 篇：
    glass           5 篇（水辅助钻孔/紫外皮秒钻孔/内部刻划/强化玻璃/厚玻璃 Bessel）
    metal           5 篇（镍基单晶螺旋钻孔/热障涂层钻削 ×3/冷却孔烧蚀仿真）
    polymer/composite 3 篇（CFRP 激光烧蚀/复合材料工艺优化/碳纤维表面处理）
    surface/织构    3 篇（超疏水表面/发射率表面/铜表面微结构）
    other 加工      4 篇（Bessel 微钻/玻璃陶瓷切割/高深宽比微通道/自导钻孔）
```

## 标注流程

1. **判断依据**：`benchmarks/cfa_confusion/B1_LABELING_GUIDE.md`（坐标依赖速查、
   7 态判定表、facet 规则、常见陷阱——先读这一份）
2. **编辑** `gold_level2_level3.jsonl`：每篇一行 JSON，把 `null` 替换为状态值
   （坐标：AVAILABLE / UNKNOWN / NOT_REPORTED / AMBIGUOUS / DEPENDENCY_MISSING /
   TEXT_COVERAGE_BLOCKED / NOT_APPLICABLE；facet：KNOWN / PARTIAL / UNKNOWN / MISMATCH）
3. **校验**：

```bash
python benchmarks/cfa_confusion/validate_gold.py artifacts/b1_annotation/gold_level2_level3.jsonl --require-complete
```

4. 完成后运行 audit（由我执行）：

```bash
python benchmarks/cfa_confusion/run_seed5.py   # 扩展清单后
# audit.audit_report(human, system) → 三层 confusion 报告
```

## Target 定义（所有论文统一判断基准）

```text
target = SiC / fs / rectangular_groove / depth_um（demo 任务）
设备：power 未知、spot=5μm 未验证
```

## 提示

- 种子 5 篇的 Material hint 已注入模板（`hint_material_level1` 字段），
  标注时请按 PDF 实际内容复核。
- 判断只看论文 PDF + target 定义，**不要参考系统预测**（独立性是 audit 前提）。
- 论文如有多个加工条件，按主要加工条件判断；条件间冲突 → 坐标标 AMBIGUOUS。
- 材料多样性意味着 Material facet 会大量 MISMATCH（对 SiC target）——这是
  预期正确行为，不是标注错误。
