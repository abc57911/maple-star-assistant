from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maple_star.backend.settings_transactions import SettingsTransactionCoordinator
from maple_star.services.settings_store import TransactionalSettingsStore


class _Worker:
    def __init__(self, *, reject: str | None = None) -> None:
        self.reject = reject
        self.calls: list[str] = []

    def prepare(self, transaction_id: str, payload: dict[str, object]) -> bool:
        self.calls.append("prepare")
        return self.reject != "prepare"

    def stage(self, transaction_id: str, payload: dict[str, object]) -> bool:
        self.calls.append("stage")
        return self.reject != "stage"

    def activate(self, transaction_id: str) -> bool:
        self.calls.append("activate")
        return self.reject != "activate"

    def abort(self, transaction_id: str) -> None:
        self.calls.append("abort")


class SettingsTransactionTests(unittest.TestCase):
    def test_prepare_rejection_never_writes_pending_or_committed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text('{"generation": 1}\n', encoding="utf-8")
            worker = _Worker(reject="prepare")
            coordinator = SettingsTransactionCoordinator(TransactionalSettingsStore(path), [worker])

            result = coordinator.apply("tx", {"generation": 2})

            self.assertFalse(result.committed)
            self.assertEqual(result.phase, "prepare")
            self.assertEqual(worker.calls, ["prepare", "abort"])
            self.assertFalse((Path(directory) / "settings.pending.tx.json").exists())

    def test_stage_rejection_aborts_all_workers_and_preserves_committed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text('{"generation": 1}\n', encoding="utf-8")
            first = _Worker()
            second = _Worker(reject="stage")
            coordinator = SettingsTransactionCoordinator(TransactionalSettingsStore(path), [first, second])

            result = coordinator.apply("tx", {"generation": 2})

            self.assertFalse(result.committed)
            self.assertEqual(result.phase, "stage")
            self.assertIn("abort", first.calls)
            self.assertEqual(TransactionalSettingsStore(path).load_committed(), {"generation": 1})

    def test_activation_failure_reports_committed_truth_for_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text('{"generation": 1}\n', encoding="utf-8")
            worker = _Worker(reject="activate")
            coordinator = SettingsTransactionCoordinator(TransactionalSettingsStore(path), [worker])

            result = coordinator.apply("tx", {"generation": 2})

            self.assertTrue(result.committed)
            self.assertFalse(result.activated)
            self.assertEqual(result.phase, "activate")
            self.assertEqual(TransactionalSettingsStore(path).load_committed(), {"generation": 2})


if __name__ == "__main__":
    unittest.main()
