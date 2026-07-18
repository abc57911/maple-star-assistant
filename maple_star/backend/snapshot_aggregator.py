from __future__ import annotations

from collections.abc import Hashable, Mapping

from maple_star.ipc.identity import MessageMeta, WorkerIdentity, WorkerRole


class SnapshotAggregator:
    def __init__(self, identities: Mapping[WorkerRole, WorkerIdentity]) -> None:
        self._identities = dict(identities)
        self._last_sequences: dict[tuple[WorkerRole, str], int] = {}
        self._signatures: dict[tuple[WorkerRole, str], Hashable] = {}

    def set_identity(self, identity: WorkerIdentity) -> None:
        self._identities[identity.worker_role] = identity
        for key in [key for key in self._last_sequences if key[0] is identity.worker_role]:
            self._last_sequences.pop(key, None)
            self._signatures.pop(key, None)

    def accept(self, meta: MessageMeta, *, signature: Hashable) -> bool:
        identity = self._identities.get(meta.worker_role)
        if identity is None or not meta.is_current(
            identity,
            last_sequence=self._last_sequences.get((meta.worker_role, meta.channel), 0),
        ):
            return False
        key = (meta.worker_role, meta.channel)
        self._last_sequences[key] = meta.stream_sequence
        if self._signatures.get(key) == signature:
            return False
        self._signatures[key] = signature
        return True


__all__ = ["SnapshotAggregator"]
