"""Rebuilds the missing sheet images of a scan, and records every sheet.

Until every sheet was recorded, the review folder only got an image for a
sheet with a doubtful line on it: 20 of September's 84 sheets were never
saved, and nothing recorded that they existed. This renders the archived
scan again -- locally, no API call -- writes the sheets that are missing,
and records all of them so the dashboard can show them and offer them as
the page a line came from.

The page number is the only link between a sheet and what was read off it,
so before anything is written the numbering is checked: every sheet that
already has an image must look more like that image than like the sheets
either side of it. If it does not, nothing is written.

An existing image is never overwritten -- it may have been turned by hand.

    ./venv/bin/python tools/rebuild_revision.py \\
        incoming_scans/2026/SEPTIEMBRE/archive/SKM_C30826092211360.pdf 2026 SEPTIEMBRE

Straightening is slow on the Pi, so it can be done elsewhere first:
--straightened DIR takes a missing sheet's image from DIR when one of the
same name is there, instead of straightening it here.
"""

import argparse
import logging
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageChops, ImageStat

from config import config
from entry_store import EntryStore
from month_folders import revision_dir_for
from page_rotation import straighten, to_portrait
from pdf_pages import is_pdf, render_pages
from review_marks import image_name, locator
from sheet_split import split_sheets

_THUMB = 48


def _thumbnail(path: str) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("L").resize((_THUMB, _THUMB))


def _distance(raw: str, existing: str) -> float:
    """How unlike two sheets are, whichever way up the raw one is."""
    target = _thumbnail(existing)
    with Image.open(raw) as image:
        grey = image.convert("L")
        turns = [grey.rotate(angle, expand=True) for angle in (0, 90, 180, 270)]
    return min(
        ImageStat.Stat(ImageChops.difference(t.resize((_THUMB, _THUMB)), target)).mean[0]
        for t in turns
    )


def raw_sheets(scan: str, workdir: str) -> list[str]:
    """The scan's sheets in reading order, split but not yet straightened.

    The same steps, in the same order, as main.page_images, so sheet n here
    is sheet n there.
    """
    pages = render_pages(scan, workdir, dpi=config.pdf_dpi) if is_pdf(scan) else [scan]
    if not config.split_sheets:
        return pages
    sheets = []
    for page in pages:
        sheets.extend(split_sheets(page, os.path.join(workdir, "hojas")))
    return sheets


def check_numbering(sheets: list[str], known: dict[int, str], revision: str) -> list[str]:
    """Problems with the numbering; empty when every known sheet lines up."""
    problems = []
    checked = 0
    for page, ref in sorted(known.items()):
        existing = os.path.join(revision, image_name(ref))
        if not os.path.isfile(existing) or not 1 <= page <= len(sheets):
            continue
        own = _distance(sheets[page - 1], existing)
        neighbours = [
            _distance(sheets[other - 1], existing)
            for other in (page - 1, page + 1) if 1 <= other <= len(sheets)
        ]
        checked += 1
        if neighbours and own >= min(neighbours):
            problems.append(
                f"sheet {page} ({image_name(ref)}) looks no more like its image "
                f"({own:.1f}) than a neighbour does ({min(neighbours):.1f})"
            )
    if checked == 0:
        problems.append("no existing image to check the numbering against")
    return problems


def rebuild(scan: str, year: str, month: str, store: EntryStore,
            straightened: str | None = None, dry_run: bool = False) -> dict:
    source = os.path.basename(scan)
    revision = revision_dir_for(config.incoming_dir, year, month)
    # By scan position, not page number: sheets are numbered in the order
    # the shifts happened, and the scan is rendered in the order it was fed.
    known = store.scan_positions(year, month, source)
    if not known:
        known = store.source_sheets(year, month, source)

    with tempfile.TemporaryDirectory(prefix="rebuild_") as workdir:
        sheets = raw_sheets(scan, workdir)
        problems = check_numbering(sheets, known, revision)
        if problems:
            raise SystemExit("Numbering check failed; nothing written:\n  "
                             + "\n  ".join(problems))
        with_image = sum(1 for r in known.values()
                         if os.path.isfile(os.path.join(revision, image_name(r))))
        logging.warning(f"{source}: {len(sheets)} sheets, numbering checked against "
                        f"{with_image} existing images")

        written, kept = [], 0
        for page, raw in enumerate(sheets, start=1):
            ref = known.get(page) or locator(None, page, source)
            destination = os.path.join(revision, image_name(ref))
            if os.path.isfile(destination):
                kept += 1
            elif not dry_run:
                ready = os.path.join(straightened, image_name(ref)) if straightened else ""
                if ready and os.path.isfile(ready):
                    shutil.copyfile(ready, destination)
                else:
                    shutil.copyfile(straighten(to_portrait(raw), only_upside_down=True),
                                    destination)
                written.append(image_name(ref))
            else:
                written.append(image_name(ref))
            if not dry_run and page not in known:
                store.record_sheet(year, month, source, page, ref)
    return {"sheets": len(sheets), "kept": kept, "written": written}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scan", help="The archived scan the month was read from")
    parser.add_argument("year")
    parser.add_argument("month")
    parser.add_argument("--straightened", help="Folder of already-straightened sheets")
    parser.add_argument("--dry-run", action="store_true",
                        help="Check the numbering and list what would be written")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    if not os.path.isfile(args.scan):
        parser.error(f"{args.scan} not found")

    with EntryStore(config.entry_db) as store:
        result = rebuild(args.scan, args.year, args.month, store,
                         straightened=args.straightened, dry_run=args.dry_run)
    verb = "Would write" if args.dry_run else "Wrote"
    print(f"{result['sheets']} sheets; {result['kept']} already had an image; "
          f"{verb} {len(result['written'])}:")
    for name in result["written"]:
        print(f"  {name}")


if __name__ == "__main__":
    main()
