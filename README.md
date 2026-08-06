# Ultrafast Laser Process Learning Kernel

主计划 V2 的正式仓库（Brownfield 迁移内核）。

- 文档与决策：`docs/`（契约冻结见 `docs/contracts/CONTRACT_V2_FREEZE.md`）
- 权威内核来源：`ultrafast_laser_memory/src/ultrafast_*`（MIGRATE，见主计划 V2 §2）
- 包边界由 `lint-imports`（import-linter）强制

## 当前包（S0-8 打包验证闭包）

```
src/
├── process_contracts/   # 契约（TaskScope v2 扩展中）
├── ultrafast_shared/    # 共享基础设施（units/config/db）
├── ultrafast_domain/    # 领域模型（leaf）
├── ultrafast_physics/   # 物理特征引擎（leaf）
├── ultrafast_e2p/       # 证据适用性/编译（leaf）
└── ultrafast_bo/        # 治理化 GP-UCB
```

注：`ultrafast_knowledge` 因依赖 `ultrafast_memory`（db/ids/config）与
`ultrafast_integrations`（storage），其 re-homing 为独立迁移项（GAP-06），
不在 S0-8 闭包内。

## 安装与验证

```bash
# 注意：系统 python 是 Windows Store 占位符，需用旧仓库 venv 的 python 建 venv：
# "C:\Users\RZF\Desktop\博士课题资料\ultrafast agent\.venv\Scripts\python.exe" -m venv .venv
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv\Scripts\python -c "import process_contracts, ultrafast_shared, ultrafast_domain, ultrafast_physics, ultrafast_e2p, ultrafast_bo"
.venv\Scripts\python -m pytest tests -q
lint-imports
```

依赖版本已按旧环境锁定（PyPI 直连在此网络环境会超时，见 docs/KNOWN_GAPS.md GAP-09/10）。
