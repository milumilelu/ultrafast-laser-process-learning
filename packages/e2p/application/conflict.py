"""Topic2 adapter: Prior–Data Conflict（delegated to ultrafast_e2p）。"""

from __future__ import annotations

from ultrafast_e2p.application.conflict import (
    apply_conflict_multiplier,
    compile_conflict_report,
)

__all__ = ["apply_conflict_multiplier", "compile_conflict_report"]
