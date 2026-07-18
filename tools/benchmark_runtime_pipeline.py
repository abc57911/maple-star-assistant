from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark_control_timing import run_benchmark as run_control_benchmark
from benchmark_preview_transport import run_benchmark as run_preview_benchmark
from maple_star.services.benchmark_environment import collect_benchmark_environment


def main() -> None:
    parser = argparse.ArgumentParser(description="exercise the production control and preview IPC pipeline")
    parser.add_argument("--duration", type=float, default=600.0)
    parser.add_argument("--interval", type=float, default=0.01)
    parser.add_argument("--p95-limit-ms", type=float, default=10.0)
    parser.add_argument("--p99-limit-ms", type=float, default=5.0)
    parser.add_argument("--max-limit-ms", type=float, default=25.0)
    parser.add_argument("--status-gap-limit-ms", type=float, default=1250.0)
    args = parser.parse_args()

    control = run_control_benchmark(max(0.1, args.duration), max(0.001, args.interval))
    preview = run_preview_benchmark(width=700, height=128, iterations=200)
    passed = bool(
        control["p95_lateness_ms"] <= args.p95_limit_ms
        and control["p99_lateness_ms"] <= args.p99_limit_ms
        and control["max_lateness_ms"] <= args.max_limit_ms
        and control["max_status_gap_ms"] <= args.status_gap_limit_ms
        and not preview["shared_memory_required_by_latency"]
    )
    result = {
        "marker": "runtime-pipeline",
        "control": control,
        "preview": {key: value for key, value in preview.items() if key != "samples_ms"},
        "limits": {
            "p95_lateness_ms": args.p95_limit_ms,
            "p99_lateness_ms": args.p99_limit_ms,
            "max_lateness_ms": args.max_limit_ms,
            "max_status_gap_ms": args.status_gap_limit_ms,
        },
        "passed": passed,
        "environment": collect_benchmark_environment(mode="python-spawn", cache_condition="warm", root=ROOT),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
