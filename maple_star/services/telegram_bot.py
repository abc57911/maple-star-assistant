from __future__ import annotations

import json
import queue
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..models.settings import app_base_dir


TELEGRAM_BOT_SECRETS_PATH = app_base_dir() / "secrets" / "telegram_bot.json"
TELEGRAM_API_BASE_URL = "https://api.telegram.org"
TELEGRAM_DEFAULT_POLL_TIMEOUT_SECONDS = 20
TELEGRAM_MIN_POLL_TIMEOUT_SECONDS = 1
TELEGRAM_MAX_POLL_TIMEOUT_SECONDS = 60
TELEGRAM_MAX_REPLY_TEXT_CHARS = 256
TELEGRAM_HTTP_TIMEOUT_PADDING_SECONDS = 15


class TelegramConfigError(ValueError):
    pass


@dataclass(frozen=True)
class TelegramBotConfig:
    bot_token: str
    allowed_chat_id: int
    poll_timeout_seconds: int = TELEGRAM_DEFAULT_POLL_TIMEOUT_SECONDS


@dataclass(frozen=True)
class TelegramReply:
    update_id: int
    chat_id: int
    message_id: int
    text: str
    received_at: float


class TelegramUpdatesClient(Protocol):
    def get_updates(self, *, offset: int | None, timeout_seconds: int) -> list[dict[str, object]]:
        ...

    def send_message(self, *, chat_id: int, text: str) -> None:
        ...


class TelegramBotApiClient:
    def __init__(self, bot_token: str, *, api_base_url: str = TELEGRAM_API_BASE_URL) -> None:
        self._bot_token = bot_token
        self._api_base_url = api_base_url.rstrip("/")

    def get_updates(self, *, offset: int | None, timeout_seconds: int) -> list[dict[str, object]]:
        payload: dict[str, object] = {
            "timeout": max(0, int(timeout_seconds)),
            "allowed_updates": json.dumps(["message"], separators=(",", ":")),
        }
        if offset is not None:
            payload["offset"] = int(offset)
        response = self._post_json("getUpdates", payload, timeout_seconds=timeout_seconds)
        if not bool(response.get("ok")):
            raise RuntimeError("Telegram getUpdates 回傳失敗")
        result = response.get("result")
        return result if isinstance(result, list) else []

    def send_message(self, *, chat_id: int, text: str) -> None:
        response = self._post_json(
            "sendMessage",
            {
                "chat_id": int(chat_id),
                "text": str(text),
            },
            timeout_seconds=20,
        )
        if not bool(response.get("ok")):
            raise RuntimeError("Telegram sendMessage 回傳失敗")

    def _post_json(
        self,
        method: str,
        payload: dict[str, object],
        *,
        timeout_seconds: int,
    ) -> dict[str, object]:
        body = urllib.parse.urlencode(payload).encode("utf-8")
        url = f"{self._api_base_url}/bot{self._bot_token}/{method}"
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(
            request,
            timeout=max(1, int(timeout_seconds) + TELEGRAM_HTTP_TIMEOUT_PADDING_SECONDS),
        ) as response:
            data = response.read()
        parsed = json.loads(data.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise RuntimeError("Telegram API 回應格式錯誤")
        return parsed


def load_telegram_bot_config(path: Path = TELEGRAM_BOT_SECRETS_PATH) -> TelegramBotConfig:
    if not path.exists():
        raise TelegramConfigError(f"Telegram secrets 未設定：{path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TelegramConfigError(f"Telegram secrets 讀取失敗：{exc}") from exc
    if not isinstance(raw, dict):
        raise TelegramConfigError("Telegram secrets 格式錯誤")

    token = raw.get("bot_token")
    if not isinstance(token, str) or not token.strip():
        raise TelegramConfigError("Telegram bot_token 未設定")
    chat_id = raw.get("allowed_chat_id")
    if isinstance(chat_id, bool):
        raise TelegramConfigError("Telegram allowed_chat_id 格式錯誤")
    try:
        normalized_chat_id = int(chat_id)
    except (TypeError, ValueError) as exc:
        raise TelegramConfigError("Telegram allowed_chat_id 格式錯誤") from exc
    poll_timeout = _read_poll_timeout(raw.get("poll_timeout_seconds"))
    return TelegramBotConfig(
        bot_token=token.strip(),
        allowed_chat_id=normalized_chat_id,
        poll_timeout_seconds=poll_timeout,
    )


def _read_poll_timeout(value: object) -> int:
    if isinstance(value, bool) or value is None:
        return TELEGRAM_DEFAULT_POLL_TIMEOUT_SECONDS
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return TELEGRAM_DEFAULT_POLL_TIMEOUT_SECONDS
    return max(TELEGRAM_MIN_POLL_TIMEOUT_SECONDS, min(TELEGRAM_MAX_POLL_TIMEOUT_SECONDS, parsed))


def extract_reply_from_update(
    update: dict[str, object],
    *,
    allowed_chat_id: int,
    received_at: float | None = None,
) -> TelegramReply | None:
    update_id = _read_int(update.get("update_id"))
    if update_id is None:
        return None
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict):
        return None
    chat_id = _read_int(chat.get("id"))
    if chat_id != int(allowed_chat_id):
        return None
    message_id = _read_int(message.get("message_id"))
    if message_id is None:
        return None
    text = _normalize_reply_text(message.get("text"))
    if text is None:
        return None
    return TelegramReply(
        update_id=update_id,
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        received_at=time.time() if received_at is None else float(received_at),
    )


def _read_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_reply_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(part.strip() for part in value.splitlines()).strip()
    if not text or text.startswith("/"):
        return None
    if len(text) > TELEGRAM_MAX_REPLY_TEXT_CHARS:
        return None
    return text


class TelegramReplyListener:
    def __init__(
        self,
        config: TelegramBotConfig,
        *,
        client: TelegramUpdatesClient | None = None,
    ) -> None:
        self.config = config
        self.client = client or TelegramBotApiClient(config.bot_token)
        self._queue: queue.Queue[TelegramReply] = queue.Queue()
        self._send_queue: queue.Queue[str | None] = queue.Queue(maxsize=20)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._send_thread: threading.Thread | None = None
        self._offset: int | None = None
        self._last_error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def start(self) -> None:
        poll_thread_alive = self._thread is not None and self._thread.is_alive()
        send_thread_alive = self._send_thread is not None and self._send_thread.is_alive()
        if poll_thread_alive and send_thread_alive:
            return
        self._stop.clear()
        self._last_error = None
        if not poll_thread_alive:
            self._thread = threading.Thread(target=self._run, name="maple-star-telegram-reply", daemon=True)
            self._thread.start()
        if not send_thread_alive:
            self._send_thread = threading.Thread(target=self._run_sender, name="maple-star-telegram-send", daemon=True)
            self._send_thread.start()

    def stop(self, timeout_seconds: float = 2.0) -> None:
        self._stop.set()
        try:
            self._send_queue.put_nowait(None)
        except queue.Full:
            pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(max(0.0, float(timeout_seconds)))
        send_thread = self._send_thread
        if send_thread is not None and send_thread.is_alive():
            send_thread.join(max(0.0, float(timeout_seconds)))

    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def drain_replies(self) -> list[TelegramReply]:
        replies: list[TelegramReply] = []
        while True:
            try:
                replies.append(self._queue.get_nowait())
            except queue.Empty:
                return replies

    def send_message(self, text: str) -> None:
        self.client.send_message(chat_id=self.config.allowed_chat_id, text=text)

    def queue_message(self, text: str) -> bool:
        try:
            self._send_queue.put_nowait(str(text))
        except queue.Full:
            self._last_error = "SendQueueFull"
            return False
        return True

    def _run_sender(self) -> None:
        while not self._stop.is_set():
            try:
                text = self._send_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if text is None:
                break
            try:
                self.send_message(text)
            except Exception as exc:
                self._last_error = type(exc).__name__

    def _run(self) -> None:
        while not self._stop.is_set():
            timeout = self.config.poll_timeout_seconds if self._offset is not None else 0
            try:
                updates = self.client.get_updates(offset=self._offset, timeout_seconds=timeout)
                self._last_error = None
            except Exception as exc:
                self._last_error = type(exc).__name__
                self._stop.wait(1.0)
                continue
            self._handle_updates(updates, skip_replies=self._offset is None)

    def _handle_updates(self, updates: list[dict[str, object]], *, skip_replies: bool) -> None:
        highest_update_id: int | None = None
        for update in updates:
            update_id = _read_int(update.get("update_id"))
            if update_id is None:
                continue
            if highest_update_id is None or update_id > highest_update_id:
                highest_update_id = update_id
            if skip_replies:
                continue
            reply = extract_reply_from_update(update, allowed_chat_id=self.config.allowed_chat_id)
            if reply is not None:
                self._queue.put(reply)
        if highest_update_id is not None:
            self._offset = highest_update_id + 1
        elif self._offset is None:
            self._offset = 0
