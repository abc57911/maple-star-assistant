from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from typing import Protocol

import numpy as np


CaptureRegion = Mapping[str, int]


class ScreenCapturePort(Protocol):
    def grab(self, region: CaptureRegion) -> np.ndarray: ...


class ScreenCaptureService:
    def __init__(self, backend_factory: Callable[[], object]) -> None:
        self._lock = threading.RLock()
        self._backend = backend_factory()
        self._closed = False

    @classmethod
    def from_backend(cls, backend: object) -> ScreenCaptureService:
        service = cls.__new__(cls)
        service._lock = threading.RLock()
        service._backend = backend
        service._closed = False
        return service

    @property
    def backend(self) -> object:
        return self._backend

    def replace_backend(self, backend: object) -> None:
        with self._lock:
            if backend is self._backend:
                return
            if not self._closed:
                self._backend.close()
            self._backend = backend
            self._closed = False

    def grab(self, region: CaptureRegion) -> np.ndarray:
        with self._lock:
            if self._closed:
                raise RuntimeError("screen capture service is closed")
            return np.asarray(self._backend.grab(dict(region))).copy()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._backend.close()
            self._closed = True


__all__ = ["CaptureRegion", "ScreenCapturePort", "ScreenCaptureService"]
