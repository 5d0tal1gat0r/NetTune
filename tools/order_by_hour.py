"""Renumbers each day's sheets in the order the shifts happened.

The scanner does not keep a day's sheets in time order. September's batch
came, every one of its 21 days, as

    position 1   15:00-23:00   SECUPOL, vigilante
    position 2   07:00-15:00   SECUPOL, vigilante
    position 3   18:00-00:00   SECUSERVI, auxiliar
    position 4   22:00-08:00   SECUPOL, vigilante

-- checked by eye against the "Horario" of all 84 sheets -- so p1 was the
afternoon and p2 the morning. --day-order says, as scan positions, which
sheet of a day came first, second and so on: 2,1,3,4 for that batch. Each
day with exactly that many sheets is renumbered to match; lines, images and
hand turns move with their sheets, and the scan position is kept.

A day already renumbered is left alone, so running it twice is safe. New
batches do not need this: the processor reads each sheet's start time and
numbers them by it.

    ./venv/bin/python tools/order_by_hour.py 2026 SEPTIEMBRE --day-order 2,1,3,4 --dry-run
    ./venv/bin/python tools/order_by_hour.py 2026 SEPTIEMBRE --day-order 2,1,3,4
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nettune.config import config
from nettune.dates.sheet_dates import renumber_files
from nettune.report.entry_store import EntryStore
from nettune.report.month_folders import revision_dir_for
from nettune.report.review_marks import plain_ref


def plan(store: EntryStore, year: str, month: str, day_order: list[int]):
    """{source: {old page: new page}}, plus days skipped and why."""
    plans, skipped = {}, []
    sources = {src for (src,) in store._connection.execute(
        "SELECT DISTINCT source FROM scan_sheets WHERE year = ? AND month = ?", (year, month))}
    for source in sorted(sources):
        rows = store._connection.execute(
            "SELECT page, review_ref, COALESCE(scan_position, page) FROM scan_sheets "
            "WHERE year = ? AND month = ? AND source = ? ORDER BY page",
            (year, month, source)).fetchall()
        days: dict[str, list] = {}
        for page, ref, position in rows:
            days.setdefault(plain_ref(ref).split(" ")[0], []).append((page, position))
        mapping = {}
        for day, sheets in days.items():
            pages = [p for p, _ in sheets]
            if len(sheets) != len(day_order):
                skipped.append(f"{source} {day}: {len(sheets)} sheets, not {len(day_order)}")
                continue
            if pages != list(range(pages[0], pages[0] + len(pages))):
                skipped.append(f"{source} {day}: its pages are not consecutive")
                continue
            if any(p != pos for p, pos in sheets):
                continue  # already renumbered
            for k, position in enumerate(day_order):
                old, new = pages[position - 1], pages[k]
                if old != new:
                    mapping[old] = new
        if mapping:
            plans[source] = mapping
    return plans, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("year")
    parser.add_argument("month")
    parser.add_argument("--day-order", required=True,
                        help="Scan positions in time order within a day, e.g. 2,1,3,4")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    day_order = [int(x) for x in args.day_order.split(",")]
    if sorted(day_order) != list(range(1, len(day_order) + 1)):
        parser.error("--day-order must list each position 1..N once")

    revision = revision_dir_for(config.incoming_dir, args.year, args.month)
    with EntryStore(config.entry_db) as store:
        plans, skipped = plan(store, args.year, args.month, day_order)
        for reason in skipped:
            print(f"skipped {reason}")
        moved = 0
        for source, mapping in plans.items():
            if args.dry_run:
                for old, new in sorted(mapping.items()):
                    print(f"would renumber {source} p{old} -> p{new}")
                moved += len(mapping)
                continue
            pairs = store.renumber_sheets(args.year, args.month, source, mapping)
            renumber_files(store, revision, pairs)
            moved += len(pairs)
            for old_ref, new_ref in pairs:
                print(f"renumbered {old_ref} -> {new_ref}")
        print(f"{moved} sheet(s) {'to renumber' if args.dry_run else 'renumbered'}.")


if __name__ == "__main__":
    main()
