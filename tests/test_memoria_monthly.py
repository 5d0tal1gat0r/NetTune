"""Marketing figures and the afluencia chart come from the month's Excel files."""

import os
from datetime import date

import pytest
from docx import Document
from openpyxl import Workbook

from nettune.report.memoria import fill_memoria
from nettune.report.memoria_monthly import (
    find_sources,
    format_count,
    format_euros,
    read_afluencia,
    read_parking_sales,
)

TEMPLATE = "templates/MEMORIA.docx"
pytestmark = pytest.mark.skipif(not os.path.exists(TEMPLATE), reason="template absent")

MONTHS = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO",
          "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]


def ventas_workbook(path, year=2026, sales=None, tickets=None):
    sales = sales or {}
    tickets = tickets or {}
    wb = Workbook()
    ws = wb.active
    ws["F2"] = f"TOTAL VENTAS AÑO {year} (POR MESES)"
    ws.append([])
    ws.append([])
    ws.append(["MESES", *MONTHS, "TOTALES"])
    ws.append([])
    ws.append(["TOTAL VENTAS ", *[sales.get(m, 0) for m in MONTHS]])
    ws.append([])
    ws.append(["TOTAL TICKETS ", *[tickets.get(m, 0) for m in MONTHS]])
    ws.append([])
    ws.append(["TOTAL € TICKETS", *[999 for _ in MONTHS]])
    wb.save(path)
    return str(path)


def aforo_workbook(path, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(["Fecha", "Aforo total", "Total de entradas", "Total de salidas", "Aforo actual"])
    for day, entries in rows:
        ws.append([day, 2000, entries, entries - 10, 10])
    wb.save(path)
    return str(path)


def campaign_text(doc):
    # The campaign sentence sits in a table nested in a cell, which cell.text
    # does not reach, so read every paragraph of the table's XML.
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    for table in doc.tables:
        text = "\n".join(
            "".join(t.text or "" for t in p.iter(w + "t")) for p in table._tbl.iter(w + "p")
        )
        if "CAMPAÑA PARKING" in text:
            return text
    raise AssertionError("campaign table missing")


def build(tmp_path, incoming, year="2026", month="SEPTIEMBRE"):
    out = str(tmp_path / "out.docx")
    fill_memoria(TEMPLATE, out, {}, [], monthly=(str(incoming), year, month))
    return Document(out)


def test_spanish_number_format():
    assert format_euros(178214.63) == "178.214,63"
    assert format_euros(104316.3400001) == "104.316,34"
    assert format_count(4438) == "4.438"
    assert format_count(31728) == "31.728"


def test_reads_the_month_column(tmp_path):
    path = ventas_workbook(tmp_path / "v.xlsx", sales={"MAYO": 178214.63},
                           tickets={"MAYO": 4438})
    assert read_parking_sales(path, "2026", "MAYO") == (178214.63, 4438)
    # A month still at zero has not been filled in.
    assert read_parking_sales(path, "2026", "SEPTIEMBRE") is None
    # Another year's workbook is not this year's figures.
    assert read_parking_sales(path, "2025", "MAYO") is None


def test_afluencia_keeps_only_the_month_in_date_order(tmp_path):
    path = aforo_workbook(tmp_path / "a.xlsx", [
        ("2026-09-02", 900), ("2026-08-31", 500), ("2026-09-01", 1200),
    ])
    assert read_afluencia(path, "2026", "SEPTIEMBRE") == [
        (date(2026, 9, 1), 1200), (date(2026, 9, 2), 900),
    ]


def test_files_found_by_content_newest_wins(tmp_path):
    month_dir = tmp_path / "2026" / "SEPTIEMBRE"
    month_dir.mkdir(parents=True)
    old = ventas_workbook(tmp_path / "ventas viejo.xlsx")
    new = ventas_workbook(month_dir / "cualquier nombre.xlsx")
    os.utime(old, (1, 1))
    aforo = aforo_workbook(tmp_path / "2026" / "aforo (34).xlsx", [])
    (month_dir / "~$lock.xlsx").write_bytes(b"x")
    assert find_sources(str(tmp_path), "2026", "SEPTIEMBRE") == {"ventas": new, "aforo": aforo}


def test_memoria_gets_figures_month_and_chart(tmp_path):
    month_dir = tmp_path / "2026" / "SEPTIEMBRE"
    month_dir.mkdir(parents=True)
    ventas_workbook(month_dir / "v.xlsx", sales={"SEPTIEMBRE": 104316.34},
                    tickets={"SEPTIEMBRE": 2007})
    aforo_workbook(month_dir / "a.xlsx", [(f"2026-09-{d:02d}", 1000 + d) for d in range(1, 31)])

    doc = build(tmp_path, tmp_path)
    text = campaign_text(doc)
    assert "fue de 104.316,34 € y el número" in text
    assert "gratis fue de 2.007." in text
    assert "MES SEPTIEMBRE 2026" in text
    assert "Septiembre" in text and "Mayo" not in text

    body = "\n".join(p.text for p in doc.paragraphs)
    assert "FALTA POR AÑADIR LA AFLUENCIA" not in body
    assert len(doc.inline_shapes) == 4  # the template's three plus the chart


def test_without_files_the_figures_are_pending(tmp_path):
    doc = build(tmp_path, tmp_path)
    text = campaign_text(doc)
    assert "178.214,63" not in text
    assert "(pendiente)" in text
    assert "MES SEPTIEMBRE 2026" in text
    body = "\n".join(p.text for p in doc.paragraphs)
    assert "FALTA POR AÑADIR LA AFLUENCIA" in body
    assert len(doc.inline_shapes) == 3


def test_the_other_marketing_table_is_left_alone(tmp_path):
    doc = build(tmp_path, tmp_path)
    other = next(t for t in doc.tables
                 if "Instalación puerta" in "".join(c.text for r in t.rows for c in r.cells))
    assert "Mayo" in "".join(c.text for r in other.rows for c in r.cells)


def _days(year, month, first, last, skip=()):
    return [(date(year, month, d), 100 + d) for d in range(first, last + 1) if d not in skip]


def test_a_whole_month_keeps_the_plain_title():
    from nettune.report.memoria_monthly import chart_title
    assert chart_title(_days(2026, 8, 1, 31), "AGOSTO", "2026") == "Afluencia diaria - Agosto 2026"


def test_a_month_cut_short_says_which_days_and_how_many_are_missing():
    """The export downloaded on 24 August stops there; the chart must not
    pass for the whole month."""
    from nettune.report.memoria_monthly import chart_title
    assert chart_title(_days(2026, 8, 1, 24), "AGOSTO", "2026") == (
        "Afluencia diaria - 1–24 agosto 2026 (faltan 7 días)")


def test_a_gap_inside_the_month_is_counted_too():
    from nettune.report.memoria_monthly import chart_title
    assert chart_title(_days(2026, 9, 1, 30, skip=(10,)), "SEPTIEMBRE", "2026") == (
        "Afluencia diaria - 1–30 septiembre 2026 (falta 1 día)")
