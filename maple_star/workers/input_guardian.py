from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from maple_star.ipc.messages import InputAction, InputCommand
from maple_star.services.input_ownership import InputOwnershipLedger, KeyboardMutationPort


class GuardianState(StrEnum):
    ARMED = "armed"
    BLOCKING = "blocking"
    RELEASING = "releasing"
    SAFE = "safe"
    REARMING = "rearming"


class InputGuardian:
    def __init__(
        self,
        adapter: KeyboardMutationPort,
        *,
        foreground_check: Callable[[], bool],
    ) -> None:
        self._adapter = adapter
        self._foreground_check = foreground_check
        self._ledger = InputOwnershipLedger()
        self.state = GuardianState.ARMED
        self.safety_generation = 0
        self._terminal = False

    @property
    def ledger(self) -> InputOwnershipLedger:
        return self._ledger

    def handle(self, command: InputCommand, *, now: float) -> bool:
        if (
            self._terminal
            or self.state is not GuardianState.ARMED
            or command.safety_generation != self.safety_generation
            or now > command.expires_at
            or (command.action is not InputAction.KEY_UP and not self._foreground_check())
        ):
            return False
        if command.action is InputAction.KEY_DOWN:
            self._ledger.key_down(command.vk_code, self._adapter)
        elif command.action is InputAction.KEY_UP:
            self._ledger.key_up(command.vk_code, self._adapter)
        elif command.action is InputAction.TAP:
            self._ledger.key_down(command.vk_code, self._adapter)
            self._ledger.key_up(command.vk_code, self._adapter)
        else:
            return False
        return True

    def safety_fence(self, *, generation: int) -> bool:
        if generation <= self.safety_generation:
            return False
        self.state = GuardianState.BLOCKING
        self.safety_generation = generation
        self.state = GuardianState.RELEASING
        self._ledger.release_all(self._adapter)
        release_mouse = getattr(self._adapter, "release_mouse_buttons", None)
        if callable(release_mouse):
            release_mouse()
        self.state = GuardianState.SAFE
        return True

    def move_cursor(self, x: int, y: int) -> None:
        self._adapter.set_cursor_position(x, y)

    def left_click(self) -> bool:
        if not self._foreground_check():
            return False
        self._adapter.left_click()
        return True

    def release_mouse_buttons(self) -> None:
        self._adapter.release_mouse_buttons()

    def rearm(self, *, generation: int) -> bool:
        if self._terminal or self.state is not GuardianState.SAFE or generation != self.safety_generation:
            return False
        self.state = GuardianState.REARMING
        self.state = GuardianState.ARMED
        return True

    def terminal_stop(self, *, generation: int) -> None:
        self._terminal = True
        if generation > self.safety_generation:
            self.safety_generation = generation
        self.state = GuardianState.RELEASING
        self._ledger.release_all(self._adapter)
        release_mouse = getattr(self._adapter, "release_mouse_buttons", None)
        if callable(release_mouse):
            release_mouse()
        self.state = GuardianState.SAFE


__all__ = ["GuardianState", "InputGuardian"]
