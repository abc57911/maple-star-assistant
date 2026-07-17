from __future__ import annotations

import ast
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

import numpy as np

from maple_star.services.screen_capture import ScreenCapturePort, ScreenCaptureService


class ScreenCaptureServiceTests(unittest.TestCase):
    def test_module_does_not_import_controller_or_gui(self) -> None:
        path = Path(__file__).resolve().parents[1] / "maple_star" / "services" / "screen_capture.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = "\n".join(
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        )
        self.assertNotIn("controllers", imports)
        self.assertNotIn("gui", imports)

    def test_factory_creates_the_single_owned_backend(self) -> None:
        backend = Mock()
        factory = Mock(return_value=backend)

        service = ScreenCaptureService(factory)

        factory.assert_called_once_with()
        self.assertIs(service.backend, backend)

    def test_controller_lazy_factory_preserves_dynamic_mss_patch_seam(self) -> None:
        from maple_star.controller import AutoPotionController

        backend = Mock()
        controller = AutoPotionController.__new__(AutoPotionController)
        with patch("maple_star.controller.mss.mss", return_value=backend) as factory:
            service = controller._screen_capture_service()

        factory.assert_called_once_with()
        self.assertIs(service.backend, backend)

    def test_grab_returns_an_independent_array(self) -> None:
        source = np.zeros((2, 3, 4), dtype=np.uint8)
        backend = Mock()
        backend.grab.return_value = source
        service = ScreenCaptureService.from_backend(backend)
        region = {"left": 1, "top": 2, "width": 3, "height": 2}

        image = service.grab(region)
        image[0, 0, 0] = 255

        backend.grab.assert_called_once_with(region)
        self.assertEqual(source[0, 0, 0], 0)

    def test_grab_calls_are_serialized(self) -> None:
        active = 0
        max_active = 0
        state_lock = threading.Lock()

        class Backend:
            def grab(self, _region):
                nonlocal active, max_active
                with state_lock:
                    active += 1
                    max_active = max(max_active, active)
                time.sleep(0.02)
                with state_lock:
                    active -= 1
                return np.zeros((1, 1, 4), dtype=np.uint8)

            def close(self):
                return

        service = ScreenCaptureService.from_backend(Backend())
        threads = [threading.Thread(target=service.grab, args=({"left": index},)) for index in range(2)]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(max_active, 1)

    def test_replace_backend_closes_previous_owner(self) -> None:
        previous = Mock()
        replacement = Mock()
        service = ScreenCaptureService.from_backend(previous)

        service.replace_backend(replacement)

        previous.close.assert_called_once_with()
        self.assertIs(service.backend, replacement)

    def test_close_is_idempotent(self) -> None:
        backend = Mock()
        service = ScreenCaptureService.from_backend(backend)

        service.close()
        service.close()

        backend.close.assert_called_once_with()
        with self.assertRaises(RuntimeError):
            service.grab({})

    def test_close_retries_after_backend_failure(self) -> None:
        backend = Mock()
        backend.close.side_effect = [RuntimeError("close failed"), None]
        service = ScreenCaptureService.from_backend(backend)

        with self.assertRaises(RuntimeError):
            service.close()
        service.close()
        service.close()

        self.assertEqual(backend.close.call_count, 2)

    def test_protocol_exposes_borrowed_grab_only(self) -> None:
        self.assertIn("grab", ScreenCapturePort.__dict__)
        self.assertNotIn("close", ScreenCapturePort.__dict__)


if __name__ == "__main__":
    unittest.main()
