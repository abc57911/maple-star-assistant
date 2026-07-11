from __future__ import annotations

import sys
import traceback
import multiprocessing as mp
from pathlib import Path


if __name__ == "__main__":
    mp.freeze_support()
    try:
        from maple_star.debug_logging import (
            configure_debug_logging,
            configure_experience_debug_logging,
            configure_telegram_reply_logging,
            log_exception,
        )

        configure_debug_logging(reset=True)
        configure_experience_debug_logging(reset=True)
        configure_telegram_reply_logging(reset=True)
        from main import main

        raise SystemExit(main())
    except Exception:
        log_exception("啟動失敗", sys.exc_info())
        Path(__file__).with_name("startup_error.log").write_text(
            traceback.format_exc(),
            encoding="utf-8",
        )
        raise
