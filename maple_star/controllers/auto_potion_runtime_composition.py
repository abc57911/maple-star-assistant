from __future__ import annotations

from ..models.settings import AutoPotionSettings
from ..services.runtime_api import RuntimeProcessPort
from ..services.runtime_processes import RuntimeProcessCoordinator
from .runtime_child_entrypoints import run_experience_stats_process, run_potion_runtime_process


def create_runtime_process_port(
    settings: AutoPotionSettings,
    target_hwnd: int = 0,
) -> RuntimeProcessPort:
    return RuntimeProcessCoordinator(
        settings,
        target_hwnd,
        potion_worker_target=run_potion_runtime_process,
        experience_worker_target=run_experience_stats_process,
    )


__all__ = ["create_runtime_process_port"]
