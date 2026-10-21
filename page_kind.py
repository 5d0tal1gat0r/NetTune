"""Tells the three paper forms apart from their printed headers, for free.

The share receives three forms. The vigilantes' security sheets come two to
a page and are split before reading. The maintenance crew's "Ficha diaria de
trabajo de mantenimiento" is one sheet to a page: split, it was cut through
its middle, the date left on one half and the work on the other, and read
twice over. The parking-ticket log ("Caja de parking", one row per ticket)
is not a log of work at all and is set aside in Parking/ unread.

The printed words settle it before anything is paid for. Tesseract reads the
top of the page upright, then turned each way and upside down, because the
ticket log is printed landscape and scanned sideways, either way round. A
page it cannot place -- tesseract missing, a blank page, a form not seen
before -- is treated as a security sheet, which is what every page was
before this existed.
"""

import logging
import re
import shutil
import subprocess
import tempfile
import unicodedata
from difflib import SequenceMatcher

PARKING = "parking"
MANTENIMIENTO = "mantenimiento"
SEGURIDAD = "seguridad"

# Printed on the form, never written by hand. Two are needed: one word can
# turn up in an entry ("se revisa el parking"), two form headers cannot.
_PARKING_WORDS = ("parking", "ticket", "comercio", "importe")
_MANTENIMIENTO_WORDS = ("ficha", "diaria", "mantenimiento")
_NEEDED = 2

# Tesseract misspells the maintenance header on one sheet in six --
# "fiicha", "daria", "mantenim!ento" -- so its words match when this close.
# Just above "diario" against "diaria" (0.83): the security form's header is
# "INFORME DIARIO". The parking words match exactly, as they are read
# cleanly, and "comercio" would otherwise match the "comercial" printed on
# the maintenance form.
_CLOSE_ENOUGH = 0.85

# Tesseract reads printed capitals well at half the scan's 300 dpi, in
# about half the time.
_OCR_SCALE = 0.5

# Only the top of the page, turned each way, is read: every form prints its
# header there, and a security sheet's handwriting below it is what made a
# whole-page pass slow -- fifteen seconds a page, most of a batch's time.
_HEADER_BAND = 0.3


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", text)


def _close(word: str, words: set[str]) -> bool:
    return word in words or any(
        SequenceMatcher(None, word, other).ratio() >= _CLOSE_ENOUGH for other in words
    )


def kind_from_text(text: str) -> str:
    """The form whose printed words appear in *text*; SEGURIDAD if none."""
    folded = _fold(text)
    if sum(word in folded for word in _PARKING_WORDS) >= _NEEDED:
        return PARKING
    words = set(re.findall(r"[a-z]+", folded))
    if sum(_close(word, words) for word in _MANTENIMIENTO_WORDS) >= _NEEDED:
        return MANTENIMIENTO
    return SEGURIDAD


def _ocr(image) -> str:
    with tempfile.NamedTemporaryFile(suffix=".png") as copy:
        image.save(copy.name)
        try:
            result = subprocess.run(
                ["tesseract", copy.name, "-", "--psm", "11"],
                capture_output=True, text=True, timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logging.warning(f"Page classification could not run tesseract: {exc}")
            return ""
    return result.stdout


def classify(image_path: str) -> str:
    """PARKING, MANTENIMIENTO or SEGURIDAD for one rendered page."""
    if not tesseract_available():
        return SEGURIDAD
    from PIL import Image

    with Image.open(image_path) as image:
        grey = image.convert("L")
    width, height = grey.size
    grey = grey.resize((max(1, int(width * _OCR_SCALE)), max(1, int(height * _OCR_SCALE))))
    # Upright first, the usual case; the ticket log arrives turned either
    # way, and any form can go through the scanner upside down.
    for degrees in (0, 90, 270, 180):
        turned = grey.rotate(degrees, expand=True) if degrees else grey
        band = turned.crop((0, 0, turned.width, max(1, int(turned.height * _HEADER_BAND))))
        kind = kind_from_text(_ocr(band))
        if kind != SEGURIDAD:
            return kind
    return SEGURIDAD
