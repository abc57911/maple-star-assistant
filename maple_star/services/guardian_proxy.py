from __future__ import annotations

import queue
import time

from maple_star.ipc.messages import CursorMoveCommand, InputAction, InputCommand, MouseAction, MouseCommand


class QueueInputMutationProxy:
    def __init__(self, command_queue, *, safety_generation: int = 0, shared_generation=None) -> None:
        self._queue = command_queue
        self._safety_generation = int(safety_generation)
        self._shared_generation = shared_generation

    @property
    def safety_generation(self) -> int:
        if self._shared_generation is not None:
            return int(self._shared_generation.value)
        return self._safety_generation

    @safety_generation.setter
    def safety_generation(self, value: int) -> None:
        self._safety_generation = int(value)

    def _put(self, action: InputAction, vk_code: int, *, ttl: float) -> None:
        command = InputCommand(
            action,
            vk_code=int(vk_code),
            safety_generation=self.safety_generation,
            expires_at=time.monotonic() + ttl,
        )
        try:
            self._queue.put_nowait(command)
        except queue.Full as exc:
            raise RuntimeError("input guardian queue is full") from exc

    def key_down(self, vk_code: int) -> None:
        self._put(InputAction.KEY_DOWN, vk_code, ttl=0.25)

    def key_up(self, vk_code: int) -> None:
        self._put(InputAction.KEY_UP, vk_code, ttl=5.0)

    def tap_key(self, vk_code: int) -> None:
        self._put(InputAction.TAP, vk_code, ttl=0.25)

    def set_cursor_position(self, x: int, y: int) -> None:
        self._put_command(CursorMoveCommand(int(x), int(y), time.monotonic() + 5.0))

    def left_click(self) -> None:
        self._put_command(MouseCommand(MouseAction.LEFT_CLICK, time.monotonic() + 0.25))

    def release_mouse_buttons(self) -> None:
        self._put_command(MouseCommand(MouseAction.RELEASE_ALL, time.monotonic() + 5.0))

    def _put_command(self, command: object) -> None:
        try:
            self._queue.put_nowait(command)
        except queue.Full as exc:
            raise RuntimeError("input guardian queue is full") from exc


__all__ = ["QueueInputMutationProxy"]
