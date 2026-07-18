from __future__ import annotations

import argparse
import json
import math
import pickle
import statistics
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maple_star.ipc.preview_transport import PreviewFrame, SerializedPreviewTransport
from maple_star.services.benchmark_environment import collect_benchmark_environment


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))]


def run_benchmark(*, width: int, height: int, iterations: int) -> dict[str, object]:
    transport = SerializedPreviewTransport(max_producers=1)
    payload = bytes(width * height * 4)
    samples_ms: list[float] = []
    for frame_id in range(1, iterations + 1):
        started = time.perf_counter()
        frame = PreviewFrame("potion", frame_id, width, height, 4, "BGRA", payload, started)
        serialized = pickle.dumps(frame, protocol=pickle.HIGHEST_PROTOCOL)
        transport.publish(pickle.loads(serialized))
        consumed = transport.drain_latest()[0]
        pickle.loads(pickle.dumps(consumed, protocol=pickle.HIGHEST_PROTOCOL))
        samples_ms.append((time.perf_counter() - started) * 1000.0)
    p95 = _percentile(samples_ms, 0.95)
    return {
        "transport": "serialized-bytes",
        "width": width,
        "height": height,
        "payload_bytes": len(payload),
        "sample_count": len(samples_ms),
        "median_ms": statistics.median(samples_ms),
        "p95_ms": p95,
        "max_ms": max(samples_ms),
        "shared_memory_required_by_latency": p95 > 2.0,
        "environment": collect_benchmark_environment(
            mode="python-serialized-preview",
            cache_condition="warm",
            root=ROOT,
        ),
        "samples_ms": samples_ms,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="benchmark serialized preview transport")
    parser.add_argument("--width", type=int, default=700)
    parser.add_argument("--height", type=int, default=128)
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_benchmark(
        width=max(1, args.width),
        height=max(1, args.height),
        iterations=max(1, args.iterations),
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered, flush=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
