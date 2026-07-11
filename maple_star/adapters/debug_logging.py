from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import TextIO

from ..models.settings import app_base_dir


DEBUG_LOG_PATH = app_base_dir() / "debug.log"
EXPERIENCE_DEBUG_LOG_PATH = app_base_dir() / "experience_debug.log"
TELEGRAM_REPLY_LOG_PATH = app_base_dir() / "telegram_reply.log"
DEBUG_LOG_MAX_BYTES = 1 * 1024 * 1024
DEBUG_LOG_BACKUP_COUNT = 3
EXPERIENCE_DEBUG_LOG_MAX_BYTES = 5 * 1024 * 1024
EXPERIENCE_DEBUG_LOG_BACKUP_COUNT = 5
TELEGRAM_REPLY_LOG_MAX_BYTES = 1 * 1024 * 1024
TELEGRAM_REPLY_LOG_BACKUP_COUNT = 3

_LOGGER_NAME = "maple_star.debug"
_EXPERIENCE_LOGGER_NAME = "maple_star.experience_debug"
_TELEGRAM_REPLY_LOGGER_NAME = "maple_star.telegram_reply"
_configured_path: Path | None = None
_experience_configured_path: Path | None = None
_telegram_reply_configured_path: Path | None = None
_original_excepthook = sys.excepthook
_original_threading_excepthook = getattr(threading, "excepthook", None)


def configure_debug_logging(
    path: Path | None = None,
    *,
    reset: bool = False,
    max_bytes: int = DEBUG_LOG_MAX_BYTES,
    backup_count: int = DEBUG_LOG_BACKUP_COUNT,
) -> Path:
    log_path = path or DEBUG_LOG_PATH
    _configure_logger(
        _LOGGER_NAME,
        log_path,
        reset=reset,
        max_bytes=max_bytes,
        backup_count=backup_count,
    )
    sys.excepthook = _handle_unhandled_exception
    if hasattr(threading, "excepthook"):
        threading.excepthook = _handle_thread_exception
    return log_path


def configure_experience_debug_logging(
    path: Path | None = None,
    *,
    reset: bool = False,
    max_bytes: int = EXPERIENCE_DEBUG_LOG_MAX_BYTES,
    backup_count: int = EXPERIENCE_DEBUG_LOG_BACKUP_COUNT,
) -> Path:
    log_path = path or EXPERIENCE_DEBUG_LOG_PATH
    _configure_logger(
        _EXPERIENCE_LOGGER_NAME,
        log_path,
        reset=reset,
        max_bytes=max_bytes,
        backup_count=backup_count,
    )
    return log_path


def configure_telegram_reply_logging(
    path: Path | None = None,
    *,
    reset: bool = False,
    max_bytes: int = TELEGRAM_REPLY_LOG_MAX_BYTES,
    backup_count: int = TELEGRAM_REPLY_LOG_BACKUP_COUNT,
) -> Path:
    log_path = path or TELEGRAM_REPLY_LOG_PATH
    _configure_logger(
        _TELEGRAM_REPLY_LOGGER_NAME,
        log_path,
        reset=reset,
        max_bytes=max_bytes,
        backup_count=backup_count,
    )
    return log_path


def close_debug_logging() -> None:
    global _configured_path
    _close_logger(_LOGGER_NAME)
    _configured_path = None


def close_experience_debug_logging() -> None:
    global _experience_configured_path
    _close_logger(_EXPERIENCE_LOGGER_NAME)
    _experience_configured_path = None


def close_telegram_reply_logging() -> None:
    global _telegram_reply_configured_path
    _close_logger(_TELEGRAM_REPLY_LOGGER_NAME)
    _telegram_reply_configured_path = None


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


def log_experience_debug(event: dict[str, object]) -> None:
    if _experience_configured_path is None:
        configure_experience_debug_logging()
    payload_event = {"logged_at": datetime.now().isoformat(timespec="seconds"), **event}
    payload = json.dumps(payload_event, ensure_ascii=False, separators=(",", ":"), default=str)
    logging.getLogger(_EXPERIENCE_LOGGER_NAME).info(payload)


def log_telegram_reply(event: dict[str, object]) -> None:
    if _telegram_reply_configured_path is None:
        configure_telegram_reply_logging()
    payload_event = {"logged_at": datetime.now().isoformat(timespec="seconds"), **event}
    payload = json.dumps(payload_event, ensure_ascii=False, separators=(",", ":"), default=str)
    logging.getLogger(_TELEGRAM_REPLY_LOGGER_NAME).info(payload)


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


def _configure_logger(
    logger_name: str,
    log_path: Path,
    *,
    reset: bool = False,
    max_bytes: int,
    backup_count: int,
) -> None:
    global _configured_path, _experience_configured_path, _telegram_reply_configured_path
    resolved = log_path.resolve()
    configured_path = _logger_configured_path(logger_name)
    logger = logging.getLogger(logger_name)
    if configured_path == resolved and logger.handlers and not reset:
        return

    resolved.parent.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    if reset:
        _reset_rotating_log_files(resolved)
    handler = RotatingFileHandler(
        resolved,
        mode="a",
        maxBytes=max(0, int(max_bytes)),
        backupCount=max(0, int(backup_count)),
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    if logger_name in {_EXPERIENCE_LOGGER_NAME, _TELEGRAM_REPLY_LOGGER_NAME}:
        formatter = logging.Formatter("%(message)s")
    else:
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    if logger_name == _EXPERIENCE_LOGGER_NAME:
        _experience_configured_path = resolved
    elif logger_name == _TELEGRAM_REPLY_LOGGER_NAME:
        _telegram_reply_configured_path = resolved
    else:
        _configured_path = resolved


def _reset_rotating_log_files(log_path: Path) -> None:
    for candidate in _rotating_log_files(log_path):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass
    log_path.write_text("", encoding="utf-8")


def _rotating_log_files(log_path: Path) -> list[Path]:
    files = [log_path]
    try:
        candidates = sorted(log_path.parent.glob(f"{log_path.name}.*"))
    except OSError:
        return files
    for candidate in candidates:
        suffix = candidate.name[len(log_path.name) + 1 :]
        if suffix.isdigit():
            files.append(candidate)
    return files


def _logger_configured_path(logger_name: str) -> Path | None:
    if logger_name == _EXPERIENCE_LOGGER_NAME:
        return _experience_configured_path
    if logger_name == _TELEGRAM_REPLY_LOGGER_NAME:
        return _telegram_reply_configured_path
    return _configured_path


def _close_logger(logger_name: str) -> None:
    logger = logging.getLogger(logger_name)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


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
