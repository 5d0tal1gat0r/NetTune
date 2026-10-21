"""Splits a scanned page into the separate daily sheets printed on it.

The scanner puts two sheets on every page: a landscape scan holds them side
by side, a portrait scan holds them stacked. They are different days, or the
two shifts of one day, written by different vigilantes and each with its own
date and signature block.

Reading a page as though it were one sheet was costing three things. Entries
ran together across the two boxes. One of the two dates was lost, so a sheet
could be filed under the wrong day. And the model's fixed resolution had to
cover two sheets at once, leaving the handwriting half the size it needed to
be. A portrait scan was worse still: the two sheets are rotated ninety
degrees in opposite directions, so no single rotation is right for the page
and the straightener could only ever fix one of them.

Splitting is deterministic and costs nothing: the gutter between two sheets
is a band with almost no ink running the full height or width of the page.
When no such band is found the page is left alone -- a single sheet, or a
layout this does not understand, is better read whole than cut in half.
"""

import logging
import os

# How far from the middle the gutter may sit, as a fraction of the page. The
# scanner centres the sheets; a band found near an edge is a margin.
_SEARCH = 0.18

# A gutter is nearly white. Above this fraction of the darkest column's ink
# it is writing, not a gap.
_MAX_GUTTER_INK = 0.06

# Truly blank: paper with no writing at all. A sheet's own margin, where the
# ends of the longest lines reach, carries a little ink -- under the gutter
# limit above but above this one -- and cutting there loses those ends.
_BLANK_INK = 0.01

# The narrowest band of bare paper taken for the gutter, as a fraction of the
# page. Shorter is a gap between two words, and the looser limit decides.
_MIN_GUTTER = 0.01

# A page whose two halves would be wildly different sizes was not two sheets.
_MIN_HALF = 0.35


def _widest_run(quiet) -> tuple[int, int]:
    """Length and last index of the longest run of True in *quiet*."""
    best_len = best_end = run = 0
    for index, empty in enumerate(quiet):
        run = run + 1 if empty else 0
        if run > best_len:
            best_len, best_end = run, index
    return best_len, best_end


def find_gutter(page) -> tuple[int, str]:
    """Where the page divides, and along which axis. (0, "") if it does not.

    Returns the position in pixels and "vertical" for two sheets side by side
    or "horizontal" for two stacked.
    """

    height, width = page.shape[:2]
    ink = page < 128

    # A landscape page is cut down its length, a portrait page across it.
    axis, size = ("vertical", width) if width >= height else ("horizontal", height)
    profile = ink.sum(axis=0) if axis == "vertical" else ink.sum(axis=1)
    if not profile.max():
        return 0, ""

    middle = size // 2
    span = int(size * _SEARCH)
    start = max(0, middle - span)
    window = profile[start:min(size, middle + span)]

    # The gutter is a band, not a line. Cut through the middle of the widest
    # run of near-empty columns, which stays put when one edge of the band is
    # dirtier than the other. Bare paper is looked for first: a sheet whose
    # writing thins out towards its edge makes a wider band of faint ink next
    # to the gutter, and its middle is inside the sheet.
    for limit in (_BLANK_INK, _MAX_GUTTER_INK):
        best_len, best_end = _widest_run(window <= profile.max() * limit)
        if best_len >= size * _MIN_GUTTER:
            break
    if not best_len:
        return 0, ""

    candidate = start + best_end - best_len // 2
    if not (_MIN_HALF < candidate / size < 1 - _MIN_HALF):
        return 0, ""
    return candidate, axis


def split_sheets(image_path: str, workdir: str) -> list[str]:
    """The sheets on *image_path*, in reading order. The original if only one.

    Left before right and top before bottom, which is the order the shifts
    run in.
    """
    try:
        import cv2

        page = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        colour = cv2.imread(image_path)
        if page is None or colour is None:
            raise ValueError("not an image this build can read")
        position, axis = find_gutter(page)
    # A page that cannot be examined is read whole: splitting is an
    # improvement, never a precondition.
    except Exception as exc:
        logging.warning(f"Could not look for a gutter in {image_path}: {exc}")
        return [image_path]

    if not axis:
        return [image_path]

    halves = (
        [colour[:, :position], colour[:, position:]] if axis == "vertical"
        else [colour[:position], colour[position:]]
    )

    os.makedirs(workdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(image_path))[0]
    written = []
    for number, half in enumerate(halves, start=1):
        out = os.path.join(workdir, f"{stem}-hoja{number}.jpg")
        cv2.imwrite(out, half, [cv2.IMWRITE_JPEG_QUALITY, 95])
        written.append(out)
    logging.warning(
        f"{os.path.basename(image_path)}: two sheets on one page, split {axis}ly"
    )
    return written
