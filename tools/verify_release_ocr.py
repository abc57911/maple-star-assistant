from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "experience_ocr" / "live_20260502_010734_001.png"
EXPECTED_CURRENT_EXP = 3796880
EXPECTED_PERCENT = 99.08
REQUIRED_PADDLEX_MODELS = (
    "PP-OCRv5_mobile_det",
    "PP-OCRv5_mobile_rec",
)
REQUIRED_MODEL_FILES = (
    "config.json",
    "inference.json",
    "inference.pdiparams",
    "inference.yml",
)


def _validate_marker(marker: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if marker.get("backend") != "paddle":
        errors.append("backend 不是 paddle")
    if marker.get("initialization") is not True:
        errors.append("PaddleOCR 未完成初始化")
    if marker.get("paddle_predict_executed") is not True:
        errors.append("未實際執行 Paddle predict")
    if marker.get("success") is not True:
        errors.append("smoke marker 未成功")
    reading = marker.get("reading")
    if not isinstance(reading, dict):
        errors.append("缺少 reading")
        return errors
    if reading.get("current_exp") != EXPECTED_CURRENT_EXP:
        errors.append(f"current_exp 不符：{reading.get('current_exp')!r}")
    percent = reading.get("percent")
    if not isinstance(percent, (int, float)) or round(float(percent), 2) != EXPECTED_PERCENT:
        errors.append(f"percent 不符：{percent!r}")
    return errors


def _validate_paddlex_model_cache(environment: dict[str, str]) -> Path:
    configured_root = environment.get("PADDLE_PDX_CACHE_HOME", "").strip()
    cache_root = Path(configured_root).expanduser() if configured_root else Path.home() / ".paddlex"
    models_root = cache_root / "official_models"
    missing: list[str] = []
    for model_name in REQUIRED_PADDLEX_MODELS:
        model_root = models_root / model_name
        for filename in REQUIRED_MODEL_FILES:
            path = model_root / filename
            if not path.is_file() or path.stat().st_size <= 0:
                missing.append(str(path))
    if missing:
        raise RuntimeError(
            "release OCR smoke 禁止下載模型；請先在 source venv 完成 PaddleOCR warm-up。缺少：\n"
            + "\n".join(missing)
        )
    return cache_root.resolve()


def _read_failure_diagnostics(extraction_dir: Path, marker_path: Path) -> str:
    sections: list[str] = []
    for label, path in (
        ("marker", marker_path),
        ("startup_error.log", extraction_dir / "startup_error.log"),
    ):
        if path.is_file():
            sections.append(f"[{label}]\n{path.read_text(encoding='utf-8', errors='replace')}")
    return "\n".join(sections) or "沒有可用的 marker/startup_error.log"


def verify_release_ocr(zip_path: Path, fixture_path: Path, timeout_seconds: float = 120.0) -> None:
    if not zip_path.is_file():
        raise FileNotFoundError(f"找不到 release ZIP：{zip_path}")
    if not fixture_path.is_file():
        raise FileNotFoundError(f"找不到 OCR fixture：{fixture_path}")
    environment = os.environ.copy()
    cache_root = _validate_paddlex_model_cache(environment)
    with tempfile.TemporaryDirectory(prefix="maple-star-release-smoke-") as temporary_directory:
        extraction_dir = Path(temporary_directory)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(extraction_dir)
        executable = extraction_dir / "MapleStar.exe"
        marker_path = extraction_dir / "ocr-smoke-result.json"
        if not executable.is_file():
            raise FileNotFoundError("release ZIP 缺少 MapleStar.exe")
        environment.update(
            {
                "MAPLE_STAR_RELEASE_OCR_SMOKE_IMAGE": str(fixture_path.resolve()),
                "MAPLE_STAR_RELEASE_OCR_SMOKE_OUTPUT": str(marker_path),
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "MODELSCOPE_OFFLINE": "1",
                "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "1",
                "PADDLE_PDX_MODEL_SOURCE": "huggingface",
                "PADDLE_PDX_CACHE_HOME": str(cache_root),
                "HF_ENDPOINT": "http://127.0.0.1:9",
                "PADDLE_PDX_HUGGING_FACE_ENDPOINT": "http://127.0.0.1:9",
                "HTTP_PROXY": "http://127.0.0.1:9",
                "HTTPS_PROXY": "http://127.0.0.1:9",
                "ALL_PROXY": "http://127.0.0.1:9",
                "http_proxy": "http://127.0.0.1:9",
                "https_proxy": "http://127.0.0.1:9",
                "all_proxy": "http://127.0.0.1:9",
                "NO_PROXY": "127.0.0.1,localhost",
                "no_proxy": "127.0.0.1,localhost",
            }
        )
        try:
            result = subprocess.run(
                [str(executable)],
                cwd=extraction_dir,
                env=environment,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            diagnostics = _read_failure_diagnostics(extraction_dir, marker_path)
            raise RuntimeError(
                f"release OCR smoke 超過 {timeout_seconds:g} 秒；暫存目錄清理前診斷：\n{diagnostics}"
            ) from exc
        if not marker_path.is_file():
            diagnostics = _read_failure_diagnostics(extraction_dir, marker_path)
            raise RuntimeError(
                f"OCR smoke marker 未建立；exit={result.returncode}\nstdout={result.stdout}\n"
                f"stderr={result.stderr}\n{diagnostics}"
            )
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        errors = _validate_marker(marker)
        if result.returncode != 0:
            errors.append(f"MapleStar.exe exit={result.returncode}")
        if errors:
            detail = json.dumps(marker, ensure_ascii=False, indent=2)
            raise RuntimeError("；".join(errors) + f"\n{detail}")
        print(json.dumps(marker, ensure_ascii=False, indent=2))


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="驗證 MapleStar release artifact 的 PaddleOCR predict")
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    verify_release_ocr(args.zip_path, args.fixture, args.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
