"""Google Cloud Vision as a second, non-generative reader.

Same role as azure_ocr, and chosen over it only because the Azure signup would
not complete. The reason for having it at all is unchanged: a vision-language
model that cannot read a handwritten word emits a plausible Spanish one, and
two passes of that model emit the *same* plausible word, so they agree and the
line is never flagged. Cloud Vision is not a language model. An unreadable word
comes back as broken characters carrying a low confidence, never as a fluent
sentence, so disagreement between the two engines says something about the page
rather than about the sampler.

DOCUMENT_TEXT_DETECTION is the dense-document mode and the only one that scores
confidence by default. Authentication is a restricted API key on the query
string, so the Raspberry Pi needs no credentials file and no Google SDK.

One thing Azure would have given and this does not: table structure. Vision
returns paragraphs, not rows, so entries the sheet keeps in separate cells can
still arrive joined.
"""

import base64
import json
import logging
import os
import urllib.error
import urllib.request

ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"

# Breaks that end a line rather than separate two words on one.
_LINE_BREAKS = frozenset({"EOL_SURE_SPACE", "LINE_BREAK"})

# Google advises against language hints when autodetection suffices, but these
# pages are Spanish cursive and the handwriting variant is worth asking for.
DEFAULT_LANGUAGE_HINTS = "es,es-t-i0-handwrit"


class VisionOcrError(RuntimeError):
    """The call failed. Retryable."""


def api_key() -> str:
    return os.getenv("GOOGLE_VISION_API_KEY", "").strip()


def available() -> bool:
    return bool(api_key())


def _language_hints() -> list[str]:
    raw = os.getenv("GOOGLE_VISION_LANGUAGE_HINTS", DEFAULT_LANGUAGE_HINTS)
    return [hint.strip() for hint in raw.split(",") if hint.strip()]


def _annotate(image_path: str) -> dict:
    with open(image_path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode("ascii")
    body = json.dumps({
        "requests": [{
            "image": {"content": encoded},
            "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
            "imageContext": {"languageHints": _language_hints()},
        }]
    }).encode("utf-8")

    request = urllib.request.Request(
        f"{ENDPOINT}?key={api_key()}",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        payload = json.loads(urllib.request.urlopen(request, timeout=120).read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise VisionOcrError(f"{exc.code} {exc.reason}: {detail}") from exc
    except OSError as exc:
        raise VisionOcrError(f"Could not reach Cloud Vision: {exc}") from exc

    response = (payload.get("responses") or [{}])[0]
    # A failed page reports its error in the body with HTTP 200.
    if "error" in response:
        raise VisionOcrError(response["error"].get("message", "unknown error"))
    return response


def _words_to_lines(paragraph: dict) -> list[dict]:
    """Split a paragraph into lines, the way the page itself is laid out.

    Vision nests symbols under words under paragraphs and marks where a line
    ends on the symbol that ends it, so the lines have to be rebuilt from the
    break markers rather than read off directly.
    """
    lines: list[dict] = []
    words: list[str] = []
    scores: list[float] = []

    for word in paragraph.get("words", []):
        symbols = word.get("symbols", [])
        words.append("".join(symbol.get("text", "") for symbol in symbols))
        if word.get("confidence") is not None:
            scores.append(word["confidence"])

        last = symbols[-1] if symbols else {}
        break_type = (
            last.get("property", {}).get("detectedBreak", {}).get("type", "")
        )
        if break_type in _LINE_BREAKS:
            text = " ".join(words).strip()
            if text:
                # A line is only as trustworthy as its worst word: one
                # unreadable word is enough to make the entry wrong.
                lines.append({
                    "text": text,
                    "confidence": min(scores) if scores else None,
                })
            words, scores = [], []

    text = " ".join(words).strip()
    if text:
        lines.append({"text": text, "confidence": min(scores) if scores else None})
    return lines


def read_page(image_path: str) -> dict:
    """Transcribe one page.

    Returns lines in reading order with a confidence each, and the paragraphs
    the engine found. `rows` is named for the azure_ocr interface but holds
    paragraphs: Cloud Vision does not detect tables.
    """
    if not available():
        raise VisionOcrError(
            "GOOGLE_VISION_API_KEY is not set. See tools/README.md."
        )
    annotation = _annotate(image_path).get("fullTextAnnotation", {})

    lines: list[dict] = []
    rows: list[str] = []
    for page in annotation.get("pages", []):
        for block in page.get("blocks", []):
            for paragraph in block.get("paragraphs", []):
                found = _words_to_lines(paragraph)
                lines.extend(found)
                joined = " ".join(line["text"] for line in found).strip()
                if joined:
                    rows.append(joined)

    weak = sum(1 for line in lines if (line["confidence"] or 1.0) < 0.8)
    logging.warning(
        f"Cloud Vision read {len(lines)} line(s), {len(rows)} paragraph(s), "
        f"{weak} line(s) below 0.80 confidence"
    )
    return {"lines": lines, "rows": rows, "pages": len(annotation.get("pages", []))}
