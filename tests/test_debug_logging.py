import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from maple_star.debug_logging import (
    close_debug_logging,
    close_experience_debug_logging,
    configure_debug_logging,
    configure_experience_debug_logging,
    log_exception,
    log_experience_debug,
    write_debug_text,
)
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
            (debug_log.parent / "debug.log.1").write_text("old backup\n", encoding="utf-8")
            (debug_log.parent / "debug.log.2").write_text("old backup\n", encoding="utf-8")

            try:
                configure_debug_logging(debug_log, reset=True)
                write_debug_text("new log\n")
            finally:
                close_debug_logging()

            text = debug_log.read_text(encoding="utf-8")
            self.assertNotIn("old log", text)
            self.assertIn("new log", text)
            self.assertFalse((debug_log.parent / "debug.log.1").exists())
            self.assertFalse((debug_log.parent / "debug.log.2").exists())

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

    def test_debug_log_rotates_instead_of_growing_without_bound(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_log = Path(temp_dir) / "debug.log"

            try:
                configure_debug_logging(debug_log, reset=True, max_bytes=220, backup_count=2)
                for index in range(20):
                    write_debug_text(f"debug line {index:02d} abcdefghijklmnopqrstuvwxyz\n")
            finally:
                close_debug_logging()

            log_files = sorted(debug_log.parent.glob("debug.log*"))
            self.assertLessEqual(len(log_files), 3)
            self.assertTrue((debug_log.parent / "debug.log.1").exists())
            self.assertTrue(debug_log.exists())

    def test_log_experience_debug_writes_jsonl_to_experience_debug_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_log = Path(temp_dir) / "experience_debug.log"

            try:
                configure_experience_debug_logging(debug_log, reset=True)
                log_experience_debug({"event": "experience_ocr_job", "current_exp": 123456, "percent": 78.9})
            finally:
                close_experience_debug_logging()

            text = debug_log.read_text(encoding="utf-8")
            self.assertIn('"event":"experience_ocr_job"', text)
            self.assertIn('"logged_at":', text)
            self.assertIn('"current_exp":123456', text)
            self.assertIn('"percent":78.9', text)

    def test_configure_experience_debug_logging_reset_clears_previous_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_log = Path(temp_dir) / "experience_debug.log"
            debug_log.write_text("old log\n", encoding="utf-8")
            (debug_log.parent / "experience_debug.log.1").write_text("old backup\n", encoding="utf-8")
            (debug_log.parent / "experience_debug.log.2").write_text("old backup\n", encoding="utf-8")

            try:
                configure_experience_debug_logging(debug_log, reset=True)
                log_experience_debug({"event": "new"})
            finally:
                close_experience_debug_logging()

            text = debug_log.read_text(encoding="utf-8")
            self.assertNotIn("old log", text)
            self.assertIn('"event":"new"', text)
            self.assertFalse((debug_log.parent / "experience_debug.log.1").exists())
            self.assertFalse((debug_log.parent / "experience_debug.log.2").exists())

    def test_experience_debug_log_rotates_instead_of_growing_without_bound(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_log = Path(temp_dir) / "experience_debug.log"

            try:
                configure_experience_debug_logging(debug_log, reset=True, max_bytes=180, backup_count=2)
                for index in range(20):
                    log_experience_debug(
                        {
                            "event": "experience_ocr_job",
                            "index": index,
                            "text": "abcdefghijklmnopqrstuvwxyz",
                        }
                    )
            finally:
                close_experience_debug_logging()

            log_files = sorted(debug_log.parent.glob("experience_debug.log*"))
            self.assertLessEqual(len(log_files), 3)
            self.assertTrue((debug_log.parent / "experience_debug.log.1").exists())
            self.assertTrue(debug_log.exists())


if __name__ == "__main__":
    unittest.main()
