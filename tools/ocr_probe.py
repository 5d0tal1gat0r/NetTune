"""Compares Document Intelligence against the Vision model on real scans.

The question this answers is narrow and worth answering before changing the
pipeline: do the two engines fail on the same words? If they do, a second
engine buys nothing and the handwriting is simply illegible. If they do not,
their disagreement locates the lines a human should check, which two passes of
one model never managed -- both passes invent the same plausible word and agree.

Reads nothing from the ledger and writes nothing to it, so it can be run
against production scans without touching the month's documents.

    ./venv/bin/python tools/ocr_probe.py ~/Downloads/SKM_*.pdf

The second engine is whichever one has credentials in .env: Cloud Vision or
Document Intelligence. Both answer the same question, so either will do.
"""

import argparse
import difflib
import json
import logging
import os
import sys
import tempfile
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gcv_ocr
import pdf_pages
from config import config
from page_rotation import straighten
from spend_guard import SpendGuard
from transcription_service import read_page as gpt_read_page

# Below this, two lines are different entries rather than two readings of one.
# 0.6 keeps "Se colocan pilonas Z1" beside "Se colocan pilonas 21" and still
# separates it from an unrelated line.
MATCH_FLOOR = 0.6

# Both engines score every word. Anything under this is the engine telling you
# it could not read the word, which is the signal the Vision model never gives.
LOW_CONFIDENCE = 0.80

ENGINE = gcv_ocr

# The OCR engines read the whole sheet; the prompt tells the model to
# transcribe only the box of events. Comparing the two directly counts every
# printed form label as a line the model missed, which is not a finding. These
# mark where that box starts and ends on both sheet types.
_BODY_START = ("descripcion de los trabajos", "orden cronologico", "acontecimientos")
_BODY_END = ("observaciones", "visto bueno", "firma del")


def _fold(text: str) -> str:
    """Lowercase and strip accents, so a marker matches however it was read."""
    folded = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in folded if not unicodedata.combining(c))


def body_lines(lines: list[dict]) -> list[dict]:
    """The lines inside the box of events, dropping the printed form around it.

    Falls back to every line when neither marker is found: losing the page
    entirely would be worse than comparing a few headers.
    """
    start, end = 0, len(lines)
    for index, line in enumerate(lines):
        folded = _fold(line["text"])
        if start == 0 and any(marker in folded for marker in _BODY_START):
            start = index + 1
        elif start and any(marker in folded for marker in _BODY_END):
            end = index
            break
    return lines[start:end] if start else lines


def _similarity(left: str, right: str) -> float:
    return difflib.SequenceMatcher(None, left.lower(), right.lower()).ratio()


def align(gpt: list[str], other: list[str]) -> list[tuple[str | None, str | None, float]]:
    """Pair each GPT line with its closest line from the other engine."""
    pairs: list[tuple[str | None, str | None, float]] = []
    unclaimed = list(range(len(other)))
    for line in gpt:
        best, score = None, 0.0
        for index in unclaimed:
            ratio = _similarity(line, other[index])
            if ratio > score:
                best, score = index, ratio
        if best is not None and score >= MATCH_FLOOR:
            unclaimed.remove(best)
            pairs.append((line, other[best], score))
        else:
            pairs.append((line, None, 0.0))
    for index in unclaimed:
        pairs.append((None, other[index], 0.0))
    return pairs


def _mark(gpt_line: str | None, engine_line: str | None, score: float) -> str:
    if gpt_line is None:
        return "ENGINE-ONLY"
    if engine_line is None:
        return "GPT-ONLY"
    if score >= 0.995:
        return "AGREE"
    return "DIFFER"


def probe_page(image_path: str, guard, engine) -> dict:
    """Read one page with both engines and align the results."""
    gpt = gpt_read_page(image_path, guard=guard)
    # One reading returns plain strings; consolidate() is what turns them into
    # {"text": ...}. The probe reads a single pass, so accept both shapes.
    gpt_lines = [
        entry["text"] if isinstance(entry, dict) else str(entry)
        for entry in gpt.get("trabajos", [])
    ]

    other = engine.read_page(image_path)
    body = body_lines(other["lines"])
    engine_lines = [line["text"] for line in body]
    confidence = {line["text"]: line["confidence"] for line in body}

    pairs = []
    for gpt_line, engine_line, score in align(gpt_lines, engine_lines):
        pairs.append({
            "verdict": _mark(gpt_line, engine_line, score),
            "gpt": gpt_line,
            "engine": engine_line,
            "similarity": round(score, 3),
            "engine_confidence": confidence.get(engine_line),
        })
    return {
        "image": os.path.basename(image_path),
        "gpt_tipo": gpt.get("tipo"),
        "gpt_lines": len(gpt_lines),
        "engine_lines": len(engine_lines),
        "engine_lines_whole_sheet": len(other["lines"]),
        "engine_rows": other["rows"],
        "pairs": pairs,
    }


def _print_page(page: dict, engine_name: str) -> None:
    label = engine_name.ljust(6)[:6]
    print(f"\n=== {page['image']} ===")
    print(f"gpt {page['gpt_lines']} line(s)  "
          f"{engine_name} {page['engine_lines']} line(s)")
    for pair in page["pairs"]:
        score = pair["engine_confidence"]
        unsure = score is not None and score < LOW_CONFIDENCE
        print(f"\n  [{pair['verdict']}] similarity {pair['similarity']}"
              f"{'' if score is None else f' confidence {score:.2f}'}"
              f"{' <-- engine unsure' if unsure else ''}")
        print(f"    gpt   : {pair['gpt'] or '-'}")
        print(f"    {label}: {pair['engine'] or '-'}")
    if page["engine_rows"]:
        print(f"\n  {engine_name} blocks ({len(page['engine_rows'])}):")
        for row in page["engine_rows"]:
            print(f"    {row}")


def _summarise(pages: list[dict]) -> None:
    counts: dict[str, int] = {}
    unsure = 0
    for page in pages:
        for pair in page["pairs"]:
            counts[pair["verdict"]] = counts.get(pair["verdict"], 0) + 1
            score = pair["engine_confidence"]
            if score is not None and score < LOW_CONFIDENCE:
                unsure += 1
    total = sum(counts.values())
    print("\n=== summary ===")
    for verdict in ("AGREE", "DIFFER", "GPT-ONLY", "ENGINE-ONLY"):
        count = counts.get(verdict, 0)
        share = f"{100 * count / total:.0f}%" if total else "-"
        print(f"  {verdict:<12} {count:>4}  {share}")
    print(f"  engine below {LOW_CONFIDENCE:.2f} confidence: {unsure}")
    print("\n  DIFFER and low-confidence lines are the ones worth reading by hand.")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="PDF or image files to probe")
    parser.add_argument("--out", default="tools/probe_out", help="where to write the JSON")
    parser.add_argument("--limit", type=int, default=0, help="stop after N pages")
    args = parser.parse_args()

    engine_name, engine = "google", ENGINE
    if not engine.available():
        print("GOOGLE_VISION_API_KEY is not set in .env.", file=sys.stderr)
        print("See tools/README.md for where to get it.", file=sys.stderr)
        return 2

    guard = SpendGuard(config.spend_db, config.monthly_budget_eur, config.eur_usd)
    os.makedirs(args.out, exist_ok=True)
    pages: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="ocr-probe-") as workdir:
        images: list[str] = []
        for path in args.paths:
            if pdf_pages.is_pdf(path):
                target = os.path.join(workdir, os.path.basename(path))
                images.extend(pdf_pages.render_pages(path, target, dpi=config.pdf_dpi))
            else:
                images.append(path)
        if args.limit:
            images = images[: args.limit]

        for image in images:
            if config.auto_rotate:
                straighten(image)
            try:
                pages.append(probe_page(image, guard, engine))
            # A probe reports what happened; one bad page must not lose the rest.
            except Exception as exc:
                print(f"\n=== {os.path.basename(image)} === FAILED: {exc}")
                continue
            _print_page(pages[-1], engine_name)

    if not pages:
        print("No page was read.", file=sys.stderr)
        return 1

    destination = os.path.join(args.out, "probe.json")
    with open(destination, "w", encoding="utf-8") as handle:
        json.dump(pages, handle, ensure_ascii=False, indent=2)
    _summarise(pages)
    print(f"\nFull result: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
