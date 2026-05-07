from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maple_star.services.experience_ocr_learning import (  # noqa: E402
    dedupe_experience_ocr_fixtures_by_case_prefix,
    dedupe_experience_ocr_fixtures_by_text,
    dedupe_experience_ocr_learning_cases,
    delete_experience_ocr_learning_case,
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
            f"text={case.get('final_text')!r} | reason={case.get('final_reason', '--')}"
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


def delete_case(args: argparse.Namespace) -> int:
    deleted = delete_experience_ocr_learning_case(args.id)
    print(f"{'deleted' if deleted else 'not found'} {args.id}")
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

    delete_parser = subparsers.add_parser("delete", help="Delete a pending learning case.")
    delete_parser.add_argument("--id", required=True, help="Pending case id.")
    delete_parser.set_defaults(func=delete_case)

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
