from __future__ import annotations

import sys as _sys

from maple_star.controllers import gamepad_controller as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    _sys.modules[__name__] = _implementation
