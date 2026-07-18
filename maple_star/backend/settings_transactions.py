from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from maple_star.services.settings_store import TransactionalSettingsStore


class SettingsParticipant(Protocol):
    def prepare(self, transaction_id: str, payload: dict[str, object]) -> bool: ...

    def stage(self, transaction_id: str, payload: dict[str, object]) -> bool: ...

    def activate(self, transaction_id: str) -> bool: ...

    def abort(self, transaction_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class SettingsTransactionResult:
    transaction_id: str
    phase: str
    committed: bool
    activated: bool
    reason: str | None = None


class SettingsTransactionCoordinator:
    def __init__(
        self,
        store: TransactionalSettingsStore,
        participants: list[SettingsParticipant],
    ) -> None:
        self._store = store
        self._participants = tuple(participants)

    def _abort_all(self, transaction_id: str) -> None:
        for participant in self._participants:
            try:
                participant.abort(transaction_id)
            except Exception:
                continue

    def apply(self, transaction_id: str, payload: dict[str, object]) -> SettingsTransactionResult:
        for participant in self._participants:
            try:
                accepted = participant.prepare(transaction_id, payload)
            except Exception as exc:
                accepted = False
                reason = str(exc)
            else:
                reason = None
            if not accepted:
                self._abort_all(transaction_id)
                return SettingsTransactionResult(transaction_id, "prepare", False, False, reason or "rejected")

        try:
            self._store.stage_candidate(transaction_id, payload)
            for participant in self._participants:
                if not participant.stage(transaction_id, payload):
                    raise RuntimeError("worker rejected staged settings")
        except Exception as exc:
            self._abort_all(transaction_id)
            self._store.discard_candidate(transaction_id)
            return SettingsTransactionResult(transaction_id, "stage", False, False, str(exc))

        try:
            self._store.commit_candidate(transaction_id)
        except Exception as exc:
            self._abort_all(transaction_id)
            return SettingsTransactionResult(transaction_id, "commit", False, False, str(exc))

        activated = True
        reason = None
        for participant in self._participants:
            try:
                accepted = participant.activate(transaction_id)
            except Exception as exc:
                accepted = False
                reason = str(exc)
            if not accepted:
                activated = False
                reason = reason or "worker activation failed"
        return SettingsTransactionResult(transaction_id, "complete" if activated else "activate", True, activated, reason)


__all__ = ["SettingsParticipant", "SettingsTransactionCoordinator", "SettingsTransactionResult"]
