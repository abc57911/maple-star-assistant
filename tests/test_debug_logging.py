import tempfile
import unittest
from pathlib import Path

from maple_star.debug_logging import close_debug_logging, configure_debug_logging, log_exception


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


if __name__ == "__main__":
    unittest.main()
