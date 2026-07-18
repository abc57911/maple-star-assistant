from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from maple_star.services.settings_store import TransactionalSettingsStore


class SettingsStoreAtomicityTests(unittest.TestCase):
    def test_candidate_is_not_startup_truth_until_atomic_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text('{"generation": 1}\n', encoding="utf-8")
            store = TransactionalSettingsStore(path)
            pending = store.stage_candidate("tx-1", {"generation": 2})

            self.assertEqual(store.load_committed(), {"generation": 1})
            self.assertTrue(pending.exists())

            store.commit_candidate("tx-1")

            self.assertEqual(store.load_committed(), {"generation": 2})
            self.assertFalse(pending.exists())

    def test_replace_failure_preserves_committed_file_and_pending_journal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text('{"generation": 1}\n', encoding="utf-8")
            store = TransactionalSettingsStore(path)
            pending = store.stage_candidate("tx-1", {"generation": 2})

            with patch("maple_star.services.settings_store.os.replace", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    store.commit_candidate("tx-1")

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"generation": 1})
            self.assertTrue(pending.exists())


if __name__ == "__main__":
    unittest.main()
