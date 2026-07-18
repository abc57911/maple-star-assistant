from __future__ import annotations

from typing import Protocol


class KeyboardMutationPort(Protocol):
    def key_down(self, vk: int) -> None: ...

    def key_up(self, vk: int) -> None: ...


class InputOwnershipLedger:
    def __init__(self) -> None:
        self._may_be_held: set[int] = set()
        self._confirmed_held: set[int] = set()

    @property
    def may_be_held(self) -> frozenset[int]:
        return frozenset(self._may_be_held)

    @property
    def confirmed_held(self) -> frozenset[int]:
        return frozenset(self._confirmed_held)

    def key_down(self, vk: int, adapter: KeyboardMutationPort) -> None:
        self._may_be_held.add(vk)
        adapter.key_down(vk)
        self._confirmed_held.add(vk)

    def key_up(self, vk: int, adapter: KeyboardMutationPort) -> None:
        adapter.key_up(vk)
        self._confirmed_held.discard(vk)
        self._may_be_held.discard(vk)

    def release_all(self, adapter: KeyboardMutationPort) -> tuple[tuple[int, Exception], ...]:
        failures: list[tuple[int, Exception]] = []
        for vk in sorted(self._may_be_held | self._confirmed_held):
            try:
                adapter.key_up(vk)
            except Exception as exc:
                failures.append((vk, exc))
                continue
            self._confirmed_held.discard(vk)
            self._may_be_held.discard(vk)
        return tuple(failures)


__all__ = ["InputOwnershipLedger", "KeyboardMutationPort"]
