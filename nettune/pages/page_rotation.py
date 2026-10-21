"""Straightens scanned pages before they are transcribed.

The security sheets come off the scanner rotated 90 degrees, and the Vision
model reads a sideways page very badly: on a real scan it invented most of the
entries, where the same page rotated upright transcribed nearly correctly.

Orientation is detected with tesseract's OSD mode, which is local and free, so
no API call is spent guessing. When tesseract is absent or unsure the page is
left as it is -- a wrong rotation is worse than none.
"""

import logging
import os
import re
import shutil
import subprocess

_ROTATE = re.compile(r"^Rotate:\s*(\d+)", re.MULTILINE)
_CONFIDENCE = re.compile(r"^Orientation confidence:\s*([0-9.]+)", re.MULTILINE)

# Below this, OSD is guessing. Handwriting scores low even when correct, so the
# bar is deliberately near the floor; 0 means tesseract had nothing to go on.
MIN_CONFIDENCE = 0.1

# How many times to ask before giving up. Two is enough for a page turned
# ninety degrees and then flipped; the third guards against OSD that keeps
# reporting a rotation on a page with nothing to read.
MAX_PASSES = 3


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def detect_rotation(image_path: str) -> int:
    """Degrees clockwise the page must turn to be upright. 0 if unknown."""
    if not tesseract_available():
        return 0
    try:
        result = subprocess.run(
            ["tesseract", image_path, "-", "--psm", "0"],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logging.warning(f"Orientation detection failed for {image_path}: {exc}")
        return 0

    output = result.stdout + result.stderr
    rotate = _ROTATE.search(output)
    confidence = _CONFIDENCE.search(output)
    if not rotate:
        return 0
    degrees = int(rotate.group(1)) % 360
    score = float(confidence.group(1)) if confidence else 0.0
    if degrees and score < MIN_CONFIDENCE:
        logging.warning(
            f"Ignoring {degrees} degree rotation for {os.path.basename(image_path)}: "
            f"confidence {score:.2f} too low"
        )
        return 0
    return degrees


def to_portrait(image_path: str) -> str:
    """Turn a sideways sheet portrait. Returns the path.

    After sheet_split every image is one A4-shaped sheet, so a landscape
    image is sideways *by construction* -- no guessing needed, unlike OSD's
    read of the ink on the page. Aspect ratio alone decides whether to turn
    it; OSD is only consulted for which way, because a 90 and a 270 degree
    turn both fix the aspect ratio but only one is upright, and getting it
    backwards would just feed straighten() a page turned twice as far.

    Does not itself guarantee the result is right-side up: a landscape sheet
    turned the wrong quarter-turn is now portrait but upside down, which is
    exactly what straighten()'s existing retry loop is for.
    """
    from PIL import Image

    with Image.open(image_path) as image:
        width, height = image.size
    if width <= height:
        return image_path

    degrees = detect_rotation(image_path)
    if degrees not in (90, 270):
        # OSD had nothing usable -- pick a consistent quarter-turn rather
        # than guess per-image. straighten() below corrects it if it lands
        # upside down.
        degrees = 90

    with Image.open(image_path) as image:
        image.rotate(-degrees, expand=True).save(image_path, quality=95)
    logging.warning(
        f"Turned {os.path.basename(image_path)} portrait ({degrees} degrees)"
    )
    return image_path


# Printed words at the top of every daily report form. Tesseract reads print
# well where it cannot read handwriting, so these settle which way up a sheet
# is when OSD -- guessing from the handwriting at confidences like 0.07 --
# cannot. On September's 84 sheets OSD had left 24 upside down; this found
# every one of them, and called all 60 others upright.
_HEADER_WORDS = re.compile(r"INFORME|DIARIO|Fecha|Servicio|Direcci", re.IGNORECASE)
_HEADER_BAND = 0.22


def _header_words(image) -> int:
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".png") as band:
        image.save(band.name)
        try:
            result = subprocess.run(
                ["tesseract", band.name, "-", "--psm", "6"],
                capture_output=True, text=True, timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            return 0
    return len(_HEADER_WORDS.findall(result.stdout))


def header_orientation(image_path: str) -> str | None:
    """"upright", "upside_down", or None when the form's header cannot tell.

    Looks for the printed header in the top band, and in the bottom band
    turned the right way up. It decides only when one end has header words
    and the other has none; anything less clear -- a form without that
    header, a blank page -- is left to OSD.
    """
    if not tesseract_available():
        return None
    from PIL import Image

    with Image.open(image_path) as image:
        grey = image.convert("L")
        width, height = grey.size
        band = int(height * _HEADER_BAND)
        top = _header_words(grey.crop((0, 0, width, band)))
        bottom = _header_words(grey.crop((0, height - band, width, height)).rotate(180))
    if top and not bottom:
        return "upright"
    if bottom and not top:
        return "upside_down"
    return None


def straighten(image_path: str, *, only_upside_down: bool = False) -> str:
    """Rotate the page upright in place if needed. Returns the path.

    Repeats until OSD reports the page upright. Six of the 42 review images
    from the September batch were still upside down after one pass: OSD only
    sees the remaining 180 degrees once the 90 has been taken out, so a page
    turned twice by the scanner needs turning twice here.

    *only_upside_down* restricts every pass to a 180 degree correction, for
    a caller that already knows the page is portrait by construction -- one
    sheet of a split page, put upright by to_portrait -- rather than merely
    portrait-shaped. Without it, a genuinely sideways full page (the fixture
    below is A4 in file dimensions yet reads 90 degrees off, because the
    paper went into the scanner sideways) would never get its real quarter
    turn; that case still needs the general loop below. With it, a wrong OSD
    reading (a 270 reported on a sheet to_portrait had already corrected,
    which the caller cannot tell from a right one) cannot re-introduce the
    exact sideways result to_portrait was written to remove, because
    only_upside_down never lets it turn the page back onto its side.
    """
    from PIL import Image

    # The printed header first: where it can tell, it is right and OSD is not.
    verdict = header_orientation(image_path)
    if verdict == "upright":
        return image_path
    if verdict == "upside_down":
        with Image.open(image_path) as image:
            image.rotate(180, expand=True).save(image_path, quality=95)
        logging.warning(f"Rotated {os.path.basename(image_path)} by 180 degrees (printed header)")
        return image_path

    total = 0
    for _ in range(MAX_PASSES):
        degrees = detect_rotation(image_path)
        if not degrees:
            break
        if only_upside_down and degrees != 180:
            logging.warning(
                f"Ignoring {degrees} degree rotation for "
                f"{os.path.basename(image_path)}: this sheet is portrait by "
                "construction, so only a 180 degree correction is trusted"
            )
            break
        with Image.open(image_path) as image:
            # PIL rotates counter-clockwise; tesseract reports clockwise.
            image.rotate(-degrees, expand=True).save(image_path, quality=95)
        total = (total + degrees) % 360
    if total:
        logging.warning(f"Rotated {os.path.basename(image_path)} by {total} degrees")
    return image_path


# The quarter turns a person can ask for from the dashboard. Anything else is
# refused rather than normalised: a request for 45 or 360 is a bug or a
# tampered form, and silently rounding it would hide both.
TURNS = (90, 180, 270)


def rotate_by(image_path: str, degrees: int) -> str:
    """Rotate the page *degrees* clockwise in place, no questions asked.

    Separate from straighten() on purpose. straighten() asks tesseract which
    way is up and declines when OSD is unsure, which is right for a batch of
    hundreds but useless for the handful it gives up on -- the September
    batch left 04-09-2026_p14.jpg sideways at "confidence 0.07 too low". A
    person looking straight at the sheet already knows which way is up, so
    this takes the angle from them and does not consult OSD at all.

    Raises ValueError for anything but a quarter turn.
    """
    if degrees not in TURNS:
        raise ValueError(f"Not a quarter turn: {degrees}")

    from PIL import Image

    with Image.open(image_path) as image:
        # PIL rotates counter-clockwise; the caller names clockwise, matching
        # the direction tesseract reports and the direction the buttons show.
        image.rotate(-degrees, expand=True).save(image_path, quality=95)
    logging.warning(
        f"Turned {os.path.basename(image_path)} by hand: {degrees} degrees"
    )
    return image_path
