from __future__ import annotations

from typing import Protocol

from ..adapters.controller_worker import CONTROLLER_BUTTONS_BY_NAME
from ..models.settings import AutoPotionSettings


class ControllerButtonBinding(Protocol):
    name: str

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
    rb_macro: ControllerButtonBinding,
    lb_macro: ControllerButtonBinding,
) -> dict[int, tuple[ControllerButtonBinding, ...]]:
    bindings: dict[int, list[ControllerButtonBinding]] = {}
    rb_button = configured_controller_button(settings.rb_controller_button)
    lb_button = configured_controller_button(settings.lb_controller_button)
    if settings.rb_enabled and rb_button is not None:
        bindings.setdefault(rb_button, []).append(rb_macro)
    if settings.lb_enabled and lb_button is not None:
        bindings.setdefault(lb_button, []).append(lb_macro)
    return {button: tuple(button_bindings) for button, button_bindings in bindings.items()}


def is_controller_binding_enabled(
    settings: AutoPotionSettings,
    binding: ControllerButtonBinding,
    rb_macro: ControllerButtonBinding,
    lb_macro: ControllerButtonBinding,
) -> bool:
    if binding is rb_macro:
        return settings.rb_enabled
    if binding is lb_macro:
        return settings.lb_enabled
    return True


def first_enabled_controller_binding(
    bindings: tuple[ControllerButtonBinding, ...],
    settings: AutoPotionSettings,
    rb_macro: ControllerButtonBinding,
    lb_macro: ControllerButtonBinding,
) -> ControllerButtonBinding | None:
    for binding in bindings:
        if is_controller_binding_enabled(settings, binding, rb_macro, lb_macro):
            return binding
    return None

