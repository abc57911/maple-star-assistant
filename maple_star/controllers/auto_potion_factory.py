from __future__ import annotations

from typing import TYPE_CHECKING

from .auto_potion_runtime_composition import create_runtime_process_port

if TYPE_CHECKING:
    from .auto_potion_controller import AutoPotionController


def _create_auto_potion_controller(*args, **kwargs) -> AutoPotionController:
    from .auto_potion_controller import AutoPotionController

    kwargs.setdefault("runtime_process_factory", create_runtime_process_port)
    controller = AutoPotionController.__new__(AutoPotionController)
    controller._initialization_completed = False
    try:
        controller.__init__(*args, **kwargs)
    except BaseException:
        controller.cleanup()
        raise
    controller._initialization_completed = True
    return controller


__all__ = ["_create_auto_potion_controller"]
