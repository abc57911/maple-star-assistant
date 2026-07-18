from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maple_star.app.resource_paths import ResourceResolver


class ResourcePathTests(unittest.TestCase):
    def test_source_and_frozen_roots_do_not_depend_on_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            frozen = Path(directory) / "bundle"
            self.assertEqual(ResourceResolver(source_root=source).resolve("maple_star/assets/a.wav"), source / "maple_star/assets/a.wav")
            self.assertEqual(ResourceResolver(source_root=source, frozen_root=frozen).resolve("maple_star/assets/a.wav"), frozen / "maple_star/assets/a.wav")

    def test_parent_segments_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ResourceResolver(source_root=Path("C:/source")).resolve("../secret")


if __name__ == "__main__":
    unittest.main()
