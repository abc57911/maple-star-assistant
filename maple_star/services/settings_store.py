from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from ..models.settings import SETTINGS_PATH, AutoPotionSettings, load_settings, save_settings


class TransactionalSettingsStore:
    def __init__(self, path: Path, *, backup_limit: int = 3) -> None:
        self.path = Path(path)
        self.backup_limit = max(0, backup_limit)

    def pending_path(self, transaction_id: str) -> Path:
        if not transaction_id or any(character in transaction_id for character in "\\/:"):
            raise ValueError("invalid transaction id")
        return self.path.with_name(f"settings.pending.{transaction_id}.json")

    def stage_candidate(self, transaction_id: str, payload: dict[str, object]) -> Path:
        pending = self.pending_path(transaction_id)
        pending.parent.mkdir(parents=True, exist_ok=True)
        rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        with pending.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        return pending

    def load_committed(self) -> dict[str, object]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("committed settings must be a mapping")
        return raw

    def commit_candidate(self, transaction_id: str) -> None:
        pending = self.pending_path(transaction_id)
        if not pending.is_file():
            raise FileNotFoundError(pending)
        raw = json.loads(pending.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("pending settings must be a mapping")
        if self.path.exists() and self.backup_limit:
            backup = self.path.with_name(f"{self.path.name}.backup.{time.time_ns()}")
            shutil.copy2(self.path, backup)
            backups = sorted(
                self.path.parent.glob(f"{self.path.name}.backup.*"),
                key=lambda item: item.stat().st_mtime_ns,
                reverse=True,
            )
            for stale in backups[self.backup_limit :]:
                stale.unlink(missing_ok=True)
        os.replace(pending, self.path)

    def discard_candidate(self, transaction_id: str) -> None:
        self.pending_path(transaction_id).unlink(missing_ok=True)

__all__ = [
    "AutoPotionSettings",
    "SETTINGS_PATH",
    "TransactionalSettingsStore",
    "load_settings",
    "save_settings",
]
