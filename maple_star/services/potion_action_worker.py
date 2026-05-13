from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field

from ..adapters.win_input import key_down, key_up, tap_hotkey


@dataclass(frozen=True)
class PotionAction:
    action: str
    bar_type: str
    key_name: str = ""
    vk_code: int = 0


@dataclass
class PotionActionWorker:
    action_queue: queue.SimpleQueue[PotionAction] = field(default_factory=queue.SimpleQueue)
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="MapleStarPotionActionWorker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self.release_all()
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        self.clear_actions()

    def tap(self, bar_type: str, key_name: str) -> None:
        self.action_queue.put(PotionAction("tap", bar_type, key_name=key_name))

    def hold(self, bar_type: str, vk_code: int) -> None:
        self.action_queue.put(PotionAction("hold", bar_type, vk_code=vk_code))

    def release(self, bar_type: str, vk_code: int) -> None:
        self.action_queue.put(PotionAction("release", bar_type, vk_code=vk_code))

    def release_all(self) -> None:
        self.action_queue.put(PotionAction("release_all", "all"))

    def clear_actions(self) -> None:
        while True:
            try:
                self.action_queue.get_nowait()
            except queue.Empty:
                return

    def drain_actions(self, limit: int = 64) -> list[PotionAction]:
        actions: list[PotionAction] = []
        for _ in range(limit):
            try:
                actions.append(self.action_queue.get_nowait())
            except queue.Empty:
                break
        return actions

    def _run(self) -> None:
        held: dict[str, int] = {}
        while not self._stop_event.is_set():
            try:
                action = self.action_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            _apply_potion_action(action, held)

        for vk_code in list(held.values()):
            key_up(vk_code)
        held.clear()


def _apply_potion_action(action: PotionAction, held: dict[str, int]) -> None:
    if action.action == "tap":
        tap_hotkey(action.key_name)
        return

    if action.action == "hold":
        current_vk = held.get(action.bar_type, 0)
        if current_vk == action.vk_code:
            return
        if current_vk:
            key_up(current_vk)
        key_down(action.vk_code)
        held[action.bar_type] = action.vk_code
        return

    if action.action == "release":
        current_vk = held.pop(action.bar_type, 0)
        vk_code = current_vk or action.vk_code
        if vk_code:
            key_up(vk_code)
        return

    if action.action == "release_all":
        for vk_code in list(held.values()):
            key_up(vk_code)
        held.clear()
