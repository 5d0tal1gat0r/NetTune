"""The centre's tenants, read from the directory table in the memoria template.

The reader mangles shop names more than anything else on the sheet: it
produced "MAC VEST" and "Parkline" for tenants the template lists as "Mae
West" and "Park Line". Those are not guesses to be made from context -- the
template carries the real list, so a near miss is corrected against it and
anything not close to a real tenant is left exactly as read.

The directory is the table headed Planta / Nº Local / M2 / Actividad / Rótulo.
It is read once and cached: it changes when a unit changes hands, not between
scans.
"""

import difflib
import functools
import logging
import re
import unicodedata

# Below this, two names are different tenants rather than one misread. Chosen
# so "MAC VEST" reaches "Mae Vest" (0.80) while ordinary words reach nothing.
MIN_SIMILARITY = 0.78

# Misreadings too far from the real name for the similarity check to catch,
# each confirmed by the author against the paper. "Posier" is the Poker: the
# reader gets the handwritten k as "si". The key is the misreading's letters,
# the value is how the memoria writes the name.
KNOWN_MISREADS = {"posier": "Poker"}

_HEADER = ("planta", "nº local", "m2", "actividad", "rótulo")

# Matched whatever the case: the reader writes "POSIER" and "posier" as well.
_MISREAD = re.compile(r"\b(" + "|".join(KNOWN_MISREADS) + r")\b", re.I)

# Runs of capitalised or shouted words: how a shop name appears in an entry.
_CANDIDATE = re.compile(
    r"\b[A-ZÑÁÉÍÓÚ][\wñáéíóú]*"
    r"(?:[\s.\-][A-ZÑ][\wñáéíóú]*)*"
)


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in folded if not unicodedata.combining(c))


def _key(name: str) -> str:
    """Compare on letters alone: MAC-VEST, MAC VEST and Mae Vest must meet."""
    return re.sub(r"[^a-z0-9]", "", _fold(name))


@functools.lru_cache(maxsize=4)
def _directory(template_path: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    from docx import Document

    try:
        document = Document(template_path)
    # A missing or unreadable template must never stop a scan.
    except Exception as exc:
        logging.warning(f"Could not read the tenant directory from {template_path}: {exc}")
        return (), ()

    for table in document.tables:
        head = [c.text.strip().lower() for c in table.rows[0].cells]
        if not all(any(h.startswith(want) for h in head) for want in _HEADER):
            continue
        names, numbers = [], []
        for row in table.rows[1:]:
            cells = [c.text.strip() for c in row.cells]
            if len(cells) < 5:
                continue
            if cells[1]:
                numbers.append(cells[1])
            rotulo = cells[4]
            if rotulo and _fold(rotulo) != "rotulo":
                names.append(rotulo)
        return tuple(dict.fromkeys(names)), tuple(dict.fromkeys(numbers))
    return (), ()


def tenant_names(template_path: str) -> tuple[str, ...]:
    return _directory(template_path)[0]


def local_numbers(template_path: str) -> tuple[str, ...]:
    return _directory(template_path)[1]


def correct_names(text: str, template_path: str) -> str:
    """Rewrite a near-miss shop name as the directory writes it.

    Only near misses are touched. A word nowhere near a real tenant is a
    misread the reader should see, not a name to be invented.
    """
    if not text:
        return text
    text = _MISREAD.sub(lambda m: KNOWN_MISREADS[_key(m.group(0))], text)
    names = tenant_names(template_path)
    if not names:
        return text
    by_key = {_key(n): n for n in names}

    def replace(match: re.Match) -> str:
        found = match.group(0)
        key = _key(found)
        if len(key) < 5 or (key in by_key and by_key[key] == found):
            return found
        if key in by_key:
            return by_key[key]
        close = difflib.get_close_matches(key, by_key, n=1, cutoff=MIN_SIMILARITY)
        return by_key[close[0]] if close else found

    return _CANDIDATE.sub(replace, text)
