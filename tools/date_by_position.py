"""Dates every sheet of a month by its place in its batch: N sheets a day.

The sheets of a batch arrive a fixed number to a day, in order. September's
batch was 84 sheets for 1-21 September, exactly four a day, and wherever the
paper was checked it agreed with the position -- including sheets whose read
date looked plausible and was wrong (06 read as 08, 13 as 15, 15 as 16), and
the 21 sheets rebuilt from the archive whose date was never read at all.

For each scan in the month, the read dates are used only to find where the
batch starts; every sheet then gets the day its position gives it. A scan
whose read dates do not follow the pattern -- fewer than half agree, as a
missing sheet would cause -- is left untouched and reported.

Every change goes through sheet_dates.set_sheet_date: lines, image file and
hand turn move together, and each corrected sheet is marked as checked.

    ./venv/bin/python tools/date_by_position.py 2026 SEPTIEMBRE --dry-run
    ./venv/bin/python tools/date_by_position.py 2026 SEPTIEMBRE
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nettune.config import config
from nettune.dates.batch_dates import dates_by_position, parse_date
from nettune.dates.sheet_dates import set_sheet_date
from nettune.report.entry_store import EntryStore
from nettune.report.month_folders import revision_dir_for
from nettune.report.review_marks import plain_ref


def plan(store: EntryStore, year: str, month: str, per_day: int) -> tuple[list, list]:
    """(changes, skipped): changes as (source, page, old ref, new date)."""
    sources = set()
    for y, m, ref in store.sheets():
        if (y, m) == (year, month):
            identity = store.sheet_identity(year, month, ref)
            if identity:
                sources.add(identity[0])
    changes, skipped = [], []
    for source in sorted(sources):
        pages = store.source_sheets(year, month, source)
        if not pages:
            continue
        numbers = list(range(1, max(pages) + 1))
        read = [parse_date(plain_ref(pages[n]).split(" ")[0]) if n in pages else None
                for n in numbers]
        fitted = dates_by_position(read, per_day)
        if fitted is None:
            skipped.append(source)
            continue
        for n, day in zip(numbers, fitted[0], strict=True):
            if n not in pages:
                continue
            wanted = day.strftime("%d-%m-%Y")
            if plain_ref(pages[n]).split(" ")[0] != wanted:
                changes.append((source, n, pages[n], wanted))
    return changes, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("year")
    parser.add_argument("month")
    parser.add_argument("--per-day", type=int, default=config.sheets_per_day)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    revision = revision_dir_for(config.incoming_dir, args.year, args.month)
    with EntryStore(config.entry_db) as store:
        changes, skipped = plan(store, args.year, args.month, args.per_day)
        for source in skipped:
            print(f"{source}: the read dates do not follow {args.per_day} a day; left as read")
        failed = 0
        for _, page, old_ref, wanted in changes:
            label = f"p{page}: {old_ref.split(' ')[0]} -> {wanted}"
            if args.dry_run:
                print(f"would set {label}")
                continue
            new_ref, error = set_sheet_date(store, args.year, args.month, old_ref,
                                            wanted, revision)
            if new_ref is None:
                failed += 1
                print(f"NOT set {label}: {error}")
            else:
                print(f"set {label}")
        verb = "to set" if args.dry_run else "set"
        print(f"{len(changes) - failed} sheet date(s) {verb}; {failed} refused.")


if __name__ == "__main__":
    main()
