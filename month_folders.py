"""Month-folder conventions shared by the watcher, the archiver and the reporter.

Scans are filed by year and Spanish month name, e.g.
``incoming_scans/2026/MARZO/scan.pdf``. What the colleague opens a month
folder to find is the memoria, so it sits in the month folder itself and is
the only thing there to see. The originals already read, the re-scans set
aside and the page images the dashboard shows are kept beside it in dot
folders, which Samba hides: nobody needs to browse past them to find the
document.

Every lookup is made *relative to the incoming root* where one is supplied: an
install at ``/srv/archive/incoming_scans`` or ``/srv/JULIO/scans`` must not have
its own parent directories mistaken for tree structure.
"""

import contextlib
import os
from datetime import datetime

MONTH_FOLDERS = (
    "ENERO",
    "FEBRERO",
    "MARZO",
    "ABRIL",
    "MAYO",
    "JUNIO",
    "JULIO",
    "AGOSTO",
    "SEPTIEMBRE",
    "OCTUBRE",
    "NOVIEMBRE",
    "DICIEMBRE",
)

# Scans already read, kept as they came in. Hidden on the share.
ARCHIVE_DIR_NAME = ".escaneos_originales"
# Page images an entry in the memoria points at, for a human to check against
# the paper. Hidden on the share; the dashboard is where they are looked at.
REVISION_DIR_NAME = ".revision"
# Scans that turned out to be re-scans of paper already read: kept, hidden
# on the share, never read.
DUPLICATES_DIR_NAME = ".duplicados"
# At the top of the share, beside the years: the parking-ticket log, which
# is set aside unread (see page_kind).
PARKING_DIR_NAME = "Parking"
# The names these folders had before, and "processed", which the memoria
# used to be written into. A month laid out that way before
# tools/rename_month_folders.py ran must still never be read as scans.
LEGACY_DIR_NAMES = ("archive", "processed", "revision", "duplicados",
                    "1_escaneos_originales", "2_duplicados")
# Every folder inside a month that holds output, never scans to read.
OUTPUT_DIR_NAMES = (ARCHIVE_DIR_NAME, REVISION_DIR_NAME, DUPLICATES_DIR_NAME,
                    PARKING_DIR_NAME, *LEGACY_DIR_NAMES)

# Scans are filed by year, then month: incoming_scans/2026/JUNIO/.
#
# A year is a rule, not a list. It used to be the tuple 2026-2030, which
# made 2031 -- or old paper logs filed under 2025 -- silently yearless: the
# folder was not recognised, and a date read off the sheet was thrown away
# as a misreading. The rule keeps that protection (a handwritten 2026 read
# as 2062 is still rejected) without an expiry date.
FIRST_YEAR = 2000


def is_year(value) -> bool:
    """True for a four-digit year from FIRST_YEAR to next year."""
    text = str(value)
    if len(text) != 4 or not text.isdigit():
        return False
    return FIRST_YEAR <= int(text) <= datetime.now().year + 1


def years_to_lay_out() -> tuple[str, ...]:
    """The years ensure_month_tree creates folders for: this one and the next.

    Next year too, so the folder is already there to drop into on the first
    working day of January. Folders for other years are only made when a
    scan needs one, rather than sixty empty ones up front.
    """
    this_year = datetime.now().year
    return (str(this_year), str(this_year + 1))


def month_sort_key(year: str, month: str) -> tuple:
    """Chronological key for a year/month pair; unknown names sort last."""
    return (
        int(year) if str(year).isdigit() else 99999,
        MONTH_FOLDERS.index(month) if month in MONTH_FOLDERS else 99,
    )


def _parts(path: str, root: str = "") -> list[str]:
    """Path components, relative to *root* when the path sits inside it."""
    if root:
        try:
            relative = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
        except ValueError:  # different drives on Windows
            relative = path
        if not relative.startswith(".." + os.sep) and relative != "..":
            path = relative
    return [part for part in path.replace("\\", "/").split("/") if part]


def get_month_folder(file_path: str, incoming_dir: str = "") -> str:
    """Return the month folder a path sits under, or "" if there is none."""
    for part in _parts(file_path, incoming_dir):
        if part in MONTH_FOLDERS:
            return part
    return ""


def get_year_folder(file_path: str, incoming_dir: str = "") -> str:
    """Return the year folder a path sits under, or "" if there is none."""
    for part in _parts(file_path, incoming_dir):
        if is_year(part):
            return part
    return ""


def memoria_name(year: str, month: str, draft: bool = False) -> str:
    """Filename of the monthly memoria, matching the hand-written convention.

    The draft -- written while sheets are still to be checked -- says so.
    """
    suffix = " (BORRADOR)" if draft else ""
    return f"MEMORIA {year} {month}{suffix}.docx"


def is_in_archive(file_path: str, incoming_dir: str = "") -> bool:
    """True when any *directory component* inside the tree is the archive folder."""
    parts = _parts(file_path, incoming_dir)[:-1]
    # The review copies are outputs too: re-reading them would transcribe the
    # same page a second time and bill for it.
    return bool(set(OUTPUT_DIR_NAMES) & set(parts))


def month_dir_for(incoming_dir: str, year: str, month: str) -> str:
    parts = [incoming_dir, year, month]
    return os.path.join(*[p for p in parts if p])


def archive_dir_for(incoming_dir: str, year: str, month: str = "") -> str:
    """Archive directory for a month, falling back to a root-level archive."""
    return os.path.join(month_dir_for(incoming_dir, year, month), ARCHIVE_DIR_NAME)


def processed_dir_for(incoming_dir: str, year: str, month: str = "") -> str:
    """Where the monthly memoria is written: the month folder itself."""
    return month_dir_for(incoming_dir, year, month)


def revision_dir_for(incoming_dir: str, year: str, month: str = "") -> str:
    """Where the pages a human has to check are copied."""
    return os.path.join(month_dir_for(incoming_dir, year, month), REVISION_DIR_NAME)


def parking_dir_for(incoming_dir: str) -> str:
    """Where parking-ticket pages are set aside, beside the year folders."""
    return os.path.join(incoming_dir, PARKING_DIR_NAME)


def ensure_month_tree(incoming_dir: str, mode: int = 0o777) -> None:
    """Create year/month folders with archive and revision, and Parking/,
    writable for Samba."""
    parking = parking_dir_for(incoming_dir)
    os.makedirs(parking, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(parking, mode)
    for year in years_to_lay_out():
        for month in MONTH_FOLDERS:
            month_dir = month_dir_for(incoming_dir, year, month)
            archive = os.path.join(month_dir, ARCHIVE_DIR_NAME)
            revision = os.path.join(month_dir, REVISION_DIR_NAME)
            for path in (month_dir, archive, revision):
                os.makedirs(path, exist_ok=True)
                # Non-fatal: the share may be owned by another account.
                with contextlib.suppress(OSError):
                    os.chmod(path, mode)
