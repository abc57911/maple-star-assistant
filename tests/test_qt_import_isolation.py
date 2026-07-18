from __future__ import annotations

import subprocess
import sys
import unittest


class QtImportIsolationTests(unittest.TestCase):
    def test_qt_shell_does_not_import_customtkinter_or_paddle(self) -> None:
        code = (
            "import sys; import maple_star.views_qt.main_window; "
            "print(int('customtkinter' in sys.modules), int('paddle' in sys.modules))"
        )
        result = subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)

        self.assertEqual(result.stdout.strip(), "0 0")


if __name__ == "__main__":
    unittest.main()
