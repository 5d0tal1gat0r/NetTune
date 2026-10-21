"""Decides which files in the incoming tree are real scans worth processing.

This is the guard that stops the pipeline eating its own output: generated
``.docx`` reports land next to the scan so the colleague can see them, and
without an allowlist the watcher would happily send them back to the Vision API.
"""

import os
from collections.abc import Iterator

from nettune.report.month_folders import OUTPUT_DIR_NAMES, is_in_archive

# Formats the OpenAI Vision API accepts as a data URL.
IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
)

# The office scanner produces multi-page PDFs; each page is rasterised and
# transcribed separately.
DOCUMENT_EXTENSIONS = frozenset({".pdf"})

SCAN_EXTENSIONS = IMAGE_EXTENSIONS | DOCUMENT_EXTENSIONS

# Partial uploads, editor locks and OS droppings.
IGNORED_SUFFIXES = (".tmp", ".part", ".crdownload", ".partial", ".swp", ".filepart")
IGNORED_PREFIXES = (".", "~$")
IGNORED_NAMES = frozenset({"thumbs.db", ".ds_store", "desktop.ini"})



def is_processable_scan(path: str, incoming_dir: str, warn: bool = False) -> bool:
    """True when *path* is a scan image that has not yet been archived.

    Set ``warn`` to log a hint for files a human probably expected to be picked
    up (a PDF dropped in a month folder, most likely).
    """
    name = os.path.basename(path)
    lowered = name.lower()
    extension = os.path.splitext(lowered)[1]

    if is_in_archive(path, incoming_dir):
        return False
    if lowered in IGNORED_NAMES:
        return False
    if name.startswith(IGNORED_PREFIXES):
        return False
    if lowered.endswith(IGNORED_SUFFIXES):
        return False
    if extension not in SCAN_EXTENSIONS:
        return False
    if not os.path.isfile(path):
        return False
    try:
        if os.path.getsize(path) == 0:
            return False
    except OSError:
        return False
    return True


def iter_pending_scans(incoming_dir: str) -> Iterator[str]:
    """Yield every unprocessed scan already sitting in the incoming tree.

    Used at startup so scans dropped while the service was down are not lost,
    and at the start of each month for scans the budget held back.
    """
    if not os.path.isdir(incoming_dir):
        return
    for dirpath, dirnames, filenames in os.walk(incoming_dir):
        dirnames[:] = [d for d in dirnames if d not in OUTPUT_DIR_NAMES]
        for filename in sorted(filenames):
            candidate = os.path.join(dirpath, filename)
            if is_processable_scan(candidate, incoming_dir):
                yield candidate
