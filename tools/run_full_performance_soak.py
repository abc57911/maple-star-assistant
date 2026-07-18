from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark_control_timing import run_benchmark
from maple_star.services.benchmark_environment import collect_benchmark_environment


def main() -> None:
    parser = argparse.ArgumentParser(description="long-running production control scheduler soak")
    parser.add_argument("--duration", type=float, default=3600.0)
    parser.add_argument("--p95-limit-ms", type=float, default=10.0)
    parser.add_argument("--p99-limit-ms", type=float, default=5.0)
    parser.add_argument("--max-limit-ms", type=float, default=25.0)
    parser.add_argument("--rss-growth-limit-mib", type=float, default=64.0)
    args = parser.parse_args()
    timing = run_benchmark(max(1.0, args.duration), 0.01, exercise_transitions=True)
    passed = bool(
        timing["p95_lateness_ms"] <= args.p95_limit_ms
        and timing["p99_lateness_ms"] <= args.p99_limit_ms
        and timing["max_lateness_ms"] <= args.max_limit_ms
        and timing["rss_growth_bytes"] <= args.rss_growth_limit_mib * 1024 * 1024
    )
    result = {
        "marker": "control-runtime-soak",
        "timing": timing,
        "passed": passed,
        "environment": collect_benchmark_environment(mode="python-spawn", cache_condition="warm", root=ROOT),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
