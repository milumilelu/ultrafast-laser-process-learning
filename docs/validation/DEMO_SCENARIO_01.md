# Demo Scenario 01（冻结，2026-08-07）

> 用途：Topic 2 Demonstration Release 的固定演示场景。任何演示/答辩/
> 组会复现必须使用本场景，禁止现场随机选数据。
> 入口：`scripts/demo_t2_vertical_slice.py`（复现命令见 §6）。

## 1. 冻结配置

```text
Target material:     SiC
Objective metric:    depth_um
Laser type:          fs
Process type:        fs_laser_processing
Geometry type:       rectangular_groove

Dataset:             data/test_fixture/topic2_experiments_v1.csv（固定版本）
Literature:          固定 5 篇 pilot 集：
                       04_arxiv_2502.16530.pdf（SiC）
                       10_arxiv_2411.18093.pdf（SiC）
                       11_arxiv_2404.09906.pdf（SiC）
                       13_arxiv_2411.18868.pdf（SiC）
                       Flat-top picosecond laser texturing of CFRP.pdf
Equipment profile:   EQ-DEMO-FS（spot_radius_um=5.0 µm，UNVERIFIED，M7 显式标记）
Model candidates:    ultrafast_e2p.application.model_selection 固定 registry
BO seed:             42（random_seed=42）
BO 模式:             Vanilla（无 prior）vs Evidence-assisted（governed_prior）
```

## 2. 演示故事线（10 步）

```text
① 导入目标实验数据（CSV → 参数域/样本）
② 自动参数辨识与模型选择（RAW/HYBRID × Group-CV）
③ 展示当前物理可计算性/缺口（Source/Target readiness + blocked coordinates）
④ 读取 5 篇论文并重建实验条件（mentions → conditions → source states）
⑤ 展示 Source ↔ Target CFA 五 facet（Uncalibrated，KNOWN/PARTIAL/UNKNOWN/MISMATCH）
⑥ 展示哪些文献 Evidence 被采用/拒绝/未知（evidence bundle accepted/rejected）
⑦ E2P 编译为 governed prior（GovernedPriorArtifact，evidence_ids 可追溯）
⑧ Vanilla BO vs Evidence-assisted BO（prior_applied true/false 对照）
⑨ 输出下一轮候选实验（recommended_parameters）
⑩ 点击任一结果回溯：dataset / paper / condition / evidence / prior / BO run
```

## 3. 展示纪律（严禁越界）

```text
× 展示 "transfer probability = 82%" 类结果（无科学依据）
× 用 B1-25 结果声称独立泛化性能
√ 表述固定为 "Uncalibrated CFA"；facet 状态限于
  KNOWN / PARTIAL / UNKNOWN / MISMATCH + warnings
√ B1-25 只能表述为 diagnostic audit 结果
√ calibration_status 一律显示 NOT_YET_CALIBRATED
```

## 4. 冻结版本依赖（随 release tag 固化）

```text
CFA: uncalibrated-cfa-v2.0（含 V2-1 dependency-aware + V2-2 RANGE 语义）
E2P: 编译/prior 链路（knowledge gate 显式放行并留痕）
BO:  BORecommendationService（governed_prior 唯一合法 prior 路径）
```

## 5. 复现命令

```text
python scripts/demo_t2_vertical_slice.py --output outputs/t2_slice_run.json
python scripts/demo_report.py                      # 生成 outputs/topic2_demo_report.html
```

重复运行必须逐字节一致（R16：fixed seed/config 可重放）。
HTML 报告为自包含单文件（零依赖，离线浏览器直开），内含 10 步故事线、
facet 表、evidence/prior/BO 对照与全链路回溯；生成时自动执行展示纪律
检查（Uncalibrated / NOT_YET_CALIBRATED / 无概率词 / B1-25 仅 diagnostic）。
