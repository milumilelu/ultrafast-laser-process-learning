# KNOWN_GAPS / 已知差距与断链登记

> 登记：S0-8 Packaging Validation（2026-08-06）。来源：主计划 V2 §12 + S0-8 实测发现。

| ID | 状态 | 描述 | 处置 |
|---|---|---|---|
| GAP-01 | 已知（来自旧仓库） | E2P prepare → GovernedPriorArtifact → BO 未形成真实完整链；无 artifact 时 Vanilla BO fail-closed（该行为**保留**） | M3：backend integration test 打通；前端后接 |
| GAP-02 | 已知 | 前端参数辨识页走 Agent 侧 identification-v2，与后端 /parameter-identification/run 双轨 | 统一到 ultrafast_learning |
| GAP-03 | 已知 | 真实 CSV 无功率列 / spot=5.0 未核实 / process_capability_config 空 | S0-3 Target Physics Readiness |
| GAP-04 | 已知 | 文献元数据不可重建（wavelength 0/226、pulse_width 14/226…） | S0-2 Metadata Re-extraction（旧仓库已有 pilot 资产，见下） |
| GAP-05 | 已知 | 旧 `src/acquisition.py` 与 ultrafast_bo UCB 双 acquisition 并存 | 旧仓库退役时清除 |
| GAP-06 | S0-8 发现 | `ultrafast_knowledge` 依赖 `ultrafast_memory`（db.session/core.ids/core.config/chat.session_state）与 `ultrafast_integrations.storage`，**不是干净可分离包** | 独立 re-home 工作流（memory core/db 子集 + storage 迁移后并入） |
| GAP-07 | S0-8 发现 | `ultrafast_e2p/application/prior_artifact.py` 原为 sys.path 注入垫片，指向旧仓库 `packages/e2p`；**治理链权威实现在旧 packages 层** | 已解决：新仓库直接内置 canonical 实现（迁移自 packages/e2p/application/prior_artifact.py） |
| GAP-08 | S0-8 发现 | 系统 `python` 为 Windows Store 占位符；venv 需用旧仓库 `.venv\Scripts\python.exe` 创建 | 文档化；建议安装正式 Python 3.12 |
| GAP-09 | S0-8 发现 | PyPI 直连超时（files.pythonhosted.org）；依赖安装须用国内镜像 | README 已记录：`-i https://pypi.tuna.tsinghua.edu.cn/simple` |
| GAP-10 | S0-8 发现 | 依赖版本需锁定：未锁定时 pip 解析冲突/挂起；已按旧环境锁定 numpy==2.3.5 / pandas==3.0.5 / pydantic==2.13.4 / scikit-learn==1.7.2 / sqlalchemy==2.0.51 | 保持锁定，升级走单独 PR |

## S0-2 相关重大发现（旧仓库既有资产，勿重复造）

`ultrafast_laser_memory/benchmarks/literature_metadata/` 已存在：
- `gold/annotations.jsonl`（gold 标注）
- `dev/pilot2_manifest.json` + `pilot2_predictions.jsonl`（已跑 pilot）
- `runs/20260805T112820Z|113444Z|130649Z/`（已跑评估 + predictions）
- `scripts/run_llm_benchmark.py` / `evaluate_extraction.py` / `prepare_annotations.py`
- `work/texts/`：100+ 篇全文 txt（含 task2_*、sc04_*、diamond/CFRP/SiC 相关）

**S0-2 的第一步应是审阅这些既有 pilot 结果（recall/unit/ambiguity），而不是重新开始抽取。**
