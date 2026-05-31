from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

from ..adapters.debug_logging import log_exception
from ..adapters.win_input import key_down, key_up, tap_hotkey

POTION_ACTION_WORKER_MAX_PENDING_ACTIONS = 64
POTION_ACTION_QUEUE_GET_TIMEOUT_SECONDS = 0.05
_COALESCED_ACTIONS = {"hold", "refresh_hold", "release"}


@dataclass(frozen=True)
class PotionAction:
    action: str
    bar_type: str
    key_name: str = ""
    vk_code: int = 0


@dataclass
class PotionActionWorker:
    max_pending_actions: int = POTION_ACTION_WORKER_MAX_PENDING_ACTIONS
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _condition: threading.Condition = field(default_factory=threading.Condition)
    _actions: deque[PotionAction] = field(default_factory=deque)
    _thread: threading.Thread | None = None

    def __post_init__(self) -> None:
        self.max_pending_actions = max(1, int(self.max_pending_actions))

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
        self._enqueue(PotionAction("tap", bar_type, key_name=key_name))

    def hold(self, bar_type: str, vk_code: int) -> None:
        self._enqueue(PotionAction("hold", bar_type, vk_code=vk_code))

    def refresh_hold(self, bar_type: str, vk_code: int) -> None:
        self._enqueue(PotionAction("refresh_hold", bar_type, vk_code=vk_code))

    def release(self, bar_type: str, vk_code: int) -> None:
        self._enqueue(PotionAction("release", bar_type, vk_code=vk_code))

    def release_all(self) -> None:
        self._enqueue(PotionAction("release_all", "all"))

    def clear_actions(self) -> None:
        with self._condition:
            self._actions.clear()

    def drain_actions(self, limit: int = 64) -> list[PotionAction]:
        actions: list[PotionAction] = []
        with self._condition:
            for _ in range(max(0, int(limit))):
                if not self._actions:
                    break
                actions.append(self._actions.popleft())
        return actions

    def _enqueue(self, action: PotionAction) -> None:
        with self._condition:
            self._coalesce_pending_actions(action)
            while len(self._actions) >= self.max_pending_actions:
                self._drop_oldest_pending_action()
            self._actions.append(action)
            self._condition.notify()

    def _coalesce_pending_actions(self, action: PotionAction) -> None:
        if action.action == "release_all":
            self._actions.clear()
            return
        if action.action not in _COALESCED_ACTIONS:
            return
        self._actions = deque(
            pending
            for pending in self._actions
            if not self._pending_action_is_superseded(pending, action)
        )

    def _pending_action_is_superseded(self, pending: PotionAction, action: PotionAction) -> bool:
        return (
            pending.action in _COALESCED_ACTIONS
            and pending.bar_type == action.bar_type
        )

    def _drop_oldest_pending_action(self) -> None:
        if not self._actions:
            return
        for index, action in enumerate(self._actions):
            if action.action != "release_all":
                del self._actions[index]
                return
        self._actions.popleft()

    def _get_action(self, timeout: float) -> PotionAction | None:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while not self._actions and not self._stop_event.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            if not self._actions:
                return None
            return self._actions.popleft()

    def _run(self) -> None:
        held: dict[str, int] = {}
        while not self._stop_event.is_set():
            action = self._get_action(POTION_ACTION_QUEUE_GET_TIMEOUT_SECONDS)
            if action is None:
                continue
            try:
                _apply_potion_action(action, held)
            except Exception:
                log_exception(
                    "喝水按鍵背景工作失敗："
                    f"action={action.action} bar={action.bar_type} "
                    f"key={action.key_name or action.vk_code}"
                )

        _release_held_potion_keys(held)


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
            held.pop(action.bar_type, None)
        key_down(action.vk_code)
        held[action.bar_type] = action.vk_code
        return

    if action.action == "refresh_hold":
        current_vk = held.get(action.bar_type, 0)
        if current_vk and current_vk != action.vk_code:
            key_up(current_vk)
            held.pop(action.bar_type, None)
        key_down(action.vk_code)
        held[action.bar_type] = action.vk_code
        return

    if action.action == "release":
        current_vk = held.get(action.bar_type, 0)
        vk_code = current_vk or action.vk_code
        if vk_code:
            key_up(vk_code)
        held.pop(action.bar_type, None)
        return

    if action.action == "release_all":
        _release_held_potion_keys(held)


def _release_held_potion_keys(held: dict[str, int]) -> None:
    for bar_type, vk_code in list(held.items()):
        try:
            key_up(vk_code)
        except Exception:
            log_exception(f"喝水按鍵釋放失敗：vk={vk_code}")
            continue
        held.pop(bar_type, None)
