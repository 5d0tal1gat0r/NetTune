"""Marks the entries a human has to check, and points at the page they came from.

Handwriting cannot be read reliably, and the failure that matters is the
silent one: a line the model could not read comes back as fluent Spanish and
nothing says so. Two readings of the same model often agree on the same wrong
word, so the reader of the finished memoria has no way to tell a certain entry
from a guessed one.

An entry in doubt therefore carries a locator into the document itself --
"Se abre el torreon de zona [?] a los tecnicos. [22-06-2026 p2]" -- and the
page image is copied under that exact name into the month's review folder. The
colleague reads the marker, opens the image, and checks the line against the
paper.
"""

import os
import re

from batch_dates import parse_date
from routine_rules import is_incoherent

IMAGE_SUFFIX = ".jpg"

# Keeps the fallback locator readable in the middle of a sentence.
_MAX_STEM = 24

# What the model writes when it cannot read a word. It already does this
# unprompted, so the mark is respected rather than reinvented.
_SELF_MARKED = re.compile(r"\[\s*\?\s*\]")

_UNSAFE = re.compile(r"[^0-9A-Za-z._-]+")

# Seguridad and Mantenimiento number their sheets each from 1, as the
# colleague reads them, so a maintenance sheet and a security sheet can share
# date and number. This mark in front of a maintenance sheet's reference keeps
# the two apart in the store and in the review folder; the dashboard never
# shows it (plain_ref).
MAINTENANCE_MARK = "mant "
# The same mark on the image's file name: mant_01-09-2026_p2.jpg.
MAINTENANCE_IMAGE_PREFIX = "mant_"


def is_maintenance_ref(review_ref: str) -> bool:
    """True for a maintenance sheet's reference."""
    return (review_ref or "").startswith(MAINTENANCE_MARK)


def plain_ref(review_ref: str) -> str:
    """The reference as the colleague reads it: "01-09-2026 p2"."""
    text = review_ref or ""
    return text[len(MAINTENANCE_MARK):] if is_maintenance_ref(text) else text


def same_kind(new_plain: str, like: str) -> str:
    """*new_plain* marked as a maintenance sheet when *like* is one."""
    return MAINTENANCE_MARK + new_plain if is_maintenance_ref(like) else new_plain


def locator(fecha: str | None, page_number: int, source_name: str,
            maintenance: bool = False) -> str:
    """How the reader finds the page: its date and page number.

    The date is what the colleague recognises -- it is written at the top of
    every sheet -- so it names the page wherever it could be read. Only when
    the date is illegible does the scan's own filename stand in. A
    maintenance sheet carries MAINTENANCE_MARK in front.
    """
    mark = MAINTENANCE_MARK if maintenance else ""
    parsed = parse_date(fecha)
    if parsed:
        return f"{mark}{parsed:%d-%m-%Y} p{page_number}"
    stem = os.path.splitext(os.path.basename(source_name or "scan"))[0]
    return f"{mark}{stem[:_MAX_STEM]} p{page_number}"


_DATED = re.compile(r"^\d{2}-\d{2}-\d{4} p\d+$")
_PAGE = re.compile(r" p(\d+)$")

# The date slot for a sheet whose date is unknown: illegible, or never read
# because the sheet was rebuilt from the archive.
UNDATED = "sin-fecha"


def image_name(mark_text: str) -> str:
    """Filename for the page image: DD-MM-YYYY_pN.jpg, or sin-fecha_pN.jpg.

    The colleague reads "[22-06-2026 p2]" and looks for 22-06-2026_p2.jpg;
    there is nothing to translate. A sheet with no date used to be named
    after its scan -- SKM_C30826092211360_p27.jpg beside 01-09-2026_p2.jpg
    in the same folder -- so it now takes the same shape with "sin-fecha" in
    the date's place. The reference itself still names the scan; only the
    file is spelled the one way.

    Anything that could point outside the review folder is stripped, because
    the locator is built from text a model read off a scan.
    """
    text = plain_ref((mark_text or "").strip())
    if not _DATED.match(text):
        page = _PAGE.search(text)
        if page:
            text = f"{UNDATED} p{page.group(1)}"
    safe = _UNSAFE.sub("_", text.replace(" ", "_")).strip("._-")
    # A maintenance sheet's image beside a security sheet of the same date
    # and number: mant_01-09-2026_p2.jpg and 01-09-2026_p2.jpg.
    prefix = MAINTENANCE_IMAGE_PREFIX if is_maintenance_ref(mark_text or "") else ""
    return prefix + (safe or "pagina") + IMAGE_SUFFIX


def legacy_image_name(mark_text: str) -> str:
    """The name image_name gave before undated sheets were renamed.

    Only for moving existing files to the new names.
    """
    safe = _UNSAFE.sub("_", (mark_text or "").replace(" ", "_")).strip("._-")
    return (safe or "pagina") + IMAGE_SUFFIX


def needs_review(entry: dict, page: dict) -> bool:
    """True when a human should check this entry against the paper."""
    if not entry.get("confident", True):
        return True
    text = entry.get("text") or ""
    if _SELF_MARKED.search(text):
        return True
    # A line that does not read as Spanish a vigilante would write, or that
    # names a floor the building has not got, was misread however sure the
    # passes were about it.
    # A doubtful date is not a doubt about the lines: it flagged every line
    # of the sheet, however clean -- 136 of September's 194 flags sat on
    # sheets flagged whole. The date is questioned on its own in the
    # dashboard (EntryStore.date_checks), which keeps the sheet to check.
    return entry.get("coherent") is False or is_incoherent(text)


def mark(text: str, mark_text: str) -> str:
    """Append the locator, leaving any mark the model made itself in place."""
    stripped = (text or "").strip()
    if not stripped:
        return text
    suffix = f"[{mark_text}]"
    if stripped.endswith(suffix):
        return text
    return f"{stripped} {suffix}"
