"""Spawn-safe IPC contracts for the maple-star runtime."""

from .identity import MessageMeta, StreamSequencer, WorkerIdentity, WorkerRole

__all__ = ["MessageMeta", "StreamSequencer", "WorkerIdentity", "WorkerRole"]
