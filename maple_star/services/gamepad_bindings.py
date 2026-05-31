from __future__ import annotations

from typing import Protocol

from ..adapters.controller_worker import CONTROLLER_BUTTONS_BY_NAME
from ..models.settings import AutoPotionSettings


class ControllerButtonBinding(Protocol):
    name: str
    slot_id: str

    def on_button_down(self) -> None: ...

    def on_button_up(self) -> None: ...

    def update(self, now: float) -> None: ...

    def next_deadline_at(self) -> float | None: ...

    def stop(self) -> None: ...

    def cleanup(self) -> None: ...


def configured_controller_button(button_name_value: str) -> int | None:
    return CONTROLLER_BUTTONS_BY_NAME.get(button_name_value)


def build_controller_button_bindings(
    settings: AutoPotionSettings,
    button_bindings: tuple[ControllerButtonBinding, ...],
) -> dict[int, tuple[ControllerButtonBinding, ...]]:
    settings.normalize_combo_slots()
    bindings: dict[int, list[ControllerButtonBinding]] = {}
    for binding in button_bindings:
        slot = settings.combo_slots.get(binding.slot_id)
        if not isinstance(slot, dict) or not slot.get("enabled"):
            continue
        button = configured_controller_button(str(slot.get("trigger_button") or ""))
        if button is not None:
            bindings.setdefault(button, []).append(binding)
    return {button: tuple(button_bindings) for button, button_bindings in bindings.items()}


def is_controller_binding_enabled(
    settings: AutoPotionSettings,
    binding: ControllerButtonBinding,
) -> bool:
    settings.normalize_combo_slots()
    slot = settings.combo_slots.get(binding.slot_id)
    return bool(isinstance(slot, dict) and slot.get("enabled"))


def first_enabled_controller_binding(
    bindings: tuple[ControllerButtonBinding, ...],
    settings: AutoPotionSettings,
) -> ControllerButtonBinding | None:
    for binding in bindings:
        if is_controller_binding_enabled(settings, binding):
            return binding
    return None
