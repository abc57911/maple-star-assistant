from __future__ import annotations

from collections import OrderedDict, deque
from threading import Lock
from typing import Generic, TypeVar


K = TypeVar("K")
T = TypeVar("T")


class LatestWinsMailbox(Generic[K, T]):
    def __init__(self, *, max_keys: int) -> None:
        if max_keys < 1:
            raise ValueError("max_keys must be positive")
        self._max_keys = max_keys
        self._items: OrderedDict[K, T] = OrderedDict()
        self._lock = Lock()
        self.dropped_count = 0

    def put(self, key: K, value: T) -> None:
        with self._lock:
            if key in self._items:
                self._items[key] = value
                return
            if len(self._items) >= self._max_keys:
                self._items.popitem(last=False)
                self.dropped_count += 1
            self._items[key] = value

    def drain(self) -> list[tuple[K, T]]:
        with self._lock:
            items = list(self._items.items())
            self._items.clear()
            return items

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


class BoundedFifo(Generic[T]):
    def __init__(self, *, maxsize: int) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be positive")
        self._maxsize = maxsize
        self._items: deque[T] = deque()
        self._lock = Lock()
        self.dropped_count = 0

    def put(self, item: T) -> bool:
        with self._lock:
            if len(self._items) >= self._maxsize:
                self.dropped_count += 1
                return False
            self._items.append(item)
            return True

    def drain(self, *, limit: int | None = None) -> list[T]:
        with self._lock:
            count = len(self._items) if limit is None else min(max(0, limit), len(self._items))
            return [self._items.popleft() for _ in range(count)]

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
