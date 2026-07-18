from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .identity import MessageMeta


@dataclass(frozen=True, slots=True)
class FeatureStateCommand:
    meta: MessageMeta
    scripts_enabled: bool
    feature_enabled: bool


@dataclass(frozen=True, slots=True)
class WorkerHeartbeat:
    meta: MessageMeta
    process_id: int
    phase: str
    progress_at: float


class InputAction(StrEnum):
    KEY_DOWN = "key_down"
    KEY_UP = "key_up"
    TAP = "tap"


@dataclass(frozen=True, slots=True)
class InputCommand:
    action: InputAction
    vk_code: int
    safety_generation: int
    expires_at: float

    def __post_init__(self) -> None:
        if not 0 < self.vk_code <= 0xFF:
            raise ValueError("vk_code must be a Windows virtual key")
        if self.safety_generation < 0:
            raise ValueError("safety_generation must not be negative")


@dataclass(frozen=True, slots=True)
class CursorMoveCommand:
    x: int
    y: int
    expires_at: float


class MouseAction(StrEnum):
    LEFT_CLICK = "left_click"
    RELEASE_ALL = "release_all"


@dataclass(frozen=True, slots=True)
class MouseCommand:
    action: MouseAction
    expires_at: float


@dataclass(frozen=True, slots=True)
class SafetyFenceCommand:
    generation: int


@dataclass(frozen=True, slots=True)
class RearmCommand:
    generation: int


class SettingsTransactionPhase(StrEnum):
    PREPARE = "prepare"
    STAGE = "stage"
    ACTIVATE = "activate"
    ABORT = "abort"


@dataclass(frozen=True, slots=True)
class SettingsTransactionCommand:
    transaction_id: str
    phase: SettingsTransactionPhase
    payload: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if not self.transaction_id:
            raise ValueError("transaction_id must not be empty")


@dataclass(frozen=True, slots=True)
class SettingsTransactionAck:
    transaction_id: str
    worker_role: str
    phase: SettingsTransactionPhase
    accepted: bool
    reason: str = ""


__all__ = [
    "CursorMoveCommand",
    "FeatureStateCommand",
    "InputAction",
    "InputCommand",
    "MouseAction",
    "MouseCommand",
    "RearmCommand",
    "SafetyFenceCommand",
    "SettingsTransactionAck",
    "SettingsTransactionCommand",
    "SettingsTransactionPhase",
    "WorkerHeartbeat",
]
