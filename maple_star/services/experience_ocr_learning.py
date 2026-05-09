from __future__ import annotations

import importlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from ..models.experience import (
    _encode_experience_pixel_font_template,
    _experience_pixel_font_templates_from_fixture,
    experience_ocr_learning_pending_dir,
)
from ..models import experience as experience_model


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "experience_ocr"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"
TEMPLATE_MODULE_PATH = ROOT / "maple_star" / "models" / "experience_pixel_templates.py"
PROMOTED_TEXT_RE = re.compile(r"([0-9]+)\[((?:[0-9]{1,2}|100)\.[0-9]{2})%\]")


def list_experience_ocr_learning_cases() -> list[dict[str, Any]]:
    pending_dir = experience_ocr_learning_pending_dir()
    if not pending_dir.exists():
        return []
    cases = []
    for metadata_path in sorted(pending_dir.glob("*/metadata.json")):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception as exc:
            cases.append(
                {
                    "id": metadata_path.parent.name,
                    "metadata_path": metadata_path,
                    "error": str(exc),
                }
            )
            continue
        final = metadata.get("final_reading") or {}
        pixel = metadata.get("pixel_reading") or {}
        paddle = metadata.get("paddle_reading") or {}
        if _is_resolved_non_actionable_learning_case(metadata):
            continue
        reading_key = str(metadata.get("reading_key") or _metadata_reading_key(metadata) or "")
        reading_source = _find_candidate_source(metadata, reading_key) if reading_key else None
        preview_file = _first_existing_preview(metadata_path.parent, metadata)
        source_warning = ""
        if reading_key and reading_source is None:
            source_warning = "預設 OCR 文字未綁定到此 case 的任何候選影像，請依預覽圖手動輸入正確值"
        cases.append(
            {
                "id": metadata_path.parent.name,
                "metadata_path": metadata_path,
                "case_dir": metadata_path.parent,
                "created_at": metadata.get("created_at", ""),
                "trigger": metadata.get("trigger", "--"),
                "final_text": final.get("text", ""),
                "final_reason": final.get("reason", "--"),
                "final_success": bool(final.get("success")),
                "pixel_text": pixel.get("text", ""),
                "pixel_reason": pixel.get("reason", "--"),
                "paddle_text": paddle.get("text", ""),
                "paddle_reason": paddle.get("reason", "--"),
                "reading_key": reading_key,
                "default_correct_text": reading_key if reading_source is not None else "",
                "source_warning": source_warning,
                "preview_file": preview_file,
                "metadata": metadata,
            }
        )
    return sorted(cases, key=lambda item: (str(item.get("created_at", "")), str(item.get("id", ""))))


def promote_experience_ocr_learning_case(
    case_id: str,
    text: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    compact = text.strip().replace(" ", "")
    match = PROMOTED_TEXT_RE.fullmatch(compact)
    if match is None:
        raise ValueError("text must look like 2043879[10.75%]")

    case_dir = _pending_case_dir(case_id)
    metadata_path = case_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"pending case not found: {case_id}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    source_file = _promotion_source_file(case_dir, metadata, compact)
    if not source_file.exists():
        raise FileNotFoundError(f"ROI file missing: {source_file}")

    exp_value = int(match.group(1))
    percent_text = match.group(2)
    percent_slug = percent_text.replace(".", "")
    sample_id = f"{case_id}_ocr_{exp_value}_{percent_slug}"
    target_name = f"{sample_id}.png"
    target_path = FIXTURE_DIR / target_name
    if target_path.exists() and not force:
        raise FileExistsError(f"fixture already exists: {target_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, target_path)

    manifest = _load_manifest()
    samples = manifest.setdefault("samples", [])
    previous_samples = [
        sample
        for sample in samples
        if sample.get("id") == sample_id
        or str(sample.get("id") or "").startswith(f"{case_id}_ocr_")
    ]
    for sample in previous_samples:
        previous_file = sample.get("file")
        if isinstance(previous_file, str):
            previous_path = FIXTURE_DIR / previous_file
            if previous_path.exists() and previous_path != target_path:
                previous_path.unlink()
    samples[:] = [
        sample
        for sample in samples
        if sample.get("id") != sample_id
        and not str(sample.get("id") or "").startswith(f"{case_id}_ocr_")
    ]
    samples.append(
        {
            "id": sample_id,
            "file": target_name,
            "current_exp": exp_value,
            "percent": float(percent_text),
            "text": compact,
        }
    )
    _write_manifest(manifest)
    return {
        "sample_id": sample_id,
        "target_path": target_path,
        "text": compact,
    }


def _is_resolved_non_actionable_learning_case(metadata: dict[str, Any]) -> bool:
    trigger = str(metadata.get("trigger") or "")
    if trigger not in {"pixel_to_paddle_fallback", "tracker_rejection"}:
        return False
    final = metadata.get("final_reading") or {}
    return bool(final.get("success"))


def validate_promoted_experience_fixture(sample_id: str) -> dict[str, Any]:
    manifest = _load_manifest()
    sample = next(
        (item for item in manifest.get("samples", []) if str(item.get("id") or "") == sample_id),
        None,
    )
    if sample is None:
        return {"success": False, "reason": f"fixture not found: {sample_id}"}

    reading = _read_fixture_sample_with_pixel(sample)
    if reading is None:
        return {"success": False, "reason": "fixture image missing or unreadable"}

    expected_exp = int(sample.get("current_exp"))
    expected_percent = round(float(sample.get("percent")), 2)
    success = (
        reading.success
        and reading.current_exp == expected_exp
        and reading.percent is not None
        and round(reading.percent, 2) == expected_percent
    )
    return {
        "success": success,
        "text": reading.text,
        "confidence": reading.confidence,
        "reason": reading.reason,
        "current_exp": reading.current_exp,
        "percent": reading.percent,
    }


def remove_experience_ocr_fixture_sample(sample_id: str) -> bool:
    manifest = _load_manifest()
    samples = manifest.get("samples", [])
    removed = [sample for sample in samples if str(sample.get("id") or "") == sample_id]
    if not removed:
        return False
    for sample in removed:
        file_name = sample.get("file")
        if isinstance(file_name, str):
            file_path = FIXTURE_DIR / file_name
            if file_path.exists():
                file_path.unlink()
    manifest["samples"] = [sample for sample in samples if str(sample.get("id") or "") != sample_id]
    _write_manifest(manifest)
    return True


def regen_experience_pixel_templates() -> dict[str, Any]:
    templates = _experience_pixel_font_templates_from_fixture(FIXTURE_DIR)
    encoded = {
        character: [_encode_experience_pixel_font_template(template) for template in character_templates]
        for character, character_templates in sorted(templates.items())
    }
    body = (
        "from __future__ import annotations\n\n"
        "# Generated by tools/experience_ocr_learning.py regen-templates.\n"
        "# Values are 48x32 boolean glyph templates encoded as rows separated by \"/\".\n"
        f"TEMPLATES: dict[str, list[str]] = {json.dumps(encoded, ensure_ascii=False, indent=2)}\n"
    )
    TEMPLATE_MODULE_PATH.write_text(body, encoding="utf-8")
    _reload_runtime_experience_pixel_templates()
    return {
        "template_path": TEMPLATE_MODULE_PATH,
        "template_count": sum(len(items) for items in encoded.values()),
    }


def delete_experience_ocr_learning_case(case_id: str) -> bool:
    case_dir = _pending_case_dir(case_id)
    if not case_dir.exists():
        return False
    shutil.rmtree(case_dir)
    return True


def dedupe_experience_ocr_learning_cases(*, delete: bool = True) -> list[dict[str, str]]:
    seen_exact: dict[str, str] = {}
    seen_reading: dict[tuple[str, str], str] = {}
    duplicates: list[dict[str, str]] = []
    for case in list_experience_ocr_learning_cases():
        metadata = case.get("metadata") or {}
        dedupe_key = str(metadata.get("dedupe_key") or "")
        reading_key = (
            str(metadata.get("reading_key") or _metadata_reading_key(metadata) or case.get("final_text") or ""),
            str(metadata.get("trigger") or case.get("trigger") or ""),
        )
        if not dedupe_key and not any(reading_key):
            continue
        case_id = str(case.get("id", ""))
        original_id = seen_exact.get(dedupe_key) if dedupe_key else None
        if original_id is None and any(reading_key):
            original_id = seen_reading.get(reading_key)
        if original_id is None:
            if dedupe_key:
                seen_exact[dedupe_key] = case_id
            if any(reading_key):
                seen_reading[reading_key] = case_id
            continue
        duplicates.append({"id": case_id, "duplicate_of": original_id})
        if delete:
            delete_experience_ocr_learning_case(case_id)
    return duplicates


def delete_experience_ocr_learning_cases_by_reading_key(reading_key: str) -> list[str]:
    deleted: list[str] = []
    normalized_key = reading_key.strip().replace(" ", "")
    for case in list_experience_ocr_learning_cases():
        metadata = case.get("metadata") or {}
        case_key = str(metadata.get("reading_key") or _metadata_reading_key(metadata) or "")
        if case_key != normalized_key:
            continue
        case_id = str(case.get("id", ""))
        if delete_experience_ocr_learning_case(case_id):
            deleted.append(case_id)
    return deleted


def dedupe_experience_ocr_fixtures_by_text(*, delete: bool = True) -> list[dict[str, str]]:
    manifest = _load_manifest()
    samples = manifest.get("samples", [])
    grouped: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        text = str(sample.get("text") or "")
        grouped.setdefault(text, []).append(sample)

    removed: list[dict[str, str]] = []
    kept_ids: set[str] = set()
    for text, group in grouped.items():
        if len(group) <= 1:
            kept_ids.update(str(sample.get("id")) for sample in group)
            continue
        keep = _select_fixture_to_keep(group)
        keep_id = str(keep.get("id"))
        kept_ids.add(keep_id)
        for sample in group:
            sample_id = str(sample.get("id"))
            if sample_id == keep_id:
                continue
            removed.append({"id": sample_id, "duplicate_of": keep_id, "text": text})
            if delete:
                file_name = sample.get("file")
                if isinstance(file_name, str):
                    file_path = FIXTURE_DIR / file_name
                    if file_path.exists():
                        file_path.unlink()

    if delete and removed:
        manifest["samples"] = [sample for sample in samples if str(sample.get("id")) in kept_ids]
        _write_manifest(manifest)
    return removed


def dedupe_experience_ocr_fixtures_by_case_prefix(*, delete: bool = True) -> list[dict[str, str]]:
    manifest = _load_manifest()
    samples = manifest.get("samples", [])
    grouped: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        sample_id = str(sample.get("id") or "")
        if "_ocr_" not in sample_id:
            continue
        grouped.setdefault(sample_id.split("_ocr_", 1)[0], []).append(sample)

    removed: list[dict[str, str]] = []
    remove_ids: set[str] = set()
    for _prefix, group in grouped.items():
        if len(group) <= 1:
            continue
        keep = group[-1]
        keep_id = str(keep.get("id") or "")
        for sample in group[:-1]:
            sample_id = str(sample.get("id") or "")
            removed.append(
                {
                    "id": sample_id,
                    "duplicate_of": keep_id,
                    "text": str(sample.get("text") or ""),
                }
            )
            remove_ids.add(sample_id)
            if delete:
                file_name = sample.get("file")
                if isinstance(file_name, str):
                    file_path = FIXTURE_DIR / file_name
                    if file_path.exists():
                        file_path.unlink()

    if delete and remove_ids:
        manifest["samples"] = [sample for sample in samples if str(sample.get("id") or "") not in remove_ids]
        _write_manifest(manifest)
    return removed


def _load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _metadata_reading_key(metadata: dict[str, Any]) -> str:
    for name in ("final_reading", "paddle_reading", "pixel_reading"):
        reading = metadata.get(name) or {}
        current_exp = reading.get("current_exp")
        percent = reading.get("percent")
        if current_exp is not None and percent is not None:
            try:
                return f"{int(current_exp)}[{float(percent):.2f}%]"
            except (TypeError, ValueError):
                pass
        text = str(reading.get("text") or "").strip().replace(" ", "")
        if text:
            return text
    return ""


def _write_manifest(manifest: dict[str, Any]) -> None:
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _reload_runtime_experience_pixel_templates() -> None:
    try:
        from ..models import experience_pixel_templates

        importlib.reload(experience_pixel_templates)
    except Exception:
        pass
    experience_model._EXPERIENCE_PIXEL_FONT_TEMPLATE_CACHE = None


def _select_fixture_to_keep(samples: list[dict[str, Any]]) -> dict[str, Any]:
    for sample in samples:
        if _fixture_sample_pixel_succeeds(sample):
            return sample
    return samples[0]


def _fixture_sample_pixel_succeeds(sample: dict[str, Any]) -> bool:
    reading = _read_fixture_sample_with_pixel(sample)
    if reading is None:
        return False
    try:
        return (
            reading.success
            and reading.current_exp == int(sample.get("current_exp"))
            and reading.percent is not None
            and round(reading.percent, 2) == round(float(sample.get("percent")), 2)
        )
    except Exception:
        return False


def _read_fixture_sample_with_pixel(sample: dict[str, Any]) -> Any | None:
    try:
        import cv2

        image = cv2.imread(str(FIXTURE_DIR / str(sample.get("file"))), cv2.IMREAD_UNCHANGED)
        if image is None:
            return None
        ocr_image = experience_model.ExperienceOcrImage(image=image, source_id=str(sample.get("id") or ""))
        bar_percent = experience_model.estimate_experience_bar_percent(
            image,
            bar_crop_left_ratio=ocr_image.bar_crop_left_ratio,
        )
        return experience_model._read_experience_pixel_font_adaptive(ocr_image, bar_percent=bar_percent)
    except Exception:
        return None


def _pending_case_dir(case_id: str) -> Path:
    pending_dir = experience_ocr_learning_pending_dir()
    case_dir = pending_dir / case_id
    resolved_pending = pending_dir.resolve()
    resolved_case = case_dir.resolve(strict=False)
    if resolved_pending != resolved_case and resolved_pending not in resolved_case.parents:
        raise ValueError(f"invalid pending case id: {case_id}")
    return case_dir


def _first_existing_preview(case_dir: Path, metadata: dict[str, Any]) -> Path | None:
    reading_key = str(metadata.get("reading_key") or _metadata_reading_key(metadata) or "")
    source = _find_candidate_source(metadata, reading_key) if reading_key else None
    if source is not None:
        _source_name, preview_name = source
        if isinstance(preview_name, str) and (case_dir / preview_name).exists():
            return case_dir / preview_name

    frames = metadata.get("frames") or []
    for frame in frames:
        for roi in frame:
            filename = roi.get("file")
            if isinstance(filename, str) and (case_dir / filename).exists():
                return case_dir / filename
    return None


def _promotion_source_file(case_dir: Path, metadata: dict[str, Any], compact_text: str) -> Path:
    frames = metadata.get("frames") or []
    if not frames or not frames[0]:
        raise ValueError("pending case has no ROI frame")
    source = _find_candidate_source(metadata, compact_text)
    if source is not None:
        source_name, _preview_name = source
        return case_dir / source_name

    metadata_key = str(metadata.get("reading_key") or _metadata_reading_key(metadata) or "")
    if metadata_key and compact_text == metadata_key:
        raise ValueError(
            "default OCR text is not tied to a saved OCR candidate; "
            "enter the correct value shown in the preview image instead"
        )

    source_name = frames[0][0]["file"]
    return case_dir / source_name


def _find_candidate_source(metadata: dict[str, Any], compact_text: str) -> tuple[str, str] | None:
    if not compact_text:
        return None
    frames = metadata.get("frames") or []
    for frame in frames:
        for roi in frame:
            preview_name = roi.get("file")
            for attempt in roi.get("attempts") or []:
                candidates = attempt.get("candidates") or []
                if any(str(candidate.get("text") or "") == compact_text for candidate in candidates):
                    source_name = attempt.get("file") or preview_name
                    if isinstance(source_name, str) and isinstance(preview_name, str):
                        return source_name, preview_name
    return None
