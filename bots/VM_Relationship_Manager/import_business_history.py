from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from business_import import BusinessHistoryImporter
from business_memory import BusinessMemory
from database import Database


BOT_DIR = Path(__file__).resolve().parent
MASTER_DIR = BOT_DIR.parent.parent
DEFAULT_DATABASE = MASTER_DIR / "shared" / "exports" / "VM_Relationship_Manager" / "vm_relationships.db"


def resolve_database(explicit: str | None) -> Path:
    load_dotenv(BOT_DIR / ".env")
    raw = (explicit or os.getenv("DATABASE_PATH") or "").strip()
    if not raw:
        return DEFAULT_DATABASE
    path = Path(raw)
    if not path.is_absolute():
        path = BOT_DIR / path
    return path.resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or import historical client/supplier CSV records into VM Relationship Manager."
    )
    parser.add_argument("csv_file", type=Path, help="Path to the CSV file")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write validated new rows. Without this flag the command is read-only.",
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Optional Relationship Manager database path; otherwise DATABASE_PATH/default is used.",
    )
    parser.add_argument(
        "--admin-id",
        type=int,
        default=None,
        help="Optional admin Telegram ID to record in the audit log for applied imports.",
    )
    return parser


def print_preview(preview) -> None:
    print("VM BUSINESS HISTORY IMPORT PREVIEW")
    print(f"Source: {preview.source_file}")
    print(f"Rows read: {preview.total_rows}")
    print(f"New rows: {preview.new_count}")
    print(f"Duplicates skipped: {preview.duplicate_count}")
    print(f"Problems: {len(preview.problems)}")
    if preview.problems:
        print("\nProblems:")
        for problem in preview.problems[:50]:
            print(f"- row {problem.source_row}: {problem.message}")
        if len(preview.problems) > 50:
            print(f"- ... plus {len(preview.problems) - 50} more")


def main() -> int:
    args = build_parser().parse_args()
    csv_path = args.csv_file.resolve()
    if not csv_path.exists() or not csv_path.is_file():
        print(f"ERROR: CSV file not found: {csv_path}")
        return 2

    db_path = resolve_database(args.database)
    if not db_path.exists():
        print(
            "ERROR: Relationship Manager database does not exist. "
            f"Start/initialize the bot first or provide --database. Path: {db_path}"
        )
        return 2

    db = Database(db_path)
    BusinessMemory(db)  # Ensure the additive Business Memory schema exists.
    importer = BusinessHistoryImporter(db)
    preview = importer.preview_file(csv_path)
    print_preview(preview)

    if preview.problems:
        print("\nNOT APPLIED: fix validation problems and run the preview again.")
        return 1

    if not args.apply:
        print("\nDRY RUN ONLY: no transaction rows were written.")
        print("Run the same command with --apply after reviewing the preview.")
        return 0

    result = importer.apply_file(csv_path, recorded_by=args.admin_id)
    print("\nIMPORT APPLIED")
    print(f"Inserted: {result.inserted}")
    print(f"Duplicates skipped: {result.skipped_duplicates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
