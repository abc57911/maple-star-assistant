from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maple_star.services.experience_ocr_learning import (  # noqa: E402
    auto_promote_experience_ocr_learning_cases,
    dedupe_experience_ocr_fixtures_by_case_prefix,
    dedupe_experience_ocr_fixtures_by_text,
    dedupe_experience_ocr_learning_cases,
    delete_experience_ocr_learning_case,
    delete_recommended_experience_ocr_learning_cases,
    list_experience_ocr_learning_cases,
    promote_experience_ocr_learning_case,
    regen_experience_pixel_templates,
)


def list_cases(_args: argparse.Namespace) -> int:
    cases = list_experience_ocr_learning_cases()
    if not cases:
        print("pending cases not found")
        return 0
    for case in cases:
        if case.get("error"):
            print(f"{case['id']}: metadata unreadable: {case['error']}")
            continue
        print(
            f"{case['id']} | {case.get('trigger', '--')} | "
            f"group={case.get('group_id', '--')}:{case.get('group_index', 1)}/{case.get('group_size', 1)} | "
            f"text={case.get('final_text')!r} | reason={case.get('final_reason', '--')} | "
            f"auto={case.get('auto_promote_skip_reason') or 'promotable'} | "
            f"review={case.get('review_label', '--')}:{case.get('review_reason', '--')}"
        )
    return 0


def promote_case(args: argparse.Namespace) -> int:
    result = promote_experience_ocr_learning_case(args.id, args.text, force=args.force)
    print(f"promoted {args.id} -> {result['target_path'].name}")
    return 0


def regen_templates(_args: argparse.Namespace) -> int:
    result = regen_experience_pixel_templates()
    print(f"wrote {result['template_path']} ({result['template_count']} templates)")
    return 0


def auto_promote_cases(args: argparse.Namespace) -> int:
    result = auto_promote_experience_ocr_learning_cases(dry_run=args.dry_run)
    action = "would promote" if args.dry_run else "promoted"
    for item in result.get("promotable", []):
        print(f"{action} {item['id']} text={item['text']}")
    for item in result.get("promoted", []):
        print(f"{action} {item['id']} -> {item['sample_id']} text={item['text']}")
    for item in result.get("rolled_back", []):
        print(
            f"rolled back {item['id']} -> {item['sample_id']} "
            f"read={item.get('read_text') or '--'} reason={item['reason']}"
        )
    for item in result.get("skipped", []):
        print(f"skipped {item['id']} reason={item['reason']}")
    print(
        "summary "
        f"promotable={len(result.get('promotable', []))} "
        f"promoted={len(result.get('promoted', []))} "
        f"rolled_back={len(result.get('rolled_back', []))} "
        f"skipped={len(result.get('skipped', []))}"
    )
    return 0


def delete_case(args: argparse.Namespace) -> int:
    deleted = delete_experience_ocr_learning_case(args.id)
    print(f"{'deleted' if deleted else 'not found'} {args.id}")
    return 0


def delete_recommended_cases(args: argparse.Namespace) -> int:
    items = delete_recommended_experience_ocr_learning_cases(dry_run=args.dry_run)
    action = "would delete" if args.dry_run else "deleted"
    for item in items:
        print(f"{action} {item['id']} reason={item['reason']}")
    if not items:
        print("no delete-recommended pending cases")
    return 0


def dedupe_cases(args: argparse.Namespace) -> int:
    duplicates = dedupe_experience_ocr_learning_cases(delete=not args.dry_run)
    for duplicate in duplicates:
        action = "would delete" if args.dry_run else "deleted"
        print(f"{action} {duplicate['id']} duplicate_of={duplicate['duplicate_of']}")
    if not duplicates:
        print("no duplicate pending cases")
    return 0


def dedupe_fixtures(args: argparse.Namespace) -> int:
    duplicates = dedupe_experience_ocr_fixtures_by_text(delete=not args.dry_run)
    duplicates.extend(dedupe_experience_ocr_fixtures_by_case_prefix(delete=not args.dry_run))
    for duplicate in duplicates:
        action = "would delete" if args.dry_run else "deleted"
        print(
            f"{action} {duplicate['id']} duplicate_of={duplicate['duplicate_of']} "
            f"text={duplicate['text']}"
        )
    if not duplicates:
        print("no duplicate fixture samples")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage Maple EXP Pixel OCR learning cases.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List pending learning cases.")
    list_parser.set_defaults(func=list_cases)

    promote_parser = subparsers.add_parser("promote", help="Promote a pending case into OCR fixtures.")
    promote_parser.add_argument("--id", required=True, help="Pending case id.")
    promote_parser.add_argument("--text", required=True, help='Correct text, e.g. "2043879[10.75%%]".')
    promote_parser.add_argument("--force", action="store_true", help="Overwrite existing fixture file.")
    promote_parser.set_defaults(func=promote_case)

    regen_parser = subparsers.add_parser("regen-templates", help="Regenerate runtime Pixel OCR templates from fixtures.")
    regen_parser.set_defaults(func=regen_templates)

    auto_promote_parser = subparsers.add_parser("auto-promote", help="Conservatively promote trusted pending cases.")
    auto_promote_parser.add_argument("--dry-run", action="store_true", help="List promotable cases without changing files.")
    auto_promote_parser.set_defaults(func=auto_promote_cases)

    delete_parser = subparsers.add_parser("delete", help="Delete a pending learning case.")
    delete_parser.add_argument("--id", required=True, help="Pending case id.")
    delete_parser.set_defaults(func=delete_case)

    delete_recommended_parser = subparsers.add_parser(
        "delete-recommended",
        help="Delete pending cases classified as not useful for OCR learning.",
    )
    delete_recommended_parser.add_argument("--dry-run", action="store_true", help="Only list cases that would be deleted.")
    delete_recommended_parser.set_defaults(func=delete_recommended_cases)

    dedupe_parser = subparsers.add_parser("dedupe", help="Delete duplicate pending learning cases.")
    dedupe_parser.add_argument("--dry-run", action="store_true", help="Only list duplicates.")
    dedupe_parser.set_defaults(func=dedupe_cases)

    dedupe_fixtures_parser = subparsers.add_parser(
        "dedupe-fixtures",
        help="Delete duplicate fixture samples with the same EXP text.",
    )
    dedupe_fixtures_parser.add_argument("--dry-run", action="store_true", help="Only list duplicates.")
    dedupe_fixtures_parser.set_defaults(func=dedupe_fixtures)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
