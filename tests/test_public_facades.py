from __future__ import annotations

import importlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

from tests.public_facade_manifest import (
    EXACT_ALL,
    EXPERIENCE_STAGED_OWNERS,
    EXPERIENCE_TARGET_OWNERS,
    MODULE_ALIASES,
    PACKAGE_ROOT_EXPORTS,
    PATCH_POINTS,
    REQUIRED_EXPORTS,
)


ROOT = Path(__file__).resolve().parents[1]


def _resolve_attribute(value: object, dotted_name: str) -> object:
    for part in dotted_name.split("."):
        value = getattr(value, part)
    return value


class PublicFacadeTests(unittest.TestCase):
    def test_package_root_exports_are_canonical_objects(self) -> None:
        package = importlib.import_module("maple_star")
        for name, owner_name in PACKAGE_ROOT_EXPORTS.items():
            with self.subTest(name=name):
                owner = importlib.import_module(owner_name)
                self.assertIs(getattr(package, name), getattr(owner, name))

    def test_required_facade_exports_are_canonical_objects(self) -> None:
        for facade_name, exports in REQUIRED_EXPORTS.items():
            facade = importlib.import_module(facade_name)
            for name, owner_name in exports.items():
                with self.subTest(facade=facade_name, name=name):
                    owner = importlib.import_module(owner_name)
                    self.assertIs(getattr(facade, name), getattr(owner, name))

    def test_exact_all_contracts(self) -> None:
        for module_name, expected in EXACT_ALL.items():
            with self.subTest(module=module_name):
                module = importlib.import_module(module_name)
                self.assertEqual(frozenset(module.__all__), expected)

    def test_controller_patch_points_exist_on_canonical_alias(self) -> None:
        for module_name, patch_points in PATCH_POINTS.items():
            module = importlib.import_module(module_name)
            for dotted_name in patch_points:
                with self.subTest(module=module_name, patch=dotted_name):
                    self.assertIsNotNone(_resolve_attribute(module, dotted_name))

    def test_experience_target_owner_manifest_matches_staged_manifest(self) -> None:
        self.assertEqual(EXPERIENCE_STAGED_OWNERS, EXPERIENCE_TARGET_OWNERS)

    def test_module_alias_identity_for_both_import_orders(self) -> None:
        for facade_name, canonical_name in MODULE_ALIASES.items():
            for order in ("canonical-first", "facade-first"):
                with self.subTest(facade=facade_name, order=order):
                    script = self._alias_script(facade_name, canonical_name, order)
                    result = subprocess.run(
                        [sys.executable, "-I", "-c", script],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @staticmethod
    def _alias_script(facade_name: str, canonical_name: str, order: str) -> str:
        first, second = (
            (canonical_name, facade_name)
            if order == "canonical-first"
            else (facade_name, canonical_name)
        )
        return "\n".join(
            (
                "import importlib, sys",
                f"sys.path.insert(0, {json.dumps(str(ROOT))})",
                f"first = importlib.import_module({json.dumps(first)})",
                f"second = importlib.import_module({json.dumps(second)})",
                f"facade = importlib.import_module({json.dumps(facade_name)})",
                f"canonical = importlib.import_module({json.dumps(canonical_name)})",
                "assert facade is canonical",
                f"assert sys.modules[{json.dumps(facade_name)}] is canonical",
                f"assert canonical.__name__ == {json.dumps(canonical_name)}",
            )
        )


if __name__ == "__main__":
    unittest.main()
