from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InputImportBoundaryTests(unittest.TestCase):
    def test_only_guardian_adapter_references_native_keyboard_mutation(self) -> None:
        consumers: list[str] = []
        for path in (ROOT / "maple_star").rglob("*.py"):
            if path.name == "win_input.py":
                continue
            source = path.read_text(encoding="utf-8")
            if any(
                name in source
                for name in (
                    "_native_key_down",
                    "_native_key_up",
                    "_native_tap_key",
                    "_native_set_cursor_position",
                    "_native_left_click",
                    "_native_release_mouse_buttons",
                )
            ):
                consumers.append(path.relative_to(ROOT).as_posix())

        self.assertEqual(consumers, ["maple_star/adapters/guardian_win_input.py"])

    def test_guardian_import_does_not_load_gui_paddle_or_pygame(self) -> None:
        code = (
            "import sys; import maple_star.workers.input_guardian_process; "
            "print([name for name in ('PySide6','tkinter','customtkinter','paddle','pygame') if name in sys.modules])"
        )
        result = subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), "[]")


if __name__ == "__main__":
    unittest.main()
