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


def run_benchmark(duration_seconds: float, interval_seconds: float) -> dict[str, float | int]:
    """Measure the spawned production control loop without sending game input."""
    from maple_star.controllers.gamepad_controller import run_control_runtime_process
    from maple_star.adapters.controller_worker import (
        EVENT_BUTTON_DOWN,
        SDL_CONTROLLER_BUTTON_LEFTSHOULDER,
        SDL_CONTROLLER_BUTTON_RIGHTSHOULDER,
    )
    from maple_star.models.settings import AutoPotionSettings
    from maple_star.services.runtime_processes import ControlCommand, ControlStatus, Shutdown, WorkerCrashed

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
    latest: ControlStatus | None = None
    heartbeat_gaps: list[float] = []
    last_heartbeat_at: float | None = None
    try:
        while time.perf_counter() < finished_at:
            timeout = min(0.25, max(0.01, finished_at - time.perf_counter()))
            try:
                item = statuses.get(timeout=timeout)
            except queue.Empty:
                if not process.is_alive():
                    raise RuntimeError(f"control runtime exited early: exitcode={process.exitcode}")
                continue
            if isinstance(item, WorkerCrashed):
                raise RuntimeError(f"control runtime failed: {item.message}")
            if isinstance(item, ControlStatus) and item.generation == 1:
                if last_heartbeat_at is not None:
                    heartbeat_gaps.append(max(0.0, item.heartbeat_at - last_heartbeat_at))
                last_heartbeat_at = item.heartbeat_at
                latest = item
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
        "p95_lateness_ms": latest.timing_p95_lateness_ms,
        "max_lateness_ms": latest.timing_max_lateness_ms,
        "max_status_gap_ms": max(heartbeat_gaps, default=0.0) * 1000.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="maple-star production control runtime timing benchmark")
    parser.add_argument("--duration", type=float, default=10.0, help="benchmark duration in seconds")
    parser.add_argument("--interval", type=float, default=0.01, help="benchmark deadline interval in seconds")
    parser.add_argument("--p95-limit-ms", type=float, default=10.0)
    parser.add_argument("--max-limit-ms", type=float, default=25.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = run_benchmark(max(0.1, args.duration), max(0.001, args.interval))
    result["p95_limit_ms"] = args.p95_limit_ms
    result["max_limit_ms"] = args.max_limit_ms
    result["passed"] = bool(
        float(result["p95_lateness_ms"]) <= args.p95_limit_ms
        and float(result["max_lateness_ms"]) <= args.max_limit_ms
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered, flush=True)
    if args.output is not None:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
