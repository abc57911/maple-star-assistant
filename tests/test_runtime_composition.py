from __future__ import annotations

import ast
import importlib
import inspect
import json
import multiprocessing as mp
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

from maple_star.controllers import auto_potion_controller
from maple_star.controllers.auto_potion_factory import _create_auto_potion_controller
from maple_star.controllers.auto_potion_runtime_composition import create_runtime_process_port
from maple_star.controllers.runtime_child_entrypoints import (
    run_experience_stats_process,
    run_potion_runtime_process,
)
from maple_star.models.settings import AutoPotionSettings
from maple_star.services import runtime_api, runtime_processes
from maple_star.services.controller_collaborator_api import ToggleBeepPattern


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PROCESSES_PATH = ROOT / "maple_star" / "services" / "runtime_processes.py"
CHILD_ENTRYPOINTS_PATH = ROOT / "maple_star" / "controllers" / "runtime_child_entrypoints.py"


def _spawn_import_probe(result_queue) -> None:
    from maple_star.controllers.runtime_child_entrypoints import (
        run_experience_stats_process as experience_target,
        run_potion_runtime_process as potion_target,
    )
    from maple_star.services.runtime_api import PotionStatus as canonical_status
    from maple_star.services.runtime_processes import PotionStatus as compatibility_status

    result_queue.put(
        (
            potion_target.__module__,
            experience_target.__module__,
            canonical_status is compatibility_status,
        )
    )


class _RecordingMediaSink:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []

    def play_media(self, path: Path, alias: str) -> None:
        self.events.append(("media", path, alias))

    def play_toggle_beep(self, pattern: ToggleBeepPattern) -> None:
        self.events.append(("beep", pattern))


class RuntimeCompositionTests(unittest.TestCase):
    def test_runtime_api_symbols_are_canonical_reexports(self) -> None:
        names = (
            "ControlCommand",
            "ControlStatus",
            "ExperienceControl",
            "ExperienceStatus",
            "InlineExecutor",
            "PotionControl",
            "PotionStatus",
            "SettingsUpdated",
            "Shutdown",
            "TargetWindowUpdated",
            "WorkerCrashed",
            "_experience_status_signature",
            "_potion_status_signature",
            "control_status_signature",
        )
        for name in names:
            with self.subTest(name=name):
                self.assertIs(getattr(runtime_processes, name), getattr(runtime_api, name))

        for name in (
            "ExperienceControl",
            "ExperienceStatus",
            "InlineExecutor",
            "PotionControl",
            "PotionStatus",
            "WorkerCrashed",
            "_experience_status_signature",
            "_potion_status_signature",
        ):
            with self.subTest(controller_symbol=name):
                self.assertIs(getattr(auto_potion_controller, name), getattr(runtime_api, name))

    def test_factory_is_canonical_and_preserves_partial_cleanup(self) -> None:
        self.assertIs(auto_potion_controller._create_auto_potion_controller, _create_auto_potion_controller)
        cleanup = Mock()

        class FailingController:
            def __init__(self, *_args, **_kwargs) -> None:
                raise RuntimeError("boom")

            def cleanup(self) -> None:
                cleanup()

        original = auto_potion_controller.AutoPotionController
        auto_potion_controller.AutoPotionController = FailingController
        try:
            with self.assertRaisesRegex(RuntimeError, "boom"):
                _create_auto_potion_controller(Mock(), runtime_processes_enabled=False)
        finally:
            auto_potion_controller.AutoPotionController = original
        cleanup.assert_called_once_with()

    def test_concrete_runtime_module_has_no_controller_import(self) -> None:
        tree = ast.parse(RUNTIME_PROCESSES_PATH.read_text(encoding="utf-8"))
        imports = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        rendered = "\n".join(ast.unparse(node) for node in imports)
        self.assertNotIn("controllers", rendered)

    def test_child_factory_imports_are_call_time_only(self) -> None:
        tree = ast.parse(CHILD_ENTRYPOINTS_PATH.read_text(encoding="utf-8"))
        module_imports = [
            node
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        self.assertNotIn("auto_potion_factory", "\n".join(ast.unparse(node) for node in module_imports))
        all_imports = "\n".join(
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        )
        self.assertIn("auto_potion_factory", all_imports)

    def test_composition_injects_canonical_spawn_targets(self) -> None:
        runtime = create_runtime_process_port(AutoPotionSettings(), 123)
        try:
            self.assertIs(runtime._potion_worker_target, run_potion_runtime_process)
            self.assertIs(runtime._experience_worker_target, run_experience_stats_process)
        finally:
            runtime.stop(timeout=0.01)

    def test_runtime_port_protocol_matches_coordinator_surface(self) -> None:
        required = {
            name
            for name, value in runtime_api.RuntimeProcessPort.__dict__.items()
            if inspect.isfunction(value) and not name.startswith("_")
        }
        actual = {
            name
            for name, value in runtime_processes.RuntimeProcessCoordinator.__dict__.items()
            if inspect.isfunction(value) and not name.startswith("_")
        }
        self.assertEqual(required, actual)
        for name in required:
            with self.subTest(name=name):
                protocol_parameters = inspect.signature(
                    getattr(runtime_api.RuntimeProcessPort, name)
                ).parameters
                concrete_parameters = inspect.signature(
                    getattr(runtime_processes.RuntimeProcessCoordinator, name)
                ).parameters
                self.assertEqual(tuple(protocol_parameters), tuple(concrete_parameters))
                for parameter_name in protocol_parameters:
                    self.assertEqual(
                        protocol_parameters[parameter_name].default,
                        concrete_parameters[parameter_name].default,
                    )

    def test_media_sink_routes_without_instance_monkey_patch(self) -> None:
        sink = _RecordingMediaSink()
        controller = auto_potion_controller.AutoPotionController.__new__(
            auto_potion_controller.AutoPotionController
        )
        controller.media_sink = sink
        path = Path("alert.mp3")
        pattern = ((440, 50),)

        controller._play_media_file(path, "alert")
        controller._play_toggle_beep(pattern)

        self.assertEqual(sink.events, [("media", path, "alert"), ("beep", pattern)])

    def test_spawn_import_round_trip_uses_canonical_targets(self) -> None:
        context = mp.get_context("spawn")
        result_queue = context.Queue()
        process = context.Process(target=_spawn_import_probe, args=(result_queue,))
        process.start()
        process.join(timeout=30)
        try:
            self.assertEqual(process.exitcode, 0)
            self.assertEqual(
                result_queue.get(timeout=5),
                (
                    "maple_star.controllers.runtime_child_entrypoints",
                    "maple_star.controllers.runtime_child_entrypoints",
                    True,
                ),
            )
        finally:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    def test_clean_import_orders_do_not_cycle(self) -> None:
        orders = (
            (
                "maple_star.controllers.auto_potion_controller",
                "maple_star.controllers.auto_potion_factory",
                "maple_star.services.runtime_processes",
            ),
            (
                "maple_star.services.runtime_processes",
                "maple_star.controllers.runtime_child_entrypoints",
                "maple_star.controllers.auto_potion_factory",
                "maple_star.controllers.auto_potion_controller",
            ),
        )
        for order in orders:
            with self.subTest(order=order):
                script = "\n".join(
                    (
                        "import importlib, sys",
                        f"sys.path.insert(0, {json.dumps(str(ROOT))})",
                        f"order = {order!r}",
                        "modules = [importlib.import_module(name) for name in order]",
                        "controller = importlib.import_module('maple_star.controllers.auto_potion_controller')",
                        "factory = importlib.import_module('maple_star.controllers.auto_potion_factory')",
                        "assert controller._create_auto_potion_controller is factory._create_auto_potion_controller",
                    )
                )
                result = subprocess.run(
                    [sys.executable, "-I", "-c", script],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
