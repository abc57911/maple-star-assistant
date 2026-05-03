from __future__ import annotations

import sys as _sys

from .controllers import auto_potion_controller as _implementation

_sys.modules[__name__] = _implementation
