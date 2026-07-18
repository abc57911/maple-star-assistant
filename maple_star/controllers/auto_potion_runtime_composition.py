from __future__ import annotations

from ..models.settings import AutoPotionSettings
from ..backend.windows_job import create_kill_on_close_worker_job
from ..backend.runtime_supervisor_adapter import SupervisedRuntimeProcessPort
from ..services.runtime_api import RuntimeProcessPort
from ..services.runtime_processes import RuntimeProcessCoordinator
from ..workers.input_guardian_process import run_input_guardian_process
from .runtime_child_entrypoints import (
    run_control_runtime_with_guardian,
    run_experience_stats_process,
    run_potion_runtime_process,
)


def create_runtime_process_port(
    settings: AutoPotionSettings,
    target_hwnd: int = 0,
) -> RuntimeProcessPort:
    coordinator = RuntimeProcessCoordinator(
        settings,
        target_hwnd,
        potion_worker_target=run_potion_runtime_process,
        experience_worker_target=run_experience_stats_process,
        guardian_worker_target=run_input_guardian_process,
        guarded_control_target=run_control_runtime_with_guardian,
        worker_job=create_kill_on_close_worker_job(),
    )
    return SupervisedRuntimeProcessPort(coordinator)


__all__ = ["create_runtime_process_port"]
