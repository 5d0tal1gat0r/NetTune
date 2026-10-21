"""A month's memoria accumulates across the scans dropped into that month."""

import os

import pytest
from docx import Document

from nettune.report.entry_store import EntryStore
from nettune.report.memoria import (
    MANTENIMIENTO_BLOCKS,
    SEGURIDAD_BLOCK,
    block_contents,
    fill_memoria,
)

TEMPLATE = "templates/MEMORIA.docx"
pytestmark = pytest.mark.skipif(not os.path.exists(TEMPLATE), reason="template absent")


def e(text, confident=True):
    return {"text": text, "confident": confident}


@pytest.fixture
def store(tmp_path):
    with EntryStore(str(tmp_path / "e.sqlite3")) as s:
        yield s


def build(store, tmp_path, year="2026", month="JUNIO"):
    out = str(tmp_path / f"MEMORIA {year} {month}.docx")
    return fill_memoria(
        TEMPLATE, out,
        {b: store.entries(year, month, b) for b in MANTENIMIENTO_BLOCKS},
        store.entries(year, month, SEGURIDAD_BLOCK),
    )


def test_template_keeps_the_authors_document(tmp_path, store):
    out = build(store, tmp_path)
    doc = Document(out)
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "ÍNDICE" in text
    assert "3.2 Limpieza" in text
    assert "SITUACION COMERCIAL" in text
    assert len(doc.tables) == 7
    assert len(doc.inline_shapes) == 3


def test_security_batch_then_maintenance_accumulate(tmp_path, store):
    store.add("2026", "JUNIO", SEGURIDAD_BLOCK,
              [e("Se expulsa a un indigente de los aseos")], "seg1.pdf")
    store.add("2026", "JUNIO", SEGURIDAD_BLOCK,
              [e("Se llama la atencion a un cliente")], "seg2.pdf")
    store.add("2026", "JUNIO", "Parking",
              [e("Con la obra de cargadores en parking (1H)")], "mant.pdf")

    blocks = block_contents(build(store, tmp_path))
    assert len(blocks[SEGURIDAD_BLOCK]) == 2
    assert blocks["Parking"] == ["Con la obra de cargadores en parking (1H)"]


def test_maintenance_entries_land_under_their_own_headings(tmp_path, store):
    store.add("2026", "JUNIO", "Electricidad y Alumbrado", [e("Revisando cuadros")], "m.pdf")
    store.add("2026", "JUNIO", "Parking", [e("Sumidero hundido en parking")], "m.pdf")
    blocks = block_contents(build(store, tmp_path))
    assert blocks["Electricidad y Alumbrado"] == ["Revisando cuadros"]
    assert blocks["Parking"] == ["Sumidero hundido en parking"]
    assert blocks["Otros"] == []


def test_a_later_drop_adds_without_losing_earlier_entries(tmp_path, store):
    store.add("2026", "JUNIO", SEGURIDAD_BLOCK, [e("primera")], "a.pdf")
    first = block_contents(build(store, tmp_path))[SEGURIDAD_BLOCK]
    store.add("2026", "JUNIO", SEGURIDAD_BLOCK, [e("segunda")], "b.pdf")
    second = block_contents(build(store, tmp_path))[SEGURIDAD_BLOCK]
    assert first == ["primera"]
    assert second == ["primera", "segunda"]


def test_redropping_the_same_scan_does_not_duplicate(tmp_path, store):
    for _ in range(3):
        store.add("2026", "JUNIO", SEGURIDAD_BLOCK, [e("una sola vez")], "a.pdf")
    assert block_contents(build(store, tmp_path))[SEGURIDAD_BLOCK] == ["una sola vez"]


def test_months_do_not_mix(tmp_path, store):
    store.add("2026", "JUNIO", SEGURIDAD_BLOCK, [e("de junio")], "a.pdf")
    store.add("2026", "JULIO", SEGURIDAD_BLOCK, [e("de julio")], "b.pdf")
    junio = block_contents(build(store, tmp_path, month="JUNIO"))
    julio = block_contents(build(store, tmp_path, month="JULIO"))
    assert junio[SEGURIDAD_BLOCK] == ["de junio"]
    assert julio[SEGURIDAD_BLOCK] == ["de julio"]


def test_the_placeholder_never_survives(tmp_path, store):
    store.add("2026", "JUNIO", "Otros", [e("algo real")], "a.pdf")
    text = "\n".join(p.text for p in Document(build(store, tmp_path)).paragraphs)
    assert "(pendiente)" not in text


# A memoria the author wrote by hand. Private, so never in the repository:
# the test runs where the file is, and skips -- like the other private
# fixtures -- where it is not, instead of failing on a missing path.
AUTHORS_JUNE = os.environ.get(
    "AUTHORS_MEMORIA",
    os.path.expanduser("~/Downloads/NetTune/MEMORIA 2026 JUNIO.docx"),
)


@pytest.mark.skipif(not os.path.exists(AUTHORS_JUNE), reason="fixture absent")
def test_entry_formatting_matches_the_authors_entries(tmp_path, store):
    store.add("2026", "JUNIO", "Parking", [e("Entrada nueva")], "a.pdf")
    doc = Document(build(store, tmp_path))
    mine = next(p for p in doc.paragraphs if p.text.strip() == "Entrada nueva")
    author = Document(AUTHORS_JUNE)
    theirs = next(p for p in author.paragraphs
                  if p.text.strip().startswith("Con la obra de cargadores"))
    assert mine.style.name == theirs.style.name
    assert (mine._p.pPr.numPr is not None) == (theirs._p.pPr.numPr is not None)


def test_every_entry_reaches_the_document_exactly_as_read(tmp_path, store):
    """Doubtful or not, the entry itself is never decorated."""
    store.add("2026", "JUNIO", SEGURIDAD_BLOCK,
              [e("Se abre el torreón de zona 6 a los técnicos.", confident=False),
               e("Se llama la atención a dos personas.")],
              "SKM_0001.pdf", review_ref="22-06-2026 p2")
    text = "\n".join(
        block_contents(build(store, tmp_path))[SEGURIDAD_BLOCK]
    )
    assert "Se abre el torreón de zona 6 a los técnicos." in text
    assert "Se llama la atención a dos personas." in text
    assert "[22-06-2026 p2]" not in text
    # The sheet is named once, for a person to open the image and check it.
    assert store.review_pages("2026", "JUNIO") == {"22-06-2026 p2": 1}


def test_the_rest_of_the_document_is_untouched_by_review(tmp_path, store):
    store.add("2026", "JUNIO", SEGURIDAD_BLOCK,
              [e("Se abre Z6.", confident=False)], "s.pdf",
              review_ref="22-06-2026 p2")
    doc = Document(build(store, tmp_path))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "ÍNDICE" in text
    assert "3.2 Limpieza" in text
    assert len(doc.tables) == 7


MONTH_NAMES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
               "septiembre", "octubre", "noviembre", "diciembre")


@pytest.mark.parametrize("year,month", [("2026", "OCTUBRE"), ("2027", "ENERO"),
                                        ("2028", "FEBRERO")])
def test_maintenance_and_security_sections_carry_no_fixed_month(tmp_path, store, year, month):
    """From 3.1 Mantenimiento to the end of 3.3 Seguridad, the document says
    only what that month's sheets said: no month or year from the template."""
    from docx import Document
    store.add(year, month, "Parking", [e("Sumidero hundido en parking")], "m.pdf")
    store.add(year, month, SEGURIDAD_BLOCK, [e("Se expulsa a un indigente")], "s.pdf")
    doc = Document(build(store, tmp_path, year, month))
    texts = [p.text for p in doc.paragraphs]
    # The section itself, not its line in the table of contents.
    first_block = texts.index(MANTENIMIENTO_BLOCKS[0])
    start = max(i for i, t in enumerate(texts[:first_block]) if t.startswith("3.1"))
    end = next(i for i, t in enumerate(texts) if t.startswith("4. SITUACION COMERCIAL"))
    section = "\n".join(texts[start:end]).lower()
    assert "sumidero hundido en parking" in section
    assert "se expulsa a un indigente" in section
    assert not any(name in section.split() or f" {name} " in f" {section} "
                   for name in MONTH_NAMES)
    assert not any(str(y) in section for y in range(2020, 2031))
