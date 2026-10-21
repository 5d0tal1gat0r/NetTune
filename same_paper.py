"""Recognising a re-scan of paper the system has already read.

The colleague scanned 15 and 16 September on the 17th, then scanned the
whole month on the 22nd -- the same eight sheets twice. Read again, the
second scan pays the API a second time and files a second copy of those
days, with near-duplicate lines wherever the two readings differ.

So before a scan is read, each of its sheets is compared with the review
images already saved for the month, on the handwriting box only (the
printed form is the same on every sheet and says nothing about which one
it is), blurred and small, by correlation. Measured on September's 84
sheets: a re-scan of the same paper scored at least 0.92 against its
original; two different sheets never scored above 0.87 across 3486 pairs.

A scan counts as a re-scan only when EVERY sheet matches a DIFFERENT
existing sheet at MATCH or better. Anything less is read as usual: reading
a duplicate costs a little, skipping a new sheet would lose it.
"""

import math
import os

from PIL import Image, ImageFilter

from scan_filter import IMAGE_EXTENSIONS

MATCH = 0.90
_SIZE = (48, 64)
# The "Orden cronologico" box, where each sheet's own handwriting is.
_BOX = (0.08, 0.20, 0.95, 0.80)


def signature(image_path: str) -> list[float]:
    """The sheet's handwriting box, small, blurred and normalised."""
    with Image.open(image_path) as image:
        grey = image.convert("L")
        width, height = grey.size
        box = grey.crop((int(width * _BOX[0]), int(height * _BOX[1]),
                         int(width * _BOX[2]), int(height * _BOX[3])))
        small = box.filter(ImageFilter.GaussianBlur(2)).resize(_SIZE)
    # Plain Python rather than numpy: 3072 values, and the Pi's runtime
    # dependencies stay as they are.
    values = [float(v) for v in small.tobytes()]
    mean = sum(values) / len(values)
    spread = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values)) + 1e-6
    return [(v - mean) / spread for v in values]


# Signatures of the saved review images, kept for the life of the service:
# a batch dropped anywhere is compared with two or three months of sheets,
# and decoding every full-size JPEG again for each scan is the slow part.
# Keyed by path, size and modification time, so a turned or replaced image
# is read again.
_CACHE: dict[tuple[str, int, int], list[float]] = {}


def _saved_signature(path: str) -> list[float]:
    stat = os.stat(path)
    key = (path, stat.st_size, stat.st_mtime_ns)
    if key not in _CACHE:
        _CACHE[key] = signature(path)
    return _CACHE[key]


def similarity(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True)) / len(a)


def already_read(sheets: list[str], revision_dirs) -> list[tuple[str, str, float]] | None:
    """(sheet, existing image path, score) for each sheet, if the whole scan
    is a re-scan of sheets already saved in *revision_dirs* (one folder or
    several: a batch dropped anywhere is compared with every month it could
    belong to); otherwise None."""
    if isinstance(revision_dirs, str):
        revision_dirs = [revision_dirs]
    if not sheets:
        return None
    existing = {
        os.path.join(folder, name): _saved_signature(os.path.join(folder, name))
        for folder in revision_dirs if os.path.isdir(folder)
        for name in sorted(os.listdir(folder))
        if os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS
    }
    # Only the folders compared now stay cached, so a Pi running for years
    # holds two or three months of signatures, not all of them.
    for key in [k for k in _CACHE if k[0] not in existing]:
        del _CACHE[key]
    if len(existing) < len(sheets):
        return None
    matches, used = [], set()
    for sheet in sheets:
        own = signature(sheet)
        scored = sorted(
            ((similarity(own, sig), path) for path, sig in existing.items() if path not in used),
            reverse=True,
        )
        if not scored or scored[0][0] < MATCH:
            return None
        score, path = scored[0]
        used.add(path)
        matches.append((sheet, path, score))
    return matches
