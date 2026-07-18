from __future__ import annotations

import math

import customtkinter as ctk


class AdaptiveScrollHost(ctk.CTkScrollableFrame):
    """Scrollable page whose natural content height is independent of its viewport."""

    def __init__(self, master, **kwargs) -> None:
        kwargs.setdefault("fg_color", "transparent")
        kwargs.setdefault("corner_radius", 0)
        kwargs.setdefault("border_width", 0)
        super().__init__(master, orientation="vertical", **kwargs)
        self._overflow_enabled = True

    def logical_content_height(self) -> int:
        bbox = self._parent_canvas.bbox("all")
        if bbox is None:
            return 0
        physical_height = max(0, int(bbox[3]) - int(bbox[1]))
        if physical_height <= 0:
            return 0
        try:
            logical_height = float(self._reverse_widget_scaling(physical_height))
        except (AttributeError, AssertionError, TypeError, ValueError):
            return 0
        if not math.isfinite(logical_height) or logical_height <= 0:
            return 0
        return max(1, round(logical_height))

    def set_viewport_height(self, logical_height: int) -> None:
        if logical_height <= 0:
            return
        self.configure(height=int(logical_height))

    def set_overflow_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._overflow_enabled == enabled:
            return
        self._overflow_enabled = enabled
        if enabled:
            self._scrollbar.grid(row=1, column=1, sticky="nsew")
            return
        self._scrollbar.grid_remove()
        self._parent_canvas.yview_moveto(0.0)


__all__ = ["AdaptiveScrollHost"]
