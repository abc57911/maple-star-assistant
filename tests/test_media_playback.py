from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from maple_star.constants import LIE_DETECTOR_ALERT_BEEP_PATTERN
from maple_star.services.controller_collaborator_api import ControllerModuleAdapters
from maple_star.services.media_playback import (
    LIE_DETECTOR_ALERT_SOUND_PATH,
    MediaPlaybackService,
)


class _FakeThread:
    def __init__(self, *, target, name: str, daemon: bool) -> None:
        self.target = target
        self.name = name
        self.daemon = daemon
        self.started = False
        self.alive = False

    def start(self) -> None:
        self.started = True

    def is_alive(self) -> bool:
        return self.alive


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []

    def play_media(self, path: Path, alias: str) -> None:
        self.events.append(("media", path, alias))

    def play_toggle_beep(self, pattern: tuple[tuple[int, int], ...]) -> None:
        self.events.append(("beep", pattern))


def _adapters(*, winmm: object | None = None, threads: list[_FakeThread] | None = None):
    beep = Mock()
    message_beep = Mock()
    play_sound = Mock()

    def thread_factory(**kwargs):
        thread = _FakeThread(**kwargs)
        if threads is not None:
            threads.append(thread)
        return thread

    return (
        ControllerModuleAdapters(
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
            thread_factory=thread_factory,
            winmm_provider=lambda: winmm,
            user32_provider=lambda: object(),
            beep=beep,
            message_beep=message_beep,
            play_sound=play_sound,
            key_down=lambda _vk: None,
            key_up=lambda _vk: None,
            tap_hotkey=lambda *_args, **_kwargs: None,
            save_settings=lambda *_args, **_kwargs: None,
        ),
        beep,
        message_beep,
        play_sound,
    )


class MediaPlaybackServiceTests(unittest.TestCase):
    def test_service_module_does_not_import_controller(self) -> None:
        path = Path(__file__).resolve().parents[1] / "maple_star" / "services" / "media_playback.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = "\n".join(
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        )
        self.assertNotIn("controllers", imports)

    def test_sink_routes_media_and_beep_without_winmm(self) -> None:
        threads: list[_FakeThread] = []
        adapters, beep, message_beep, play_sound = _adapters(
            winmm=None,
            threads=threads,
        )
        sink = _RecordingSink()
        service = MediaPlaybackService(adapters, sink=sink)
        path = Path("missing.mp3")
        pattern = ((440, 50),)

        self.assertTrue(service.play_media(path, "alert"))
        service.play_toggle_beep(pattern)
        service.preload()
        service.play_system_notification()
        service.play_minimap_toggle(True)
        service.start_lie_detector_alert(35)

        expected_alert = (
            ("media", LIE_DETECTOR_ALERT_SOUND_PATH, "minimap_lie_detector_alert")
            if LIE_DETECTOR_ALERT_SOUND_PATH.exists()
            else ("beep", LIE_DETECTOR_ALERT_BEEP_PATTERN)
        )
        self.assertEqual(
            sink.events,
            [("media", path, "alert"), ("beep", pattern), expected_alert],
        )
        self.assertEqual(threads, [])
        beep.assert_not_called()
        message_beep.assert_not_called()
        play_sound.assert_not_called()

    def test_local_media_reuses_open_alias(self) -> None:
        winmm = SimpleNamespace(mciSendStringW=Mock(return_value=0))
        adapters, _, _, _ = _adapters(winmm=winmm)
        service = MediaPlaybackService(adapters)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sound.mp3"
            path.write_bytes(b"test")

            self.assertTrue(service.play_media(path, "sound"))
            winmm.mciSendStringW.reset_mock()
            self.assertTrue(service.play_media(path, "sound"))

        commands = [call.args[0] for call in winmm.mciSendStringW.call_args_list]
        self.assertEqual(commands, ["stop sound", "setaudio sound volume to 200", "play sound from 0"])

    def test_play_failure_invokes_explicit_callback(self) -> None:
        adapters, _, _, _ = _adapters(winmm=None)
        service = MediaPlaybackService(adapters)
        failure = Mock()

        self.assertFalse(service.play_media(Path("missing.mp3"), "missing", on_failure=failure))

        failure.assert_called_once_with()

    def test_alert_thread_is_service_owned_and_not_duplicated(self) -> None:
        threads: list[_FakeThread] = []
        adapters, _, _, _ = _adapters(winmm=None, threads=threads)
        service = MediaPlaybackService(adapters)

        service.start_lie_detector_alert(35)
        self.assertEqual(len(threads), 1)
        self.assertIs(service.alert_thread, threads[0])
        self.assertIs(threads[0].target.__self__, service)
        self.assertTrue(threads[0].started)

        threads[0].alive = True
        service.start_lie_detector_alert(80)
        self.assertEqual(len(threads), 1)

    def test_close_is_idempotent_and_closes_each_alias_once(self) -> None:
        winmm = SimpleNamespace(mciSendStringW=Mock(return_value=0))
        adapters, _, _, _ = _adapters(winmm=winmm)
        aliases = {
            "a": (Path("a.mp3"), "mpegvideo", 200),
            "b": (Path("b.mp3"), "mpegvideo", 200),
        }
        service = MediaPlaybackService(adapters)
        service.alias_paths.update(aliases)

        service.close()
        service.close()

        commands = [call.args[0] for call in winmm.mciSendStringW.call_args_list]
        self.assertEqual(commands, ["close a", "close b"])
        self.assertEqual(service.alias_paths, {})

    def test_sink_close_never_touches_local_winmm(self) -> None:
        winmm = SimpleNamespace(mciSendStringW=Mock(return_value=0))
        adapters, _, _, _ = _adapters(winmm=winmm)
        service = MediaPlaybackService(adapters, sink=_RecordingSink())
        service.alias_paths["unexpected"] = (Path("a.mp3"), "mpegvideo", 200)

        service.close()

        winmm.mciSendStringW.assert_not_called()
        self.assertEqual(service.alias_paths, {})

    def test_beep_falls_back_to_message_beep(self) -> None:
        adapters, beep, message_beep, _ = _adapters(winmm=None)
        beep.side_effect = RuntimeError
        service = MediaPlaybackService(adapters)

        service.play_toggle_beep(((440, 50),))

        message_beep.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
