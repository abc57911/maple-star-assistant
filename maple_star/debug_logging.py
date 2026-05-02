from __future__ import annotations

import logging
import sys
import threading
import traceback
from pathlib import Path
from types import TracebackType
from typing import TextIO

from .settings import app_base_dir


DEBUG_LOG_PATH = app_base_dir() / "debug.log"

_LOGGER_NAME = "maple_star.debug"
_configured_path: Path | None = None
_original_excepthook = sys.excepthook
_original_threading_excepthook = getattr(threading, "excepthook", None)


def configure_debug_logging(path: Path | None = None, *, reset: bool = False) -> Path:
    log_path = path or DEBUG_LOG_PATH
    _configure_logger(log_path, reset=reset)
    sys.excepthook = _handle_unhandled_exception
    if hasattr(threading, "excepthook"):
        threading.excepthook = _handle_thread_exception
    return log_path


def close_debug_logging() -> None:
    global _configured_path
    logger = logging.getLogger(_LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    _configured_path = None


def install_tk_exception_logging(root: object) -> None:
    configure_debug_logging()
    setattr(root, "report_callback_exception", _handle_tk_exception)


def log_exception(
    message: str,
    exc_info: tuple[type[BaseException], BaseException, TracebackType | None] | None = None,
) -> None:
    if _configured_path is None:
        configure_debug_logging()
    logger = logging.getLogger(_LOGGER_NAME)
    if exc_info is None:
        logger.exception(message)
        return
    logger.error(message, exc_info=exc_info)


def log_debug(message: str) -> None:
    if _configured_path is None:
        configure_debug_logging()
    logging.getLogger(_LOGGER_NAME).info(message)


def write_debug_text(text: str) -> None:
    if not text:
        return
    for line in text.rstrip("\n").splitlines():
        if line:
            log_debug(line)


def write_exception_text(
    message: str,
    exc_info: tuple[type[BaseException], BaseException, TracebackType | None] | None = None,
    stream: TextIO | None = None,
) -> None:
    if stream is None:
        stream = sys.__stderr__
    if stream is None:
        return
    try:
        stream.write(f"{message}\n")
        if exc_info is None:
            stream.write(traceback.format_exc())
        else:
            traceback.print_exception(*exc_info, file=stream)
        stream.flush()
    except Exception:
        pass


def _configure_logger(log_path: Path, *, reset: bool = False) -> None:
    global _configured_path
    resolved = log_path.resolve()
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured_path == resolved and logger.handlers and not reset:
        return

    resolved.parent.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    handler = logging.FileHandler(resolved, mode="w" if reset else "a", encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    _configured_path = resolved


def _handle_unhandled_exception(
    exc_type: type[BaseException],
    exc: BaseException,
    tb: TracebackType | None,
) -> None:
    log_exception("未捕捉例外", (exc_type, exc, tb))
    if _original_excepthook is not None and _original_excepthook is not _handle_unhandled_exception:
        _original_excepthook(exc_type, exc, tb)


def _handle_thread_exception(args: threading.ExceptHookArgs) -> None:
    log_exception(
        f"threading 未捕捉例外：{getattr(args.thread, 'name', '--')}",
        (args.exc_type, args.exc_value, args.exc_traceback),
    )
    if (
        _original_threading_excepthook is not None
        and _original_threading_excepthook is not _handle_thread_exception
    ):
        _original_threading_excepthook(args)


def _handle_tk_exception(
    exc_type: type[BaseException],
    exc: BaseException,
    tb: TracebackType | None,
) -> None:
    exc_info = (exc_type, exc, tb)
    log_exception("Tkinter callback 例外", exc_info)
    write_exception_text("Exception in Tkinter callback", exc_info)
