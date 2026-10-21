"""Routes a maintenance entry to one of the memoria's four fixed subheadings.

The model is asked to classify, but an unrecognised or missing answer must not
drop an entry, so a keyword fallback assigns one. "Otros" is the catch-all the
author's own document uses for everything that is not electrical, vertical
transport or parking.
"""

import re
import unicodedata

ELECTRICIDAD = "Electricidad y Alumbrado"
ASCENSORES = "Ascensores, rampas, escaleras y puertas"
PARKING = "Parking"
OTROS = "Otros"

BLOCKS = (ELECTRICIDAD, ASCENSORES, PARKING, OTROS)

# What the dashboard's tag chips say, and what its URLs carry. A full
# subheading is too long for a chip, and its commas and spaces make a poor
# query string.
SHORT_NAMES = {
    ELECTRICIDAD: "Electricidad",
    ASCENSORES: "Ascensores",
    PARKING: "Parking",
    OTROS: "Otros",
}
SLUGS = {
    "electricidad": ELECTRICIDAD,
    "ascensores": ASCENSORES,
    "parking": PARKING,
    "otros": OTROS,
}


def slug_of(block: str) -> str:
    """The URL name of a maintenance block, or "" for any other block."""
    return next((slug for slug, name in SLUGS.items() if name == block), "")


def block_from_slug(slug) -> str:
    """The block a URL name stands for, or "" -- never the input echoed."""
    if not isinstance(slug, str):
        return ""
    return SLUGS.get(slug.strip().lower(), "")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


_PARKING = (
    "parking", "aparcamiento", "cargador", "plaza", "minusvalido",
    "planta -1", "planta -2", "p-1", "p-2", "sotano",
)
_ASCENSORES = (
    "ascensor", "montacargas", "rampa", "escalera", "schindler", "puerta",
    "manivela", "iman", "pasamanos", "presionador", "portico",
)
# No "contador": a meter visit (Endesa, Aguasur, a broken water-meter tap)
# is filed under Otros in the author's hand-labelled lines.
_ELECTRICIDAD = (
    "cuadro electrico", "cuadros electricos", "alumbrado", "luz", "luces",
    "lampara", "tubo", "plc", "foco", "acometida electrica",
    "grupo electrogeno", "electricista", "magnetotermico",
)


def normalise(raw) -> str:
    """Map whatever the model returned onto one of the four blocks, or ""."""
    if not isinstance(raw, str):
        return ""
    folded = _fold(raw)
    if "electric" in folded or "alumbrado" in folded:
        return ELECTRICIDAD
    if any(w in folded for w in ("ascensor", "rampa", "escalera", "puerta")):
        return ASCENSORES
    if "parking" in folded:
        return PARKING
    if "otro" in folded:
        return OTROS
    return ""


def classify(text: str) -> str:
    """Pick a block from the entry's own words. Never returns "" -- Otros is the
    author's own catch-all, so an unclassifiable entry still has a home."""
    folded = _fold(text)
    # Parking wins: the memoria groups by where the work happened.
    if any(w in folded for w in _PARKING):
        return PARKING
    if any(w in folded for w in _ASCENSORES):
        return ASCENSORES
    if any(w in folded for w in _ELECTRICIDAD):
        return ELECTRICIDAD
    return OTROS


# The time a job took, "(2H)", "(1 hora)", "(1,5 horas)": only parking work
# is written down with one, so it settles the block whatever the model said.
_DURATION = re.compile(r"\(\s*\d+(?:[.,]\d+)?\s*(h|hora|horas)\.?\s*\)", re.I)


def has_duration(text: str) -> bool:
    return bool(_DURATION.search(str(text or "")))


def strip_duration(text: str) -> str:
    """"Desatoro en aseo (2H)." -> "Desatoro en aseo." The duration has done
    its work once the block is decided; the memoria does not carry it."""
    stripped = _DURATION.sub("", str(text or ""))
    stripped = re.sub(r"\s+([.,;:])", r"\1", stripped)
    return re.sub(r"\s{2,}", " ", stripped).strip()


def decide(model_answer, text: str) -> str:
    """Parking for a line with a duration; else the model's block if it named
    a real one, else one from the text."""
    if has_duration(text):
        return PARKING
    return normalise(model_answer) or classify(text)


