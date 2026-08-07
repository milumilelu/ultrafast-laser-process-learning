# 标注与检索任务规范（任务分配.md）一致性审查

日期：2026-08-06 ｜ 依据：gold 203 篇（冻结 SHA `7ACC67...`）对照《任务分配.md》八组检索规范

## 1. 材料标签映射（任务标签 → 当前 canonical → gold 覆盖）

| 任务标签 | canonical | gold 篇数 | 语义核对 |
|---|---|---|---|
| `nickel_superalloy` | NickelSuperalloy | 31 | ✓ 镍基高温合金（IN792/CMSX4/René N5/DD6/DZ125/Inconel718 等牌号已标） |
| `TBC_YSZ` | TBC / ZrO2 | 21 | ✓ TBC=陶瓷热障涂层系统（hierarchy TBC⊃ZrO2）；ZrO2=氧化锆 |
| `SiCp/Al` | SiCp/Al | **2** | ✓ 铝基碳化硅（铝基体+SiC 增强，hierarchy SiCp/Al⊃{Al,SiC}）；**缺口见 §3** |
| `CFRP_T300` | CFRP | 24 | ✓ 树脂基碳纤维；**牌号 T300 未标出，缺口见 §3** |
| `diamond` | Diamond | 24 | ✓ |
| `SiC` | SiC | 9 | ✓（4H-SiC/碳化硅陶瓷） |
| `glass_ceramic` | GlassCeramic | 3 | ✓ 微晶玻璃（LAS 牌号已标 1 篇） |
| `quartz_glass` / `SiO2` | FusedSilica | 9 | ✓ 石英玻璃/熔融石英/二氧化硅 |
| `glass_wafer` | Glass | 46 | ✓（TGV 场景 8 主材料） |
| `aluminosilicate_glass` | Glass | 46 | ✓ 铝硅玻璃（含 alkali-free alumina-borosilicate grade） |

未映射但语料存在：Steel 2 / Silicon 5 / Epoxy 1 / Aluminum 7 / Ti6Al4V 2 / Sapphire 1 / Copper 2
——任务标签为"至少覆盖"集合，非穷举，不冲突。

## 2. 工艺标签映射（任务标签 → 当前 primary_process canonical）

| 任务工艺标签 | canonical 覆盖 | 说明 |
|---|---|---|
| `film_cooling_hole_repair` | drilling/micromachining | 79 篇（primary_process 近似） |
| `surface_microtexturing` | surface_texturing/ablation/micromachining | 46 |
| `adhesive_bonding_pretreatment` | surface_texturing/ablation/bonding | 34 |
| `xray_crl_micromachining` | micromachining/ablation | 35 |
| `xray_crystal_structuring` | micromachining/cutting | 48 |
| `glass_cover_cutting` | cutting/scribing/micromachining | 49 |
| `TGV_drilling` | drilling/laser_induced_etching | 56 |
| `beam_shaping` | （无独立 canonical） | Bessel 束等由正文/几何表达，属第二层字段 |
| `in_situ_monitoring` | （无） | 监测是测量手段非工艺；TGV 场景 8 关注——第二层字段 |

结论：工艺粒度（通用工艺 vs 场景标签）是两层语义，当前第一层用通用工艺正确；
场景标签（scenario_id）应由派生视图提供，不改冻结 gold。

## 3. 缺口与待办

### 3.1 语料缺口（P0 影响场景 2）
任务场景 2 核心方向「**高体份 SiCp/Al 铝基碳化硅 + 激光表面微结构 + 胶接增强**」
当前 gold 仅 2 篇 SiCp/Al 且**均非激光加工**（AFSD 固态增材、泡沫碰撞吸能）。
即：语料中该方向激光织构论文基本缺失 → 需按任务检索式补充
`("SiCp/Al" OR "aluminum silicon carbide") AND ("femtosecond laser" OR "laser texturing") AND "adhesive bonding"`
（建议至少 5~10 篇入语料后重新标注）。

### 3.2 CFRP 牌号标注遗漏
24 篇 CFRP 论文全部无 material_grade。任务明确 T300/CFRP（场景 2）。
需复核：正文出现 T300/T700/T800 的论文补牌号（列 blind audit 复核项）。

### 3.3 第二层字段设计输入（P0-A 第二层）
任务卡片质量指标字段（`recast_layer_thickness` / `HAZ_width` / `taper_angle` /
`roundness` / `chipping_size` / `delamination` / `lap_shear_strength` /
`retention_ratio` / `aspect_ratio` / `yield` / `form_error` / `wavefront_error` 等）
即第二层 Scientific Knowledge Extraction 的目标字段，第二层 schema 直接复用。

## 4. 结论

- 三个澄清的材料定义与当前 canonical/gold 语义**一致**：
  SiCp/Al=铝基碳化硅（hierarchy 组成 Al+SiC）、ZrO2=氧化锆（TBC 组成相）、CFRP=树脂基碳纤维。
- 主要问题不在语义映射，而在**语料覆盖**（SiCp/Al 激光方向缺失）与**牌号标注遗漏**（CFRP T300）。
