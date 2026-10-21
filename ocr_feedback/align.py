"""Which line of one stage is which line of the next.

Never forced: below the profile's threshold a stage has no match, and the
record says how close the best candidate came.
"""

import re
import unicodedata
from difflib import SequenceMatcher


def normalize(text: str, fold_accents: bool = True, strip_punctuation: bool = True) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")) if fold_accents else str(text or "")
    if fold_accents:
        text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    text = re.sub(r"^[\s*\-•·.]+", "", text)
    if strip_punctuation:
        text = re.sub(r"[^\w\s/]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def ratio(a: str, b: str, profile) -> float:
    na = normalize(a, profile.fold_accents, profile.strip_punctuation)
    nb = normalize(b, profile.fold_accents, profile.strip_punctuation)
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def best_match(anchor: str, lines: list, profile):
    best, score = None, 0.0
    for line in lines:
        r = ratio(anchor, line.text, profile)
        if r > score:
            best, score = line, r
    if best is None or score < profile.same_line:
        return None, score
    return best, score


def _contains_tokens(whole: list, part: list) -> bool:
    n = len(part)
    return any(whole[i:i + n] == part for i in range(len(whole) - n + 1))


def contains_match(anchor: str, lines: list, profile):
    """Fallback for joined or split lines: the candidate whose normalized token
    sequence contains the anchor's (joined) or is contained in it (split).
    The shorter side must have at least 2 tokens and 8 characters, so a short
    anchor never attaches to a longer unrelated line. Highest ratio wins.
    Returns (None, 0.0) when nothing qualifies."""
    na = normalize(anchor, profile.fold_accents, profile.strip_punctuation)
    best, score = None, 0.0
    ta = na.split()
    if not ta:
        return None, score
    for line in lines:
        nl = normalize(line.text, profile.fold_accents, profile.strip_punctuation)
        tl = nl.split()
        if not tl:
            continue
        short, long_ = (ta, tl) if len(ta) <= len(tl) else (tl, ta)
        if len(short) < 2 or len(" ".join(short)) < 8 or not _contains_tokens(long_, short):
            continue
        r = ratio(anchor, line.text, profile)
        if best is None or r > score:
            best, score = line, r
    return best, score
