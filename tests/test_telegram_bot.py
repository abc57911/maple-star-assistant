import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from maple_star.services.telegram_bot import (
    TelegramBotConfig,
    TelegramConfigError,
    TelegramReplyListener,
    extract_reply_from_update,
    load_telegram_bot_config,
)


class TelegramBotConfigTests(unittest.TestCase):
    def test_missing_secrets_disables_configuration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(TelegramConfigError):
                load_telegram_bot_config(Path(temp_dir) / "missing.json")

    def test_invalid_token_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "telegram_bot.json"
            path.write_text(json.dumps({"bot_token": "", "allowed_chat_id": 123}), encoding="utf-8")

            with self.assertRaises(TelegramConfigError):
                load_telegram_bot_config(path)

    def test_valid_config_clamps_poll_timeout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "telegram_bot.json"
            path.write_text(
                json.dumps({"bot_token": "123:ABC", "allowed_chat_id": "456", "poll_timeout_seconds": 999}),
                encoding="utf-8",
            )

            config = load_telegram_bot_config(path)

        self.assertEqual(config.bot_token, "123:ABC")
        self.assertEqual(config.allowed_chat_id, 456)
        self.assertEqual(config.poll_timeout_seconds, 60)


class TelegramUpdateParsingTests(unittest.TestCase):
    def test_extracts_allowed_chat_text_reply(self):
        update = {
            "update_id": 10,
            "message": {
                "message_id": 22,
                "chat": {"id": 123},
                "text": " A\nB ",
            },
        }

        reply = extract_reply_from_update(update, allowed_chat_id=123, received_at=1.5)

        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertEqual(reply.update_id, 10)
        self.assertEqual(reply.chat_id, 123)
        self.assertEqual(reply.message_id, 22)
        self.assertEqual(reply.text, "A B")
        self.assertEqual(reply.received_at, 1.5)

    def test_ignores_other_chat_and_commands(self):
        other_chat = {
            "update_id": 10,
            "message": {"message_id": 22, "chat": {"id": 999}, "text": "ABC"},
        }
        command = {
            "update_id": 11,
            "message": {"message_id": 23, "chat": {"id": 123}, "text": "/start"},
        }

        self.assertIsNone(extract_reply_from_update(other_chat, allowed_chat_id=123))
        self.assertIsNone(extract_reply_from_update(command, allowed_chat_id=123))

    def test_ignores_non_text_and_overlong_text(self):
        non_text = {
            "update_id": 10,
            "message": {"message_id": 22, "chat": {"id": 123}, "photo": []},
        }
        overlong = {
            "update_id": 11,
            "message": {"message_id": 23, "chat": {"id": 123}, "text": "A" * 300},
        }

        self.assertIsNone(extract_reply_from_update(non_text, allowed_chat_id=123))
        self.assertIsNone(extract_reply_from_update(overlong, allowed_chat_id=123))


class FakeTelegramClient:
    def __init__(self, batches):
        self.batches = list(batches)
        self.calls = []
        self.sent_messages = []

    def get_updates(self, *, offset, timeout_seconds):
        self.calls.append((offset, timeout_seconds))
        if self.batches:
            return self.batches.pop(0)
        time.sleep(0.01)
        return []

    def send_message(self, *, chat_id, text):
        self.sent_messages.append((chat_id, text))


class TelegramReplyListenerTests(unittest.TestCase):
    def test_listener_skips_existing_updates_before_accepting_replies(self):
        client = FakeTelegramClient(
            [
                [
                    {
                        "update_id": 100,
                        "message": {"message_id": 1, "chat": {"id": 123}, "text": "OLD"},
                    }
                ],
                [
                    {
                        "update_id": 101,
                        "message": {"message_id": 2, "chat": {"id": 123}, "text": "NEW"},
                    }
                ],
            ]
        )
        listener = TelegramReplyListener(
            TelegramBotConfig(bot_token="token", allowed_chat_id=123, poll_timeout_seconds=1),
            client=client,
        )

        try:
            listener.start()
            deadline = time.monotonic() + 1.0
            replies = []
            while time.monotonic() < deadline:
                replies = listener.drain_replies()
                if replies:
                    break
                time.sleep(0.01)
        finally:
            listener.stop()

        self.assertEqual([reply.text for reply in replies], ["NEW"])
        self.assertEqual(client.calls[0], (None, 0))
        self.assertEqual(client.calls[1], (101, 1))

    def test_listener_stop_terminates_background_thread(self):
        wait_started = threading.Event()
        release_wait = threading.Event()

        class BlockingClient:
            def get_updates(self, *, offset, timeout_seconds):
                wait_started.set()
                release_wait.wait(1.0)
                return []

            def send_message(self, *, chat_id, text):
                pass

        listener = TelegramReplyListener(
            TelegramBotConfig(bot_token="token", allowed_chat_id=123, poll_timeout_seconds=1),
            client=BlockingClient(),
        )

        listener.start()
        self.assertTrue(wait_started.wait(1.0))
        release_wait.set()
        listener.stop()

        self.assertFalse(listener.is_running())

    def test_listener_sends_message_to_allowed_chat(self):
        client = FakeTelegramClient([])
        listener = TelegramReplyListener(
            TelegramBotConfig(bot_token="token", allowed_chat_id=123, poll_timeout_seconds=1),
            client=client,
        )

        listener.send_message("hello")

        self.assertEqual(client.sent_messages, [(123, "hello")])


if __name__ == "__main__":
    unittest.main()
