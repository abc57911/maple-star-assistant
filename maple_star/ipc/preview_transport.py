from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .mailbox import LatestWinsMailbox


@dataclass(frozen=True, slots=True)
class PreviewFrame:
    producer: str
    frame_id: int
    width: int
    height: int
    bytes_per_pixel: int
    pixel_format: str
    payload: bytes | bytearray | memoryview
    created_at: float

    def __post_init__(self) -> None:
        if not self.producer or not self.pixel_format:
            raise ValueError("preview producer and format must not be empty")
        if self.frame_id < 1 or min(self.width, self.height, self.bytes_per_pixel) < 1:
            raise ValueError("preview dimensions and frame id must be positive")
        copied = bytes(self.payload)
        expected = self.width * self.height * self.bytes_per_pixel
        if len(copied) != expected:
            raise ValueError(f"preview payload size mismatch: expected {expected}, got {len(copied)}")
        object.__setattr__(self, "payload", copied)


class PreviewTransport(Protocol):
    def publish(self, frame: PreviewFrame) -> None: ...

    def drain_latest(self) -> list[PreviewFrame]: ...


class SerializedPreviewTransport:
    def __init__(self, *, max_producers: int) -> None:
        self._mailbox: LatestWinsMailbox[str, PreviewFrame] = LatestWinsMailbox(max_keys=max_producers)

    @property
    def dropped_count(self) -> int:
        return self._mailbox.dropped_count

    def publish(self, frame: PreviewFrame) -> None:
        copied = PreviewFrame(
            producer=frame.producer,
            frame_id=frame.frame_id,
            width=frame.width,
            height=frame.height,
            bytes_per_pixel=frame.bytes_per_pixel,
            pixel_format=frame.pixel_format,
            payload=bytes(frame.payload),
            created_at=frame.created_at,
        )
        self._mailbox.put(copied.producer, copied)

    def drain_latest(self) -> list[PreviewFrame]:
        return [frame for _producer, frame in self._mailbox.drain()]


__all__ = ["PreviewFrame", "PreviewTransport", "SerializedPreviewTransport"]
