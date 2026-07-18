from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import queue
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maple_star.services.benchmark_environment import collect_benchmark_environment


def run_benchmark(
    duration_seconds: float,
    interval_seconds: float,
    *,
    exercise_transitions: bool = False,
    transition_scale: float = 1.0,
) -> dict[str, float | int]:
    """Measure the spawned production control loop without sending game input."""
    from maple_star.controllers.gamepad_controller import run_control_runtime_process
    from maple_star.adapters.controller_worker import (
        EVENT_BUTTON_DOWN,
        SDL_CONTROLLER_BUTTON_LEFTSHOULDER,
        SDL_CONTROLLER_BUTTON_RIGHTSHOULDER,
    )
    from maple_star.models.settings import AutoPotionSettings
    from maple_star.services.runtime_processes import (
        ControlCommand,
        ControlStatus,
        SettingsUpdated,
        Shutdown,
        WorkerCrashed,
    )

    context = mp.get_context("spawn")
    commands = context.Queue(maxsize=256)
    statuses = context.Queue(maxsize=256)
    controller_events = context.Queue(maxsize=256)
    release_event = context.Event()
    settings = AutoPotionSettings()
    settings.normalize_combo_slots()
    settings.combo_slots["A"]["enabled"] = True
    settings.combo_slots["B"]["enabled"] = True
    settings.minimap_cruise_left_x = 100
    settings.minimap_cruise_right_x = 200
    settings.minimap_cruise_detect_y = 80
    settings.minimap_cruise_periodic_key_1_enabled = True
    settings.minimap_cruise_periodic_key_1 = "Z"
    settings.minimap_cruise_periodic_key_1_interval_seconds = 0.5
    process = context.Process(
        target=run_control_runtime_process,
        args=(
            commands,
            statuses,
            settings.to_json_dict(),
            0,
            release_event,
            controller_events,
            True,
        ),
        name="MapleStarControlTimingBenchmark",
    )
    process.start()
    try:
        import psutil

        measured_process = psutil.Process(process.pid)
        rss_start_bytes = measured_process.memory_info().rss
    except Exception:
        measured_process = None
        rss_start_bytes = 0
    rss_peak_bytes = rss_start_bytes
    rss_end_bytes = rss_start_bytes
    commands.put(
        ControlCommand(
            scripts_enabled=True,
            gameplay_hud_active=True,
            cruise_enabled=True,
            generation=1,
            benchmark_deadline_interval_seconds=interval_seconds,
        )
    )
    controller_events.put((EVENT_BUTTON_DOWN, SDL_CONTROLLER_BUTTON_RIGHTSHOULDER, None))
    controller_events.put((EVENT_BUTTON_DOWN, SDL_CONTROLLER_BUTTON_LEFTSHOULDER, None))

    started_at = time.perf_counter()
    finished_at = started_at + duration_seconds
    expected_generation = 1
    focus_transition_count = 0
    settings_transition_count = 0
    transition_scale = max(0.001, float(transition_scale))
    next_focus_transition_at = started_at + 600.0 * transition_scale
    focus_resume_at = float("inf")
    next_settings_transition_at = started_at + 900.0 * transition_scale
    observer_delay_at = started_at + 1800.0 * transition_scale
    observer_delay_until = float("-inf")
    observer_delay_count = 0
    latest: ControlStatus | None = None
    worst_p95_lateness_ms = 0.0
    worst_p99_lateness_ms = 0.0
    worst_max_lateness_ms = 0.0
    heartbeat_gaps: list[float] = []
    last_heartbeat_at: float | None = None
    try:
        while time.perf_counter() < finished_at:
            now_perf = time.perf_counter()
            if exercise_transitions and now_perf >= next_focus_transition_at:
                expected_generation += 1
                focus_transition_count += 1
                commands.put(ControlCommand(True, False, False, generation=expected_generation))
                focus_resume_at = now_perf + min(1.0, 100.0 * transition_scale)
                next_focus_transition_at += 600.0 * transition_scale
            if exercise_transitions and now_perf >= focus_resume_at:
                expected_generation += 1
                commands.put(ControlCommand(True, True, True, generation=expected_generation))
                focus_resume_at = float("inf")
            if exercise_transitions and now_perf >= next_settings_transition_at:
                settings_transition_count += 1
                settings.minimap_cruise_periodic_key_1_interval_seconds = 0.5 + (
                    settings_transition_count % 2
                ) * 0.1
                commands.put(SettingsUpdated(settings.to_json_dict()))
                next_settings_transition_at += 900.0 * transition_scale
            if exercise_transitions and observer_delay_count == 0 and now_perf >= observer_delay_at:
                observer_delay_count = 1
                observer_delay_until = now_perf + min(3.0, 300.0 * transition_scale)
            if now_perf < observer_delay_until:
                time.sleep(0.01)
                continue
            if measured_process is not None:
                try:
                    rss_end_bytes = measured_process.memory_info().rss
                    rss_peak_bytes = max(rss_peak_bytes, rss_end_bytes)
                except Exception:
                    measured_process = None
            timeout = min(0.25, max(0.01, finished_at - time.perf_counter()))
            try:
                item = statuses.get(timeout=timeout)
            except queue.Empty:
                if not process.is_alive():
                    raise RuntimeError(f"control runtime exited early: exitcode={process.exitcode}")
                continue
            if isinstance(item, WorkerCrashed):
                raise RuntimeError(f"control runtime failed: {item.message}")
            if isinstance(item, ControlStatus) and item.generation == expected_generation:
                if last_heartbeat_at is not None:
                    heartbeat_gaps.append(max(0.0, item.heartbeat_at - last_heartbeat_at))
                last_heartbeat_at = item.heartbeat_at
                latest = item
                worst_p95_lateness_ms = max(worst_p95_lateness_ms, item.timing_p95_lateness_ms)
                worst_p99_lateness_ms = max(worst_p99_lateness_ms, item.timing_p99_lateness_ms)
                worst_max_lateness_ms = max(worst_max_lateness_ms, item.timing_max_lateness_ms)
    finally:
        release_event.set()
        try:
            commands.put(Shutdown(), timeout=0.25)
        except queue.Full:
            pass
        process.join(timeout=5.0)
        if process.is_alive():
            process.terminate()
            process.join(timeout=2.0)

    if process.exitcode != 0:
        raise RuntimeError(f"control timing benchmark failed: exitcode={process.exitcode}")
    if latest is None:
        raise RuntimeError("control timing benchmark produced no status")
    return {
        "duration_seconds": time.perf_counter() - started_at,
        "interval_seconds": interval_seconds,
        "sample_count": latest.timing_sample_count,
        "p95_lateness_ms": worst_p95_lateness_ms,
        "p99_lateness_ms": worst_p99_lateness_ms,
        "max_lateness_ms": worst_max_lateness_ms,
        "max_status_gap_ms": max(heartbeat_gaps, default=0.0) * 1000.0,
        "rss_start_bytes": rss_start_bytes,
        "rss_peak_bytes": rss_peak_bytes,
        "rss_end_bytes": rss_end_bytes,
        "rss_growth_bytes": max(0, rss_end_bytes - rss_start_bytes),
        "focus_transition_count": focus_transition_count,
        "settings_transition_count": settings_transition_count,
        "observer_delay_count": observer_delay_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="maple-star production control runtime timing benchmark")
    parser.add_argument("--duration", type=float, default=10.0, help="benchmark duration in seconds")
    parser.add_argument("--interval", type=float, default=0.01, help="benchmark deadline interval in seconds")
    parser.add_argument("--p95-limit-ms", type=float, default=10.0)
    parser.add_argument("--p99-limit-ms", type=float, default=5.0)
    parser.add_argument("--max-limit-ms", type=float, default=25.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = run_benchmark(max(0.1, args.duration), max(0.001, args.interval))
    result["marker"] = "scheduler_deadline"
    result["environment"] = collect_benchmark_environment(
        mode="python-spawn",
        cache_condition="warm",
        root=ROOT,
    )
    result["p95_limit_ms"] = args.p95_limit_ms
    result["p99_limit_ms"] = args.p99_limit_ms
    result["max_limit_ms"] = args.max_limit_ms
    result["passed"] = bool(
        float(result["p95_lateness_ms"]) <= args.p95_limit_ms
        and float(result["p99_lateness_ms"]) <= args.p99_limit_ms
        and float(result["max_lateness_ms"]) <= args.max_limit_ms
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered, flush=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
