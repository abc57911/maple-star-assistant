from __future__ import annotations

import ctypes
import os
import platform
import re
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path


def _run_text(command: list[str], *, cwd: Path | None = None) -> str | None:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value or None


def _git_commit(root: Path) -> str | None:
    return _run_text(["git", "rev-parse", "HEAD"], cwd=root)


def _cpu_name() -> str:
    return os.environ.get("PROCESSOR_IDENTIFIER") or platform.processor() or "unknown"


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _total_ram_bytes() -> int | None:
    if sys.platform != "win32":
        return None
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.ullTotalPhys)


def _active_power_plan() -> str | None:
    output = _run_text(["powercfg", "/getactivescheme"])
    if output is None:
        return None
    match = re.search(r"([0-9a-fA-F-]{36})(?:\s+\(([^)]*)\))?", output)
    if match is None:
        return output
    guid, name = match.groups()
    return f"{guid} ({name})" if name else guid


def _system_dpi() -> int | None:
    if sys.platform != "win32":
        return None
    try:
        return int(ctypes.windll.user32.GetDpiForSystem())
    except (AttributeError, OSError):
        return None


def collect_benchmark_environment(
    *,
    mode: str,
    cache_condition: str,
    root: Path | None = None,
    game_window_size: tuple[int, int] | None = None,
    worker_identity: dict[str, object] | None = None,
) -> dict[str, object]:
    project_root = root or Path(__file__).resolve().parents[2]
    metadata: dict[str, object] = {
        "commit": _git_commit(project_root),
        "mode": mode,
        "python": platform.python_version(),
        "executable": sys.executable,
        "cpu": _cpu_name(),
        "logical_cores": os.cpu_count() or 1,
        "ram_bytes": _total_ram_bytes(),
        "windows_build": platform.platform(),
        "system_dpi": _system_dpi(),
        "power_plan": _active_power_plan(),
        "cache_condition": cache_condition,
    }
    if game_window_size is not None:
        metadata["game_window_size"] = list(game_window_size)
    if worker_identity is not None:
        metadata["worker_identity"] = dict(worker_identity)
    return metadata
