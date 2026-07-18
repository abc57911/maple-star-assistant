from __future__ import annotations

from . import win_input


class GuardianWinInput:
    """The only production adapter allowed to invoke native keyboard mutation."""

    def key_down(self, vk: int) -> None:
        win_input._native_key_down(vk)

    def key_up(self, vk: int) -> None:
        win_input._native_key_up(vk)

    def set_cursor_position(self, x: int, y: int) -> None:
        win_input._native_set_cursor_position(x, y)

    def left_click(self) -> None:
        win_input._native_left_click()

    def release_mouse_buttons(self) -> None:
        win_input._native_release_mouse_buttons()


__all__ = ["GuardianWinInput"]
