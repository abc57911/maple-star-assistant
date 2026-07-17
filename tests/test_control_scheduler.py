from __future__ import annotations

import unittest
import queue
from types import SimpleNamespace
from unittest.mock import patch

from maple_star.adapters.controller_worker import EVENT_RELEASE_ALL, _put_event
import maple_star.controllers.gamepad_controller as gamepad_controller
from maple_star.controllers.gamepad_controller import _minimap_next_deadline, _put_control_status

from maple_star.services.control_scheduler import (
    DeadlineTimingRecorder,
    next_absolute_deadline,
    wait_until_next_poll,
)
from maple_star.services.runtime_processes import (
    ControlCommand,
    ControlStatus,
    RuntimeProcessCoordinator,
    Shutdown,
    control_status_signature,
)


class ControlSchedulerTests(unittest.TestCase):
    def test_absolute_deadline_skips_backlog_without_drifting(self) -> None:
        self.assertAlmostEqual(next_absolute_deadline(10.0, 0.2, 10.05), 10.2)
        self.assertAlmostEqual(next_absolute_deadline(10.0, 0.2, 10.65), 10.8)

    def test_timing_snapshot_reports_p95_and_max(self) -> None:
        recorder = DeadlineTimingRecorder(max_samples=100)
        for lateness_ms in range(1, 101):
            recorder.record(10.0, 10.0 + lateness_ms / 1000.0)
        snapshot = recorder.snapshot()
        self.assertEqual(snapshot.sample_count, 100)
        self.assertAlmostEqual(snapshot.p95_lateness_ms, 95.0)
        self.assertAlmostEqual(snapshot.max_lateness_ms, 100.0)

    def test_wait_reserves_fine_window(self) -> None:
        sleeps: list[float] = []
        wait_until_next_poll(10.010, clock=lambda: 10.0, sleep=sleeps.append)
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 0.005)

    def test_status_signature_excludes_heartbeat_and_urgent_payload(self) -> None:
        first = ControlStatus(1, 10.0, "running", False, False, "--", "--", "idle")
        second = ControlStatus(
            1,
            11.0,
            "running",
            False,
            False,
            "--",
            "--",
            "idle",
            notice="urgent",
            urgent_events=("alert",),
            console_lines=("line",),
        )
        self.assertEqual(control_status_signature(first), control_status_signature(second))

    def test_required_control_command_replaces_saturated_snapshot_queue(self) -> None:
        runtime = RuntimeProcessCoordinator.__new__(RuntimeProcessCoordinator)
        runtime._control_commands = queue.Queue(maxsize=1)
        runtime._control_commands.put(ControlCommand(True, True, False))

        self.assertTrue(runtime._put_control_command(Shutdown(), required=True))
        self.assertIsInstance(runtime._control_commands.get_nowait(), Shutdown)

    def test_coalesced_control_state_is_retained_until_queue_has_capacity(self) -> None:
        runtime = RuntimeProcessCoordinator.__new__(RuntimeProcessCoordinator)
        runtime._control_commands = queue.Queue(maxsize=1)
        runtime._pending_control_settings = None
        runtime._pending_control_target = None
        runtime._pending_control_command = None
        runtime._control_commands.put_nowait(object())
        latest = ControlCommand(True, True, True, generation=7)

        runtime.send_control(latest)
        self.assertIs(runtime._pending_control_command, latest)
        runtime._control_commands.get_nowait()
        runtime._flush_pending_control_messages()

        self.assertIsNone(runtime._pending_control_command)
        self.assertIs(runtime._control_commands.get_nowait(), latest)

    def test_pending_periodic_tap_does_not_keep_original_deadline_due(self) -> None:
        runtime = SimpleNamespace(
            enabled=True,
            lie_detector_challenge_active=False,
            status="attacking",
            red_player_alert_active=False,
            next_detect_at=0.0,
            next_lie_detector_check_at=0.0,
            next_lie_detector_alert_at=0.0,
            next_red_player_check_at=0.0,
            next_red_player_alert_at=0.0,
            turn_key_up_at=0.0,
            resume_attack_at=0.0,
            pre_boundary_skill_key_up_at=0.0,
            stationary_skill_key_up_at=0.0,
            stationary_skill_post_delay_until=0.0,
            stationary_tracking_delay_until=0.0,
            foreground_resume_at=0.0,
            periodic_key_next_at={1: 10.0},
            periodic_key_pending_taps={1: (65, 10.05, 2.0)},
        )
        self.assertEqual(_minimap_next_deadline(runtime), 10.05)

    def test_controller_queue_saturation_collapses_to_release_all(self) -> None:
        events: queue.Queue = queue.Queue(maxsize=1)
        events.put_nowait(("button_down", 1, None))
        _put_event(events, ("button_up", 1, None))
        event_type, _value, message = events.get_nowait()
        self.assertEqual(event_type, EVENT_RELEASE_ALL)
        self.assertIn("釋放", message)

    def test_urgent_status_replacement_preserves_queued_payloads(self) -> None:
        statuses: queue.Queue = queue.Queue(maxsize=1)
        statuses.put_nowait(
            ControlStatus(
                1,
                10.0,
                "running",
                True,
                False,
                "--",
                "--",
                "old",
                notice="舊通知",
                urgent_events=("red_player_detected",),
                console_lines=("old log\n",),
            )
        )
        current = ControlStatus(
            1,
            11.0,
            "running",
            True,
            False,
            "--",
            "--",
            "new",
            urgent_events=("red_player_alert",),
            console_lines=("new log\n",),
        )

        self.assertTrue(_put_control_status(statuses, current, required=True))
        merged = statuses.get_nowait()
        self.assertEqual(merged.notice, "舊通知")
        self.assertEqual(merged.urgent_events, ("red_player_detected", "red_player_alert"))
        self.assertIn("old log", "".join(merged.console_lines))
        self.assertIn("new log", "".join(merged.console_lines))

    def test_benchmark_input_sink_blocks_tap_key_send(self) -> None:
        previous = gamepad_controller.BENCHMARK_INPUT_SINK_ACTIVE
        gamepad_controller.BENCHMARK_INPUT_SINK_ACTIVE = True
        try:
            with patch.object(gamepad_controller, "send_tap_key") as send:
                gamepad_controller.tracked_tap_key(0x43)
            send.assert_not_called()
        finally:
            gamepad_controller.BENCHMARK_INPUT_SINK_ACTIVE = previous


if __name__ == "__main__":
    unittest.main()
