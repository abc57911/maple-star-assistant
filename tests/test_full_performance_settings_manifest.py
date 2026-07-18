from __future__ import annotations

import unittest

from tests.full_performance_settings_manifest import assert_complete_settings_v2_mapping


class FullPerformanceSettingsManifestTests(unittest.TestCase):
    def test_every_setting_has_one_v2_path(self) -> None:
        assert_complete_settings_v2_mapping()


if __name__ == "__main__":
    unittest.main()
