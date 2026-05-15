from __future__ import annotations

import importlib
import hashlib
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
AUTO_PROMOTE_MIN_CONFIDENCE = 0.965
AUTO_PROMOTE_MIN_CONFIDENCE_GAP = 0.006
AUTO_PROMOTE_MIN_MATCHING_ATTEMPTS = 2
AUTO_PROMOTE_STRONG_ATTEMPT_MIN_CONFIDENCE = 0.93
AUTO_PROMOTE_STRONG_ATTEMPT_MIN_CONFIDENCE_GAP = 0.02
AUTO_PROMOTE_STRONG_ATTEMPT_MIN_MATCHING_ATTEMPTS = 4
REVIEW_ACTION_AUTO_PROMOTE = "auto_promote"
REVIEW_ACTION_MANUAL_REVIEW = "manual_review"
REVIEW_ACTION_DIAGNOSTIC_ONLY = "diagnostic_only"
REVIEW_ACTION_DELETE_RECOMMENDED = "delete_recommended"
FALSE_POSITIVE_REVIEW_TRIGGERS = {"tracker_rejected", "ocr_continuity_rejected"}
REVIEW_ACTION_SORT_PRIORITY = {
    REVIEW_ACTION_AUTO_PROMOTE: 0,
    REVIEW_ACTION_MANUAL_REVIEW: 1,
    REVIEW_ACTION_DIAGNOSTIC_ONLY: 2,
    REVIEW_ACTION_DELETE_RECOMMENDED: 3,
}


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
        candidate_stats = _learning_case_candidate_stats(metadata, reading_key)
        auto_decision: dict[str, Any] = {"promotable": False, "skip_reason": "尚未評估"}
        case_item = {
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
            "top_candidates": candidate_stats["top_candidates"],
            "confidence_gap": candidate_stats["confidence_gap"],
            "candidate_match_count": candidate_stats["matching_attempts"],
            "top_candidate_text": candidate_stats["top_text"],
            "top_candidate_confidence": candidate_stats["top_confidence"],
            "glyph_ambiguities": candidate_stats["glyph_ambiguities"],
            "glyph_ambiguity_count": candidate_stats["glyph_ambiguity_count"],
        }
        auto_decision = _auto_promote_decision(case_item, str(case_item["default_correct_text"]))
        case_item["auto_promote_decision"] = auto_decision
        case_item["auto_promote_skip_reason"] = auto_decision["skip_reason"]
        case_item["auto_promote_promotable"] = bool(auto_decision["promotable"])
        review = _learning_case_review(case_item)
        case_item.update(review)
        cases.append(case_item)
    cases = sorted(cases, key=_learning_case_sort_key)
    _attach_learning_case_groups(cases)
    return cases


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
    bar_crop_left_ratio = _promotion_source_bar_crop_left_ratio(metadata, compact)
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
            "paddle_fallback": False,
            "bar_crop_left_ratio": bar_crop_left_ratio,
        }
    )
    _write_manifest(manifest)
    return {
        "sample_id": sample_id,
        "target_path": target_path,
        "text": compact,
    }


def auto_promote_experience_ocr_learning_cases(*, dry_run: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "dry_run": dry_run,
        "promotable": [],
        "promoted": [],
        "skipped": [],
        "rolled_back": [],
        "template_count": None,
    }
    for case in list_experience_ocr_learning_cases():
        case_id = str(case.get("id") or "")
        text = str(case.get("default_correct_text") or "").strip()
        decision = _auto_promote_decision(case, text)
        if not decision["promotable"]:
            result["skipped"].append({"id": case_id, "reason": decision["skip_reason"], "decision": decision})
            continue
        if dry_run:
            result["promotable"].append({"id": case_id, "text": text, "decision": decision})
            continue

        try:
            promoted = promote_experience_ocr_learning_case(case_id, text, force=True)
            regen = regen_experience_pixel_templates()
            validation = validate_promoted_experience_fixture(str(promoted["sample_id"]))
        except Exception as exc:
            result["skipped"].append({"id": case_id, "reason": f"套用失敗：{exc}"})
            continue

        if validation.get("success"):
            deleted_ids = set(delete_experience_ocr_learning_cases_by_reading_key(str(promoted["text"])))
            if delete_experience_ocr_learning_case(case_id):
                deleted_ids.add(case_id)
            result["template_count"] = regen["template_count"]
            result["promoted"].append(
                {
                    "id": case_id,
                    "sample_id": promoted["sample_id"],
                    "text": promoted["text"],
                    "deleted_count": len(deleted_ids),
                }
            )
            continue

        record_experience_ocr_learning_validation_failure(
            case_id,
            sample_id=str(promoted["sample_id"]),
            text=str(promoted["text"]),
            validation=validation,
        )
        remove_experience_ocr_fixture_sample(str(promoted["sample_id"]))
        regen = regen_experience_pixel_templates()
        result["template_count"] = regen["template_count"]
        result["rolled_back"].append(
            {
                "id": case_id,
                "sample_id": promoted["sample_id"],
                "text": promoted["text"],
                "reason": validation.get("reason") or "Pixel validation failed",
                "read_text": validation.get("text") or "",
            }
        )
    return result


def record_experience_ocr_learning_validation_failure(
    case_id: str,
    *,
    sample_id: str,
    text: str,
    validation: dict[str, Any],
) -> bool:
    metadata_path = _pending_case_dir(case_id) / "metadata.json"
    if not metadata_path.exists():
        return False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    metadata["last_promotion_validation"] = {
        "success": False,
        "sample_id": sample_id,
        "text": text,
        "read_text": validation.get("text") or "",
        "reason": validation.get("reason") or "Pixel validation failed",
        "confidence": validation.get("confidence"),
        "current_exp": validation.get("current_exp"),
        "percent": validation.get("percent"),
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def delete_recommended_experience_ocr_learning_cases(*, dry_run: bool = False) -> list[dict[str, str]]:
    deleted: list[dict[str, str]] = []
    for case in list_experience_ocr_learning_cases():
        if case.get("review_action") != REVIEW_ACTION_DELETE_RECOMMENDED:
            continue
        case_id = str(case.get("id") or "")
        item = {
            "id": case_id,
            "reason": str(case.get("review_reason") or ""),
        }
        deleted.append(item)
        if not dry_run:
            delete_experience_ocr_learning_case(case_id)
    return deleted


def _auto_promote_skip_reason(case: dict[str, Any], text: str) -> str:
    return str(_auto_promote_decision(case, text)["skip_reason"])


def _learning_case_review(case: dict[str, Any]) -> dict[str, str]:
    if case.get("error"):
        return {
            "review_action": REVIEW_ACTION_MANUAL_REVIEW,
            "review_label": "需人工確認",
            "review_reason": f"metadata unreadable: {case['error']}",
        }
    metadata = case.get("metadata") or {}
    validation = metadata.get("last_promotion_validation") or {}
    if validation and validation.get("success") is False:
        reason = str(validation.get("reason") or "Pixel validation failed")
        return {
            "review_action": REVIEW_ACTION_DELETE_RECOMMENDED,
            "review_label": "建議刪除",
            "review_reason": f"套用後 Pixel validation 仍失敗，不適合作為 template case：{reason}",
        }
    if case.get("auto_promote_promotable"):
        return {
            "review_action": REVIEW_ACTION_AUTO_PROMOTE,
            "review_label": "可自動套用",
            "review_reason": "符合保守自動套用條件",
        }

    auto_reason = str(case.get("auto_promote_skip_reason") or "")
    final_reason = str(case.get("final_reason") or "")
    source_warning = str(case.get("source_warning") or "")
    trigger = str(metadata.get("trigger") or case.get("trigger") or "")
    reading_key = str(metadata.get("reading_key") or case.get("reading_key") or "")
    stats = _learning_case_candidate_stats(metadata, reading_key)
    if trigger in FALSE_POSITIVE_REVIEW_TRIGGERS:
        return {
            "review_action": REVIEW_ACTION_DIAGNOSTIC_ONLY,
            "review_label": "背景診斷",
            "review_reason": "已由 OCR/tracker 防線拒絕，保留證據即可，不需日常校正",
        }
    if final_reason == "EXP OCR 連續性不可信":
        return {
            "review_action": REVIEW_ACTION_DIAGNOSTIC_ONLY,
            "review_label": "背景診斷",
            "review_reason": "OCR 連續性防線已拒絕此值，保留證據即可",
        }
    if final_reason == "EXP OCR 模糊數字候選不一致":
        return {
            "review_action": REVIEW_ACTION_DIAGNOSTIC_ONLY,
            "review_label": "背景診斷",
            "review_reason": "Pixel glyph 模糊候選已保留證據，不需日常校正",
        }
    if auto_reason == "glyph 模糊候選僅作背景診斷":
        return {
            "review_action": REVIEW_ACTION_DIAGNOSTIC_ONLY,
            "review_label": "背景診斷",
            "review_reason": "Pixel glyph 模糊候選已保留證據，不需日常校正",
        }
    if auto_reason == "candidate 百分比與綠條不一致":
        return {
            "review_action": REVIEW_ACTION_DELETE_RECOMMENDED,
            "review_label": "建議刪除",
            "review_reason": "候選文字百分比與 saved 綠條估算衝突，不適合作為學習 fixture",
        }
    if (
        final_reason == "EXP 百分比與綠條不一致"
        and source_warning
        and reading_key
        and _find_candidate_source(metadata, reading_key) is None
    ):
        return {
            "review_action": REVIEW_ACTION_DELETE_RECOMMENDED,
            "review_label": "建議刪除",
            "review_reason": "預設 OCR 文字未綁定 saved candidate，且百分比與綠條衝突",
        }
    if (
        final_reason == "EXP 百分比與綠條不一致"
        and not stats["top_text"]
        and not case.get("default_correct_text")
    ):
        return {
            "review_action": REVIEW_ACTION_DELETE_RECOMMENDED,
            "review_label": "建議刪除",
            "review_reason": "沒有可信候選文字且百分比與綠條衝突",
        }
    if source_warning or not case.get("default_correct_text"):
        return {
            "review_action": REVIEW_ACTION_DIAGNOSTIC_ONLY,
            "review_label": "背景診斷",
            "review_reason": "沒有可綁定的 OCR 候選文字，保留證據即可，不需日常校正",
        }
    return {
        "review_action": REVIEW_ACTION_MANUAL_REVIEW,
        "review_label": "需人工校正",
        "review_reason": source_warning or auto_reason or "需人工確認正確值",
    }


def _auto_promote_decision(case: dict[str, Any], text: str) -> dict[str, Any]:
    compact_text = text.strip().replace(" ", "")
    metadata = case.get("metadata") or {}
    stats = _learning_case_candidate_stats(metadata, compact_text)
    source_bound = bool(compact_text and _find_candidate_source(metadata, compact_text) is not None)
    decision: dict[str, Any] = {
        "promotable": False,
        "skip_reason": "",
        "confidence_gap": stats["confidence_gap"],
        "source_bound": source_bound,
        "continuity_status": "not_available",
        "top_candidate_text": stats["top_text"],
        "top_candidate_confidence": stats["top_confidence"],
        "candidate_match_count": stats["matching_attempts"],
        "candidate_bar_mismatch_count": stats["bar_mismatch_count"],
    }
    if case.get("error"):
        decision["skip_reason"] = f"metadata unreadable: {case['error']}"
        return decision
    trigger = str(metadata.get("trigger") or case.get("trigger") or "")
    validation = metadata.get("last_promotion_validation") or {}
    if validation and validation.get("success") is False:
        decision["skip_reason"] = "Pixel validation 已失敗，建議清理此 case"
        return decision
    if trigger in FALSE_POSITIVE_REVIEW_TRIGGERS:
        decision["skip_reason"] = "false-positive case 僅作背景診斷"
        return decision
    final_reason = str((metadata.get("final_reading") or {}).get("reason") or case.get("final_reason") or "")
    if final_reason == "EXP OCR 模糊數字候選不一致":
        decision["skip_reason"] = "Pixel glyph 模糊候選僅作背景診斷"
        return decision
    if not compact_text:
        decision["skip_reason"] = "沒有可自動套用的預設文字"
        return decision
    if case.get("source_warning"):
        decision["skip_reason"] = str(case["source_warning"])
        return decision
    if PROMOTED_TEXT_RE.fullmatch(compact_text) is None:
        decision["skip_reason"] = "文字格式不符合 EXP[percent%]"
        return decision
    if not source_bound:
        decision["skip_reason"] = "預設文字未綁定到 saved candidate"
        return decision
    if stats["top_text"] != compact_text:
        decision["skip_reason"] = "top candidate 與預設文字不同"
        return decision
    if stats["bar_mismatch_count"] > 0:
        decision["skip_reason"] = "candidate 百分比與綠條不一致"
        return decision
    has_confident_gap = (
        stats["top_confidence"] is not None
        and stats["confidence_gap"] is not None
        and stats["top_confidence"] >= AUTO_PROMOTE_MIN_CONFIDENCE
        and stats["confidence_gap"] >= AUTO_PROMOTE_MIN_CONFIDENCE_GAP
    )
    has_attempt_support = stats["matching_attempts"] >= AUTO_PROMOTE_MIN_MATCHING_ATTEMPTS
    has_strong_attempt_support = (
        stats["top_confidence"] is not None
        and stats["confidence_gap"] is not None
        and stats["top_confidence"] >= AUTO_PROMOTE_STRONG_ATTEMPT_MIN_CONFIDENCE
        and stats["confidence_gap"] >= AUTO_PROMOTE_STRONG_ATTEMPT_MIN_CONFIDENCE_GAP
        and stats["matching_attempts"] >= AUTO_PROMOTE_STRONG_ATTEMPT_MIN_MATCHING_ATTEMPTS
    )
    decision["strong_candidate_support"] = has_strong_attempt_support
    if stats["glyph_ambiguity_count"] > 0 and not has_strong_attempt_support:
        decision["skip_reason"] = "glyph 模糊候選僅作背景診斷"
        return decision
    if not has_confident_gap and not has_attempt_support:
        decision["skip_reason"] = "candidate 信心或獨立 attempt 支援不足"
        return decision
    decision["promotable"] = True
    return decision


def _learning_case_sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
    priority = REVIEW_ACTION_SORT_PRIORITY.get(str(item.get("review_action") or ""), 99)
    return (priority, str(item.get("created_at", "")), str(item.get("id", "")))


def _learning_case_candidate_stats(metadata: dict[str, Any], compact_text: str) -> dict[str, Any]:
    attempt_tops: list[str] = []
    bar_mismatch_count = 0
    candidates_by_text: dict[str, dict[str, Any]] = {}
    glyph_ambiguities: list[dict[str, Any]] = []
    frames = metadata.get("frames") or []
    for frame_index, frame in enumerate(frames):
        for roi_index, roi in enumerate(frame):
            for attempt_index, attempt in enumerate(roi.get("attempts") or []):
                attempt_candidates: list[tuple[str, float | None, int]] = []
                for index, candidate in enumerate(attempt.get("candidates") or []):
                    text = str(candidate.get("text") or "").strip().replace(" ", "")
                    if not text:
                        continue
                    confidence = _candidate_confidence(candidate.get("confidence"))
                    attempt_candidates.append((text, confidence, index))
                    entry = candidates_by_text.setdefault(
                        text,
                        {"text": text, "confidence": None, "count": 0},
                    )
                    entry["count"] = int(entry["count"]) + 1
                    if confidence is not None and (
                        entry["confidence"] is None or confidence > float(entry["confidence"])
                    ):
                        entry["confidence"] = confidence
                if attempt_candidates:
                    attempt_top = max(
                        attempt_candidates,
                        key=lambda item: (-1.0 if item[1] is None else item[1], -item[2]),
                    )
                    attempt_tops.append(attempt_top[0])
                    if attempt_top[0] == compact_text and _candidate_attempt_bar_mismatches(compact_text, attempt):
                        bar_mismatch_count += 1
                for segment_index, segment in enumerate(attempt.get("segments") or []):
                    ambiguity = segment.get("ambiguity")
                    if not isinstance(ambiguity, dict):
                        continue
                    item = dict(ambiguity)
                    item["frame_index"] = frame_index
                    item["roi_index"] = roi_index
                    item["attempt_index"] = attempt_index
                    item["segment_index"] = segment_index
                    item["file"] = segment.get("file", "")
                    glyph_ambiguities.append(item)

    top_candidates = sorted(
        candidates_by_text.values(),
        key=lambda item: (
            -1.0 if item.get("confidence") is None else float(item["confidence"]),
            int(item.get("count") or 0),
            str(item.get("text") or ""),
        ),
        reverse=True,
    )
    top_text = str(top_candidates[0]["text"]) if top_candidates else ""
    top_confidence = top_candidates[0].get("confidence") if top_candidates else None
    second_confidence = top_candidates[1].get("confidence") if len(top_candidates) > 1 else None
    confidence_gap = None
    if top_confidence is not None and second_confidence is not None:
        confidence_gap = float(top_confidence) - float(second_confidence)
    return {
        "top_candidates": top_candidates[:5],
        "top_text": top_text,
        "top_confidence": top_confidence,
        "confidence_gap": confidence_gap,
        "matching_attempts": sum(1 for text in attempt_tops if text == compact_text),
        "bar_mismatch_count": bar_mismatch_count,
        "glyph_ambiguities": glyph_ambiguities[:8],
        "glyph_ambiguity_count": len(glyph_ambiguities),
    }


def _candidate_confidence(value: Any) -> float | None:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    return confidence if 0.0 <= confidence <= 1.0 else None


def _candidate_attempt_bar_mismatches(compact_text: str, attempt: dict[str, Any]) -> bool:
    bar_percent = _candidate_confidence(attempt.get("bar_percent"))
    if bar_percent is None:
        try:
            bar_percent = float(attempt.get("bar_percent"))
        except (TypeError, ValueError):
            return False
    match = PROMOTED_TEXT_RE.fullmatch(compact_text)
    if match is None:
        return False
    percent = float(match.group(2))
    return abs(percent - bar_percent) > experience_model.EXP_PIXEL_FONT_RECOGNIZER_BAR_PERCENT_TOLERANCE


def _attach_learning_case_groups(cases: list[dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        grouped.setdefault(_learning_case_group_key(case), []).append(case)
    for group_key, group in grouped.items():
        group_id = hashlib.blake2b(group_key.encode("utf-8"), digest_size=6).hexdigest()
        for index, case in enumerate(group, start=1):
            case["group_id"] = group_id
            case["group_size"] = len(group)
            case["group_index"] = index


def _learning_case_group_key(case: dict[str, Any]) -> str:
    default_text = str(case.get("default_correct_text") or "").strip().replace(" ", "")
    if default_text:
        return f"text:{default_text}"
    candidate_texts = [str(item.get("text") or "") for item in case.get("top_candidates") or [] if item.get("text")]
    if candidate_texts:
        return json.dumps(
            [
                "candidates",
                candidate_texts[:3],
                str(case.get("source_warning") or ""),
                str(case.get("pixel_reason") or ""),
                str(case.get("final_reason") or ""),
            ],
            ensure_ascii=False,
        )
    metadata = case.get("metadata") or {}
    fallback_key = str(metadata.get("dedupe_key") or metadata.get("reading_key") or "")
    if fallback_key:
        return f"metadata:{fallback_key}"
    return f"case:{case.get('id', '')}"


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
        try:
            bar_crop_left_ratio = float(sample.get("bar_crop_left_ratio", experience_model.EXP_OCR_BAR_CROP_LEFT_RATIO))
        except (TypeError, ValueError):
            bar_crop_left_ratio = experience_model.EXP_OCR_BAR_CROP_LEFT_RATIO
        ocr_image = experience_model.ExperienceOcrImage(
            image=image,
            bar_crop_left_ratio=bar_crop_left_ratio,
            source_id=str(sample.get("id") or ""),
        )
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


def _promotion_source_bar_crop_left_ratio(metadata: dict[str, Any], compact_text: str) -> float:
    source = _find_candidate_source(metadata, compact_text)
    frames = metadata.get("frames") or []
    for frame in frames:
        for roi in frame:
            roi_ratio = _coerce_bar_crop_left_ratio(roi.get("bar_crop_left_ratio"))
            if source is None:
                return roi_ratio
            source_name, preview_name = source
            if roi.get("file") == preview_name:
                return roi_ratio
            for attempt in roi.get("attempts") or []:
                if attempt.get("file") == source_name:
                    return roi_ratio
    return experience_model.EXP_OCR_BAR_CROP_LEFT_RATIO


def _coerce_bar_crop_left_ratio(value: Any) -> float:
    try:
        return max(0.0, min(0.98, float(value)))
    except (TypeError, ValueError):
        return experience_model.EXP_OCR_BAR_CROP_LEFT_RATIO


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
