"""Stage 2: tidy the consolidated transcription and redact personal data.

Stage 1 transcribes literally and flags what the reading passes disagreed on.
This stage makes the text readable for filing -- expanding abbreviations,
fixing obvious concordance errors, removing people's names -- without changing
what the sheet says.

It is deliberately fenced in: it may only rewrite entries one for one. If it
returns a different number of entries, or an empty one, the literal text is
kept instead. Losing an entry to a cosmetic pass would be far worse than an
untidy report, and the uncertainty flags from stage 1 always survive.
"""

import json
import logging
import os
import re

from openai import OpenAI

from config import config
from document_type import MANTENIMIENTO, SEGURIDAD
from illegible import is_group_marker
from locales import correct_names
from memoria_blocks import strip_duration
from routine_rules import (
    expand_codes,
    expand_maintenance_terms,
    is_noise,
    is_routine_text,
    name_companies,
    reads_as_event,
    strip_time_prefix,
    tidy_caps,
)

client = OpenAI(api_key=config.openai_api_key)


def load_prompt(filename: str) -> str:
    path = os.path.join(os.path.dirname(__file__), "prompts", filename)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


_PROMPT_BY_TYPE = {
    MANTENIMIENTO: "filter_mantenimiento.md",
    SEGURIDAD: "filter_seguridad.md",
}


def prompt_for(document_type) -> str:
    """Filter prompt for a document type.

    An unrecognised type falls back to the maintenance prompt, which rewrites
    less: applying the security prompt's impersonal phrasing to a maintenance
    sheet would distort it more than the other way round.
    """
    return _PROMPT_BY_TYPE.get(document_type, "filter_mantenimiento.md")


def _normalise(entries: list[dict], tipo=None) -> None:
    """Strip clock times, sentence-case capitals and write codes out in full.

    Runs last, after any rewrite by the filter model: the model returns the
    line with its time and codes intact, so normalising before the rewrite is
    undone by it. Done for every document type -- a page typed "desconocido"
    must not carry "07:00" into the memoria either.

    Shop names are settled against the directory in the template, which is
    what the centre actually calls its tenants: the reader gave "MAC VEST"
    and "Parkline" for units listed as "Mae Vest" and "Park Line".
    """
    for entry in entries:
        cleaned = expand_codes(tidy_caps(strip_time_prefix(entry["text"])))
        if tipo == MANTENIMIENTO:
            # The block was settled from the duration before this runs.
            cleaned = strip_duration(expand_maintenance_terms(cleaned))
        cleaned = name_companies(cleaned)
        entry["text"] = correct_names(cleaned, config.template_path)


# How the vigilantes describe people. The author keeps every one of these in
# the memoria; only proper names are taken out.
_PEOPLE = re.compile(
    r"\b(j[oó]ven(es)?|chic[oa]s?|chaval\w*|muchach[oa]s?|ni[ñn][oa]s?|menor(es)?|"
    r"adolescentes?|hombres?|mujer(es)?|se[ñn]or(a|as|es)?|pareja|chavales)\b",
    re.I,
)
_PERSONA = re.compile(r"\bpersonas?\b", re.I)


def generalises_people(literal: str, rewrite: str) -> bool:
    """True when the rewrite swapped the log's description of people for
    "persona": "unos jóvenes" -> "unas personas"."""
    said = {m.group(0).lower() for m in _PEOPLE.finditer(literal)}
    if not said:
        return False
    kept = {m.group(0).lower() for m in _PEOPLE.finditer(rewrite)}
    return bool(said - kept) and len(_PERSONA.findall(rewrite)) > len(_PERSONA.findall(literal))


def apply_filter(
    page: dict,
    cleaned: list[str] | None,
    routine: list[bool] | None = None,
    blocks: list[str] | None = None,
    coherent: list[bool] | None = None,
) -> dict:
    """Overlay cleaned text and routine flags onto a page, one entry for one.

    Rejects any result that does not line up exactly with the original: a
    cosmetic stage must never change how many entries there are.
    """
    entries = page.get("trabajos") or []
    if not entries:
        return page

    if coherent and len(coherent) != len(entries):
        logging.warning(
            f"Filter judged coherence for {len(coherent)} of {len(entries)} "
            "entry(ies); relying on the text instead"
        )
        coherent = None

    if routine and len(routine) != len(entries):
        logging.warning(
            f"Filter returned {len(routine)} routine flag(s) for {len(entries)} "
            "entry(ies); deciding from the text instead"
        )
        routine = None

    for index, entry in enumerate(entries):
        text = entry["text"]
        # Either signal is enough to call a line routine: the model spots
        # forms the patterns do not, and the patterns catch what the model
        # waves through -- it kept calling "Se colocan pilonas" an event
        # on text the readings had agreed on.
        by_model = bool(routine[index]) if routine is not None else False
        is_routine = by_model or is_routine_text(text)
        # An entry that reads as an event is never hidden, whoever called it
        # routine. Hiding an incident is the one failure that matters here.
        # A line that lost its words to the scanner is dropped like routine:
        # an empty bullet helps nobody.
        entry["routine"] = (is_routine and not reads_as_event(text)) or is_noise(text)
        # A line that does not read as a real sentence stays in the document
        # and is marked, never silently dropped: the words are on the paper
        # and only a human can recover them.
        if coherent is not None:
            entry["coherent"] = coherent[index]

    if page.get("tipo") == MANTENIMIENTO:
        from memoria_blocks import PARKING as PARKING_BLOCK
        from memoria_blocks import decide as decide_block

        answers = blocks if blocks and len(blocks) == len(entries) else [None] * len(entries)
        for entry, answer in zip(entries, answers, strict=True):
            # A circled X or red ink on the paper marks a parking line; the
            # reading reports it (consensus.parking_mark).
            entry["bloque"] = (PARKING_BLOCK if entry.get("parking_mark")
                               else decide_block(answer, entry.get("text", "")))

    if not cleaned or len(cleaned) != len(entries):
        if cleaned:
            logging.warning(
                f"Filter returned {len(cleaned)} entry(ies) for {len(entries)}; "
                "keeping the literal transcription"
            )
        _normalise(entries, page.get("tipo"))
        return page

    for entry, replacement in zip(entries, cleaned, strict=True):
        text = (replacement or "").strip()
        if not text:
            continue                      # blank rewrite: keep the literal
        if is_group_marker(entry["text"]):
            continue                      # nothing to tidy; the paper decides
        if generalises_people(entry["text"], text):
            # The log said who: "unos jóvenes", "dos chicas". The memoria
            # says it too -- 174 of the author's own lines name jóvenes --
            # so a rewrite that turned them into "personas" is not used.
            continue
        entry["literal"] = entry["text"]
        entry["text"] = text

    _normalise(entries, page.get("tipo"))
    return page


def redact_operarios(page: dict, enabled: bool = True) -> dict:
    """Remove the operarios' names. The date is never touched."""
    if enabled and page.get("operarios"):
        page["operarios"] = []
        page["operarios_redacted"] = True
    return page


def _parse(
    text: str,
) -> tuple[list[str], list[bool] | None, list[str] | None, list[bool] | None]:
    body = re.sub(r"^```(?:json)?", "", (text or "").strip()).strip()
    body = re.sub(r"```$", "", body).strip()
    if not body.startswith("{"):
        match = re.search(r"\{.*\}", body, re.DOTALL)
        if not match:
            return [], None, None, None
        body = match.group(0)
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return [], None, None, None
    entries = data.get("trabajos") or []
    entries = [str(e) for e in entries] if isinstance(entries, list) else []
    routine = data.get("rutinarias")
    routine = [bool(r) for r in routine] if isinstance(routine, list) else None
    blocks = data.get("bloques")
    blocks = [str(b) for b in blocks] if isinstance(blocks, list) else None
    coherent = data.get("coherentes")
    coherent = [bool(c) for c in coherent] if isinstance(coherent, list) else None
    return entries, routine, blocks, coherent


def filter_page(page: dict, guard=None, model: str | None = None) -> dict:
    """Run the cleanup prompt over a page, falling back to the literal text."""
    entries = page.get("trabajos") or []
    if not entries:
        return redact_operarios(page, enabled=config.redact_names)

    model = model or config.model_name
    prompt_file = prompt_for(page.get("tipo"))
    numbered = "\n".join(f"{i + 1}. {e['text']}" for i, e in enumerate(entries))
    user = (
        f"FICHA: {page.get('titulo') or ''}\n"
        f"FECHA: {page.get('fecha') or ''}\n"
        f"OPERARIOS: {', '.join(page.get('operarios') or []) or '(ninguno)'}\n\n"
        f"ANOTACIONES ({len(entries)}):\n{numbered}"
    )

    try:
        if guard is not None:
            guard.check_affordable(model, 600, 400)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": load_prompt(prompt_file)},
                {"role": "user", "content": user},
            ],
            max_completion_tokens=2000,
        )
        if guard is not None and response.usage:
            guard.record(model, response.usage.prompt_tokens, response.usage.completion_tokens)
        cleaned, routine, blocks, coherent = _parse(
            response.choices[0].message.content or ""
        )
    except Exception as exc:
        # Cosmetic stage: never fail a page over it.
        logging.warning(f"Filter stage skipped ({exc}); keeping literal transcription")
        cleaned, routine, blocks, coherent = [], None, None, None

    page = apply_filter(
        page, cleaned, routine=routine, blocks=blocks, coherent=coherent
    )
    return redact_operarios(page, enabled=config.redact_names)
