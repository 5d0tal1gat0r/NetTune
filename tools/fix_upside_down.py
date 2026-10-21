"""Turns upright the review images of a month that are upside down.

Finds them by the printed form header (page_rotation.header_orientation),
which is reliable where OSD, reading the handwriting, is not: on September
it found 24 of 84 sheets upside down that OSD had passed. Each one turned is
recorded as a hand turn, so a re-dropped scan keeps it upright.

A sheet a person has already turned by hand is never touched: they looked
at it, and that decision stands.

    ./venv/bin/python tools/fix_upside_down.py 2026 SEPTIEMBRE --dry-run
    ./venv/bin/python tools/fix_upside_down.py 2026 SEPTIEMBRE
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nettune.config import config
from nettune.intake.scan_filter import IMAGE_EXTENSIONS
from nettune.pages.page_rotation import header_orientation, rotate_by
from nettune.report.entry_store import EntryStore
from nettune.report.month_folders import revision_dir_for


def upside_down(folder: str, hand_turned: frozenset) -> tuple[list[str], list[str]]:
    """(to turn, left alone because a person already turned them)."""
    turn, kept = [], []
    for name in sorted(os.listdir(folder)):
        if os.path.splitext(name)[1].lower() not in IMAGE_EXTENSIONS:
            continue
        if header_orientation(os.path.join(folder, name)) != "upside_down":
            continue
        (kept if name in hand_turned else turn).append(name)
    return turn, kept


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("year")
    parser.add_argument("month")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    folder = revision_dir_for(config.incoming_dir, args.year, args.month)
    with EntryStore(config.entry_db) as store:
        turn, kept = upside_down(folder, store.hand_turned())
        for name in kept:
            print(f"left alone (turned by hand already): {name}")
        for name in turn:
            if not args.dry_run:
                rotate_by(os.path.join(folder, name), 180)
                store.record_turn(name, 180)
            print(f"{'would turn' if args.dry_run else 'turned'} 180: {name}")
    print(f"{len(turn)} sheet(s) {'to turn' if args.dry_run else 'turned'} upright.")


if __name__ == "__main__":
    main()
