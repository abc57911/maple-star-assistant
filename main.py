from __future__ import annotations

import ctypes
import os
import sys

try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame
import pygame._sdl2.controller as controller

from maple_gamepad_macro import main as run_all_features


def main() -> int:
    try:
        run_all_features()
    except KeyboardInterrupt:
        print("\n已停止。")
        return 0
    finally:
        controller.quit()
        pygame.quit()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
