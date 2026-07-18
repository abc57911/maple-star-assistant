from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maple_star.services.benchmark_environment import collect_benchmark_environment


def _measure_python_once() -> tuple[float, float]:
    command = (
        "from maple_star.models.settings import AutoPotionSettings;"
        "from maple_star.views_qt.settings_gui import AutoPotionSettingsGui;"
        "import time;"
        "s=time.perf_counter();"
        "g=AutoPotionSettingsGui(AutoPotionSettings());"
        "g.show();g.application.processEvents();"
        "print(time.perf_counter()-s);"
        "g.close()"
    )
    started = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - started
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    gui_elapsed = float(lines[-1])
    return max(gui_elapsed, elapsed), gui_elapsed


def _measure_executable_once(executable: Path, timeout_seconds: float = 30.0) -> float:
    marker_path = Path(tempfile.gettempdir()) / f"maple-star-startup-{os.getpid()}-{time.time_ns()}.txt"
    env = os.environ.copy()
    env["MAPLE_STAR_STARTUP_BENCHMARK_OUTPUT"] = str(marker_path)
    started = time.perf_counter()
    process = subprocess.Popen([str(executable)], cwd=executable.parent, env=env)
    try:
        deadline = started + timeout_seconds
        while time.perf_counter() < deadline:
            if marker_path.exists():
                return time.perf_counter() - started
            if process.poll() is not None:
                raise RuntimeError(f"EXE exited before startup marker: exitcode={process.returncode}")
            time.sleep(0.005)
        raise RuntimeError("EXE startup benchmark timeout; close any running maple-star instance")
    finally:
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=2.0)
        marker_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="measure maple-star GUI cold startup")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--baseline-seconds", type=float)
    parser.add_argument("--executable", type=Path, help="measure a packaged EXE using the safe ready-marker mode")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.executable is not None:
        executable = args.executable.resolve()
        if not executable.is_file():
            raise SystemExit(f"找不到 EXE：{executable}")
        measure = lambda: (_measure_executable_once(executable), None)
        mode = "exe"
    else:
        measure = _measure_python_once
        mode = "python"
    measurements = [measure() for _ in range(max(1, args.runs))]
    samples = [measurement[0] for measurement in measurements]
    visible_samples = [measurement[1] for measurement in measurements if measurement[1] is not None]
    median = sorted(samples)[len(samples) // 2]
    result: dict[str, object] = {
        "mode": mode,
        "marker": "main_ready",
        "samples_seconds": samples,
        "median_seconds": median,
        "environment": collect_benchmark_environment(
            mode=mode,
            cache_condition="cold-process/warm-os-cache",
            root=ROOT,
        ),
    }
    if visible_samples:
        visible_median = sorted(visible_samples)[len(visible_samples) // 2]
        result["first_visible_shell_samples_seconds"] = visible_samples
        result["first_visible_shell_median_seconds"] = visible_median
        result["first_visible_shell_passed"] = visible_median <= 0.2
    if args.baseline_seconds is not None:
        improvement = (args.baseline_seconds - median) / args.baseline_seconds * 100.0
        result["baseline_seconds"] = args.baseline_seconds
        result["improvement_percent"] = improvement
        result["passed"] = improvement >= 30.0
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered, flush=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if result.get("passed") is False or result.get("first_visible_shell_passed") is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
