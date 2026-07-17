from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from maple_star.models.controller_state import ExperienceBaselineCalibration, ExperienceOcrJob
from maple_star.models.experience import ExperienceTextReading
from maple_star.services.experience_capture_coordinator import ExperienceCaptureCoordinator


class ExperienceCaptureCoordinatorTests(unittest.TestCase):
    def _job(self) -> tuple[ExperienceOcrJob, Mock]:
        cancel = Mock()
        future = SimpleNamespace(cancel=cancel)
        return ExperienceOcrJob(submitted_at=1.0, future=future), cancel

    def test_cancel_baseline_cancels_job_closes_open_ui_and_restores_cursor(self) -> None:
        coordinator = ExperienceCaptureCoordinator(Mock())
        coordinator.baseline_ocr_job, cancel = self._job()
        coordinator.baseline_calibration = ExperienceBaselineCalibration(
            phase="capture",
            attempt=1,
            started_at=1.0,
            next_step_at=2.0,
            opened_ui=True,
        )
        coordinator.baseline_cursor_position = (11, 22)
        close_ui = Mock()
        set_cursor = Mock()

        coordinator.cancel_baseline(
            close_ui=True,
            close_ui_action=close_ui,
            set_cursor=set_cursor,
        )

        cancel.assert_called_once_with()
        close_ui.assert_called_once_with()
        set_cursor.assert_called_once_with(11, 22)
        self.assertIsNone(coordinator.baseline_ocr_job)
        self.assertIsNone(coordinator.baseline_calibration)
        self.assertIsNone(coordinator.baseline_cursor_position)

    def test_cancel_checkpoint_does_not_close_ui_when_not_requested(self) -> None:
        coordinator = ExperienceCaptureCoordinator(Mock())
        coordinator.checkpoint_ocr_job, cancel = self._job()
        coordinator.checkpoint_capture = ExperienceBaselineCalibration(
            phase="capture",
            attempt=1,
            started_at=1.0,
            next_step_at=2.0,
            opened_ui=True,
        )
        close_ui = Mock()

        coordinator.cancel_checkpoint(close_ui=False, close_ui_action=close_ui)

        cancel.assert_called_once_with()
        close_ui.assert_not_called()
        self.assertIsNone(coordinator.checkpoint_ocr_job)
        self.assertIsNone(coordinator.checkpoint_capture)

    def test_cancel_baseline_finishes_cleanup_when_closing_ui_fails(self) -> None:
        coordinator = ExperienceCaptureCoordinator(Mock())
        coordinator.baseline_calibration = ExperienceBaselineCalibration(
            phase="capture",
            attempt=1,
            started_at=1.0,
            next_step_at=2.0,
            opened_ui=True,
        )
        coordinator.baseline_cursor_position = (7, 8)
        set_cursor = Mock()

        coordinator.cancel_baseline(
            close_ui=True,
            close_ui_action=Mock(side_effect=RuntimeError("close failed")),
            set_cursor=set_cursor,
        )

        set_cursor.assert_called_once_with(7, 8)
        self.assertIsNone(coordinator.baseline_calibration)

    def test_submit_and_poll_are_the_only_future_result_boundary(self) -> None:
        reading = ExperienceTextReading(current_exp=123, percent=1.5, success=True)
        future = SimpleNamespace(done=lambda: True, result=lambda: reading)
        executor = SimpleNamespace(submit=Mock(return_value=future))
        coordinator = ExperienceCaptureCoordinator(executor)

        job = coordinator.submit(
            "baseline",
            Mock(),
            "image",
            submitted_at=2.0,
            source="tooltip_baseline",
        )
        poll = coordinator.poll("baseline")

        self.assertIs(poll.job, job)
        self.assertIs(poll.reading, reading)
        self.assertEqual(poll.state, "completed")
        self.assertIsNone(coordinator.baseline_ocr_job)

    def test_signature_generation_and_repeat_gate_are_owned_by_coordinator(self) -> None:
        coordinator = ExperienceCaptureCoordinator(Mock())
        signature = coordinator.image_signature([[np.zeros((12, 30, 3), dtype=np.uint8)]])
        coordinator.last_failed_signature = signature

        self.assertEqual(
            coordinator.repeated_signature(signature, has_samples=False),
            "failed",
        )

    def test_borrowed_capture_port_is_used_but_not_closed(self) -> None:
        capture = Mock()
        capture.grab.return_value = np.zeros((4, 5, 4), dtype=np.uint8)
        coordinator = ExperienceCaptureCoordinator(Mock(), screen_capture=capture)

        image = coordinator.capture_text_image((1, 2, 5, 4))

        self.assertEqual(image.shape, (4, 5, 4))
        capture.grab.assert_called_once_with({"left": 1, "top": 2, "width": 5, "height": 4})
        coordinator.close()
        capture.close.assert_not_called()

    def test_checkpoint_eligibility_uses_owned_job_and_schedule_state(self) -> None:
        coordinator = ExperienceCaptureCoordinator(Mock())
        coordinator.next_checkpoint_at = 10.0

        self.assertFalse(
            coordinator.can_start_checkpoint(
                9.0,
                enabled=True,
                paused=False,
                hud_active=True,
                has_checkpoint=True,
            )
        )
        self.assertTrue(
            coordinator.can_start_checkpoint(
                10.0,
                enabled=True,
                paused=False,
                hud_active=True,
                has_checkpoint=True,
            )
        )

    def test_close_attempts_all_resources_and_preserves_failed_cursor_for_retry(self) -> None:
        executor = Mock()
        coordinator = ExperienceCaptureCoordinator(executor)
        coordinator.ocr_job, cancel_ocr = self._job()
        coordinator.baseline_ocr_job, cancel_baseline = self._job()
        cancel_baseline.side_effect = RuntimeError("cancel failed")
        coordinator.baseline_cursor_position = (9, 10)
        set_cursor = Mock(side_effect=RuntimeError("cursor failed"))

        with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
            coordinator.close(set_cursor=set_cursor)

        cancel_ocr.assert_called_once_with()
        executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
        self.assertEqual(coordinator.baseline_cursor_position, (9, 10))
        self.assertIsNotNone(coordinator.baseline_ocr_job)

    def test_close_cancels_all_jobs_restores_cursor_and_shuts_down_once(self) -> None:
        executor = Mock()
        coordinator = ExperienceCaptureCoordinator(executor)
        coordinator.ocr_job, cancel_ocr = self._job()
        coordinator.baseline_ocr_job, cancel_baseline = self._job()
        coordinator.checkpoint_ocr_job, cancel_checkpoint = self._job()
        coordinator.baseline_cursor_position = (3, 4)
        set_cursor = Mock()

        coordinator.close(set_cursor=set_cursor)
        coordinator.close(set_cursor=set_cursor)

        cancel_ocr.assert_called_once_with()
        cancel_baseline.assert_called_once_with()
        cancel_checkpoint.assert_called_once_with()
        set_cursor.assert_called_once_with(3, 4)
        executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)


if __name__ == "__main__":
    unittest.main()
