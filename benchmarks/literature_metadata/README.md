# Literature Metadata Enrichment Benchmark

P0-A 第一阶段产物：**先建基准，再改模型**。目标是让文献进入 RAG 前，TaskScope 相关
metadata（材料/牌号/工艺/激光类型/波长/脉宽/加工对象）基本可靠，且**允许 unknown，禁止猜**。

## 数据流

```text
人工标注（gold/annotations.jsonl，目标 50~100 篇）
        ↓
Extractor V2 预测（同 schema 的 JSONL）
        ↓
evaluate_extraction.py 计算指标
```

## 当前状态（2026-08-05）

- gold 已有 **203 篇**（全语料抽取完成：10 seed + 18 round2 + 23 round3 + 全量 132 篇），
  其中综述 20 篇、材料 abstain 44 篇（无 canonical/非加工论文）
- 构成：Glass 46、NickelSuperalloy 31、Diamond 24、CFRP 24、TBC 21、FusedSilica/SiC 9…
  体制：fs 75、ps 14、uv 3、ns 2、unknown 109（多体制/未标注/非激光）
- rule-only 基线（无 LLM）：laser_regime 0.75~0.90、evidence_page 0.39~0.54；
  primary 全 abstain（无 LLM 禁止猜，符合设计）
- 抽取流水线：`prepare_annotations.py --per-scenario N`（语料→文本→规则草稿→工作单）；
  文件名特殊字符/扫描件自动记录（ASCII 副本法可补提）

## 标注 schema（每行一篇论文）

| 字段 | 类型 | 说明 |
|---|---|---|
| `paper_id` | str | 稳定标识（优先使用 `literature_paper.paper_id`；未入库时用文件名） |
| `title` | str | 论文标题 |
| `is_review` | bool | 是否综述 |
| `primary_material` | list[str] | 本文**主实验材料** canonical id 集合；多材料论文可为多个；**无法判定 = 空数组** |
| `material_grade` | dict[str,str] | canonical id → 牌号原文（如 "T300"）；无牌号 = 空对象 |
| `primary_process` | str | 主工艺 canonical id；未知 = 空字符串 |
| `laser_type` | str | `fs` / `ps` / `ns` / `uv` / 空（未知） |
| `wavelength_nm` | float\|null | 主实验波长；未知 = null |
| `pulse_width` | {value, unit, evidence} \| null | 脉宽值+单位+原文证据；未知 = null |
| `geometry` | str | 加工对象/几何 canonical id；未知 = 空字符串 |
| `material_mentions` | list | `{raw_text, canonical_material_id, role, page}` |
| `process_mentions` | list | `{raw_text, canonical_process_id, role, page}` |
| `evidence_page_primary_material` | int\|null | primary material 首次作为主工件出现的页码（作证据页指标用） |
| `notes` | str | 标注备注（歧义/困难点） |

### Mention role（材料）

`primary_workpiece` / `substrate` / `coating` / `reinforcement` / `comparison_material`
/ `tool_material` / `background_only`

### Mention role（工艺）

`primary_process` / `pretreatment` / `postprocess` / `comparison_process` / `background_only`

### Canonical id（材料）

`SiCp/Al` `CFRP` `Diamond` `FusedSilica` `SiC` `Ti6Al4V` `ZrO2` `NickelSuperalloy`
`TBC` `Glass` `Silicon` `Copper` `Steel` `Aluminum` `Epoxy` `Sapphire`（见
`ultrafast_shared/ontology.py` 的扩充别名表）

### Canonical id（工艺/几何）

工艺：`cutting` `scribing` `drilling` `milling` `ablation` `surface_texturing`
`micromachining` `bonding` `laser_induced_etching` `wet_etching` `cleaning`
`polishing` `non_laser_reference`（非激光对照工艺，如机械加工/超声）
几何：`rectangular_groove` `circular_hole` `single_line` `surface_texture`
`lens` `plate` `sheet` `wafer` `film` `custom`

## Gold 标注政策（2026-08-06）

1. `primary_material` 取**最具体 canonical**：复合物优先于组成相
   （`SiCp/Al` 而非 `Aluminum+SiC`；`GlassCeramic` 而非 `Glass`；`TBC` 优先于 `ZrO2`）。
2. 基体/涂层/增强相/对比材料/工具材料用 `material_mentions[].role` 表达，
   不并入 primary_material（除非论文主对象即涂层系统本身，如 TBC 钻孔论文）。
3. 非激光论文 / 无法判定 → 字段留空（abstain），禁止猜测。
4. 无法解析为现有 canonical 的材料（hBN/Ge/SiOx/碲酸盐/聚氨酯/木材等）
   → primary 留空并在 notes 说明（ontology-v2 候选）。
5. 等级：当前为 **AI 策展 silver benchmark**（未见独立人工盲审前不得称人工 gold）；
   盲审完成前，dev/test 划分与指标均视为开发期结果。

## 数据划分（2026-08-06）

- **dev**（`dev/`）：27 篇（pilot2 分层样本，raw baseline 已冻结）——仅用于管道调试与
  prompt/策略迭代；其回归结果**不得**作为独立测试结论。
- **test**（未查看）：gold 中除 dev 外的 176 篇；全量运行前不得用于任何调参。
- **audit**（`audit/`）：40 篇独立人工盲审子集（固定 seed 分层抽取，见 `audit/audit_ids.txt`）。

## 指标（evaluate_extraction.py 输出，v2 方法学）

| 指标 | 定义 |
|---|---|
| Material exact accuracy | 论文级 primary_material 集合精确一致（gold 非空样本） |
| Material multi-label F1 | 论文×材料对 微平均 P/R/F1；**FP 无条件统计**（gold 材料为空时乱报也计入 FP） |
| Material FP on abstain papers | gold 材料为空的论文中，模型乱报材料的比例（乱报率） |
| Material grade / Process / Laser / Geometry accuracy | 各字段 gold 非空的全样本为分母；**模型 abstain 按 miss 计**（不排除 abstain 虚高） |
| Abstention recall / precision（每字段独立） | primary_material / material_grade / primary_process / laser_type / wavelength_nm 各自的正确 abstain 比例 |
| Evidence-page accuracy | gold 给了证据页的论文中，预测在正确页含正确 primary material mention 的比例 |
| 95% CI | 所有比例指标输出 Wilson score interval |

**方法学约定（v2，2026-08-05）**：
1. 材料 FP 无条件统计：非激光论文（gold 材料空）上乱报材料必须被惩罚；
2. process/laser/grade 的 accuracy 分母 = gold 非空全样本，模型 abstain 算错；
3. 各字段独立报告 abstention recall/precision（禁止用整体 abstention 掩盖单字段问题）；
4. 比例指标带 Wilson 95% CI（F1 除外，F1 非简单比例，CI 用 bootstrap 另行提供）。

## 困难案例要求（标注集必须包含）

多材料论文（基体+涂层）、材料只在 Methods 出现、牌号只在表格出现、
Introduction 出现大量其他材料、综述、扫描 PDF、别名（SiC/SiCp/Al-SiC）、
工具材料与工件材料并存（金刚石刀具加工钢）、非激光对照工艺论文。

## 用法

```powershell
# schema 校验 + 指标
python benchmarks/literature_metadata/scripts/evaluate_extraction.py `
  --gold benchmarks/literature_metadata/gold/annotations.jsonl `
  --pred <predictions.jsonl>
# 仅 schema 校验
python benchmarks/literature_metadata/scripts/evaluate_extraction.py --schema-check <file.jsonl>
```
