from __future__ import annotations

import ast
import dataclasses
import inspect
import unittest
from pathlib import Path
from threading import Thread
from typing import Callable, get_type_hints

from maple_star.services.controller_collaborator_api import (
    ControllerModuleAdapters,
    RuntimeMediaSink,
    ToggleBeepPattern,
)
from tests.public_facade_manifest import PATCH_POINTS, REQUIRED_EXPORTS
from tests.stage4_controller_manifest import (
    CONTROLLER_BASELINE,
    CONTROLLER_STAGE_EXPECTED,
    CONSTRUCTOR_BASELINE_PARAMETERS,
    CONSTRUCTOR_STAGE4_KEYWORD_ONLY_PARAMETERS,
    MSS_GRAB_CALL_SITES,
    PATCH_POINT_CLASSIFICATIONS,
    PUBLIC_METHODS,
    PUBLIC_METHOD_SIGNATURES,
    REQUIRED_PRIVATE_ATTRIBUTES,
    REQUIRED_PRIVATE_METHOD_SHIMS,
    RESOURCE_OWNERS,
    SCREEN_CAPTURE_GRAB_CALL_SITES,
    STORED_FIELDS,
)


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER_PATH = ROOT / "maple_star" / "controllers" / "auto_potion_controller.py"
CONTRACTS_PATH = ROOT / "maple_star" / "services" / "controller_collaborator_api.py"
MEDIA_PLAYBACK_PATH = ROOT / "maple_star" / "services" / "media_playback.py"
CONTROL_HOTKEY_COORDINATOR_PATH = (
    ROOT / "maple_star" / "services" / "control_hotkey_coordinator.py"
)
SCREEN_CAPTURE_PATH = ROOT / "maple_star" / "services" / "screen_capture.py"
HUD_BAR_DETECTOR_PATH = ROOT / "maple_star" / "services" / "hud_bar_detector.py"
EXPERIENCE_CAPTURE_COORDINATOR_PATH = (
    ROOT / "maple_star" / "services" / "experience_capture_coordinator.py"
)
PRIVATE_CONSUMER_PATHS = (
    CONTROLLER_PATH,
    ROOT / "maple_star" / "controllers" / "gamepad_controller.py",
    ROOT / "maple_star" / "controllers" / "auto_potion_factory.py",
    ROOT / "maple_star" / "controllers" / "runtime_child_entrypoints.py",
    ROOT / "maple_star" / "services" / "runtime_processes.py",
    ROOT / "tests" / "test_auto_potion_foreground_guard.py",
    ROOT / "tests" / "test_bar_detection_debug.py",
    ROOT / "tests" / "test_runtime_cleanup.py",
)


def _controller_class() -> ast.ClassDef:
    tree = ast.parse(CONTROLLER_PATH.read_text(encoding="utf-8"))
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AutoPotionController"
    )


def _class_stored_fields(path: Path, class_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    target = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return {
        node.attr
        for node in ast.walk(target)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and isinstance(node.ctx, ast.Store)
    }


def _direct_private_consumer_surface() -> set[str]:
    names: set[str] = set()
    for path in PRIVATE_CONSUMER_PATHS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr.startswith("_")
                and not node.attr.startswith("__")
                and isinstance(node.value, ast.Name)
                and node.value.id in {"auto_potion", "controller"}
            ):
                names.add(node.attr)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "object"
                and len(node.args) >= 2
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id in {"auto_potion", "controller"}
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
                and node.args[1].value.startswith("_")
            ):
                names.add(node.args[1].value)
    return names


def _controller_patch_literals() -> set[str]:
    prefixes = tuple(f"{module_name}." for module_name in PATCH_POINTS)
    names: set[str] = set()
    for path in (ROOT / "tests").glob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "patch":
                continue
            target = node.args[0]
            if not isinstance(target, ast.Constant) or not isinstance(target.value, str):
                continue
            if target.value.startswith(prefixes):
                names.add(target.value)
    return names


def _mss_grab_call_sites() -> dict[str, int]:
    sites: dict[str, int] = {}

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.function_name: str | None = None

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            previous = self.function_name
            self.function_name = node.name
            self.generic_visit(node)
            self.function_name = previous

        def visit_Call(self, node: ast.Call) -> None:
            function = node.func
            if (
                self.function_name is not None
                and isinstance(function, ast.Attribute)
                and function.attr == "grab"
                and isinstance(function.value, ast.Attribute)
                and function.value.attr == "sct"
                and isinstance(function.value.value, ast.Name)
                and function.value.value.id == "self"
            ):
                sites[self.function_name] = sites.get(self.function_name, 0) + 1
            self.generic_visit(node)

    Visitor().visit(_controller_class())
    return sites


def _screen_capture_grab_call_sites() -> dict[str, int]:
    sites: dict[str, int] = {}

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.function_name: str | None = None

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            previous = self.function_name
            self.function_name = node.name
            self.generic_visit(node)
            self.function_name = previous

        def visit_Call(self, node: ast.Call) -> None:
            function = node.func
            service_call = function.value if isinstance(function, ast.Attribute) else None
            if (
                self.function_name is not None
                and isinstance(function, ast.Attribute)
                and function.attr == "grab"
                and isinstance(service_call, ast.Call)
                and isinstance(service_call.func, ast.Attribute)
                and service_call.func.attr == "_screen_capture_service"
                and isinstance(service_call.func.value, ast.Name)
                and service_call.func.value.id == "self"
            ):
                sites[self.function_name] = sites.get(self.function_name, 0) + 1
            self.generic_visit(node)

    Visitor().visit(_controller_class())
    return sites


class Stage4ControllerContractTests(unittest.TestCase):
    def test_controller_baseline_shape_is_locked(self) -> None:
        from maple_star.controllers.auto_potion_controller import AutoPotionController

        source = CONTROLLER_PATH.read_text(encoding="utf-8")
        controller = _controller_class()
        methods = [node.name for node in controller.body if isinstance(node, ast.FunctionDef)]
        stored_fields = {
            node.attr
            for node in ast.walk(controller)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
            and isinstance(node.ctx, ast.Store)
        }
        public_methods = {name for name in methods if not name.startswith("_")}

        self.assertLessEqual(len(source.splitlines()), CONTROLLER_STAGE_EXPECTED["loc"])
        self.assertEqual(len(methods), CONTROLLER_STAGE_EXPECTED["method_count"])
        self.assertEqual(len(public_methods), CONTROLLER_STAGE_EXPECTED["public_method_count"])
        self.assertEqual(
            len(methods) - len(public_methods),
            CONTROLLER_STAGE_EXPECTED["private_method_count"],
        )
        self.assertEqual(len(stored_fields), CONTROLLER_STAGE_EXPECTED["stored_field_count"])
        self.assertEqual(source.count("self.sct.grab("), CONTROLLER_STAGE_EXPECTED["mss_grab_call_count"])
        self.assertEqual(public_methods, PUBLIC_METHODS)
        self.assertEqual(
            stored_fields,
            STORED_FIELDS | {"media_playback_service", "media_sink", "runtime_process_factory"},
        )
        self.assertTrue(REQUIRED_PRIVATE_METHOD_SHIMS.issubset(methods))
        compatibility_properties = REQUIRED_PRIVATE_ATTRIBUTES - {"_initialization_completed"}
        self.assertTrue(
            all(
                isinstance(getattr(AutoPotionController, name), property)
                for name in compatibility_properties
            )
        )

    def test_public_method_signatures_are_locked(self) -> None:
        from maple_star.controllers.auto_potion_controller import AutoPotionController

        actual = {
            name: str(inspect.signature(getattr(AutoPotionController, name)))
            for name in PUBLIC_METHOD_SIGNATURES
            if name != "__init__"
        }
        expected = {name: value for name, value in PUBLIC_METHOD_SIGNATURES.items() if name != "__init__"}
        self.assertEqual(actual, expected)
        constructor = inspect.signature(AutoPotionController.__init__)
        parameters = tuple(str(parameter) for parameter in constructor.parameters.values())
        self.assertEqual(parameters[: len(CONSTRUCTOR_BASELINE_PARAMETERS)], CONSTRUCTOR_BASELINE_PARAMETERS)
        self.assertEqual(parameters[len(CONSTRUCTOR_BASELINE_PARAMETERS) :], CONSTRUCTOR_STAGE4_KEYWORD_ONLY_PARAMETERS)
        for name in ("runtime_process_factory", "media_sink"):
            self.assertIs(constructor.parameters[name].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(str(constructor.return_annotation), "None")

    def test_private_consumer_manifest_is_complete(self) -> None:
        self.assertEqual(
            _direct_private_consumer_surface(),
            REQUIRED_PRIVATE_METHOD_SHIMS | REQUIRED_PRIVATE_ATTRIBUTES,
        )

    def test_resource_and_capture_manifests_match_controller(self) -> None:
        controller_owner_fields = {
            owner.rsplit(".", 1)[-1]
            for owner in RESOURCE_OWNERS.values()
            if owner.startswith("AutoPotionController.")
        }
        self.assertTrue(controller_owner_fields <= STORED_FIELDS)
        media_owner_fields = {
            owner.rsplit(".", 1)[-1]
            for owner in RESOURCE_OWNERS.values()
            if owner.startswith("MediaPlaybackService.")
        }
        self.assertTrue(
            media_owner_fields
            <= _class_stored_fields(MEDIA_PLAYBACK_PATH, "MediaPlaybackService")
        )
        hotkey_owner_fields = {
            owner.rsplit(".", 1)[-1]
            for owner in RESOURCE_OWNERS.values()
            if owner.startswith("ControlHotkeyCoordinator.")
        }
        self.assertTrue(
            hotkey_owner_fields
            <= _class_stored_fields(
                CONTROL_HOTKEY_COORDINATOR_PATH,
                "ControlHotkeyCoordinator",
            )
        )
        experience_capture_owner_fields = {
            owner.rsplit(".", 1)[-1]
            for owner in RESOURCE_OWNERS.values()
            if owner.startswith("ExperienceCaptureCoordinator.")
        }
        self.assertTrue(
            experience_capture_owner_fields
            <= _class_stored_fields(
                EXPERIENCE_CAPTURE_COORDINATOR_PATH,
                "ExperienceCaptureCoordinator",
            )
        )
        capture_owner_fields = {
            owner.rsplit(".", 1)[-1]
            for owner in RESOURCE_OWNERS.values()
            if owner.startswith("ScreenCaptureService.")
        }
        self.assertTrue(
            capture_owner_fields
            <= _class_stored_fields(SCREEN_CAPTURE_PATH, "ScreenCaptureService")
        )
        hud_owner_fields = {
            owner.rsplit(".", 1)[-1]
            for owner in RESOURCE_OWNERS.values()
            if owner.startswith("HudBarDetector.")
        }
        self.assertTrue(
            hud_owner_fields
            <= _class_stored_fields(HUD_BAR_DETECTOR_PATH, "HudBarDetector")
        )
        self.assertEqual(
            RESOURCE_OWNERS,
            {
                "mss": "ScreenCaptureService._backend",
                "gdi_capture": "HudBarDetector.direct_capture_context",
                "control_hotkey_worker": "ControlHotkeyCoordinator.worker",
                "potion_action_worker": "AutoPotionController.potion_action_worker",
                "ocr_executor": "ExperienceCaptureCoordinator.executor",
                "runtime_processes": "AutoPotionController.runtime_processes",
                "mci_aliases": "MediaPlaybackService.alias_paths",
                "lie_detector_thread": "MediaPlaybackService.alert_thread",
            },
        )
        self.assertEqual(_mss_grab_call_sites(), MSS_GRAB_CALL_SITES)
        self.assertEqual(
            _screen_capture_grab_call_sites(),
            SCREEN_CAPTURE_GRAB_CALL_SITES,
        )
        experience_capture_source = EXPERIENCE_CAPTURE_COORDINATOR_PATH.read_text(encoding="utf-8")
        self.assertEqual(experience_capture_source.count("self.screen_capture.grab("), 1)

    def test_all_controller_patch_points_have_one_classification(self) -> None:
        facade_patch_points = {
            f"{module_name}.{patch_point}"
            for module_name, patch_points in PATCH_POINTS.items()
            for patch_point in patch_points
        }
        categories = PATCH_POINT_CLASSIFICATIONS
        self.assertEqual(facade_patch_points, categories["dynamic_adapter"])
        self.assertEqual(_controller_patch_literals(), categories["dynamic_adapter"])
        self.assertFalse(categories["dynamic_adapter"] & categories["controller_shim"])
        self.assertFalse(categories["dynamic_adapter"] & categories["canonical_reexport"])
        self.assertFalse(categories["controller_shim"] & categories["canonical_reexport"])

    def test_canonical_reexport_manifest_covers_facade_and_runtime_api(self) -> None:
        controller_facade = set(REQUIRED_EXPORTS["maple_star.controller"])
        runtime_api = {
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
        }
        required = controller_facade | runtime_api | {"_create_auto_potion_controller"}
        self.assertTrue(required <= PATCH_POINT_CLASSIFICATIONS["canonical_reexport"])

    def test_contracts_module_is_a_leaf_without_resource_imports(self) -> None:
        tree = ast.parse(CONTRACTS_PATH.read_text(encoding="utf-8"))
        imported_roots = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_roots.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertTrue(imported_roots <= {"__future__", "dataclasses", "pathlib", "threading", "typing"})
        self.assertFalse({"ctypes", "mss", "multiprocessing", "maple_star", "winsound"} & imported_roots)

    def test_adapter_contract_is_frozen_and_complete(self) -> None:
        field_names = {field.name for field in dataclasses.fields(ControllerModuleAdapters)}
        self.assertEqual(
            field_names,
            {
                "monotonic",
                "sleep",
                "thread_factory",
                "winmm_provider",
                "user32_provider",
                "beep",
                "message_beep",
                "play_sound",
                "key_down",
                "key_up",
                "tap_hotkey",
                "save_settings",
            },
        )
        self.assertTrue(ControllerModuleAdapters.__dataclass_params__.frozen)
        noop = lambda *args, **kwargs: None
        adapters = ControllerModuleAdapters(
            monotonic=lambda: 0.0,
            sleep=noop,
            thread_factory=noop,
            winmm_provider=lambda: object(),
            user32_provider=lambda: object(),
            beep=noop,
            message_beep=noop,
            play_sound=noop,
            key_down=noop,
            key_up=noop,
            tap_hotkey=noop,
            save_settings=noop,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            adapters.monotonic = lambda: 1.0  # type: ignore[misc]

        adapter_hints = get_type_hints(ControllerModuleAdapters)
        self.assertEqual(adapter_hints["monotonic"], Callable[[], float])
        self.assertEqual(adapter_hints["sleep"], Callable[[float], None])
        self.assertEqual(adapter_hints["thread_factory"], Callable[..., Thread])
        self.assertEqual(adapter_hints["winmm_provider"], Callable[[], object])
        self.assertEqual(adapter_hints["user32_provider"], Callable[[], object])
        self.assertEqual(adapter_hints["beep"], Callable[[int, int], None])
        self.assertEqual(adapter_hints["message_beep"], Callable[..., None])
        self.assertEqual(adapter_hints["play_sound"], Callable[..., None])
        self.assertEqual(adapter_hints["key_down"], Callable[[int], None])
        self.assertEqual(adapter_hints["key_up"], Callable[[int], None])
        self.assertEqual(adapter_hints["tap_hotkey"], Callable[..., None])
        self.assertEqual(adapter_hints["save_settings"], Callable[..., None])

        params = inspect.signature(RuntimeMediaSink.play_media).parameters
        self.assertEqual(tuple(params), ("self", "path", "alias"))
        media_hints = get_type_hints(RuntimeMediaSink.play_media)
        self.assertEqual(media_hints, {"path": Path, "alias": str, "return": type(None)})
        beep_params = inspect.signature(RuntimeMediaSink.play_toggle_beep).parameters
        self.assertEqual(tuple(beep_params), ("self", "pattern"))
        beep_hints = get_type_hints(RuntimeMediaSink.play_toggle_beep)
        self.assertEqual(beep_hints["pattern"], ToggleBeepPattern)
        self.assertEqual(beep_hints["return"], type(None))


if __name__ == "__main__":
    unittest.main()
