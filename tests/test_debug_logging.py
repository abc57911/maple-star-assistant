import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from maple_star.debug_logging import close_debug_logging, configure_debug_logging, log_exception, write_debug_text
from maple_star.gui import GuiConsoleWriter


class DebugLoggingTests(unittest.TestCase):
    def test_log_exception_writes_traceback_to_debug_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_log = Path(temp_dir) / "debug.log"
            configure_debug_logging(debug_log)

            try:
                try:
                    raise RuntimeError("sample failure")
                except RuntimeError:
                    log_exception("測試例外")

            finally:
                close_debug_logging()
            text = debug_log.read_text(encoding="utf-8")
            self.assertIn("測試例外", text)
            self.assertIn("RuntimeError", text)
            self.assertIn("sample failure", text)

    def test_configure_debug_logging_reset_clears_previous_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_log = Path(temp_dir) / "debug.log"
            debug_log.write_text("old log\n", encoding="utf-8")

            try:
                configure_debug_logging(debug_log, reset=True)
                write_debug_text("new log\n")
            finally:
                close_debug_logging()

            text = debug_log.read_text(encoding="utf-8")
            self.assertNotIn("old log", text)
            self.assertIn("new log", text)

    def test_gui_console_writer_mirrors_console_text_to_debug_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_log = Path(temp_dir) / "debug.log"
            gui = Mock()
            writer = GuiConsoleWriter(gui, original=None)

            try:
                configure_debug_logging(debug_log, reset=True)
                writer.write("經驗效率 OCR 錯誤：sample\n")
            finally:
                close_debug_logging()

            gui.append_console.assert_called_once_with("經驗效率 OCR 錯誤：sample\n")
            text = debug_log.read_text(encoding="utf-8")
            self.assertIn("經驗效率 OCR 錯誤：sample", text)


if __name__ == "__main__":
    unittest.main()
