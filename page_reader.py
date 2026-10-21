"""Reads one page several times and reconciles the readings.

A single reading of cursive is not trustworthy and, worse, is not *visibly*
untrustworthy. Reading the page independently several times and comparing turns
a silent error into a flagged line.
"""

import logging

from config import config
from consensus import consolidate
from document_type import decide
from illegible import collapse
from spend_guard import BudgetExceeded
from transcription_service import RefusalError, TranscriptionError, read_page


def read_page_with_consensus(
    image_path: str, guard=None, readings: int = 3, model: str | None = None,
    collector: list | None = None,
) -> dict:
    """Return a consolidated reading of *image_path*.

    Raises TranscriptionError if no pass succeeded, so the caller can retry.
    BudgetExceeded propagates untouched: that is not a transient failure.
    *collector*, when given, receives each pass as read, before consensus
    (for ocr_feedback); the result is the same with or without it.
    """
    collected = []
    refusals = 0

    for attempt in range(1, readings + 1):
        try:
            reading = read_page(image_path, guard=guard, model=model)
            collected.append(reading)
            if collector is not None:
                collector.append(reading)
        except BudgetExceeded:
            if collected:
                logging.warning(
                    f"Budget reached after {len(collected)} of {readings} readings; "
                    "consolidating what we have"
                )
                break
            raise
        except RefusalError as exc:
            refusals += 1
            logging.warning(f"Reading {attempt}/{readings} unusable: {exc}")
        except TranscriptionError as exc:
            logging.warning(f"Reading {attempt}/{readings} failed: {exc}")

    if not collected:
        raise TranscriptionError(
            f"No usable reading of {image_path} after {readings} attempts "
            f"({refusals} refusals)"
        )

    result = consolidate(collected, min_seen=config.min_readings_per_entry)
    result["trabajos"] = collapse(result["trabajos"])
    result["readings"] = len(collected)
    result["titulo"] = next(
        (r.get("titulo") for r in collected if r.get("titulo")), None
    )
    # Settle the document type from the passes' labels, checked against the
    # page's own vocabulary. It decides which filter prompt runs.
    labels = [r.get("tipo") for r in collected if r.get("tipo")]
    result["tipo"] = decide(
        labels[0] if labels else None,
        result["titulo"] or "",
        [t["text"] for t in result["trabajos"]],
    )
    flagged = sum(1 for t in result["trabajos"] if not t["confident"])
    logging.warning(
        f"{len(collected)} reading(s) consolidated: tipo={result['tipo']}, "
        f"{len(result['trabajos'])} entry(ies), {flagged} flagged for review"
    )
    return result
