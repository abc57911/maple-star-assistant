from __future__ import annotations

import os
import sys
import traceback
import multiprocessing as mp
from pathlib import Path


if __name__ == "__main__":
    mp.freeze_support()
    project_log_exception = None
    try:
        from maple_star.debug_logging import (
            configure_debug_logging,
            configure_experience_debug_logging,
            configure_telegram_reply_logging,
            log_exception as project_log_exception,
        )

        configure_debug_logging(reset=True)
        configure_experience_debug_logging(reset=True)
        configure_telegram_reply_logging(reset=True)
        if all(
            os.environ.get(name, "").strip()
            for name in (
                "MAPLE_STAR_RELEASE_OCR_SMOKE_IMAGE",
                "MAPLE_STAR_RELEASE_OCR_SMOKE_OUTPUT",
            )
        ):
            from maple_star.release_ocr_smoke import run_release_ocr_smoke_if_requested

            smoke_exit_code = run_release_ocr_smoke_if_requested()
            if smoke_exit_code is not None:
                raise SystemExit(smoke_exit_code)
        from main import main

        raise SystemExit(main())
    except Exception:
        exception_info = sys.exc_info()
        error_text = traceback.format_exc()
        try:
            Path(__file__).with_name("startup_error.log").write_text(
                error_text,
                encoding="utf-8",
            )
        except Exception:
            pass
        if project_log_exception is not None:
            try:
                project_log_exception("啟動失敗", exception_info)
            except Exception:
                pass
        raise
