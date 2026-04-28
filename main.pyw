from __future__ import annotations

import traceback
import multiprocessing as mp
from pathlib import Path

from main import main


if __name__ == "__main__":
    mp.freeze_support()
    try:
        raise SystemExit(main())
    except Exception:
        Path(__file__).with_name("startup_error.log").write_text(
            traceback.format_exc(),
            encoding="utf-8",
        )
        raise
