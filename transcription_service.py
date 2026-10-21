"""OpenAI Vision transcription of a scanned page.

Two behaviours matter here beyond the API call itself:

* The model sometimes *refuses* to transcribe handwriting. The refusal comes
  back as ordinary text, so without detection it flows downstream and becomes a
  report. Measured at 4 refusals in 6 calls with the old prompt; the current
  prompt, which frames the page as the owner's own internal document, measured
  0 in 6.
* Every call is priced against the monthly budget before it is made.
"""

import base64
import io
import json
import os
import re
from datetime import date, datetime

from openai import OpenAI

from config import config
from spend_guard import OutOfCredit

client = OpenAI(api_key=config.openai_api_key)


class TranscriptionError(RuntimeError):
    """The API call failed. Retryable."""


class RefusalError(TranscriptionError):
    """The model declined, or returned something unusable. Retryable."""


# What OpenAI answers, with a 429, when the account's balance is spent. A
# plain rate limit is also a 429 and is worth retrying; these are not.
_NO_CREDIT = ("insufficient_quota", "credit_balance_exhausted")


def is_out_of_credit(exc: Exception) -> bool:
    """True when *exc* is OpenAI saying the account has no credit left."""
    return getattr(exc, "code", None) in _NO_CREDIT or any(
        code in str(exc) for code in _NO_CREDIT
    )


_REFUSAL_PATTERNS = (
    r"^\s*i['\u2019]?m\s+sorry",
    r"^\s*i\s+am\s+sorry",
    r"^\s*sorry[,.]",
    r"^\s*lo\s+siento",
    r"i\s+can['\u2019]?t\s+(assist|help|provide)",
    r"i\s+cannot\s+(assist|help|provide|transcribe)",
    r"i['\u2019]?m\s+unable\s+to\s+(assist|help|transcribe)",
    r"no\s+puedo\s+(ayudar|asistir|transcribir)",
)

_MIME_BY_EXTENSION = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif",
}
_CONVERT_TO_PNG = frozenset({".tif", ".tiff", ".bmp"})


def is_refusal(text: str) -> bool:
    """True when the reply is a refusal or empty rather than a transcription."""
    if not text or not text.strip():
        return True
    lowered = text.strip().lower()
    return any(re.search(p, lowered) for p in _REFUSAL_PATTERNS)


def parse_reading(text: str) -> dict:
    """Parse one model reply into {titulo, fecha, operarios, trabajos}."""
    if is_refusal(text):
        raise RefusalError(f"model declined or returned nothing: {text.strip()[:120]!r}")

    body = text.strip()
    body = re.sub(r"^```(?:json)?", "", body).strip()
    body = re.sub(r"```$", "", body).strip()
    if not body.startswith("{"):
        match = re.search(r"\{.*\}", body, re.DOTALL)
        if not match:
            raise RefusalError(f"no JSON in reply: {body[:120]!r}")
        body = match.group(0)

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RefusalError(f"unparseable JSON: {exc}") from exc

    trabajos = data.get("trabajos") or []
    if isinstance(trabajos, str):
        trabajos = [trabajos]
    operarios = data.get("operarios") or []
    if isinstance(operarios, str):
        operarios = [operarios]

    return {
        "tipo": data.get("tipo"),
        "titulo": data.get("titulo"),
        "fecha": data.get("fecha"),
        "horario": normalise_hour(data.get("horario")),
        "operarios": [str(o).strip() for o in operarios if str(o).strip()],
        "trabajos": [str(t).strip() for t in trabajos if str(t).strip()],
    }


_HOUR = re.compile(r"^\s*(\d{1,2})\s*[:.h]\s*(\d{2})")


def normalise_hour(value) -> str | None:
    """"7:00", "07.00", "22h00" -> "07:00" / "22:00"; anything else -> None."""
    match = _HOUR.match(str(value or ""))
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 24 or minute > 59:
        return None
    return f"{hour % 24:02d}:{minute:02d}"


def data_url_mime(image_path: str) -> str:
    extension = os.path.splitext(image_path)[1].lower()
    if extension in _CONVERT_TO_PNG:
        return "image/png"
    return _MIME_BY_EXTENSION.get(extension, "image/jpeg")


def encode_image(image_path: str) -> tuple[str, str]:
    """Return (base64 payload, mime), converting formats the API rejects."""
    extension = os.path.splitext(image_path)[1].lower()
    if extension in _CONVERT_TO_PNG:
        from PIL import Image
        buffer = io.BytesIO()
        with Image.open(image_path) as image:
            image.convert("RGB").save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8"), "image/png"
    with open(image_path, "rb") as handle:
        return base64.b64encode(handle.read()).decode("utf-8"), data_url_mime(image_path)


def load_prompt(filename: str) -> str:
    path = os.path.join(os.path.dirname(__file__), "prompts", filename)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def with_year(prompt: str, today: date | None = None) -> str:
    """The prompt with the years it expects filled in from today's date.

    It used to say the sheets were from 2026 and that 2027 was a misreading,
    which would have dated every sheet of 2027 a year early.
    """
    year = (today or datetime.now().astimezone().date()).year
    return (prompt.replace("{AÑO_ANTERIOR}", str(year - 1))
                  .replace("{AÑO_DIEZ_ANTES}", str(year - 10))
                  .replace("{AÑO}", str(year)))


def read_page(image_path: str, guard=None, model: str | None = None) -> dict:
    """One independent reading of a page. Raises on refusal or API failure."""
    model = model or config.model_name
    payload, mime = encode_image(image_path)
    prompt = with_year(load_prompt("transcription.md"))

    if guard is not None:
        # Price the call before making it, using a measured estimate.
        guard.check_affordable(model, config.estimated_tokens_in, config.estimated_tokens_out)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{payload}"}},
            ]}],
            max_completion_tokens=config.max_output_tokens,
        )
    except Exception as exc:
        if is_out_of_credit(exc):
            raise OutOfCredit(f"The OpenAI account has no credit left: {exc}") from exc
        raise TranscriptionError(f"Vision API call failed for {image_path}: {exc}") from exc

    if guard is not None and response.usage:
        guard.record(model, response.usage.prompt_tokens, response.usage.completion_tokens)

    return parse_reading(response.choices[0].message.content or "")


def transcribe_image(image_path: str) -> str:
    """Backwards-compatible plain-text transcription."""
    reading = read_page(image_path)
    lines = [f"{reading['titulo'] or ''}", f"FECHA: {reading['fecha'] or ''}"]
    if reading["operarios"]:
        lines.append("OPERARIOS: " + ", ".join(reading["operarios"]))
    lines += [f"- {t}" for t in reading["trabajos"]]
    return "\n".join(line for line in lines if line.strip())
