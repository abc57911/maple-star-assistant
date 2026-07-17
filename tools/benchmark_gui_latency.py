from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maple_star.models.settings import AutoPotionSettings
from maple_star.views.settings_gui import AutoPotionSettingsGui


PAGES = ("監控", "自動喝水", "小地圖巡航", "手把組合", "Console")


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))]


def run_benchmark(rounds: int) -> dict[str, object]:
    gui = AutoPotionSettingsGui(AutoPotionSettings())
    gui.root.withdraw()
    gui.root.update()
    samples: list[float] = []
    usable_samples: list[float] = []
    try:
        for _ in range(max(1, rounds)):
            for page in PAGES:
                started_at = time.perf_counter()
                gui.show_page(page)
                samples.append((time.perf_counter() - started_at) * 1000.0)
                # Allow deferred first-build work to complete before measuring
                # the next visible response.
                time.sleep(0.005)
                gui.root.update()
                usable_samples.append((time.perf_counter() - started_at) * 1000.0)
    finally:
        gui.root.destroy()
    return {
        "sample_count": len(samples),
        "p95_latency_ms": percentile(samples, 0.95),
        "max_latency_ms": max(samples),
        "samples_ms": samples,
        "usable_p95_latency_ms": percentile(usable_samples, 0.95),
        "usable_max_latency_ms": max(usable_samples),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="measure GUI page visible-response latency")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--p95-limit-ms", type=float, default=150.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_benchmark(args.rounds)
    result["p95_limit_ms"] = args.p95_limit_ms
    result["passed"] = float(result["p95_latency_ms"]) <= args.p95_limit_ms
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered, flush=True)
    if args.output is not None:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
