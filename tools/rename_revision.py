"""Renames review images to the one naming scheme, once.

Sheets with no date used to be named after their scan --
SKM_C30826092211360_p27.jpg beside 01-09-2026_p2.jpg in the same folder.
review_marks.image_name now gives every sheet the same shape,
DD-MM-YYYY_pN.jpg or sin-fecha_pN.jpg, and this moves the files already on
disk to match, carrying each one's hand turn with it.

Nothing is renamed if two sheets of a month would end up with the same
name: that would put one sheet's picture in front of another's lines.

    ./venv/bin/python tools/rename_revision.py            # rename
    ./venv/bin/python tools/rename_revision.py --dry-run  # only list
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from entry_store import EntryStore
from month_folders import revision_dir_for
from review_marks import image_name, legacy_image_name


def plan(store: EntryStore, incoming_dir: str) -> tuple[list, list]:
    """(renames, clashes): renames as (folder, old name, new name)."""
    renames, clashes = [], []
    months = {(y, m) for y, m, _ in store.sheets()}
    for year, month in sorted(months):
        folder = revision_dir_for(incoming_dir, year, month)
        refs = {ref for y, m, ref in store.sheets() if (y, m) == (year, month)}
        owners: dict[str, set] = {}
        for ref in refs:
            owners.setdefault(image_name(ref), set()).add(ref)
        clashes += [(year, month, name, sorted(r)) for name, r in owners.items() if len(r) > 1]
        for ref in sorted(refs):
            old, new = legacy_image_name(ref), image_name(ref)
            if old != new and os.path.isfile(os.path.join(folder, old)):
                renames.append((folder, old, new))
    return renames, clashes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with EntryStore(config.entry_db) as store:
        renames, clashes = plan(store, config.incoming_dir)
        if clashes:
            print("Not renaming anything: these sheets would share a name:")
            for year, month, name, refs in clashes:
                print(f"  {year}/{month}: {name} <- {', '.join(refs)}")
            raise SystemExit(1)
        blocked = [(f, o, n) for f, o, n in renames if os.path.exists(os.path.join(f, n))]
        if blocked:
            print("Not renaming anything: the new name is already taken:")
            for folder, old, new in blocked:
                print(f"  {old} -> {new} in {folder}")
            raise SystemExit(1)
        for folder, old, new in renames:
            print(f"{'would rename' if args.dry_run else 'renamed'}: {old} -> {new}")
            if not args.dry_run:
                os.rename(os.path.join(folder, old), os.path.join(folder, new))
                store.rename_turn(old, new)
        print(f"{len(renames)} image(s) {'to rename' if args.dry_run else 'renamed'}.")


if __name__ == "__main__":
    main()
