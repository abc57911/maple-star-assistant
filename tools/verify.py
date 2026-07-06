from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINTS = ("main.py", "main.pyw", "maple_gamepad_macro.py", "auto_potion.py")
QUICK_TEST_MODULES = (
    "tests.test_control_hotkey_worker",
    "tests.test_gamepad_macro",
    "tests.test_minimap_cruise",
    "tests.test_settings_profiles",
    "tests.test_win_input",
)


def _run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    shown = " ".join(command)
    started = time.perf_counter()
    print(f"\n$ {shown}", flush=True)
    result = subprocess.run(command, cwd=ROOT, env=env)
    elapsed = time.perf_counter() - started
    print(f"[{elapsed:.1f}s] exit={result.returncode}", flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)


def _python() -> str:
    return sys.executable or "python"


def _with_slow_ocr_enabled() -> dict[str, str]:
    env = os.environ.copy()
    env["MAPLE_STAR_RUN_SLOW_OCR_TESTS"] = "1"
    return env


def run_quick() -> None:
    _run([_python(), "-m", "py_compile", *ENTRYPOINTS])
    _run([_python(), "-m", "compileall", "-q", "maple_star"])
    _run([_python(), "-m", "unittest", *QUICK_TEST_MODULES])
    _run(["git", "diff", "--check"])


def run_full() -> None:
    _run([_python(), "-m", "py_compile", *ENTRYPOINTS])
    _run([_python(), "-m", "compileall", "-q", "maple_star"])
    _run([_python(), "-m", "unittest", "discover", "-s", "tests"], env=_with_slow_ocr_enabled())
    _run(["git", "diff", "--check"])


def run_ocr_slow() -> None:
    paddle_python = ROOT / ".venv-paddleocr" / "Scripts" / "python.exe"
    if not paddle_python.exists():
        raise SystemExit(f"找不到 PaddleOCR venv：{paddle_python}")
    _run([str(paddle_python), "-m", "unittest", "discover", "-s", "tests"], env=_with_slow_ocr_enabled())
    _run([str(paddle_python), "-m", "pip", "check"])


def main() -> None:
    parser = argparse.ArgumentParser(description="maple-star validation profiles")
    parser.add_argument(
        "profile",
        nargs="?",
        choices=("quick", "full", "ocr-slow"),
        default="quick",
        help="quick: daily smoke checks; full: all tests with slow OCR fixtures; ocr-slow: PaddleOCR venv checks",
    )
    args = parser.parse_args()

    if args.profile == "quick":
        run_quick()
    elif args.profile == "full":
        run_full()
    else:
        run_ocr_slow()


if __name__ == "__main__":
    main()
