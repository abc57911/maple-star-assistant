import unittest

from maple_star.adapters.window_style import (
    WS_EX_APPWINDOW,
    WS_EX_TOOLWINDOW,
    background_toolwindow_exstyle,
)


class WindowStyleTests(unittest.TestCase):
    def test_background_toolwindow_exstyle_adds_toolwindow_and_removes_appwindow(self):
        original = WS_EX_APPWINDOW | 0x00000008

        updated = background_toolwindow_exstyle(original)

        self.assertTrue(updated & WS_EX_TOOLWINDOW)
        self.assertFalse(updated & WS_EX_APPWINDOW)
        self.assertTrue(updated & 0x00000008)


if __name__ == "__main__":
    unittest.main()
