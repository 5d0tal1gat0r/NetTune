"""Moves month folders laid out an older way to the current layout.

A month used to hold four folders side by side -- archive, duplicados,
processed, revision -- and the memoria the colleague came for was one of
them, next to eighty-odd page images. Then the memoria moved into the month
folder itself, with the originals and re-scans numbered after it. Now
everything but the memoria is in dot folders Samba hides, so the memoria is
all a month folder shows:

    archive/                -> .escaneos_originales/
    1_escaneos_originales/  -> .escaneos_originales/
    duplicados/             -> .duplicados/
    2_duplicados/           -> .duplicados/
    revision/               -> .revision/
    processed/*             -> the month folder

An old folder is removed once it is empty. Nothing is overwritten: a file
whose new place is already taken stays where it is and is listed, and its
old folder stays with it. A month already laid out the current way has
nothing to move, so running it again does nothing. Stop the processor before
running this, so no scan is filed into a folder while it moves; deploy.sh
does, and runs it on every deploy.

    ./venv/bin/python tools/rename_month_folders.py            # move
    ./venv/bin/python tools/rename_month_folders.py --dry-run  # only list
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from month_folders import (
    ARCHIVE_DIR_NAME,
    DUPLICATES_DIR_NAME,
    MONTH_FOLDERS,
    REVISION_DIR_NAME,
)

# Old folder name -> where its contents go, relative to the month folder.
MOVES = {
    "archive": ARCHIVE_DIR_NAME,
    "1_escaneos_originales": ARCHIVE_DIR_NAME,
    "duplicados": DUPLICATES_DIR_NAME,
    "2_duplicados": DUPLICATES_DIR_NAME,
    "revision": REVISION_DIR_NAME,
    "processed": "",
}


def plan(incoming_dir: str) -> tuple[list, list, list, list]:
    """(folders, moves, clashes, emptied).

    folders pairs each old folder with its new one; moves and clashes are
    (old path, new path) per file; emptied lists the old folders to remove.
    """
    moves, clashes, emptied = [], [], []
    folders = []
    for year in sorted(os.listdir(incoming_dir)):
        # Any four digits: is_year stops at next year, and trees laid out
        # further ahead by older code are renamed too.
        if not (len(year) == 4 and year.isdigit()):
            continue
        for month in MONTH_FOLDERS:
            month_dir = os.path.join(incoming_dir, year, month)
            for old_name, new_name in MOVES.items():
                old_dir = os.path.join(month_dir, old_name)
                if not os.path.isdir(old_dir):
                    continue
                new_dir = os.path.join(month_dir, new_name) if new_name else month_dir
                folders.append((old_dir, new_dir))
                blocked = False
                for name in sorted(os.listdir(old_dir)):
                    target = os.path.join(new_dir, name)
                    pair = (os.path.join(old_dir, name), target)
                    if os.path.exists(target):
                        clashes.append(pair)
                        blocked = True
                    else:
                        moves.append(pair)
                if not blocked:
                    emptied.append(old_dir)
    return folders, moves, clashes, emptied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="list, move nothing")
    args = parser.parse_args()

    incoming_dir = config.incoming_dir
    folders, moves, clashes, emptied = plan(incoming_dir)
    for old, new in moves:
        print(f"{os.path.relpath(old, incoming_dir)} -> {os.path.relpath(new, incoming_dir)}")
    for old, new in clashes:
        print(f"LEFT IN PLACE, {os.path.relpath(new, incoming_dir)} already exists: "
              f"{os.path.relpath(old, incoming_dir)}")
    print(f"{len(moves)} file(s) to move, {len(emptied)} old folder(s) to remove, "
          f"{len(clashes)} left in place")
    if args.dry_run:
        return 0

    # Every new folder, even for an empty old one, so the tree keeps its
    # shape; with the old folder's permissions, so Samba can still write it.
    for old_dir, new_dir in folders:
        if not os.path.isdir(new_dir):
            os.makedirs(new_dir)
            os.chmod(new_dir, os.stat(old_dir).st_mode & 0o777)
    for old, new in moves:
        os.replace(old, new)
    for old_dir in emptied:
        os.rmdir(old_dir)
    return 1 if clashes else 0


if __name__ == "__main__":
    sys.exit(main())
