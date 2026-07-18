from __future__ import annotations

import queue
import time

from maple_star.adapters.guardian_win_input import GuardianWinInput
from maple_star.backend.parent_lease import WindowsParentProcessLease
from maple_star.backend.process_priority import set_current_process_above_normal
from maple_star.ipc.messages import (
    CursorMoveCommand,
    InputCommand,
    MouseAction,
    MouseCommand,
    RearmCommand,
    SafetyFenceCommand,
)
from maple_star.services.runtime_api import Shutdown, TargetWindowUpdated, WorkerCrashed
from maple_star.services.runtime_processes import _is_target_hwnd_active

from .input_guardian import InputGuardian


def run_input_guardian_process(command_queue, status_queue, target_hwnd: int, parent_pid: int) -> None:
    set_current_process_above_normal()
    target = {"hwnd": int(target_hwnd or 0)}
    guardian = InputGuardian(
        GuardianWinInput(),
        foreground_check=lambda: _is_target_hwnd_active(target["hwnd"]),
    )
    parent_lease = WindowsParentProcessLease(parent_pid)
    try:
        while True:
            if not parent_lease.alive():
                guardian.terminal_stop(generation=guardian.safety_generation + 1)
                return
            try:
                command = command_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if isinstance(command, Shutdown):
                guardian.terminal_stop(generation=guardian.safety_generation + 1)
                return
            if isinstance(command, TargetWindowUpdated):
                target["hwnd"] = int(command.hwnd or 0)
                continue
            if isinstance(command, SafetyFenceCommand):
                guardian.safety_fence(generation=command.generation)
                continue
            if isinstance(command, RearmCommand):
                guardian.rearm(generation=command.generation)
                continue
            if isinstance(command, InputCommand):
                guardian.handle(command, now=time.monotonic())
                continue
            if isinstance(command, CursorMoveCommand) and time.monotonic() <= command.expires_at:
                guardian.move_cursor(command.x, command.y)
                continue
            if isinstance(command, MouseCommand) and time.monotonic() <= command.expires_at:
                if command.action is MouseAction.LEFT_CLICK:
                    guardian.left_click()
                elif command.action is MouseAction.RELEASE_ALL:
                    guardian.release_mouse_buttons()
    except Exception as exc:
        guardian.terminal_stop(generation=guardian.safety_generation + 1)
        status_queue.put(WorkerCrashed("guardian", str(exc)))
    finally:
        parent_lease.close()


__all__ = ["run_input_guardian_process"]
