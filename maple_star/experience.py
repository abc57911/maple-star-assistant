from __future__ import annotations

import sys as _sys

from .models import experience as _implementation

_sys.modules[__name__] = _implementation
