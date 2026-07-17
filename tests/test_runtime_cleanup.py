from __future__ import annotations

import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from maple_star.controllers.auto_potion_controller import AutoPotionController, _create_auto_potion_controller
from maple_star.controllers import gamepad_controller
from maple_star.controllers.gamepad_controller import _run_shutdown_step
from maple_star.services.runtime_processes import (
    RuntimeProcessCoordinator,
    WorkerCrashed,
    _report_worker_crash,
    _run_child_cleanup_step,
    _run_experience_stats_process,
    _run_potion_runtime_process,
)


class _EmptyQueue:
    def get_nowait(self):
        import queue

        raise queue.Empty


class _RecordingQueue:
    def __init__(self) -> None:
        self.items: list[object] = []

    def put(self, item: object) -> None:
        self.items.append(item)


class RuntimeProcessCleanupTests(unittest.TestCase):
    @staticmethod
    def _runtime_coordinator() -> RuntimeProcessCoordinator:
        runtime = RuntimeProcessCoordinator.__new__(RuntimeProcessCoordinator)
        runtime._started = False
        runtime._stopped = False
        runtime._potion_commands = Mock()
        runtime._experience_commands = Mock()
        runtime._control_process = None
        runtime._control_release_event = Mock()
        runtime._potion_process = Mock(name="potion_process")
        runtime._potion_process.name = "potion"
        runtime._experience_process = Mock(name="experience_process")
        runtime._experience_process.name = "experience"
        runtime._potion_process.is_alive.return_value = False
        runtime._experience_process.is_alive.return_value = False
        return runtime

    def _run_failing_child(self, target, worker_name: str) -> list[str]:
        events: list[str] = []

        class FailingController:
            def __init__(self, *_args, **_kwargs) -> None:
                self._log_potion_key_trigger_interval = lambda *_args: None
                self.auto_drink_enabled = True

            def update(self, *_args, **_kwargs) -> None:
                raise RuntimeError(f"{worker_name}-update-failed")

            def _release_all_potion_keys(self) -> None:
                events.append("release-potion-keys")

            def _cancel_experience_baseline_calibration(self, *, close_ui: bool) -> None:
                self.assert_close_ui(close_ui)
                events.append("cancel-experience")

            def assert_close_ui(self, close_ui: bool) -> None:
                if not close_ui:
                    raise AssertionError("close_ui must be true")

            def cleanup(self) -> None:
                events.append("cleanup")

        fake_module = types.ModuleType("maple_star.controllers.auto_potion_controller")
        fake_module.AutoPotionController = FailingController
        fake_module._create_auto_potion_controller = lambda *_args, **_kwargs: FailingController()
        status_queue = _RecordingQueue()
        with (
            patch.dict(sys.modules, {fake_module.__name__: fake_module}),
            patch("maple_star.services.runtime_processes.log_exception"),
        ):
            target(_EmptyQueue(), status_queue, {}, 0)

        crashes = [item for item in status_queue.items if isinstance(item, WorkerCrashed)]
        self.assertEqual(len(crashes), 1)
        self.assertEqual(crashes[0].worker, worker_name)
        self.assertEqual(crashes[0].message, f"{worker_name}-update-failed")
        return events

    def test_potion_child_cleans_up_after_update_failure(self) -> None:
        self.assertEqual(
            self._run_failing_child(_run_potion_runtime_process, "potion"),
            ["release-potion-keys", "cleanup"],
        )

    def test_experience_child_cleans_up_after_update_failure(self) -> None:
        self.assertEqual(
            self._run_failing_child(_run_experience_stats_process, "experience"),
            ["cancel-experience", "cleanup"],
        )

    def test_cleanup_logging_failure_does_not_escape(self) -> None:
        with (
            patch(
                "maple_star.services.runtime_processes.log_exception",
                side_effect=RuntimeError("logger failed"),
            ),
            patch("builtins.print") as print_message,
        ):
            _run_child_cleanup_step(
                "potion",
                "test resource",
                Mock(side_effect=RuntimeError("cleanup failed")),
            )

        print_message.assert_called_once()

    def test_parent_shutdown_step_contains_failure(self) -> None:
        with patch("builtins.print") as print_message:
            _run_shutdown_step("test resource", Mock(side_effect=RuntimeError("cleanup failed")))

        print_message.assert_called_once()

    def test_parent_shutdown_step_contains_print_failure(self) -> None:
        with patch("builtins.print", side_effect=RuntimeError("stdout failed")):
            _run_shutdown_step("test resource", Mock(side_effect=RuntimeError("cleanup failed")))

    def test_worker_crash_queue_still_receives_message_when_logger_fails(self) -> None:
        status_queue = _RecordingQueue()
        with patch(
            "maple_star.services.runtime_processes.log_exception",
            side_effect=RuntimeError("logger failed"),
        ):
            _report_worker_crash(status_queue, "potion", RuntimeError("runtime failed"))

        self.assertEqual(status_queue.items, [WorkerCrashed("potion", "runtime failed")])

    def test_worker_crash_reporting_contains_queue_failure(self) -> None:
        status_queue = Mock()
        status_queue.put.side_effect = RuntimeError("queue failed")
        with patch("maple_star.services.runtime_processes.log_exception"):
            _report_worker_crash(status_queue, "potion", RuntimeError("runtime failed"))

    def test_main_wrapper_cleans_registered_resources_after_startup_failure(self) -> None:
        cleanup = Mock()

        def fail_startup(actions):
            actions["auto-potion controller"] = cleanup
            raise RuntimeError("startup failed")

        with patch.object(gamepad_controller, "_run_main", side_effect=fail_startup):
            with self.assertRaisesRegex(RuntimeError, "startup failed"):
                gamepad_controller.main()

        cleanup.assert_called_once_with()

    def test_coordinator_stops_first_process_when_second_start_fails(self) -> None:
        runtime = self._runtime_coordinator()
        runtime._potion_process.is_alive.return_value = True
        runtime._experience_process.start.side_effect = RuntimeError("experience start failed")

        with (
            patch("maple_star.services.runtime_processes.log_exception"),
            self.assertRaisesRegex(RuntimeError, "experience start failed"),
        ):
            runtime.start()

        runtime._potion_process.terminate.assert_called_once_with()
        self.assertGreaterEqual(runtime._potion_process.join.call_count, 2)
        self.assertTrue(runtime._stopped)

    def test_coordinator_stop_continues_after_queue_failure(self) -> None:
        runtime = self._runtime_coordinator()
        runtime._started = True
        runtime._potion_commands.put.side_effect = [RuntimeError("queue failed"), None]

        with patch("maple_star.services.runtime_processes.log_exception") as log_exception:
            runtime.stop()
            runtime.stop()

        runtime._experience_commands.put.assert_called()
        runtime._potion_process.join.assert_called_once_with(timeout=1.0)
        runtime._experience_process.join.assert_called_once_with(timeout=1.0)
        log_exception.assert_called()


class AutoPotionControllerCleanupTests(unittest.TestCase):
    def _controller(self) -> tuple[AutoPotionController, dict[str, Mock]]:
        controller = AutoPotionController.__new__(AutoPotionController)
        calls = {
            "release_pickup": Mock(side_effect=RuntimeError("pickup release failed")),
            "release_potion": Mock(),
            "runtime_stop": Mock(),
            "unregister": Mock(),
            "control_worker_stop": Mock(),
            "potion_worker_stop": Mock(),
            "mouse_stop": Mock(),
            "close_media": Mock(),
            "capture_close": Mock(),
            "executor_shutdown": Mock(),
            "sct_close": Mock(),
            "gui_close": Mock(),
        }
        controller._release_pickup_key = calls["release_pickup"]
        controller._release_all_potion_keys = calls["release_potion"]
        controller.runtime_processes = SimpleNamespace(stop=calls["runtime_stop"])
        controller._unregister_toggle_hotkey = calls["unregister"]
        controller.control_hotkey_worker = SimpleNamespace(stop=calls["control_worker_stop"])
        controller.potion_action_worker = SimpleNamespace(stop=calls["potion_worker_stop"])
        controller.mouse_activity_observer = SimpleNamespace(stop=calls["mouse_stop"])
        controller._close_media_files = calls["close_media"]
        controller.direct_bar_capture_context = SimpleNamespace(close=calls["capture_close"])
        controller.experience_ocr_executor = SimpleNamespace(shutdown=calls["executor_shutdown"])
        controller.save_settings_on_cleanup = False
        controller.sct = SimpleNamespace(close=calls["sct_close"])
        controller.gui = SimpleNamespace(closed=False, close=calls["gui_close"])
        controller.original_stdout = None
        controller.original_stderr = None
        return controller, calls

    def test_cleanup_continues_after_a_step_fails(self) -> None:
        controller, calls = self._controller()
        with patch("maple_star.controllers.auto_potion_controller.log_exception") as log_exception:
            controller.cleanup()

        calls["release_potion"].assert_called_once_with()
        calls["runtime_stop"].assert_called_once_with()
        calls["unregister"].assert_called_once_with()
        calls["control_worker_stop"].assert_called_once_with()
        calls["potion_worker_stop"].assert_called_once_with()
        calls["mouse_stop"].assert_called_once_with()
        calls["close_media"].assert_called_once_with()
        calls["capture_close"].assert_called_once_with()
        calls["executor_shutdown"].assert_called_once_with(wait=False, cancel_futures=True)
        calls["sct_close"].assert_called_once_with()
        calls["gui_close"].assert_called_once_with()
        log_exception.assert_called()

        calls["release_pickup"].side_effect = None
        controller.cleanup()
        controller.cleanup()
        self.assertEqual(calls["release_pickup"].call_count, 2)
        for label, cleanup_call in calls.items():
            if label != "release_pickup":
                cleanup_call.assert_called_once()

    def test_cleanup_is_idempotent_after_completion(self) -> None:
        controller, calls = self._controller()
        calls["release_pickup"].side_effect = None
        with patch("maple_star.controllers.auto_potion_controller.log_exception"):
            controller.cleanup()
            controller.cleanup()

        for cleanup_call in calls.values():
            cleanup_call.assert_called_once()

    def test_constructor_failure_cleans_partially_initialized_resources(self) -> None:
        close_capture = Mock()

        def fail_initialization(controller, *_args, **_kwargs) -> None:
            controller.sct = SimpleNamespace(close=close_capture)
            controller.gui = SimpleNamespace(closed=True, close=Mock())
            controller.original_stdout = None
            controller.original_stderr = None
            controller.settings = SimpleNamespace()
            raise RuntimeError("constructor failed")

        with (
            patch.object(AutoPotionController, "__init__", new=fail_initialization),
            patch("maple_star.controllers.auto_potion_controller.log_exception"),
            patch("maple_star.controllers.auto_potion_controller.save_settings") as save_settings,
        ):
            with self.assertRaisesRegex(RuntimeError, "constructor failed"):
                _create_auto_potion_controller(Mock())

        close_capture.assert_called_once_with()
        save_settings.assert_not_called()


if __name__ == "__main__":
    unittest.main()
