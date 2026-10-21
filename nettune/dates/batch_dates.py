"""Cross-checks the dates of the pages in one scanned batch.

A batch is a single scanning session: the sheets cover contiguous days, so a
page dated months or years away from its neighbours has been misread. This
catches the case consensus cannot -- where every reading pass agreed on the
same wrong date -- and it costs nothing, being pure arithmetic over dates the
passes already produced.

Observed on a real 25-page July batch: one sheet read unanimously as
16-04-2026, and another as 03-07-2027 where 03-07-2026 was among the readings.
"""

import re
from collections import Counter
from datetime import date, timedelta

from nettune.report.month_folders import is_year

# How far from the batch's centre a page may sit before it looks misread.
# A batch is one scanning session covering about a month, so no real page is
# more than half a month from the middle; 20 days allows a batch that spills
# over a month boundary. It was 45, which let a sheet read a whole month out
# -- "07-10-2026" among September sheets -- pass as though it fitted.
_MAX_DAYS_FROM_BATCH = 20


def parse_date(text: str | None) -> date | None:
    """Parse DD-MM-YYYY (or with / or .), returning None if it is not a date."""
    if not text:
        return None
    match = re.match(r"\s*(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", str(text))
    if not match:
        return None
    day, month, year = (int(g) for g in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _median(values: list[date]) -> date:
    return sorted(values)[len(values) // 2]


def _in_batch_month(own: date, centre: date) -> str:
    """The page's own day, in the batch's month. "" if that is not a date.

    Never invents a day: a 31st that the batch's month has not got is left
    for a human rather than moved to a day nobody wrote.
    """
    try:
        repaired = date(centre.year, centre.month, own.day)
    except ValueError:
        return ""
    if abs((repaired - centre).days) > _MAX_DAYS_FROM_BATCH:
        return ""
    return repaired.strftime("%d-%m-%Y")


def reconcile_batch(pages: list[dict]) -> list[dict]:
    """Flag pages whose date does not fit the rest of the batch.

    A page is corrected only to a date one of its own readings already
    produced -- a date is never invented -- and any page touched here is left
    marked for review.
    """
    parsed = [parse_date(p.get("fecha")) for p in pages]
    known = [d for d in parsed if d]

    # With fewer than three dated pages there is no batch to compare against.
    if len(known) < 3:
        return pages

    centre = _median(known)

    for page, own in zip(pages, parsed, strict=True):
        if own is None:
            continue
        if abs((own - centre).days) <= _MAX_DAYS_FROM_BATCH:
            continue

        # An outlier. Prefer a reading of this same page that does fit.
        better = None
        for variant in page.get("fecha_variants") or []:
            candidate = parse_date(variant)
            if candidate and abs((candidate - centre).days) <= _MAX_DAYS_FROM_BATCH:
                better = variant
                break

        if not better:
            # No reading of this page fits, but the batch is one scanning
            # session of consecutive days, so its month is known. On the
            # September batch every outlier had the day right and the month
            # wrong -- "03-04-2026" on a sheet between two dated 02-09 and
            # 03-09 -- so the day is kept and the month taken from the batch.
            better = _in_batch_month(own, centre)

        if better:
            page["fecha_note"] = (
                f"corregida por coherencia con el lote (se leyó {page.get('fecha')})"
            )
            page["fecha"] = better
        else:
            page["fecha_note"] = (
                f"fuera del rango del lote (resto del lote: {centre.strftime('%m-%Y')})"
            )
        page["fecha_confident"] = False

    return pages


# How many of the read dates must agree with a sheets-per-day fit before the
# fit is trusted over them. The model misreads handwritten days often enough
# -- 6 as 8, 3 as 5, 5 as 6 on September's forms -- that a third wrong is
# normal; below half, the batch probably does not follow the pattern (a day
# with a missing sheet shifts everything after it) and nothing is changed.
MIN_POSITION_AGREEMENT = 0.5


def dates_by_position(read: list[date | None], per_day: int) -> tuple[list[date], float] | None:
    """Every sheet's date from its place in the batch, or None if it does not fit.

    The sheets arrive *per_day* to a day, in order: September's batch was 84
    sheets for 1-21 September, exactly four a day, and the paper agreed with
    that position every time it was checked -- including six sheets whose
    read date looked plausible and was wrong. So position, not the read
    date, says what day a sheet is. The read dates are only used to find
    where the batch starts: which day, and which of that day's sheets it
    begins on.
    """
    dated = [(i, d) for i, d in enumerate(read) if d is not None]
    # At least a day's worth of read dates to fit against.
    if per_day < 1 or len(dated) < per_day:
        return None
    best = None
    for phase in range(per_day):
        starts = Counter(d - timedelta(days=(i + phase) // per_day) for i, d in dated)
        start, agreeing = starts.most_common(1)[0]
        if best is None or agreeing > best[2]:
            best = (start, phase, agreeing)
    start, phase, agreeing = best
    agreement = agreeing / len(dated)
    if agreement < MIN_POSITION_AGREEMENT:
        return None
    return [start + timedelta(days=(i + phase) // per_day) for i in range(len(read))], agreement


def date_pages_by_position(pages: list[dict], per_day: int) -> list[dict]:
    """Set each page's date from its place in the batch, where it fits.

    A page whose read date differs keeps what was read in fecha_note and is
    left marked for review; a page with no date gets one.
    """
    fitted = dates_by_position([parse_date(p.get("fecha")) for p in pages], per_day)
    if fitted is None:
        return pages
    for page, day in zip(pages, fitted[0], strict=True):
        wanted = day.strftime("%d-%m-%Y")
        read = parse_date(page.get("fecha"))
        if read == day:
            continue
        page["fecha_note"] = (
            f"fecha por posición en el lote, {per_day} hojas por día "
            f"(se leyó {page.get('fecha') or 'nada'})"
        )
        page["fecha"] = wanted
        page["fecha_confident"] = False
    return pages


# A shift starting before this hour belongs to the end of the day that is
# written on the sheet, not its start: a night shift written "de 00:00" or
# "de 01:00" follows the evening ones.
_NIGHT_CUTOFF = 6


def _shift_key(horario: str | None) -> int | None:
    match = re.match(r"^(\d{2}):(\d{2})$", horario or "")
    if not match:
        return None
    minutes = int(match.group(1)) * 60 + int(match.group(2))
    return minutes + (24 * 60 if int(match.group(1)) < _NIGHT_CUTOFF else 0)


def chronological_order(pages: list[dict]) -> list[int]:
    """Indices of *pages* in the order the shifts happened.

    The scanner does not keep a day's sheets in time order: September's
    batch came as 15:00, 07:00, 18:00, 22:00 every single day. Within a run
    of sheets sharing a date, they are ordered by the start of their
    "Horario" -- but only when every sheet of that run has one; a run with
    a missing start time is left in scan order rather than half sorted.
    Sheets are never moved from one date to another.
    """
    order: list[int] = []
    run: list[int] = []

    def flush():
        keys = [_shift_key(pages[i].get("horario")) for i in run]
        if len(run) > 1 and all(k is not None for k in keys):
            order.extend(i for _, i in sorted(zip(keys, run, strict=True)))
        else:
            order.extend(run)
        run.clear()

    for i, page in enumerate(pages):
        if run and page.get("fecha") != pages[run[0]].get("fecha"):
            flush()
        run.append(i)
    if run:
        flush()
    return order


# Month folder names, indexed by month number.
_MONTH_NAMES = (
    "", "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
    "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
)


def dominant_year(pages: list[dict]) -> str:
    """Year folder the batch belongs to, from the dates on its sheets.

    Used with dominant_month when a scan is dropped at the top of the share:
    between them the sheets say where the batch goes, so nobody has to pick a
    folder. A year the share does not have is a misreading, not a year.
    """
    years = [d.year for d in (parse_date(p.get("fecha")) for p in pages) if d]
    if not years:
        return ""
    winner = str(Counter(years).most_common(1)[0][0])
    return winner if is_year(winner) else ""


def dominant_month(pages: list[dict]) -> str:
    """Month folder the batch belongs to, from the dates on its sheets.

    Used when a scan is dropped straight into the year folder: the sheets
    themselves say which month they are, so the batch can be filed without
    asking anyone to choose a folder. Returns "" if no date was legible.
    """
    months = [d.month for d in (parse_date(p.get("fecha")) for p in pages) if d]
    if not months:
        return ""
    return _MONTH_NAMES[Counter(months).most_common(1)[0][0]]


def batch_summary(pages: list[dict]) -> str:
    known = [d for d in (parse_date(p.get("fecha")) for p in pages) if d]
    if not known:
        return "sin fechas legibles"
    months = Counter(d.strftime("%m-%Y") for d in known)
    return f"{min(known)} .. {max(known)} (mes dominante {months.most_common(1)[0][0]})"


def filing_months(pages: list[dict], year: str, month: str,
                  min_sheets: int) -> list[tuple[str, str]]:
    """The year and month folder each page is filed under.

    A batch dropped in one month's folder can run over into the next or begin
    in the last: 29 December to 3 January dropped in DICIEMBRE. The memoria is
    monthly, so those sheets belong to their own month's document. A sheet
    moves only to the month either side of the folder's, and only when at
    least *min_sheets* of the batch are dated there -- a whole day of
    sheets, not one misread date. Anything else stays in the folder's month.
    """
    if month not in _MONTH_NAMES or not str(year).isdigit():
        return [(year, month)] * len(pages)
    here = int(year) * 12 + _MONTH_NAMES.index(month) - 1
    days = [parse_date(p.get("fecha")) for p in pages]

    def neighbour(day: date | None) -> tuple[str, str] | None:
        if day is None or abs(day.year * 12 + day.month - 1 - here) != 1:
            return None
        return str(day.year), _MONTH_NAMES[day.month]

    counts = Counter(neighbour(day) for day in days)
    counts.pop(None, None)
    moving = {key for key, count in counts.items() if count >= max(1, min_sheets)}
    return [neighbour(day) if neighbour(day) in moving else (year, month) for day in days]


def batch_month(pages: list[dict], min_sheets: int) -> tuple[str, str] | None:
    """The year and month most of the batch's sheets are dated in, or None.

    Where a batch is filed is decided by its sheets, not the folder it was
    dropped in: it can be dropped anywhere in the share. None when too few
    sheets carry a date to say -- fewer than half of the dated ones, or
    fewer than *min_sheets* (or all of them, for a batch that small) -- and
    then the folder decides.
    """
    days = [d for d in (parse_date(p.get("fecha")) for p in pages) if d]
    if not days:
        return None
    (year, month), count = Counter((d.year, d.month) for d in days).most_common(1)[0]
    if count * 2 < len(days) or count < min(min_sheets, len(days)):
        return None
    if not is_year(str(year)):
        return None
    return str(year), _MONTH_NAMES[month]
