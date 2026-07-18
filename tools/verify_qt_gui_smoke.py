from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def verify_source(*, offscreen: bool) -> None:
    if offscreen:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from maple_star.models.settings import AutoPotionSettings
    from maple_star.views_qt.settings_gui import AutoPotionSettingsGui

    gui = AutoPotionSettingsGui(AutoPotionSettings())
    gui.show()
    gui.application.processEvents()
    for width, height in ((860, 560), (1080, 720), (1440, 900)):
        gui.resize(width, height)
        for page in gui.page_names:
            gui.show_page(page)
            gui.application.processEvents()
    gui.show_toggle_notice("Qt GUI smoke")
    gui.application.processEvents()
    gui.close()
    gui.application.processEvents()
    if not gui.closed:
        raise RuntimeError("Qt window did not close")


def verify_executable(executable: Path) -> None:
    marker = Path(tempfile.gettempdir()) / f"maple-star-qt-smoke-{os.getpid()}-{time.time_ns()}.txt"
    env = os.environ.copy()
    env["MAPLE_STAR_STARTUP_BENCHMARK_OUTPUT"] = str(marker)
    process = subprocess.Popen([str(executable)], cwd=executable.parent, env=env)
    try:
        process.wait(timeout=30.0)
        if process.returncode != 0 or not marker.is_file():
            raise RuntimeError(f"artifact GUI smoke failed: exitcode={process.returncode}")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5.0)
        marker.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="verify Qt source or packaged GUI lifecycle")
    parser.add_argument("--offscreen", action="store_true")
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--scale", type=float)
    parser.add_argument("--all-scales", action="store_true")
    args = parser.parse_args()
    if args.all_scales:
        for scale in (1.0, 1.25, 1.5, 1.75):
            subprocess.run(
                [sys.executable, __file__, "--offscreen", "--scale", str(scale)],
                cwd=ROOT,
                check=True,
            )
        print("qt-gui-smoke: all simulated scales passed", flush=True)
        return
    if args.scale is not None:
        os.environ["QT_SCALE_FACTOR"] = str(max(0.5, args.scale))
    if args.executable is None:
        verify_source(offscreen=args.offscreen)
    else:
        executable = args.executable.resolve()
        if not executable.is_file():
            raise SystemExit(f"找不到 EXE：{executable}")
        verify_executable(executable)
    print("qt-gui-smoke: passed", flush=True)


if __name__ == "__main__":
    main()
