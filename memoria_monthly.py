"""Fills the memoria's two spreadsheet-fed parts: marketing and afluencia.

Every month two Excel files are dropped on the share:

- the parking sales workbook ("TOTAL VENTAS PARKING 2026 POR MESES.xlsx"),
  one column per month, from which the free-parking campaign text in
  5. Gestión de Marketing takes the month's total sales in euros and the
  number of validated tickets;
- the footfall export ("aforo (33).xlsx"), one row per day, from which
  6. Afluencia gets a bar chart of the month's daily entries.

Files are recognised by their contents, not their names: the export's name
changes on every download. They are looked for in the month folder, then the
year folder, then the top of the share, and the newest of each kind wins.
Both workbooks are cumulative, so last month's copy is a valid source too.

Nothing here may stop a memoria being written. A missing or unreadable file
leaves "(pendiente)" in the campaign text and the placeholder in Afluencia.
"""

import calendar
import io
import logging
import os
import re
import unicodedata
from datetime import date, datetime

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm

PLACEHOLDER = "(pendiente)"

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

_MONTHS = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

# Marks the marketing table this module fills; the other tables under
# 5. Gestión de Marketing are the author's.
_CAMPAIGN_TITLE = "campana parking 2h gratis"
_CAMPAIGN_TEXT = "dos horas gratis de parking"
_MECHANIC_HEADING = re.compile(r"^\s*MES\s+\S+\s+\d{4}\s*$", re.IGNORECASE)

_AFLUENCIA_HEADING = re.compile(r"^\s*\d+\s*[.\-]+\s*afluencia", re.IGNORECASE)
_AFLUENCIA_PLACEHOLDER = "falta por anadir la afluencia"
_NEXT_HEADING = re.compile(r"^\s*\d+\s*[.\-]")

_YEAR_IN_TITLE = re.compile(r"\ba[ñn]o\s+(\d{4})\b", re.IGNORECASE)


def _fold(text) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    return " ".join(
        "".join(c for c in text if not unicodedata.combining(c)).lower().split()
    )


def _month_index(month: str) -> int:
    """1-12 for a Spanish month name in any case or accenting."""
    return _MONTHS.index(_fold(month)) + 1


def format_euros(value: float) -> str:
    """178214.63 -> '178.214,63' (Spanish grouping, two decimals)."""
    text = f"{value:,.2f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def format_count(value: float) -> str:
    """4438 -> '4.438'."""
    return f"{round(value):,}".replace(",", ".")


# --- Reading the workbooks -------------------------------------------------


def _load(path: str):
    from openpyxl import load_workbook

    return load_workbook(path, read_only=True, data_only=True)


def read_parking_sales(path: str, year: str, month: str) -> tuple[float, int] | None:
    """(total sales in €, ticket count) for *month*, or None if not there.

    Finds the header row starting "MESES", the month's column in it, and the
    rows labelled "TOTAL VENTAS" and "TOTAL TICKETS". A month still at 0 has
    not been filled in yet and counts as missing.
    """
    wanted = _fold(month)
    workbook = _load(path)
    try:
        for sheet in workbook.worksheets:
            rows = [list(r) for r in sheet.iter_rows(values_only=True)]
            stated_years = {
                m.group(1)
                for row in rows for cell in row if isinstance(cell, str)
                for m in [_YEAR_IN_TITLE.search(cell)] if m
            }
            if stated_years and str(year) not in stated_years:
                continue
            column = None
            sales = tickets = None
            for row in rows:
                if not row:
                    continue
                label = _fold(row[0])
                if label == "meses":
                    column = next(
                        (i for i, cell in enumerate(row) if _fold(cell) == wanted), None
                    )
                elif column is not None and column < len(row):
                    if label == "total ventas":
                        sales = row[column]
                    elif label == "total tickets":
                        tickets = row[column]
            if column is None:
                continue
            if not isinstance(sales, (int, float)) or not isinstance(tickets, (int, float)):
                return None
            if not sales and not tickets:
                return None
            return round(float(sales), 2), round(tickets)
    finally:
        workbook.close()
    return None


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def read_afluencia(path: str, year: str, month: str) -> list[tuple[date, int]]:
    """Daily entries for *month*, oldest first. Empty when there are none.

    Reads the "Fecha" and "Total de entradas" columns of the footfall export.
    """
    wanted = (int(year), _month_index(month))
    workbook = _load(path)
    try:
        for sheet in workbook.worksheets:
            date_col = entries_col = None
            days: dict[date, int] = {}
            for row in sheet.iter_rows(values_only=True):
                if date_col is None:
                    folded = [_fold(cell) for cell in row]
                    if "fecha" in folded and "total de entradas" in folded:
                        date_col = folded.index("fecha")
                        entries_col = folded.index("total de entradas")
                    continue
                if max(date_col, entries_col) >= len(row):
                    continue
                day = _as_date(row[date_col])
                count = row[entries_col]
                if day is None or not isinstance(count, (int, float)):
                    continue
                if (day.year, day.month) == wanted:
                    days[day] = int(count)
            if date_col is not None:
                return sorted(days.items())
    finally:
        workbook.close()
    return []


def _kind(path: str) -> str | None:
    """'ventas', 'aforo' or None, judged from the first rows of the workbook."""
    try:
        workbook = _load(path)
    except Exception as exc:
        logging.warning(f"Excel ilegible, se ignora: {path}: {exc}")
        return None
    try:
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows(max_row=15, values_only=True):
                folded = [_fold(cell) for cell in row]
                if "fecha" in folded and "total de entradas" in folded:
                    return "aforo"
                if folded and folded[0] == "meses":
                    return "ventas"
    finally:
        workbook.close()
    return None


def find_sources(incoming_dir: str, year: str, month: str) -> dict[str, str]:
    """Newest workbook of each kind near the month: {'ventas': path, 'aforo': path}."""
    folders = (
        os.path.join(incoming_dir, str(year), month),
        os.path.join(incoming_dir, str(year)),
        incoming_dir,
    )
    found: dict[str, tuple[float, str]] = {}
    for folder in folders:
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            if not name.lower().endswith(".xlsx") or name.startswith(("~$", ".")):
                continue
            path = os.path.join(folder, name)
            if not os.path.isfile(path):
                continue
            kind = _kind(path)
            if kind is None:
                continue
            mtime = os.path.getmtime(path)
            if kind not in found or mtime > found[kind][0]:
                found[kind] = (mtime, path)
    return {kind: path for kind, (_, path) in found.items()}


# --- Writing the memoria ---------------------------------------------------


def _text(element) -> str:
    return "".join(t.text or "" for t in element.iter(_W + "t"))


def _set_run_text(run, text: str) -> None:
    for node in run.findall(_W + "t"):
        run.remove(node)
    t = run.makeelement(_W + "t", {})
    t.text = text
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    run.append(t)


def _is_bold(run) -> bool:
    props = run.find(_W + "rPr")
    if props is None:
        return False
    bold = props.find(_W + "b")
    return bold is not None and bold.get(_W + "val") not in ("0", "false")


def _campaign_table(doc):
    for table in doc.tables:
        if _CAMPAIGN_TITLE in _fold(_text(table._tbl)):
            return table._tbl
    raise ValueError("marketing parking campaign table not found in template")


def set_marketing(doc, year: str, month: str, figures: tuple[float, int] | None) -> None:
    """Point the parking campaign table at *month* and write its two figures.

    The month name cells ("Mes", "Periodo") and the "MES MAYO 2026" heading
    are rewritten; in the campaign sentence the two bold figures are replaced
    run by run, so their bold and underline stay as the author set them.
    """
    table = _campaign_table(doc)
    month_title = _fold(month).capitalize()

    for run in table.iter(_W + "r"):
        text = _text(run)
        if _fold(text) in _MONTHS:
            _set_run_text(run, month_title)
        elif _MECHANIC_HEADING.match(text):
            _set_run_text(run, f"MES {month_title.upper()} {year}")

    paragraph = next(
        (p for p in table.iter(_W + "p") if _CAMPAIGN_TEXT in _fold(_text(p))), None
    )
    if paragraph is None:
        raise ValueError("parking campaign sentence not found in template")
    number_runs = [
        r for r in paragraph.iter(_W + "r")
        if _is_bold(r) and re.search(r"\d", _text(r))
    ]
    if len(number_runs) < 2:
        raise ValueError("parking campaign sentence lost its two bold figures")
    if figures is None:
        sales_text, tickets_text = PLACEHOLDER, f"{PLACEHOLDER}."
    else:
        sales, tickets = figures
        sales_text, tickets_text = format_euros(sales), f"{format_count(tickets)}."
    _set_run_text(number_runs[0], sales_text)
    _set_run_text(number_runs[1], tickets_text)


def chart_title(days: list[tuple[date, int]], month: str, year: str) -> str:
    """The chart's title, saying so when the export does not cover the month.

    The aforo export stops on the day it was downloaded: one taken on 24
    August charts 1-24 August, and a plain "Agosto 2026" would pass it off
    as the whole month.
    """
    name = _fold(month)
    if days:
        first, last = days[0][0], days[-1][0]
        in_month = calendar.monthrange(first.year, first.month)[1]
        missing = in_month - len(days)
        if missing > 0:
            falta = "falta 1 día" if missing == 1 else f"faltan {missing} días"
            return (f"Afluencia diaria - {first.day}–{last.day} {name} {year} "
                    f"({falta})")
    return f"Afluencia diaria - {name.capitalize()} {year}"


def afluencia_chart(days: list[tuple[date, int]], month: str, year: str) -> bytes:
    """PNG bar chart: one bar per day, labelled with the full YYYY-MM-DD date."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = [d.isoformat() for d, _ in days]
    values = [v for _, v in days]
    fig, ax = plt.subplots(figsize=(10, 5), dpi=200)
    try:
        bars = ax.bar(labels, values, color="#2f5597")
        ax.bar_label(bars, fontsize=6, padding=1)
        ax.set_title(chart_title(days, month, year))
        ax.set_ylabel("Total de entradas")
        ax.tick_params(axis="x", labelrotation=90, labelsize=7)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=0.3)
        ax.set_axisbelow(True)
        fig.tight_layout()
        out = io.BytesIO()
        fig.savefig(out, format="png")
        return out.getvalue()
    finally:
        plt.close(fig)


def set_afluencia(doc, year: str, month: str, days: list[tuple[date, int]]) -> bool:
    """Put the daily chart under 6. Afluencia. False when there was no data.

    The "FALTA POR AÑADIR LA AFLUENCIA." paragraph is replaced by the chart;
    without one, the chart goes right after the heading.
    """
    if not days:
        return False
    paragraphs = doc.paragraphs
    heading = next(
        (i for i, p in enumerate(paragraphs) if _AFLUENCIA_HEADING.match(p.text)), None
    )
    if heading is None:
        raise ValueError("6. Afluencia heading not found in template")

    target = None
    for p in paragraphs[heading + 1:]:
        if _NEXT_HEADING.match(p.text):
            break
        if _AFLUENCIA_PLACEHOLDER in _fold(p.text):
            target = p
            break
    if target is None:
        target = paragraphs[heading].insert_paragraph_before("")
        paragraphs[heading]._p.addnext(target._p)
    for run in list(target.runs):
        run._r.getparent().remove(run._r)

    target.alignment = WD_ALIGN_PARAGRAPH.CENTER
    image = io.BytesIO(afluencia_chart(days, month, year))
    target.add_run().add_picture(image, width=Cm(16.5))
    return True


def fill_monthly(doc, incoming_dir: str, year: str, month: str) -> None:
    """Fill marketing and afluencia from the workbooks found for the month."""
    sources = find_sources(incoming_dir, year, month)

    figures = None
    if "ventas" in sources:
        try:
            figures = read_parking_sales(sources["ventas"], year, month)
        except Exception as exc:
            logging.error(f"No se pudo leer {sources['ventas']}: {exc}")
        if figures is None:
            logging.warning(f"{year}/{month}: sin ventas del parking en {sources['ventas']}")
    else:
        logging.warning(f"{year}/{month}: no hay Excel de ventas del parking")
    set_marketing(doc, year, month, figures)

    days: list[tuple[date, int]] = []
    if "aforo" in sources:
        try:
            days = read_afluencia(sources["aforo"], year, month)
        except Exception as exc:
            logging.error(f"No se pudo leer {sources['aforo']}: {exc}")
        if not days:
            logging.warning(f"{year}/{month}: sin días de afluencia en {sources['aforo']}")
    else:
        logging.warning(f"{year}/{month}: no hay Excel de aforo")
    set_afluencia(doc, year, month, days)
