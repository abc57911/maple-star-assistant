from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from ctypes import wintypes


@dataclass(slots=True)
class ParentLease:
    heartbeat_timeout: float
    last_heartbeat_at: float

    def heartbeat(self, *, now: float) -> None:
        self.last_heartbeat_at = now

    def check(self, *, now: float, gui_pipe_alive: bool, launcher_alive: bool) -> str | None:
        if not gui_pipe_alive:
            return "gui-pipe-eof"
        if not launcher_alive:
            return "launcher-exited"
        if now - self.last_heartbeat_at > self.heartbeat_timeout:
            return "heartbeat-timeout"
        return None


class WindowsParentProcessLease:
    SYNCHRONIZE = 0x00100000
    WAIT_OBJECT_0 = 0

    def __init__(self, parent_pid: int) -> None:
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if sys.platform == "win32" else None
        if self._kernel32 is not None:
            self._kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            self._kernel32.OpenProcess.restype = wintypes.HANDLE
            self._kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            self._kernel32.WaitForSingleObject.restype = wintypes.DWORD
            self._kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._handle = (
            self._kernel32.OpenProcess(self.SYNCHRONIZE, False, int(parent_pid))
            if self._kernel32 is not None
            else None
        )
        if self._kernel32 is not None and not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def alive(self) -> bool:
        if self._kernel32 is None:
            return True
        return bool(self._handle) and self._kernel32.WaitForSingleObject(self._handle, 0) != self.WAIT_OBJECT_0

    def __enter__(self) -> "WindowsParentProcessLease":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._kernel32 is not None and self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


__all__ = ["ParentLease", "WindowsParentProcessLease"]
