"""Fills the two system-generated blocks of the MEMORIA document.

The memoria is the monthly report the manager writes by hand. Only two parts of
it come from scanned sheets: the corrective maintenance list (split across four
fixed subheadings) and the security interventions list. Two more come from
monthly Excel files: the parking campaign in 5. Gestión de Marketing and the
chart in 6. Afluencia (memoria_monthly). Everything else -- index, cleaning,
commercial situation, tables, header -- is the author's and is never touched.

Entries are written by cloning an existing entry paragraph, so the list
numbering, style and run formatting of the original document are preserved
exactly rather than approximated.
"""

import copy
import os
import re
import unicodedata

from docx import Document

from nettune.report.memoria_monthly import fill_monthly

# Bold subheadings inside 3.1.2 Correctivo, in document order.
MANTENIMIENTO_BLOCKS = (
    "Electricidad y Alumbrado",
    "Ascensores, rampas, escaleras y puertas",
    "Parking",
    "Otros",
)
SEGURIDAD_BLOCK = "Intervenciones Seguridad:"

# Kept in the template as the formatting model for cloned entries; always
# replaced when the memoria is filled.
PLACEHOLDER = "(pendiente)"

# A heading that ends a block: "3.2 Limpieza", "4. SITUACION COMERCIAL"...
_NEXT_HEADING = re.compile(r"^\s*\d+\s*[.\-]")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).strip().lower()


def _is_anchor(text: str, anchor: str) -> bool:
    return _fold(text) == _fold(anchor)


def find_block(doc, anchor: str) -> tuple[int, int]:
    """Return (start, end) paragraph indices of the entries under *anchor*.

    start is the first entry, end is one past the last. Raises if the anchor is
    missing, which means the template is not the document we expect.
    """
    paragraphs = doc.paragraphs
    index = next(
        (i for i, p in enumerate(paragraphs) if _is_anchor(p.text, anchor)), None
    )
    if index is None:
        raise ValueError(f"anchor not found in template: {anchor!r}")

    start = index + 1
    known = {_fold(a) for a in (*MANTENIMIENTO_BLOCKS, SEGURIDAD_BLOCK)}
    end = start
    for i in range(start, len(paragraphs)):
        text = paragraphs[i].text.strip()
        if _fold(text) in known or _NEXT_HEADING.match(text):
            break
        end = i + 1
    return start, end


def _entry_model(doc, start: int, end: int):
    """An existing entry paragraph to clone, so formatting is inherited."""
    for i in range(start, end):
        if doc.paragraphs[i].text.strip():
            return doc.paragraphs[i]
    return None


def set_block(doc, anchor: str, entries: list[str]) -> int:
    """Replace the entries under *anchor*. Returns how many were written."""
    start, end = find_block(doc, anchor)
    model = _entry_model(doc, start, end)
    paragraphs = doc.paragraphs

    if model is None:
        if not entries:
            return 0
        # The template must keep one entry per block to clone formatting from.
        # Inventing a paragraph here would silently lose the list numbering and
        # run formatting of the author's document.
        raise ValueError(
            f"no entry to use as formatting model under {anchor!r}. The template "
            "must keep one placeholder entry in each block."
        )

    anchor_element = paragraphs[start - 1]._p
    for paragraph in paragraphs[start:end]:
        paragraph._p.getparent().remove(paragraph._p)

    previous = anchor_element
    for text in entries:
        new_element = copy.deepcopy(model._p)
        # Keep the first run's formatting, drop the rest, set the text.
        runs = new_element.findall(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}r"
        )
        for extra in runs[1:]:
            new_element.remove(extra)
        if runs:
            for node in runs[0].findall(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
            ):
                runs[0].remove(node)
            t = runs[0].makeelement(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t", {}
            )
            t.text = text
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            runs[0].append(t)
        previous.addnext(new_element)
        previous = new_element
    return len(entries)


def fill_memoria(
    template_path: str,
    output_path: str,
    mantenimiento: dict[str, list[str]],
    seguridad: list[str],
    monthly: tuple[str, str, str] | None = None,
) -> str:
    """Write a memoria from *template_path* with the two blocks filled.

    *monthly* is (incoming_dir, year, month): when given, 5. Gestión de
    Marketing and 6. Afluencia are filled from the Excel files dropped on the
    share for that month (see memoria_monthly).
    """
    doc = Document(template_path)
    for block in MANTENIMIENTO_BLOCKS:
        set_block(doc, block, mantenimiento.get(block, []))
    set_block(doc, SEGURIDAD_BLOCK, seguridad)
    if monthly is not None:
        fill_monthly(doc, *monthly)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    doc.save(output_path)
    return output_path


def block_contents(path: str) -> dict[str, list[str]]:
    """Read back the five blocks. Used by tests and for inspection."""
    doc = Document(path)
    out = {}
    for anchor in (*MANTENIMIENTO_BLOCKS, SEGURIDAD_BLOCK):
        start, end = find_block(doc, anchor)
        out[anchor] = [
            doc.paragraphs[i].text.strip()
            for i in range(start, end)
            if doc.paragraphs[i].text.strip()
        ]
    return out
