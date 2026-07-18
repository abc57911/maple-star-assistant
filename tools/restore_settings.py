from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from maple_star.services.settings_restoration import SettingsRestorationError, restore_settings


def _running_maple_star_processes() -> list[str]:
    try:
        import psutil
    except ImportError as exc:
        raise SettingsRestorationError("缺少 psutil，無法確認 MapleStar 是否已關閉") from exc
    root_text = str(PROJECT_ROOT).lower()
    matches: list[str] = []
    for process in psutil.process_iter(("pid", "cmdline")):
        try:
            command = " ".join(process.info.get("cmdline") or [])
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        lowered = command.lower()
        if root_text in lowered and ("main.py" in lowered or "main.pyw" in lowered or "run_maple_star" in lowered):
            matches.append(f"PID {process.info['pid']}: {command}")
    return matches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="安全恢復 MapleStar legacy 設定")
    parser.add_argument("--source", required=True, type=Path, help="legacy settings.json 來源")
    parser.add_argument("--target", default=PROJECT_ROOT / "settings.json", type=Path, help="目標 settings.json")
    args = parser.parse_args(argv)
    running = _running_maple_star_processes()
    if running:
        print("請先關閉 MapleStar：", file=sys.stderr)
        print("\n".join(running), file=sys.stderr)
        return 2
    try:
        result = restore_settings(args.source, args.target)
    except (OSError, SettingsRestorationError) as exc:
        print(f"設定恢復失敗：{exc}", file=sys.stderr)
        return 1
    print(f"設定恢復完成：{args.target.resolve()}")
    print(f"來源 SHA-256：{result.source_sha256}")
    print(f"目標 SHA-256：{result.target_sha256}")
    if result.backup_path is not None:
        print(f"原設定備份：{result.backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
