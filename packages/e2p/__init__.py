"""Topic2 E2P contract adapter.

科学实现已迁移至独立模块 `ultrafast_e2p`（ultrafast_laser_memory/src/ultrafast_e2p）。
本包只保留 Topic2 验收 API 的契约形状（evidence_id / transfer_level 等命名），
算法一律委托给 ultrafast_e2p，避免双份实现。
"""

from __future__ import annotations

import sys
from pathlib import Path

_E2P_SRC = Path(__file__).resolve().parents[2] / "ultrafast_laser_memory" / "src"
if str(_E2P_SRC) not in sys.path:
    sys.path.insert(0, str(_E2P_SRC))
