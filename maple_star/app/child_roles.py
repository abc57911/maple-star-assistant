from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Protocol

from maple_star.ipc.identity import WorkerIdentity, WorkerRole


class ResultQueue(Protocol):
    def put(self, item: object) -> None: ...


@dataclass(frozen=True, slots=True)
class ChildRoleBootstrap:
    session_epoch: str
    role: WorkerRole
    incarnation: int
    parent_pid: int

    def __post_init__(self) -> None:
        WorkerIdentity(self.session_epoch, self.role, self.incarnation)
        if self.parent_pid < 1:
            raise ValueError("parent_pid must be positive")

    @property
    def identity(self) -> WorkerIdentity:
        return WorkerIdentity(self.session_epoch, self.role, self.incarnation)


def _bootstrap_result(bootstrap: ChildRoleBootstrap) -> dict[str, object]:
    return {
        "session_epoch": bootstrap.session_epoch,
        "role": bootstrap.role.value,
        "incarnation": bootstrap.incarnation,
        "parent_pid": bootstrap.parent_pid,
    }


def run_noop_child(bootstrap: ChildRoleBootstrap, result_queue: ResultQueue) -> None:
    """Top-level spawn target used to prove child bootstrap semantics."""

    _ = bootstrap.identity
    result_queue.put(_bootstrap_result(bootstrap))


def probe_child_imports(bootstrap: ChildRoleBootstrap, result_queue: ResultQueue) -> None:
    """Report forbidden packages loaded by the minimal child bootstrap graph."""

    forbidden_roots = ("PySide6", "tkinter", "customtkinter", "paddle", "paddleocr", "pygame")
    loaded = sorted(
        root
        for root in forbidden_roots
        if root in sys.modules or any(name.startswith(f"{root}.") for name in sys.modules)
    )
    result_queue.put(
        {
            "role": bootstrap.role.value,
            "pid": os.getpid(),
            "loaded_forbidden_modules": loaded,
        }
    )
