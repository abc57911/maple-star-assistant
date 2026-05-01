import unittest
from unittest.mock import Mock

from maple_star.gui import AutoPotionSettingsGui


class ToggleNoticePositionTests(unittest.TestCase):
    def make_gui(self):
        gui = AutoPotionSettingsGui.__new__(AutoPotionSettingsGui)
        gui.root = Mock()
        gui.root.winfo_screenwidth.return_value = 1920
        gui.root.winfo_screenheight.return_value = 1080
        return gui

    def test_toggle_notice_uses_foreground_client_center_area(self):
        gui = self.make_gui()

        position = gui._toggle_notice_position(240, 60, (100, 200, 1700, 1100))

        self.assertEqual(position, (780, 575))

    def test_toggle_notice_falls_back_to_screen_center_area(self):
        gui = self.make_gui()

        position = gui._toggle_notice_position(240, 60, None)

        self.assertEqual(position, (840, 456))

    def test_toggle_notice_position_is_clamped_inside_bounds(self):
        gui = self.make_gui()

        position = gui._toggle_notice_position(240, 80, (0, 0, 200, 120))

        self.assertEqual(position, (16, 16))


if __name__ == "__main__":
    unittest.main()
