"""Reconciles several independent reads of the same handwritten page.

Cursive cannot be transcribed perfectly. Measured on a real sheet, the word
"aire" was read as "cobre" by most passes and correctly by one. The point of
reading a page several times is therefore not to average toward the truth --
the majority can be wrong -- but to surface *where the reads disagree*, so a
human checks those lines and trusts the rest.
"""

import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

from nettune.report.routine_rules import strip_time_prefix

# Two entries this similar after normalisation are the same line, read slightly
# differently, rather than two different lines.
_SAME_LINE = 0.72

# What a reading adds to a line marked on the paper with a circled X or red
# ink -- the maintenance crew's sign for a parking job. A mark, not words: it
# is taken off before the reads are compared, so one read seeing it and
# another not is not a disagreement about the line.
_PARKING_MARK = re.compile(r"\s*\[\s*parking\s*\]\s*", re.I)


def _unmark(line) -> tuple[str, bool]:
    text = str(line or "")
    return _PARKING_MARK.sub(" ", text).strip(), bool(_PARKING_MARK.search(text))


def normalize(text: str) -> str:
    """Strip accents, case, punctuation and bullets for comparison only."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    text = re.sub(r"^[\s*\-•·.]+", "", text)
    text = re.sub(r"[.,;:!]+$", "", text)
    text = re.sub(r"[^\w\s\[\]?/()-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# Words that carry no fact. Two readings that differ only in these differ
# about grammar, not about what happened: "Apertura de muelle" against
# "Apertura del muelle", "los camaras" against "las camaras".
_FILLER = frozenset({
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    "de", "del", "al", "a", "y", "e", "o", "u", "en",
})


def comparable(text: str) -> str:
    """The form two readings are compared on: what will reach the document.

    The clock time is dropped before the memoria is written, so two readings
    that differ only in the time do not differ about the entry. Articles go
    the same way. Everything that carries a fact -- every zone, floor, number
    and noun -- is kept, so a real difference still reads as one.
    """
    stripped = strip_time_prefix(str(text or ""))
    words = [w for w in normalize(stripped).split() if w not in _FILLER]
    return " ".join(words)


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def _vote(values: list) -> tuple:
    """Most common value, plus every distinct value seen."""
    present = [v for v in values if v not in (None, "", [])]
    if not present:
        return None, []
    keys = [str(v) for v in present]
    winner_key = Counter(keys).most_common(1)[0][0]
    winner = next(v for v in present if str(v) == winner_key)
    return winner, sorted(set(keys))


def consolidate(reads: list[dict], min_reads: int = 2, min_seen: int = 1) -> dict:
    """Merge reads into one result, marking every field as confident or not.

    ``confident`` means every read that saw the field agreed on it, and there
    were at least *min_reads* reads to corroborate it. A single read is never
    confident: nothing has checked it.

    *min_seen* drops entries fewer than that many reads saw at all. A line only
    one read produced is far more likely to be invented than missed by the
    others, and an invented line in this document is worse than a missing one.
    """
    usable = [r for r in reads if r]
    # Each read's lines without the parking mark, and which of them had it.
    marks: dict[int, dict[str, bool]] = {}
    unmarked = []
    for r in usable:
        lines = [_unmark(t) for t in (r.get("trabajos") or [])]
        marks[len(unmarked)] = {}
        for text, marked in lines:
            marks[len(unmarked)][text] = marks[len(unmarked)].get(text, False) or marked
        unmarked.append({**r, "trabajos": [text for text, _ in lines]})
    usable = unmarked
    if not usable:
        return {"fecha": None, "fecha_confident": False, "fecha_variants": [],
                "horario": None,
                "operarios": [], "operarios_confident": False, "trabajos": []}

    corroborated = len(usable) >= min_reads

    fecha, fecha_variants = _vote([r.get("fecha") for r in usable])
    # The shift's start time: it orders a day's sheets. A read that did not
    # see it does not vote.
    horario, _ = _vote([r.get("horario") for r in usable if r.get("horario")])
    operarios, operarios_variants = _vote(
        [tuple(r.get("operarios") or []) for r in usable]
    )

    # The canonical number of entries is what most reads saw; a pass that
    # hallucinates an extra line should not add one, and a pass that drops a
    # line should not remove one.
    counts = [len(r.get("trabajos") or []) for r in usable if r.get("trabajos")]
    canonical = Counter(counts).most_common(1)[0][0] if counts else 0
    reference = next(
        (r["trabajos"] for r in usable if len(r.get("trabajos") or []) == canonical), []
    )

    trabajos = []
    for line in reference:
        variants = []
        marked = 0
        for index, r in enumerate(usable):
            entries = r.get("trabajos") or []
            if not entries:
                continue
            best = max(entries, key=lambda e: _similar(line, e))
            if _similar(line, best) >= _SAME_LINE:
                variants.append(str(best).strip())
                marked += marks[index].get(best, False)
            else:
                variants.append(None)   # this read did not see this line

        seen = [v for v in variants if v]
        # Compared on what reaches the document (comparable): a different
        # clock time or article is not a disagreement about the entry.
        distinct = sorted({comparable(v) for v in seen})
        missing = any(v is None for v in variants)
        text, _ = _vote(seen)
        if len(seen) < min_seen:
            continue
        trabajos.append({
            "text": (text or line).strip(),
            "confident": corroborated and len(distinct) == 1 and not missing,
            "variants": sorted({v for v in seen}) if len(distinct) > 1 else [],
            "seen_by": len(seen),
            "of": len(usable),
            # At least half the reads that saw the line saw the mark.
            "parking_mark": bool(seen) and marked * 2 >= len(seen),
        })

    return {
        "fecha": fecha,
        "fecha_confident": corroborated and len(fecha_variants) == 1,
        "fecha_variants": fecha_variants,
        "horario": horario,
        "operarios": list(operarios) if operarios else [],
        "operarios_confident": corroborated and len(operarios_variants) == 1,
        "trabajos": trabajos,
    }
