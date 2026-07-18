from __future__ import annotations

from PySide6.QtGui import QImage

from maple_star.ipc.preview_transport import PreviewFrame


class LatestPreviewImage:
    def __init__(self) -> None:
        self.frame_id = 0
        self.image = QImage()

    def update(self, frame: PreviewFrame) -> bool:
        if frame.frame_id <= self.frame_id or frame.pixel_format != "BGRA":
            return False
        image = QImage(
            frame.payload,
            frame.width,
            frame.height,
            frame.width * frame.channels,
            QImage.Format.Format_ARGB32,
        ).copy()
        self.frame_id = frame.frame_id
        self.image = image
        return True


__all__ = ["LatestPreviewImage"]
