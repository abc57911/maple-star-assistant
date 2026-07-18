from __future__ import annotations

import pickle


def serialize_message(message: object) -> bytes:
    return pickle.dumps(message, protocol=pickle.HIGHEST_PROTOCOL)


def deserialize_message(payload: bytes) -> object:
    if not isinstance(payload, bytes):
        raise TypeError("IPC payload must be bytes")
    return pickle.loads(payload)


__all__ = ["deserialize_message", "serialize_message"]
