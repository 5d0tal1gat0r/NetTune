"""Straightens review images already sitting in a month's revision/ folder.

Fixing them in place costs nothing. Re-reading the scans that produced them
would mean paying the Vision API again for pages already transcribed --
wrong rotation and all -- so this only touches the copy a human checks
against, using the same aspect-ratio-then-OSD logic main.page_images() now
applies before transcription.

    ./venv/bin/python tools/straighten_revision.py incoming_scans/2026/09/revision
"""

import argparse
import hashlib
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from page_rotation import straighten, to_portrait
from scan_filter import IMAGE_EXTENSIONS


def straighten_folder(folder: str, hand_turned: frozenset = frozenset()) -> list[str]:
    """Straightens every image directly inside *folder*. Returns what changed.

    *hand_turned* names images a person has already turned in the dashboard.
    They are left alone: somebody looked at that sheet and decided which way
    is up, and OSD -- which on handwriting is guessing at confidences as low
    as 0.07 -- does not get to overrule them.
    """
    changed = []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        if os.path.splitext(name)[1].lower() not in IMAGE_EXTENSIONS:
            continue
        if name in hand_turned:
            logging.info(f"Skipping {name}: turned by hand in the dashboard")
            continue

        with open(path, "rb") as handle:
            before = hashlib.sha256(handle.read()).digest()

        # only_upside_down: every image here is a review copy of one split
        # sheet, portrait by construction, so a 90/270 from OSD past this
        # point would only be it misreading a sheet to_portrait already
        # fixed -- never a real correction.
        straighten(to_portrait(path), only_upside_down=True)

        with open(path, "rb") as handle:
            after = hashlib.sha256(handle.read()).digest()

        # A 180-degree correction leaves the dimensions the same, so the
        # file's bytes -- not its size -- are what tell us it was touched.
        if after != before:
            changed.append(name)
    return changed


def _hand_turned() -> frozenset:
    """Names of review images a person turned by hand, from the entry store.

    An unreadable store means nothing is known to be hand-turned, which is
    the tool's old behaviour -- not a reason to refuse to run.
    """
    try:
        from config import config
        from entry_store import EntryStore

        with EntryStore(config.entry_db) as store:
            return store.hand_turned()
    except Exception as exc:
        logging.warning(f"Could not read hand turns, straightening everything: {exc}")
        return frozenset()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", help="A month's revision/ folder")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not os.path.isdir(args.folder):
        parser.error(f"{args.folder} is not a directory")

    changed = straighten_folder(args.folder, _hand_turned())
    if changed:
        print(f"Rotated {len(changed)} image(s):")
        for name in changed:
            print(f"  {name}")
    else:
        print("Nothing needed rotating.")


if __name__ == "__main__":
    main()
