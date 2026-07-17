from __future__ import annotations

import multiprocessing as mp
import unittest
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from maple_star.models.experience_types import ExperienceOcrImage, ExperienceTextReading
from maple_star.services import experience_paddle_reader


class _FakeSpawnReader:
    def __init__(self) -> None:
        self.calls = 0

    def _reading(self, source: str) -> ExperienceTextReading:
        self.calls += 1
        return ExperienceTextReading(
            current_exp=self.calls,
            percent=float(self.calls),
            success=True,
            source=source,
        )

    def read_burst_frames(self, image_frames, *, continuity_hint=None) -> ExperienceTextReading:
        return self._reading("burst")

    def read_stat_window_exp(self, image) -> ExperienceTextReading:
        return self._reading("stat_window")

    def read_tooltip_exp(self, image, *, continuity_hint=None) -> ExperienceTextReading:
        return self._reading("tooltip")


def _install_fake_spawn_reader() -> None:
    experience_paddle_reader.PaddleExperienceTextReader = _FakeSpawnReader
    experience_paddle_reader._EXPERIENCE_WORKER_READER = None


class ExperienceWorkerSpawnTests(unittest.TestCase):
    def test_worker_entries_are_owned_by_canonical_module(self) -> None:
        expected = "maple_star.services.experience_paddle_reader"
        self.assertEqual(experience_paddle_reader.read_experience_burst_frames_in_worker.__module__, expected)
        self.assertEqual(experience_paddle_reader.read_stat_window_exp_in_worker.__module__, expected)
        self.assertEqual(experience_paddle_reader.read_experience_tooltip_in_worker.__module__, expected)

    def test_spawned_worker_returns_leaf_dataclass_and_reuses_child_reader(self) -> None:
        self.assertIsNone(experience_paddle_reader._EXPERIENCE_WORKER_READER)
        context = mp.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=1,
            mp_context=context,
            initializer=_install_fake_spawn_reader,
        ) as executor:
            burst = executor.submit(
                experience_paddle_reader.read_experience_burst_frames_in_worker,
                [],
            ).result(timeout=30)
            tooltip = executor.submit(
                experience_paddle_reader.read_experience_tooltip_in_worker,
                ExperienceOcrImage(np.zeros((1, 1, 4), dtype=np.uint8)),
            ).result(timeout=30)

        self.assertIs(type(burst), ExperienceTextReading)
        self.assertIs(type(tooltip), ExperienceTextReading)
        self.assertEqual((burst.current_exp, burst.source), (1, "burst"))
        self.assertEqual((tooltip.current_exp, tooltip.source), (2, "tooltip"))
        self.assertIsNone(experience_paddle_reader._EXPERIENCE_WORKER_READER)


if __name__ == "__main__":
    unittest.main()
