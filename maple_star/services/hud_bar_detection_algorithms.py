from __future__ import annotations

import numpy as np

from ..constants import BAR_MIN_BODY_ROW_COUNT


class HudBarDetectionAlgorithms:
    def _capture_bar_percent(
        self,
        bar_type: str,
        require_clear_tail: bool = False,
        *,
        capture_direct,
        find_regions,
        record_failure,
        set_debug,
        failure_reason,
        set_failure_debug,
    ) -> float | None:
        direct_percent = capture_direct(bar_type, require_clear_tail=require_clear_tail)
        if direct_percent is not None:
            return direct_percent
        region = find_regions().get(bar_type)
        if region is None:
            reason = "找不到 HP/MP 定位座標，無法直接取色"
            record_failure(reason)
            set_debug(
                bar_type,
                source="自動定位",
                region=None,
                track_region=None,
                percent=None,
                success=False,
                reason=reason,
                require_clear_tail=require_clear_tail,
                tail_clear=None,
            )
            return None
        direct_percent = capture_direct(bar_type, require_clear_tail=require_clear_tail)
        if direct_percent is not None:
            return direct_percent
        reason = failure_reason("直接取色失敗")
        record_failure(reason)
        set_failure_debug(bar_type, reason, require_clear_tail=require_clear_tail)
        return None

    def _capture_bar_percents(
        self,
        *,
        capture_direct,
        find_regions,
        record_failure,
        failure_reason,
        set_failure_debug,
    ) -> tuple[float | None, float | None]:
        direct = capture_direct()
        if direct is not None:
            return direct
        regions = find_regions()
        if "hp" not in regions or "mp" not in regions:
            reason = "找不到 HP/MP 定位座標，無法直接取色"
            record_failure(reason)
            for bar_type in ("hp", "mp"):
                set_failure_debug(bar_type, reason)
            return None, None
        direct = capture_direct()
        if direct is not None:
            return direct
        reason = failure_reason("直接取色失敗")
        record_failure(reason)
        for bar_type in ("hp", "mp"):
            set_failure_debug(bar_type, reason)
        return None, None

    def _cached_bottom_bar_screen_regions_for_current_client(
        self,
        client_bounds: tuple[int, int, int, int] | None = None,
    ) -> tuple[
        dict[str, tuple[int, int, int, int]],
        dict[str, tuple[int, int, int, int]],
        tuple[int, int, int, int],
    ] | None:
        if client_bounds is None:
            return None
        client_left, client_top, client_width, client_height = client_bounds
        if getattr(self, "bottom_bar_client_size", None) != (client_width, client_height):
            return None

        client_regions = getattr(self, "bottom_bar_regions_client", {})
        if "hp" not in client_regions or "mp" not in client_regions:
            return None

        regions = {
            bar_type: self._client_region_to_screen(region, client_left, client_top)
            for bar_type, region in client_regions.items()
        }
        track_regions = {
            bar_type: self._client_region_to_screen(region, client_left, client_top)
            for bar_type, region in getattr(self, "bottom_bar_track_regions_client", {}).items()
        }
        return regions, track_regions, client_bounds

    def _reuse_cached_bottom_bar_regions_with_direct_sample(
        self,
        now: float,
        *,
        cached_regions=None,
        sample_direct=None,
    ) -> bool:
        cached = (cached_regions or self._cached_bottom_bar_screen_regions_for_current_client)()
        if cached is None:
            return False
        regions, track_regions, client_bounds = cached
        if not self._bar_region_pair_geometry_is_valid(regions, track_regions, client_bounds):
            return False
        for bar_type in ("mp", "hp"):
            sample_region = track_regions.get(bar_type) or regions.get(bar_type)
            if sample_region is None:
                return False
            percent, reason, _tail_clear = (sample_direct or self._sample_direct_bar_percent_from_region)(
                sample_region,
                bar_type,
                require_clear_tail=False,
            )
            if percent is None:
                return False
        self.bottom_bar_regions = regions
        self.bottom_bar_track_regions = track_regions
        self.bottom_bar_client_bounds = client_bounds
        self.bottom_bar_regions_at = now
        return True

    def _can_reuse_stale_bottom_bar_regions(
        self,
        regions: dict[str, tuple[int, int, int, int]],
        track_regions: dict[str, tuple[int, int, int, int]],
        client_bounds: tuple[int, int, int, int] | None,
        *,
        current_bounds: tuple[int, int, int, int] | None = None,
        snapshot_reader=None,
    ) -> bool:
        if "hp" not in regions or "mp" not in regions:
            return False
        if client_bounds is None or client_bounds != current_bounds:
            return False
        if not self._bar_region_pair_geometry_is_valid(regions, track_regions, client_bounds):
            return False

        for bar_type in ("mp", "hp"):
            try:
                percent, reason, _tail_clear = (snapshot_reader or self._bar_percent_from_region_snapshot)(
                    regions[bar_type],
                    bar_type,
                    require_clear_tail=False,
                    track_region=track_regions.get(bar_type),
                )
            except Exception:
                return False
            if percent is None:
                return False
        return True

    def _can_keep_current_bottom_bar_geometry(
        self,
        regions: dict[str, tuple[int, int, int, int]],
        track_regions: dict[str, tuple[int, int, int, int]],
        client_bounds: tuple[int, int, int, int] | None,
        *,
        current_bounds: tuple[int, int, int, int] | None = None,
    ) -> bool:
        if "hp" not in regions or "mp" not in regions:
            return False
        if client_bounds is None or client_bounds != current_bounds:
            return False
        return self._bar_region_pair_geometry_is_valid(regions, track_regions, client_bounds)

    def _capture_bar_percents_direct(
        self,
        *,
        cached_regions=None,
        image_provider=None,
        sample_image=None,
    ) -> tuple[float | None, float | None] | None:
        cached = (cached_regions or self._cached_bottom_bar_screen_regions_for_current_client)()
        if cached is None:
            self._note_direct_bar_failure_reason("沒有 cached HUD geometry")
            return None
        regions, track_regions, client_bounds = cached
        if not self._bar_region_pair_geometry_is_valid(regions, track_regions, client_bounds):
            self._note_direct_bar_failure_reason("HUD geometry 不可信")
            return None
        sample_regions = {
            bar_type: track_regions.get(bar_type) or regions.get(bar_type)
            for bar_type in ("hp", "mp")
        }
        if sample_regions["hp"] is None or sample_regions["mp"] is None:
            self._note_direct_bar_failure_reason("HP/MP direct 取色範圍缺失")
            return None

        union = self._union_direct_bar_regions(sample_regions["hp"], sample_regions["mp"])
        if union is None:
            self._note_direct_bar_failure_reason("HP/MP direct union 範圍無效")
            return None
        image = (image_provider or self._direct_bar_image_from_region)(union)
        if image is None:
            self._note_direct_bar_failure_reason("direct GDI capture 失敗")
            return None

        results: dict[str, float] = {}
        for bar_type in ("hp", "mp"):
            region = sample_regions[bar_type]
            assert region is not None
            crop = self._crop_direct_bar_image(image, union, region)
            if crop is None:
                self._note_direct_bar_failure_reason(f"{bar_type.upper()} direct crop 範圍無效")
                return None
            percent, reason, tail_clear = (sample_image or self._sample_direct_bar_percent_from_image)(
                crop,
                bar_type,
            )
            if percent is None:
                self._note_direct_bar_failure_reason(f"{bar_type.upper()}: {reason}")
                self._set_bar_detection_debug(
                    bar_type,
                    source="直接取色",
                    region=region,
                    track_region=region,
                    percent=None,
                    success=False,
                    reason=reason,
                    require_clear_tail=False,
                    tail_clear=tail_clear,
                )
                return None
            results[bar_type] = percent
            self._remember_stable_bar_sample(bar_type, percent, region)
            self._set_bar_detection_debug(
                bar_type,
                source="直接取色",
                region=region,
                track_region=region,
                percent=percent,
                success=True,
                reason=reason,
                require_clear_tail=False,
                tail_clear=tail_clear,
            )

        self.bottom_bar_regions = regions
        self.bottom_bar_track_regions = track_regions
        self.bottom_bar_client_bounds = client_bounds
        self.bottom_bar_regions_at = self._monotonic()
        self._record_direct_bar_success()
        return results.get("hp"), results.get("mp")

    def _union_direct_bar_regions(
        self,
        first: tuple[int, int, int, int] | None,
        second: tuple[int, int, int, int] | None,
    ) -> tuple[int, int, int, int] | None:
        if first is None or second is None:
            return None
        left = min(first[0], second[0])
        top = min(first[1], second[1])
        right = max(first[0] + first[2], second[0] + second[2])
        bottom = max(first[1] + first[3], second[1] + second[3])
        width = right - left
        height = bottom - top
        if width <= 0 or height <= 0:
            return None
        return left, top, width, height

    def _crop_direct_bar_image(
        self,
        image: np.ndarray,
        source_region: tuple[int, int, int, int],
        target_region: tuple[int, int, int, int],
    ) -> np.ndarray | None:
        source_left, source_top, source_width, source_height = source_region
        target_left, target_top, target_width, target_height = target_region
        x = target_left - source_left
        y = target_top - source_top
        if x < 0 or y < 0 or target_width <= 0 or target_height <= 0:
            return None
        if x + target_width > source_width or y + target_height > source_height:
            return None
        return image[y : y + target_height, x : x + target_width]

    def _capture_bar_percent_direct(
        self,
        bar_type: str,
        *,
        require_clear_tail: bool = False,
        cached_regions=None,
        sample_direct=None,
    ) -> float | None:
        cached = (cached_regions or self._cached_bottom_bar_screen_regions_for_current_client)()
        if cached is None:
            self._note_direct_bar_failure_reason("沒有 cached HUD geometry")
            return None
        regions, track_regions, client_bounds = cached
        if not self._bar_region_pair_geometry_is_valid(regions, track_regions, client_bounds):
            self._note_direct_bar_failure_reason("HUD geometry 不可信")
            return None
        region = track_regions.get(bar_type) or regions.get(bar_type)
        if region is None:
            self._note_direct_bar_failure_reason(f"{bar_type.upper()} direct 取色範圍缺失")
            return None

        percent, reason, tail_clear = (sample_direct or self._sample_direct_bar_percent_from_region)(
            region,
            bar_type,
            require_clear_tail=require_clear_tail,
        )
        if percent is None:
            self._note_direct_bar_failure_reason(f"{bar_type.upper()}: {reason}")
            self._set_bar_detection_debug(
                bar_type,
                source="直接取色",
                region=region,
                track_region=region,
                percent=None,
                success=False,
                reason=reason,
                require_clear_tail=require_clear_tail,
                tail_clear=tail_clear,
            )
            return None
        self.bottom_bar_regions = regions
        self.bottom_bar_track_regions = track_regions
        self.bottom_bar_client_bounds = client_bounds
        self.bottom_bar_regions_at = self._monotonic()
        self._remember_stable_bar_sample(bar_type, percent, region)
        self._set_bar_detection_debug(
            bar_type,
            source="直接取色",
            region=region,
            track_region=region,
            percent=percent,
            success=True,
            reason=reason,
            require_clear_tail=require_clear_tail,
            tail_clear=tail_clear,
        )
        self._record_direct_bar_success()
        return percent

    def _capture_bar_percent_from_region(
        self,
        region: tuple[int, int, int, int],
        bar_type: str,
        require_clear_tail: bool = False,
        source: str = "指定區域",
        *,
        track_region: tuple[int, int, int, int] | None = None,
        snapshot_reader=None,
    ) -> float | None:
        percent, reason, tail_clear = (snapshot_reader or self._bar_percent_from_region_snapshot)(
            region,
            bar_type,
            require_clear_tail=require_clear_tail,
            track_region=track_region,
        )
        if percent is not None:
            self._remember_stable_bar_sample(bar_type, percent, region)
        elif not require_clear_tail:
            stable_percent = self._recent_stable_bar_percent(bar_type, region)
            if stable_percent is not None:
                percent = stable_percent
                reason = "短暫失敗，沿用最近穩定取樣"
        self._set_bar_detection_debug(
            bar_type,
            source=source,
            region=region,
            track_region=track_region,
            percent=percent,
            success=percent is not None,
            reason=reason,
            require_clear_tail=require_clear_tail,
            tail_clear=tail_clear,
        )
        return percent

    def _bar_percent_from_region_snapshot(
        self,
        region: tuple[int, int, int, int],
        bar_type: str,
        *,
        require_clear_tail: bool = False,
        track_region: tuple[int, int, int, int] | None = None,
        screen_capture=None,
        bar_color_mask=None,
        percent_reader=None,
    ) -> tuple[float | None, str, bool | None]:
        left, top, width, height = region
        capture = screen_capture or self.screen_capture
        image = capture.grab(
            {"left": left, "top": top, "width": width, "height": height}
        )
        mask = (bar_color_mask or self._bar_color_mask)(image, bar_type)
        percent_mask, percent_image = self._bar_percent_inputs(region, mask, image, track_region)
        percent, reason, tail_clear = (percent_reader or self._percent_from_bar_mask_result)(
            percent_mask,
            percent_image,
            require_clear_tail,
        )
        if (
            percent is None
            and track_region is not None
            and reason == "找不到符合顏色的填滿欄位"
            and self._bar_track_looks_empty(percent_mask, percent_image)
        ):
            return 0.0, "OK:EmptyTrack", True if require_clear_tail and percent_image is not None else tail_clear
        return percent, reason, tail_clear

    def _sample_direct_bar_percent_from_region(
        self,
        region: tuple[int, int, int, int],
        bar_type: str,
        *,
        require_clear_tail: bool = False,
        image_provider=None,
    ) -> tuple[float | None, str, bool | None]:
        image = (image_provider or self._direct_bar_image_from_region)(region)
        if image is None:
            return None, "直接取色讀取畫面失敗", None

        return self._sample_direct_bar_percent_from_image(image, bar_type)

    def _sample_direct_bar_percent_from_image(
        self,
        image: np.ndarray,
        bar_type: str,
    ) -> tuple[float | None, str, bool | None]:
        mask = self._direct_bar_color_mask(image, bar_type)
        percent, reason, tail_clear = self._percent_from_bar_mask_result(
            mask,
            image,
            require_clear_tail=False,
        )
        if percent is None:
            clamped = self._direct_bar_track_like_crop(image, mask, bar_type)
            if clamped is not None:
                clamped_image, crop_reason = clamped
                clamped_mask = self._direct_bar_color_mask(clamped_image, bar_type)
                percent, clamped_reason, tail_clear = self._percent_from_bar_mask_result(
                    clamped_mask,
                    clamped_image,
                    require_clear_tail=False,
                )
                if percent is not None:
                    if clamped_reason == "OK":
                        return percent, f"OK:DirectClamp:{crop_reason}", tail_clear
                    if clamped_reason == "OK:FullWidth":
                        return percent, f"OK:DirectClampFullWidth:{crop_reason}", tail_clear
                else:
                    reason = f"{reason}；clamp={clamped_reason}"
        if (
            percent is None
            and reason == "找不到符合顏色的填滿欄位"
            and self._bar_track_looks_empty(mask, image)
        ):
            return 0.0, "OK:EmptyTrack", None
        if percent is None:
            return None, f"直接取色{reason}", tail_clear
        if reason == "OK":
            reason = "OK:Direct"
        elif reason == "OK:FullWidth":
            reason = "OK:DirectFullWidth"
        return percent, reason, tail_clear

    def _direct_bar_track_like_crop(
        self,
        image: np.ndarray,
        color_mask: np.ndarray,
        bar_type: str,
    ) -> tuple[np.ndarray, str] | None:
        if image.size == 0 or color_mask.size == 0 or not bool(color_mask.any()):
            return None

        height, width = color_mask.shape
        if height <= 2 or width <= 8:
            return None

        track_like = self._bar_track_like_mask(image, color_mask, bar_type)
        if track_like.shape != color_mask.shape:
            return None

        row_like = track_like.mean(axis=1) >= 0.28
        row_like = self._close_column_gaps(row_like, max(1, round(height * 0.12)))
        row_edges = np.flatnonzero(np.diff(np.concatenate(([False], row_like, [False]))))
        if row_edges.size < 2:
            return None

        min_rows = min(max(3, BAR_MIN_BODY_ROW_COUNT), height)
        row_runs: list[tuple[int, int, float]] = []
        for start, end in zip(row_edges[::2], row_edges[1::2]):
            if end - start < min_rows:
                continue
            density = float(track_like[start:end, :].mean())
            row_runs.append((int(start), int(end), density))
        if not row_runs:
            return None
        row_start, row_end, _density = max(row_runs, key=lambda item: (item[1] - item[0], item[2]))

        band_like = track_like[row_start:row_end, :]
        band_color = color_mask[row_start:row_end, :]
        column_like = band_like.mean(axis=0) >= 0.30
        column_like = self._close_column_gaps(column_like, max(2, round(width * 0.015)))
        column_edges = np.flatnonzero(np.diff(np.concatenate(([False], column_like, [False]))))
        if column_edges.size < 2:
            return None

        min_width = min(width, max(24, round(width * 0.45)))
        candidates: list[tuple[int, int, float]] = []
        for start, end in zip(column_edges[::2], column_edges[1::2]):
            run_width = int(end - start)
            if run_width < min_width:
                continue
            color_coverage = float(band_color[:, start:end].mean())
            if color_coverage <= 0.0:
                continue
            trim_score = (start / max(1, width)) + ((width - end) / max(1, width))
            score = run_width + color_coverage * 100.0 + trim_score * 20.0
            candidates.append((int(start), int(end), score))
        if not candidates:
            return None

        col_start, col_end, _score = max(candidates, key=lambda item: item[2])
        if col_start == 0 and col_end == width and row_start == 0 and row_end == height:
            return None

        cropped = image[row_start:row_end, col_start:col_end]
        if cropped.size == 0:
            return None
        return cropped, f"x={col_start}-{col_end},y={row_start}-{row_end}"


__all__ = ["HudBarDetectionAlgorithms"]
