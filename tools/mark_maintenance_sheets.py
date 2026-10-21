"""Marks a maintenance scan read before sheets carried their section, once.

Seguridad and Mantenimiento number their sheets each from 1, and a
maintenance sheet's reference carries review_marks.MAINTENANCE_MARK to keep
the two apart. A scan read before that has plain references, and one of them
can be a security sheet's too: September 2026's maintenance sheet of 01-09
and the security one were both "01-09-2026 p2", and the maintenance image,
written later, overwrote the security one.

This gives the scan's sheets the mark and numbers them from p1 -- on from
any other maintenance scan of the month -- in the order they have, moves
their lines with them, and renames their images -- where two sheets shared an
image, the file on disk is the later scan's, which is this one when it is
used as intended. The other scan's lost image is then rebuilt from its
archived PDF:

    ./venv/bin/python tools/mark_maintenance_sheets.py S25C-0i26093013070.pdf 2026 SEPTIEMBRE
    ./venv/bin/python tools/rebuild_revision.py \\
        incoming_scans/2026/SEPTIEMBRE/.escaneos_originales/SKM_C30826092211360.pdf \\
        2026 SEPTIEMBRE
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from entry_store import EntryStore
from month_folders import revision_dir_for
from review_marks import MAINTENANCE_MARK, image_name, is_maintenance_ref
from sheet_dates import renumber_files


def renumbering(store: EntryStore, year: str, month: str, source: str) -> dict[int, int]:
    """Old page -> new page putting the scan's sheets at p1, p2... of the
    maintenance series, in their present order. Empty when they already are.

    September 30's scan was first moved to p85-p110, past the security
    sheets, by a tool this one replaced; this brings it back.
    """
    pages = sorted(store.source_sheets(year, month, source))
    first = store.last_page(year, month, excluding=source, maintenance=True) + 1
    mapping = {old: first + n for n, old in enumerate(pages)}
    return {old: new for old, new in mapping.items() if old != new}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", help="The scan's filename, as the dashboard records it")
    parser.add_argument("year")
    parser.add_argument("month")
    parser.add_argument("--dry-run", action="store_true", help="list, change nothing")
    args = parser.parse_args()

    folder = revision_dir_for(config.incoming_dir, args.year, args.month)
    with EntryStore(config.entry_db) as store:
        refs = [ref for ref in store.source_sheets(args.year, args.month, args.source).values()
                if not is_maintenance_ref(ref)]
        if not refs:
            mapping = renumbering(store, args.year, args.month, args.source)
            if not mapping:
                print("Nothing to do: the scan's sheets are marked and numbered.")
                return 0
            sheets = store.source_sheets(args.year, args.month, args.source)
            for old, new in sorted(mapping.items()):
                print(f"{image_name(sheets[old])} -> p{new}")
            print(f"{len(mapping)} sheet(s) {'to renumber' if args.dry_run else 'renumbered'}")
            if not args.dry_run:
                renumber_files(store, folder, store.renumber_sheets(
                    args.year, args.month, args.source, mapping))
            return 0
        taken = [image_name(MAINTENANCE_MARK + ref) for ref in refs
                 if os.path.exists(os.path.join(folder, image_name(MAINTENANCE_MARK + ref)))]
        if taken:
            print(f"Not changing anything: already in {folder}: {', '.join(taken)}")
            return 1
        for ref in refs:
            print(f"{image_name(ref)} -> {image_name(MAINTENANCE_MARK + ref)}")
        print(f"{len(refs)} sheet(s) {'to mark' if args.dry_run else 'marked'}")
        if args.dry_run:
            return 0
        for old_ref, new_ref in store.mark_maintenance(args.year, args.month, args.source):
            old_name, new_name = image_name(old_ref), image_name(new_ref)
            if os.path.isfile(os.path.join(folder, old_name)):
                os.rename(os.path.join(folder, old_name), os.path.join(folder, new_name))
                store.rename_turn(old_name, new_name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
