"""Accumulates the entries that belong in each month's memoria.

A month arrives as many scans: a batch of security sheets plus one maintenance
PDF. Each drop adds its entries, and the memoria for that month is rebuilt from
all of them. Keeping the entries here rather than only in the document means a
later drop never has to re-read earlier scans, and the document can be
regenerated at any time.

Entries are deduplicated by (year, month, block, text) so re-dropping the same
scan does not duplicate lines in the memoria.
"""

import logging
import os
import re
import sqlite3
import unicodedata
from datetime import date, datetime, timezone
from typing import NamedTuple

from nettune.ops.nettune_feedback import page_id as feedback_page_id
from nettune.ops.nettune_feedback import ref_page_id
from nettune.pages.illegible import ILLEGIBLE_GROUP, is_group_marker
from nettune.report.memoria_blocks import BLOCKS as MANTENIMIENTO_BLOCKS
from nettune.report.month_folders import month_sort_key
from nettune.report.review_marks import MAINTENANCE_MARK, is_maintenance_ref, plain_ref, same_kind
from ocr_feedback.model import ReviewEvent
from ocr_feedback.recorder import NullRecorder

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memoria_entries (
    year        TEXT NOT NULL,
    month       TEXT NOT NULL,
    block       TEXT NOT NULL,
    position    INTEGER NOT NULL,
    text        TEXT NOT NULL,
    source      TEXT NOT NULL,
    flagged     INTEGER NOT NULL DEFAULT 0,
    review_ref  TEXT NOT NULL DEFAULT '',
    hand_edited   INTEGER NOT NULL DEFAULT 0,
    original_text TEXT NOT NULL DEFAULT '',
    edited_at     TEXT NOT NULL DEFAULT '',
    added_at    TEXT NOT NULL,
    -- Keyed on the comparison form, not the text: the September batch read
    -- the same line twice, once with a trailing full stop and once without,
    -- and both reached the memoria.
    dedupe_key  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (year, month, block, text)
)
"""


_REF = re.compile(r"^(.*) p(\d+)$")


def review_line(review_ref: str, count: int) -> str:
    """The one line the memoria carries for a sheet worth checking."""
    match = _REF.match(plain_ref(review_ref))
    sheet, page = (match.group(1), match.group(2)) if match else (review_ref, "?")
    noun = "anotación dudosa" if count == 1 else "anotaciones dudosas"
    # A date reads "la hoja del 20-09-2026"; a scan name, which stands in when
    # no date could be read, reads "la hoja SKM_C3082609". Both sections
    # number from 1, so a maintenance sheet says which it is.
    named = f"del {sheet}" if re.fullmatch(r"\d{2}-\d{2}-\d{4}", sheet) else sheet
    hoja = "hoja de mantenimiento" if is_maintenance_ref(review_ref) else "hoja"
    return f"Revisar la {hoja} {named} (página {page}): {count} {noun}."


# The source of a line a person added by hand, rather than one read off a scan.
HAND_SOURCE = "revisión"

# The dashboard's two tabs, and the two parts of the ready email.
SEGURIDAD_SECTION = "seguridad"
MANTENIMIENTO_SECTION = "mantenimiento"


def section_of_block(block: str) -> str:
    """The section a memoria block belongs to."""
    return MANTENIMIENTO_SECTION if block in MANTENIMIENTO_BLOCKS else SEGURIDAD_SECTION


# Room for every line of a month in one block before the next block starts.
_BLOCK_STRIDE = 10000


def legacy_paper_order(block: str, position: int) -> float:
    """A paper order for a line read before the paper's order was kept.

    Lines were split by block before they were saved, and position counts
    within a block, so the order across blocks on one sheet is gone. This
    keeps each sheet's lines grouped by subheading, in the memoria's order,
    and in their old order inside each.
    """
    index = MANTENIMIENTO_BLOCKS.index(block) if block in MANTENIMIENTO_BLOCKS else 0
    return float(index * _BLOCK_STRIDE + position)


class RetagResult(NamedTuple):
    """What retag_entry did. other_id names the line that blocked a move."""
    status: str  # changed | unchanged | not_found | not_maintenance | collision
    other_id: int = 0

_FECHA_REF = re.compile(r"^(\d{2})-(\d{2})-(\d{4}) p(\d+)$")


def sheet_order(review_ref: str) -> tuple:
    """Sort key putting a month's sheets in date order, then page order.

    position alone is the order the scans were fed to the machine, which is
    not the order the days happened: a real September batch ran
    01-09 p2, 11-09 p3, 01-09 p4, 02-09 p5 ... 24-09 p7, because the pages
    came off the scanner in whatever order the paper sat in the tray. The
    memoria is a record of a month and has to read in date order.

    A reference with no date in it -- a scan-named sheet, or a row written
    before review_ref existed -- sorts after everything dated rather than
    being scattered through it, and keeps its position order among its own.
    """
    match = _FECHA_REF.match(plain_ref(review_ref))
    if not match:
        return (1, "", 0)
    day, month, year, page = match.groups()
    return (0, f"{year}{month}{day}", int(page))


_PAGE = re.compile(r" p(\d+)$")


def _page_number(review_ref: str) -> int | None:
    """The page number at the end of a sheet reference, or None."""
    match = _PAGE.search(review_ref or "")
    return int(match.group(1)) if match else None


# How far a read date may sit from its neighbours in the scan before it is
# questioned. Two days: a day shift and a night shift, and a sheet or two out
# of place in the stack, are normal.
_DATE_SLACK = 2
_REF_DATE = re.compile(r"^(\d{2})-(\d{2})-(\d{4}) p\d+$")


def _ref_date(review_ref: str) -> int | None:
    """Day number (days since 0001-01-01) of a dated reference, or None."""
    match = _REF_DATE.match(plain_ref(review_ref))
    if not match:
        return None
    try:
        return date(int(match.group(3)), int(match.group(2)),
                    int(match.group(1))).toordinal()
    except ValueError:
        return None


def _longest_non_decreasing(values: list[int]) -> set[int]:
    """Indices of one longest non-decreasing subsequence of *values*."""
    import bisect

    tails: list[int] = []      # smallest tail value of a run of each length
    tail_index: list[int] = []  # index in values of that tail
    parent = [-1] * len(values)
    for i, value in enumerate(values):
        k = bisect.bisect_right(tails, value)
        if k == len(tails):
            tails.append(value)
            tail_index.append(i)
        else:
            tails[k] = value
            tail_index[k] = i
        parent[i] = tail_index[k - 1] if k else -1
    chosen: set[int] = set()
    i = tail_index[-1] if tail_index else -1
    while i != -1:
        chosen.add(i)
        i = parent[i]
    return chosen


def _in_month(date_text: str, year: str, month: str) -> bool:
    """True for a real DD-MM-YYYY that falls in the folder's year and month."""
    from nettune.report.month_folders import MONTH_FOLDERS

    match = re.fullmatch(r"(\d{2})-(\d{2})-(\d{4})", date_text or "")
    if not match:
        return False
    try:
        date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError:
        return False
    return (match.group(3) == str(year)
            and month in MONTH_FOLDERS
            and int(match.group(2)) == MONTH_FOLDERS.index(month) + 1)


def _sheet_keys(rows: list, ref_of, position_of, block_of) -> dict:
    """id(row) -> the sheet key each row sorts under.

    Until review_ref was stored on every line, a line the reader was sure of
    was saved with none -- 29 of September's. Sorting those by sheet_order
    alone sent them to the bottom of the month as one "no sheet" group, away
    from the days they were written on. Instead each takes the key of the
    line before it in the scan (position order, within its block): pages are
    written in page order, so that is the page it followed, and it stays
    beside its neighbours.
    """
    keys = {}
    for block in {block_of(r) for r in rows}:
        en_bloque = sorted((r for r in rows if block_of(r) == block), key=position_of)
        # Lines before the block's first dated sheet came before it in the
        # scan, so they open the month with it rather than closing it. The
        # first *dated* sheet: an undated one at the start (page 1 of a scan,
        # rebuilt with no date) would otherwise hand them its own "no date"
        # key and send them to the end of the month.
        primera = next((ref_of(r) for r in en_bloque
                        if ref_of(r) and sheet_order(ref_of(r))[0] == 0), "")
        carried = sheet_order(primera) if primera else (1, "", 0)
        for row in en_bloque:
            ref = ref_of(row)
            # Only a dated sheet moves the key on. A sheet named after the
            # scan, because its date could not be read, stays where the scan
            # put it -- sheet_order alone would send it to the end of the month.
            if ref and sheet_order(ref)[0] == 0:
                carried = sheet_order(ref)
            keys[id(row)] = carried
    return keys


def in_date_order(rows: list, ref_of, position_of, block_of=lambda r: "") -> list:
    """Sort rows by block, then sheet date, keeping sheetless rows where the
    scan put them (see _sheet_keys)."""
    keys = _sheet_keys(rows, ref_of, position_of, block_of)
    return sorted(rows, key=lambda r: (block_of(r), keys[id(r)], position_of(r)))


def in_paper_order(rows: list, ref_of, position_of, block_of, paper_of) -> list:
    """Sort maintenance rows by sheet, then where they sat on the paper.

    Unlike in_date_order the block is not the first key: a sheet's lines are
    filed under four subheadings, and grouping by them first showed one day
    up to four times. The block still decides which sheet a sheetless line
    is carried to, because position only counts within a block.
    """
    keys = _sheet_keys(rows, ref_of, position_of, block_of)

    def own_sheet(row) -> tuple:
        # A line carried to the dated sheet before it -- one with no sheet,
        # or on a sheet with no readable date -- comes after that sheet's own
        # lines, grouped by its own sheet: paper order restarts on every
        # page, so sorting by it alone would interleave the two pages.
        ref = ref_of(row) or ""
        return (0, "") if ref and sheet_order(ref) == keys[id(row)] else (1, ref)

    return sorted(rows, key=lambda r: (keys[id(r)], own_sheet(r), paper_of(r),
                                       block_of(r), position_of(r)))


def dedupe_key(text: str) -> str:
    """What makes two entries the same line: the letters and digits alone."""
    folded = unicodedata.normalize("NFKD", (text or "").lower())
    stripped = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", stripped).strip()


class EntryStore:
    def __init__(self, db_path: str, recorder=None):
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._connection = sqlite3.connect(db_path, timeout=30)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(_SCHEMA)
        self._migrate()
        self._connection.commit()
        # Where review actions are told to ocr_feedback. None for every tool
        # and test that opens a store; only the dashboard passes one.
        self._recorder = recorder or NullRecorder()

    def _migrate(self) -> None:
        """Add columns a database written by an older version has not got.

        The Pi's store predates review_ref and holds entries already in a
        memoria; dropping and recreating the table would lose them.
        """
        columns = {
            row[1] for row in
            self._connection.execute("PRAGMA table_info(memoria_entries)")
        }
        if "review_ref" not in columns:
            self._connection.execute(
                "ALTER TABLE memoria_entries ADD COLUMN "
                "review_ref TEXT NOT NULL DEFAULT ''"
            )
        if "dedupe_key" not in columns:
            self._connection.execute(
                "ALTER TABLE memoria_entries ADD COLUMN "
                "dedupe_key TEXT NOT NULL DEFAULT ''"
            )
            for row in self._connection.execute(
                "SELECT rowid, text FROM memoria_entries"
            ).fetchall():
                self._connection.execute(
                    "UPDATE memoria_entries SET dedupe_key = ? WHERE rowid = ?",
                    (dedupe_key(row[1]), row[0]),
                )
        # A correction outranks anything the reader produced, so what the
        # reader produced is kept beside it: original_text is the labelled
        # half of the pair, and the only thing that lets a reprocess tell a
        # re-read original from a new entry.
        for column, definition in (
            ("hand_edited", "INTEGER NOT NULL DEFAULT 0"),
            ("original_text", "TEXT NOT NULL DEFAULT ''"),
            ("edited_at", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column not in columns:
                self._connection.execute(
                    f"ALTER TABLE memoria_entries ADD COLUMN {column} {definition}"
                )
        self._connection.execute(
            "UPDATE memoria_entries SET original_text = text "
            "WHERE original_text = ''"
        )
        # Where a line sat on its page, across the four maintenance
        # subheadings, so the dashboard can show a sheet as it was written.
        if "paper_order" not in columns:
            self._connection.execute(
                "ALTER TABLE memoria_entries ADD COLUMN paper_order REAL"
            )
        # Set when a person moved a line to another subheading. A reprocess
        # is the reader speaking again and must not move it back.
        if "hand_block" not in columns:
            self._connection.execute(
                "ALTER TABLE memoria_entries ADD COLUMN "
                "hand_block INTEGER NOT NULL DEFAULT 0"
            )
        for rowid, block, position in self._connection.execute(
            "SELECT rowid, block, position FROM memoria_entries "
            "WHERE paper_order IS NULL"
        ).fetchall():
            self._connection.execute(
                "UPDATE memoria_entries SET paper_order = ? WHERE rowid = ?",
                (legacy_paper_order(block, position), rowid),
            )
        # A database written before this key existed can already hold the
        # duplicates it exists to prevent -- that is why it was added. They
        # have to go before the index can be unique; the earliest row of each
        # pair is kept, which is the one the memoria already showed.
        removed = self._connection.execute(
            "DELETE FROM memoria_entries WHERE rowid NOT IN ("
            "  SELECT MIN(rowid) FROM memoria_entries"
            "  GROUP BY year, month, block, dedupe_key)"
        ).rowcount
        if removed:
            logging.warning(f"Removed {removed} duplicate entry(ies) from the store")
        self._connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS memoria_entries_dedupe "
            "ON memoria_entries (year, month, block, dedupe_key)"
        )
        # How far a person has turned each review image by hand, relative to
        # the copy the pipeline wrote. Without it the turn lived only in the
        # file, and the next thing to write that file -- a re-dropped scan, or
        # tools/straighten_revision.py -- quietly put the sheet back.
        # Every sheet of every scan, by its page number in the scan. The
        # entries only knew the sheets their lines pointed at, and before
        # every line kept its sheet that left whole pages unrecorded: 20 of
        # September's 84 had no row anywhere, so they could be neither shown
        # nor offered as the page a line came from.
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS scan_sheets ("
            "  year       TEXT NOT NULL,"
            "  month      TEXT NOT NULL,"
            "  source     TEXT NOT NULL,"
            "  page       INTEGER NOT NULL,"
            "  review_ref TEXT NOT NULL,"
            "  PRIMARY KEY (year, month, source, page))"
        )
        sheet_columns = {
            row[1] for row in
            self._connection.execute("PRAGMA table_info(scan_sheets)")
        }
        if "scan_position" not in sheet_columns:
            # Where the sheet came in the scan, when that is not its page
            # number: sheets are numbered in the order the shifts happened,
            # and the scanner does not keep that order.
            self._connection.execute(
                "ALTER TABLE scan_sheets ADD COLUMN scan_position INTEGER"
            )
            self._connection.execute(
                "UPDATE scan_sheets SET scan_position = page WHERE scan_position IS NULL"
            )
        if "date_checked" not in sheet_columns:
            # Set once a person has looked at the sheet and settled its date,
            # so a date that is right but out of step with its neighbours is
            # not questioned again.
            self._connection.execute(
                "ALTER TABLE scan_sheets ADD COLUMN date_checked INTEGER NOT NULL DEFAULT 0"
            )
        if "empty_checked" not in sheet_columns:
            # Set when a person has looked at a sheet the reading found
            # nothing on and confirmed there is nothing to add, so it stops
            # counting as still to check.
            self._connection.execute(
                "ALTER TABLE scan_sheets ADD COLUMN empty_checked INTEGER NOT NULL DEFAULT 0"
            )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS sheet_turns ("
            "  filename TEXT PRIMARY KEY,"
            "  degrees  INTEGER NOT NULL,"
            "  at       TEXT NOT NULL)"
        )

    def add(self, year: str, month: str, block: str, entries: list[dict],
            source: str, review_ref: str = "") -> int:
        """Add entries to a block. Returns how many were new.

        *review_ref* locates the page these entries were read from. It is
        stored against the entries the readings disagreed on, so the rebuilt
        memoria can point a human at the image.
        """
        start = self._connection.execute(
            "SELECT COALESCE(MAX(position), -1) FROM memoria_entries "
            "WHERE year = ? AND month = ? AND block = ?",
            (year, month, block),
        ).fetchone()[0]
        superseded = self._corrected_sources(year, month, block)
        retagged = self._retagged_elsewhere(year, month, block, review_ref)

        added = groups = 0
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for entry in entries:
            text = (entry.get("text") or "").strip()
            if not text:
                continue
            start += 1
            key = dedupe_key(text)
            orden = entry.get("orden")
            paper = (float(orden) if isinstance(orden, (int, float))
                     else legacy_paper_order(block, start))
            if is_group_marker(text):
                # Every unreadable stretch is its own line, though they all
                # read the same: keyed by the sheet and its place on it, so a
                # re-read of that sheet still matches it. The text is the
                # table's key too, so the second one in a month is numbered.
                groups += 1
                key = f"{dedupe_key(ILLEGIBLE_GROUP)} {review_ref or source} {groups}"
                if self._connection.execute(
                    "SELECT 1 FROM memoria_entries WHERE year = ? AND month = ? "
                    "AND block = ? AND dedupe_key = ?", (year, month, block, key),
                ).fetchone():
                    continue
                text = self._free_group_text(year, month, block)
            if key in retagged:
                # A person filed this line under another subheading; their
                # choice stands, and the line takes its place on the sheet.
                self._connection.execute(
                    "UPDATE memoria_entries SET paper_order = ? WHERE rowid = ?",
                    (paper, retagged[key]),
                )
                continue
            if key in superseded:
                # Somebody has already corrected this line; their text stands,
                # but it moves back to the slot its source line just claimed,
                # so the rebuilt document keeps the sheet's own order.
                # Only when this is the correction's own sheet being read
                # again: the same words on another day's sheet must not move
                # it around the day it belongs to.
                self._connection.execute(
                    "UPDATE memoria_entries SET position = ?, paper_order = ? "
                    "WHERE rowid = ? AND review_ref IN (?, '')",
                    (start, paper, superseded[key], review_ref),
                )
                continue
            doubtful = not entry.get("confident", True)
            cursor = self._connection.execute(
                "INSERT OR IGNORE INTO memoria_entries "
                "(year, month, block, position, text, source, flagged, "
                "review_ref, added_at, dedupe_key, original_text, paper_order) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                # review_ref on every entry, not only the doubtful ones: it
                # is what lets a person open the sheet a line came from, and
                # wanting to see the paper is not the same as the reader
                # having been unsure. review_pages() still filters on flagged,
                # so the memoria's "Revisar la hoja ..." lines are unchanged.
                (year, month, block, start, text, source, int(doubtful),
                 review_ref, now, key, text, paper),
            )
            added += cursor.rowcount
        self._connection.commit()
        return added

    def _free_group_text(self, year: str, month: str, block: str) -> str:
        """ILLEGIBLE_GROUP, or "... ilegible 2", 3... if the month has it."""
        taken = {row[0] for row in self._connection.execute(
            "SELECT text FROM memoria_entries WHERE year = ? AND month = ? AND block = ? "
            "AND text LIKE ?", (year, month, block, ILLEGIBLE_GROUP[:-1] + "%"),
        )}
        text, number = ILLEGIBLE_GROUP, 1
        while text in taken:
            number += 1
            text = f"{ILLEGIBLE_GROUP[:-1]} {number})"
        return text

    def entries(self, year: str, month: str, block: str) -> list[str]:
        """Entry texts for one block, in the order they were added.

        The text is returned as it was read. A doubtful entry used to carry
        its page locator inline, but on a real batch four entries in five
        came back doubtful, and a marker that common tells a reader nothing.
        The pages to check are listed once each instead; see review_pages.
        """
        rows = self._connection.execute(
            "SELECT text, review_ref, position, paper_order FROM memoria_entries "
            "WHERE year = ? AND month = ? AND block = ?",
            (year, month, block),
        ).fetchall()
        if block in MANTENIMIENTO_BLOCKS:
            rows = in_paper_order(rows, ref_of=lambda r: r[1], position_of=lambda r: r[2],
                                  block_of=lambda r: block,
                                  paper_of=lambda r: r[3] if r[3] is not None else 0.0)
        else:
            rows = in_date_order(rows, ref_of=lambda r: r[1], position_of=lambda r: r[2])
        return [row[0] for row in rows]

    def months(self) -> list[tuple[str, str]]:
        """Every year/month that has entries, oldest first.

        Read from the data, so a month exists here because something was
        filed in it -- not because it is on a list of years someone wrote
        down in advance.
        """
        rows = self._connection.execute(
            "SELECT DISTINCT year, month FROM memoria_entries"
        ).fetchall()
        return sorted(((y, m) for y, m in rows), key=lambda r: month_sort_key(*r))

    def entry_month(self, entry_id: int) -> tuple[str, str] | None:
        """The year and month an entry belongs to, or None if it is gone."""
        row = self._connection.execute(
            "SELECT year, month FROM memoria_entries WHERE rowid = ?", (entry_id,)
        ).fetchone()
        return (row[0], row[1]) if row else None

    def sheets(self) -> list[tuple[str, str, str]]:
        """Every (year, month, review_ref) that names a sheet, in one query."""
        return self._connection.execute(
            "SELECT DISTINCT year, month, review_ref FROM memoria_entries "
            "WHERE review_ref != '' "
            "UNION SELECT year, month, review_ref FROM scan_sheets"
        ).fetchall()

    def record_sheet(self, year: str, month: str, source: str, page: int,
                     review_ref: str, scan_position: int | None = None) -> None:
        """Note that sheet *page* of *source* exists and what it is called.

        *scan_position* is where it came in the scan, when that differs from
        its page number; it defaults to the page number.
        """
        self._connection.execute(
            "INSERT INTO scan_sheets (year, month, source, page, review_ref, scan_position) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(year, month, source, page) "
            "DO UPDATE SET review_ref = excluded.review_ref, "
            "scan_position = excluded.scan_position",
            (year, month, source, page, review_ref,
             scan_position if scan_position is not None else page),
        )
        self._connection.commit()

    def scan_positions(self, year: str, month: str, source: str) -> dict[int, str]:
        """Scan position -> sheet reference, for tools that re-render a scan."""
        return dict(self._connection.execute(
            "SELECT COALESCE(scan_position, page), review_ref FROM scan_sheets "
            "WHERE year = ? AND month = ? AND source = ?", (year, month, source)
        ).fetchall())

    def renumber_sheets(self, year: str, month: str, source: str,
                        mapping: dict[int, int]) -> list[tuple[str, str]]:
        """Give sheets new page numbers; returns (old ref, new ref) pairs.

        Every line filed under a sheet, hand-added ones included, follows it.
        A swap (1 -> 2, 2 -> 1) goes through placeholder references, so no
        sheet ever shares a reference with another part-way through. Pages
        may also move to numbers the scan does not use -- clear of another
        scan's, see last_page -- but never onto one of its pages that stays.
        """
        targets = list(mapping.values())
        staying = {page for (page,) in self._connection.execute(
            "SELECT page FROM scan_sheets WHERE year = ? AND month = ? AND source = ?",
            (year, month, source)) if page not in mapping}
        if len(set(targets)) != len(targets) or staying & set(targets):
            raise ValueError("two sheets of a scan would share a page number")
        sheets = {
            page: (ref, position) for page, ref, position in self._connection.execute(
                "SELECT page, review_ref, COALESCE(scan_position, page) FROM scan_sheets "
                "WHERE year = ? AND month = ? AND source = ?", (year, month, source))
        }
        moves = []
        for old_page, new_page in mapping.items():
            if old_page == new_page or old_page not in sheets:
                continue
            old_ref = sheets[old_page][0]
            new_ref = _PAGE.sub(f" p{new_page}", old_ref)
            moves.append((old_page, new_page, old_ref, new_ref, sheets[old_page][1]))
        where = f"year = ? AND month = ? AND source IN (?, '{HAND_SOURCE}')"
        for old_page, _, old_ref, _, _ in moves:
            placeholder = f"__renumbering__ {old_page}"
            self._connection.execute(
                f"UPDATE memoria_entries SET review_ref = ? WHERE {where} AND review_ref = ?",
                (placeholder, year, month, source, old_ref))
            self._connection.execute(
                "UPDATE scan_sheets SET page = ? WHERE year = ? AND month = ? "
                "AND source = ? AND page = ?", (-old_page, year, month, source, old_page))
        for old_page, new_page, _, new_ref, position in moves:
            placeholder = f"__renumbering__ {old_page}"
            self._connection.execute(
                f"UPDATE memoria_entries SET review_ref = ? WHERE {where} AND review_ref = ?",
                (new_ref, year, month, source, placeholder))
            self._connection.execute(
                "UPDATE scan_sheets SET page = ?, review_ref = ?, scan_position = ? "
                "WHERE year = ? AND month = ? AND source = ? AND page = ?",
                (new_page, new_ref, position, year, month, source, -old_page))
        self._connection.commit()
        return [(old_ref, new_ref) for _, _, old_ref, new_ref, _ in moves]



    def last_page(self, year: str, month: str, excluding: str = "",
                  maintenance: bool = False) -> int:
        """The highest page number one section's sheets use in the month, 0
        for none.

        A new scan numbers its sheets on from here, so two security batches
        -- or two maintenance ones -- in a month never share a name. The two
        sections number independently (MAINTENANCE_MARK keeps them apart).
        *excluding* leaves out the scan being numbered, so reading it again
        gives it the numbers it had.
        """
        pages = [
            number for ref, source in self._connection.execute(
                "SELECT review_ref, source FROM scan_sheets WHERE year = ? AND month = ? "
                "UNION SELECT review_ref, source FROM memoria_entries "
                "WHERE year = ? AND month = ? AND review_ref != ''",
                (year, month, year, month))
            if source != excluding and is_maintenance_ref(ref) == maintenance
            and (number := _page_number(ref)) is not None
        ]
        return max(pages, default=0)

    def mark_maintenance(self, year: str, month: str, source: str) -> list[tuple[str, str]]:
        """Give a scan read before MAINTENANCE_MARK existed its mark, once.

        Returns (old ref, new ref) pairs; the image files are the caller's.
        The scan's lines follow their sheet. Lines added by hand follow too,
        unless another scan has a sheet of the same name -- then there is no
        telling whose they are, and they stay.
        """
        moves = [
            (page, ref, MAINTENANCE_MARK + ref) for page, ref in self._connection.execute(
                "SELECT page, review_ref FROM scan_sheets "
                "WHERE year = ? AND month = ? AND source = ?", (year, month, source))
            if not is_maintenance_ref(ref)
        ]
        for page, old, new in moves:
            shared = self._connection.execute(
                "SELECT 1 FROM scan_sheets WHERE year = ? AND month = ? "
                "AND review_ref = ? AND source != ?", (year, month, old, source)).fetchone()
            sources = (source,) if shared else (source, HAND_SOURCE)
            marks = ", ".join("?" for _ in sources)
            self._connection.execute(
                "UPDATE memoria_entries SET review_ref = ? WHERE year = ? AND month = ? "
                f"AND review_ref = ? AND source IN ({marks})",
                (new, year, month, old, *sources))
            self._connection.execute(
                "UPDATE scan_sheets SET review_ref = ? "
                "WHERE year = ? AND month = ? AND source = ? AND page = ?",
                (new, year, month, source, page))
        self._connection.commit()
        return [(old, new) for _, old, new in sorted(moves)]

    def source_sheets(self, year: str, month: str, source: str) -> dict[int, str]:
        """Page number -> sheet reference for one scan, from everything known.

        Page numbers count within a scan, so they are only comparable inside
        one: a month holding two scans has two page 3s.
        """
        known = dict(self._connection.execute(
            "SELECT page, review_ref FROM scan_sheets "
            "WHERE year = ? AND month = ? AND source = ?", (year, month, source)
        ).fetchall())
        for (ref,) in self._connection.execute(
            "SELECT DISTINCT review_ref FROM memoria_entries "
            "WHERE year = ? AND month = ? AND source = ? AND review_ref != ''",
            (year, month, source),
        ):
            page = _page_number(ref)
            if page is not None:
                known.setdefault(page, ref)
        return known

    def candidate_sheets(self, entry_id: int) -> list[str]:
        """The sheets a line with no recorded sheet can have come from.

        Pages are written in page order with consecutive positions, so such
        a line was read from the page of the nearest line before it that
        has one, the page of the nearest after, or a page in between. Only
        sheets the store knows of are offered -- a candidate that cannot be
        opened and checked is no use to the person choosing.
        """
        row = self._connection.execute(
            "SELECT year, month, block, position, source, review_ref "
            "FROM memoria_entries WHERE rowid = ?", (entry_id,)
        ).fetchone()
        if row is None or row[5]:
            return []
        year, month, block, position, source = row[:5]

        # Everything here is in scan order -- where a sheet came in the scan
        # -- not page order. Page numbers follow the shifts now, and a day
        # renumbered 15:00, 07:00 -> 07:00, 15:00 turned "between p5 and p6"
        # into "between p6 and p5", an empty range: five of September's lines
        # lost every candidate and showed "Página no registrada".
        by_position = {
            position: ref for position, ref in self.scan_positions(year, month, source).items()
        }
        position_of = {ref: position for position, ref in by_position.items()}
        for page, ref in self.source_sheets(year, month, source).items():
            position_of.setdefault(ref, page)
            by_position.setdefault(page, ref)

        def nearest(comparison: str, order: str):
            found = self._connection.execute(
                "SELECT review_ref FROM memoria_entries "
                "WHERE year = ? AND month = ? AND block = ? AND source = ? "
                f"AND review_ref != '' AND position {comparison} ? "
                f"ORDER BY position {order} LIMIT 1",
                (year, month, block, source, position),
            ).fetchone()
            return position_of.get(found[0]) if found else None

        before, after = nearest("<", "DESC"), nearest(">", "ASC")
        if before is None and after is None:
            return []
        first = before if before is not None else 1
        last = after if after is not None else before + 1
        first, last = min(first, last), max(first, last)
        candidates = [by_position[p] for p in range(first, last + 1) if p in by_position]
        # Offered in page order, which is the order the person reads them in.
        return sorted(candidates, key=_page_number)

    def assign_sheet(self, entry_id: int, review_ref: str) -> bool:
        """Give a line with no recorded sheet the one a person chose.

        Refused unless *review_ref* is one of its candidates, so neither a
        slip nor a forged form can file a line under an unrelated page, and
        a line that already has a sheet is never re-filed this way.
        """
        if review_ref not in self.candidate_sheets(entry_id):
            return False
        changed = self._connection.execute(
            "UPDATE memoria_entries SET review_ref = ?, edited_at = ? "
            "WHERE rowid = ? AND review_ref = ''",
            (review_ref, self._now(), entry_id),
        ).rowcount
        self._connection.commit()
        return bool(changed)

    def sheet_identity(self, year: str, month: str, review_ref: str) -> tuple[str, int] | None:
        """(source, page) of a sheet, from its reference."""
        row = self._connection.execute(
            "SELECT source, page FROM scan_sheets "
            "WHERE year = ? AND month = ? AND review_ref = ?",
            (year, month, review_ref),
        ).fetchone()
        if row:
            return row[0], row[1]
        row = self._connection.execute(
            "SELECT source FROM memoria_entries "
            "WHERE year = ? AND month = ? AND review_ref = ? "
            f"ORDER BY source = '{HAND_SOURCE}' LIMIT 1",
            (year, month, review_ref),
        ).fetchone()
        page = _page_number(review_ref)
        return (row[0], page) if row and page is not None else None

    def date_checks(self, year: str, month: str) -> dict[str, list[str]]:
        """Sheets whose date does not fit the scan, with the dates it could be.

        A batch is scanned in the order the paper was stacked, which is day
        order give or take a day, so a read date far from its neighbours in
        the scan is almost always a misreading: September had page 3 read as
        11-09 between two 01-09 sheets, and page 77 as 29-09 between 19-09 and
        20-09. Only the paper says what the date really is, so this does not
        correct anything -- it names the sheet and offers the neighbours'
        dates as the likely answers. A date a person has confirmed is not
        questioned again.

        Returns {review_ref: [suggested DD-MM-YYYY, ...]}.
        """
        checked = {
            (src, page) for src, page in self._connection.execute(
                "SELECT source, page FROM scan_sheets "
                "WHERE year = ? AND month = ? AND date_checked = 1", (year, month))
        }
        # Lines added by hand are not a scan: their sheets come from every
        # scan of the month, so read as one they are out of order, and a
        # confirmation (kept against the real scan) never clears them.
        sources = {src for (src,) in self._connection.execute(
            "SELECT DISTINCT source FROM scan_sheets WHERE year = ? AND month = ? "
            "UNION SELECT DISTINCT source FROM memoria_entries "
            "WHERE year = ? AND month = ? AND review_ref != '' "
            f"AND source != '{HAND_SOURCE}'",
            (year, month, year, month))}
        doubtful: dict[str, list[str]] = {}
        for source in sources:
            dated = []
            for page, ref in sorted(self.source_sheets(year, month, source).items()):
                day = _ref_date(ref)
                if day is not None:
                    dated.append((page, ref, day))
            # The backbone: the longest run of pages whose dates never go
            # backwards. Comparing each page with the middle of its
            # neighbours let one bad date drag its good neighbours into doubt
            # (p2, read right as 01-09, was questioned because p3 beside it
            # was read as 11-09). Against the backbone, a misread page stands
            # alone.
            backbone = _longest_non_decreasing([day for _, _, day in dated])
            for i, (page, ref, day) in enumerate(dated):
                if i in backbone or (source, page) in checked:
                    continue
                before = next((dated[j] for j in range(i - 1, -1, -1) if j in backbone), None)
                after = next((dated[j] for j in range(i + 1, len(dated)) if j in backbone), None)
                low = before[2] - _DATE_SLACK if before else None
                high = after[2] + _DATE_SLACK if after else None
                if (low is None or day >= low) and (high is None or day <= high):
                    continue
                suggestions = []
                for neighbour in (before, after):
                    if neighbour is None:
                        continue
                    text = plain_ref(neighbour[1]).split(" ")[0]
                    if text not in suggestions:
                        suggestions.append(text)
                doubtful[ref] = suggestions
        return doubtful

    def redate_sheet(self, year: str, month: str, review_ref: str,
                     new_date: str) -> str | None:
        """Give a sheet the date a person read off it. Returns the new reference.

        Every line filed under the sheet moves with it, and the sheet is
        marked as checked. None when the sheet is unknown, the date is not a
        DD-MM-YYYY in this sheet's month, or another sheet already has that
        name. The image file is the caller's to rename: it knows the folder.
        """
        identity = self.sheet_identity(year, month, review_ref)
        if identity is None or not _in_month(new_date, year, month):
            return None
        source, page = identity
        new_ref = same_kind(f"{new_date} p{page}", review_ref)
        if new_ref != review_ref:
            taken = self._connection.execute(
                "SELECT 1 FROM scan_sheets WHERE year = ? AND month = ? AND review_ref = ? "
                "AND NOT (source = ? AND page = ?) "
                "UNION SELECT 1 FROM memoria_entries WHERE year = ? AND month = ? "
                "AND review_ref = ? AND source != ?",
                (year, month, new_ref, source, page, year, month, new_ref, source),
            ).fetchone()
            if taken:
                return None
            # Lines added by hand carry the sheet's reference but "revisión"
            # as their source; they belong to the sheet and move with it.
            # Found on the Pi: a line added under p29 stayed behind under the
            # old date, splitting the sheet into two headings.
            self._connection.execute(
                "UPDATE memoria_entries SET review_ref = ? "
                "WHERE year = ? AND month = ? AND review_ref = ? "
                f"AND source IN (?, '{HAND_SOURCE}')",
                (new_ref, year, month, review_ref, source),
            )
        self._connection.execute(
            "INSERT INTO scan_sheets (year, month, source, page, review_ref, date_checked) "
            "VALUES (?, ?, ?, ?, ?, 1) ON CONFLICT(year, month, source, page) "
            "DO UPDATE SET review_ref = excluded.review_ref, date_checked = 1",
            (year, month, source, page, new_ref),
        )
        self._connection.commit()
        return new_ref

    def restore_sheet_ref(self, year: str, month: str, source: str, page: int,
                          current_ref: str, previous_ref: str) -> None:
        """Undo redate_sheet, when the file it names could not be renamed."""
        self._connection.execute(
            "UPDATE memoria_entries SET review_ref = ? "
            "WHERE year = ? AND month = ? AND review_ref = ? "
            f"AND source IN (?, '{HAND_SOURCE}')",
            (previous_ref, year, month, current_ref, source),
        )
        self._connection.execute(
            "UPDATE scan_sheets SET review_ref = ?, date_checked = 0 "
            "WHERE year = ? AND month = ? AND source = ? AND page = ?",
            (previous_ref, year, month, source, page),
        )
        self._connection.commit()

    def rename_turn(self, old_filename: str, new_filename: str) -> None:
        """Carry a sheet's hand turn over to its new file name."""
        self._connection.execute(
            "UPDATE sheet_turns SET filename = ? WHERE filename = ?",
            (new_filename, old_filename),
        )
        self._connection.commit()

    def record_turn(self, filename: str, degrees: int) -> int:
        """Add a hand turn to a review image's running total. Returns it.

        Clockwise, modulo 360: turning right then left leaves 0, and a sheet
        at 0 is simply one nobody needed to turn, so its row goes.
        """
        row = self._connection.execute(
            "SELECT degrees FROM sheet_turns WHERE filename = ?", (filename,)
        ).fetchone()
        total = ((row[0] if row else 0) + degrees) % 360
        if total:
            self._connection.execute(
                "INSERT INTO sheet_turns (filename, degrees, at) VALUES (?, ?, ?) "
                "ON CONFLICT(filename) DO UPDATE SET degrees = excluded.degrees, "
                "at = excluded.at",
                (filename, total, self._now()),
            )
        else:
            self._connection.execute(
                "DELETE FROM sheet_turns WHERE filename = ?", (filename,)
            )
        self._connection.commit()
        return total

    def hand_turned(self) -> frozenset:
        """Names of every review image a person has turned by hand."""
        return frozenset(
            row[0] for row in self._connection.execute("SELECT filename FROM sheet_turns")
        )

    def hand_turn(self, filename: str) -> int:
        """Degrees a person has turned this review image by hand, or 0."""
        row = self._connection.execute(
            "SELECT degrees FROM sheet_turns WHERE filename = ?", (filename,)
        ).fetchone()
        return row[0] if row else 0

    def month_entries(self, year: str, month: str) -> list[dict]:
        """Every entry of a month in document order, for the dashboard.

        Carries the row id, because the dashboard addresses one entry at a
        time, and original_text, because a correction is only meaningful
        beside what it corrected.
        """
        rows = self._connection.execute(
            "SELECT rowid, block, position, text, flagged, review_ref, "
            "hand_edited, original_text, paper_order, hand_block "
            "FROM memoria_entries WHERE year = ? AND month = ?",
            (year, month),
        ).fetchall()
        # Seguridad as before; Mantenimiento as each sheet was written. The
        # dashboard shows one section at a time, so their relative order
        # does not matter.
        seguridad = [r for r in rows if r[1] not in MANTENIMIENTO_BLOCKS]
        mantenimiento = [r for r in rows if r[1] in MANTENIMIENTO_BLOCKS]
        rows = (
            in_date_order(seguridad, ref_of=lambda r: r[5], position_of=lambda r: r[2],
                          block_of=lambda r: r[1])
            + in_paper_order(mantenimiento, ref_of=lambda r: r[5],
                             position_of=lambda r: r[2], block_of=lambda r: r[1],
                             paper_of=lambda r: r[8] if r[8] is not None else 0.0)
        )
        return [
            {"id": r[0], "block": r[1], "position": r[2], "text": r[3],
             "flagged": r[4], "review_ref": r[5], "hand_edited": r[6],
             "original_text": r[7],
             "paper_order": r[8] if r[8] is not None else 0.0,
             "hand_block": r[9]}
            for r in rows
        ]

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _event_row(self, entry_id: int):
        """(year, month, review_ref, block, text) of an entry, for the
        feedback record; None when nothing is recorded or on any error."""
        if not getattr(self._recorder, "enabled", False):
            return None
        try:
            return self._connection.execute(
                "SELECT year, month, review_ref, block, text FROM memoria_entries "
                "WHERE rowid = ?", (entry_id,),
            ).fetchone()
        except Exception:
            return None

    def _record(self, action: str, entry_id: int, before, after,
                host_action: str | None = None) -> None:
        """Tell ocr_feedback what a person did. Called after the change is
        committed, and never raises: a lost record is acceptable, a lost
        correction is not."""
        row = after or before
        if row is None:
            return
        try:
            year, month, ref = row[0], row[1], row[2]
            sheet = self._connection.execute(
                "SELECT source, scan_position FROM scan_sheets "
                "WHERE year = ? AND month = ? AND review_ref = ? LIMIT 1",
                (year, month, ref),
            ).fetchone()
            page = (feedback_page_id(sheet[0], sheet[1]) if sheet
                    else ref_page_id(year, month, ref))
            self._recorder.record_event(ReviewEvent(
                page_id=page, line_ref=str(entry_id), action=action,
                before_text=before[4] if before else None,
                after_text=after[4] if after else None,
                before_tag=before[3] if before else None,
                after_tag=after[3] if after else None,
                meta={"host_action": host_action or action, "year": year,
                      "month": month, "review_ref": ref},
            ))
        except Exception as exc:
            logging.warning(f"ocr_feedback: {action} on entry {entry_id} not recorded: {exc}")

    def edit_entry(self, entry_id: int, text: str) -> bool:
        """Replace an entry's text with a person's. False if there is none.

        The flag goes: a line somebody has read against the paper does not
        need reading again. original_text is untouched, so what the reader
        produced survives the correction.
        """
        cleaned = (text or "").strip()
        if not cleaned:
            return False
        before = self._event_row(entry_id)
        try:
            changed = self._connection.execute(
                "UPDATE memoria_entries SET text = ?, dedupe_key = ?, flagged = 0, "
                "hand_edited = 1, edited_at = ? WHERE rowid = ?",
                (cleaned, dedupe_key(cleaned), self._now(), entry_id),
            ).rowcount
        except sqlite3.IntegrityError:
            # The dedupe index is on (year, month, block, dedupe_key); typing
            # a sibling entry's text word for word collides with it. Refusing
            # the edit is correct here -- the two entries would otherwise be
            # indistinguishable, and the person can just delete the redundant one.
            # The failed UPDATE left its transaction open, and with it the
            # write lock every other connection needs.
            self._connection.rollback()
            return False
        self._connection.commit()
        if changed:
            self._record("edit", entry_id, before, self._event_row(entry_id))
        return bool(changed)

    def rewrite_entry(self, entry_id: int, text: str) -> bool:
        """Replace the reader's text with a corrected reading of the same line.

        For corrections made by rule rather than by a person -- a shop name
        the reader always gets wrong -- so the line keeps its flag and is not
        counted as checked. False if nothing changed or the text collides with
        a sibling entry.
        """
        cleaned = (text or "").strip()
        if not cleaned:
            return False
        before = self._event_row(entry_id)
        try:
            changed = self._connection.execute(
                "UPDATE memoria_entries SET text = ?, dedupe_key = ? "
                "WHERE rowid = ? AND text != ?",
                (cleaned, dedupe_key(cleaned), entry_id, cleaned),
            ).rowcount
        except sqlite3.IntegrityError:
            self._connection.rollback()
            return False
        self._connection.commit()
        if changed:
            self._record("edit", entry_id, before, self._event_row(entry_id),
                         host_action="rewrite")
        return bool(changed)

    def confirm_entry(self, entry_id: int) -> bool:
        """Mark an entry read and correct, without changing a word of it."""
        before = self._event_row(entry_id)
        changed = self._connection.execute(
            "UPDATE memoria_entries SET flagged = 0, hand_edited = 1, edited_at = ? "
            "WHERE rowid = ?",
            (self._now(), entry_id),
        ).rowcount
        self._connection.commit()
        if changed:
            self._record("confirm", entry_id, before, self._event_row(entry_id))
        return bool(changed)

    def flag_entry(self, entry_id: int) -> bool:
        """Mark an entry for a second reader, as a person could not settle it.

        hand_edited, so a reprocess keeps the line and its mark; the next
        person clears it with Correcto or by correcting the text.
        """
        before = self._event_row(entry_id)
        changed = self._connection.execute(
            "UPDATE memoria_entries SET flagged = 1, hand_edited = 1, edited_at = ? "
            "WHERE rowid = ?",
            (self._now(), entry_id),
        ).rowcount
        self._connection.commit()
        if changed:
            self._record("flag", entry_id, before, self._event_row(entry_id))
        return bool(changed)

    def retag_entry(self, entry_id: int, block: str) -> RetagResult:
        """Move a maintenance line to another of the memoria's subheadings.

        Marked hand_block, so a reprocess leaves it where the person put it.
        The text and the flag are untouched: choosing a subheading is not
        reading the line against the paper. A move onto an identical line
        already under that subheading is refused rather than merged -- a
        merge would make one copy vanish from its day without anybody
        choosing that.
        """
        if block not in MANTENIMIENTO_BLOCKS:
            raise ValueError(f"not a maintenance block: {block!r}")
        row = self._connection.execute(
            "SELECT year, month, block, dedupe_key, text FROM memoria_entries "
            "WHERE rowid = ?", (entry_id,),
        ).fetchone()
        if row is None:
            return RetagResult("not_found")
        year, month, current, key, text = row
        before = self._event_row(entry_id)
        if current not in MANTENIMIENTO_BLOCKS:
            return RetagResult("not_maintenance")
        if current == block:
            return RetagResult("unchanged")
        other = self._connection.execute(
            "SELECT rowid FROM memoria_entries "
            "WHERE year = ? AND month = ? AND block = ? AND dedupe_key = ?",
            (year, month, block, key),
        ).fetchone()
        if other:
            return RetagResult("collision", other[0])
        position = self._place_in_block(year, month, block, entry_id)
        # Every unreadable stretch reads the same and is told apart by a
        # number within its block, so it takes the next free one there.
        if is_group_marker(text):
            text = self._free_group_text(year, month, block)
        try:
            self._connection.execute(
                "UPDATE memoria_entries SET block = ?, position = ?, hand_block = 1, "
                "text = ? WHERE rowid = ?", (block, position, text, entry_id),
            )
        except sqlite3.IntegrityError:
            # Same text under the target block with a different dedupe key
            # (the primary key is on the raw text): still the same line.
            self._connection.rollback()
            other = self._connection.execute(
                "SELECT rowid FROM memoria_entries WHERE year = ? AND month = ? "
                "AND block = ? AND text = (SELECT text FROM memoria_entries "
                "WHERE rowid = ?)", (year, month, block, entry_id),
            ).fetchone()
            return RetagResult("collision", other[0] if other else 0)
        self._connection.commit()
        self._record("retag", entry_id, before, self._event_row(entry_id))
        return RetagResult("changed")

    def _paper_beside(self, anchor_id: int, before: bool) -> float:
        """A paper order directly before or after *anchor_id* on its sheet.

        Halfway to the neighbour on that side, across every maintenance
        subheading of the sheet, so no other line has to move -- moving them
        would mean renumbering lines in blocks the person never touched.
        """
        anchor = self._connection.execute(
            "SELECT year, month, block, review_ref, paper_order FROM memoria_entries "
            "WHERE rowid = ?", (anchor_id,),
        ).fetchone()
        if anchor is None:
            return 0.0
        year, month, block, ref, mine = anchor
        mine = mine if mine is not None else 0.0
        if block in MANTENIMIENTO_BLOCKS and ref:
            marks = ", ".join("?" for _ in MANTENIMIENTO_BLOCKS)
            rows = self._connection.execute(
                "SELECT paper_order FROM memoria_entries WHERE year = ? AND month = ? "
                f"AND review_ref = ? AND block IN ({marks}) AND rowid != ?",
                (year, month, ref, *MANTENIMIENTO_BLOCKS, anchor_id),
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT paper_order FROM memoria_entries WHERE year = ? AND month = ? "
                "AND review_ref = ? AND block = ? AND rowid != ?",
                (year, month, ref, block, anchor_id),
            ).fetchall()
        values = [v for (v,) in rows if v is not None]
        if before:
            lower = [v for v in values if v < mine]
            return (max(lower) + mine) / 2 if lower else mine - 1
        higher = [v for v in values if v > mine]
        return (min(higher) + mine) / 2 if higher else mine + 1

    def add_entry(self, year: str, month: str, block: str, text: str,
                  after_id: int | None = None, before_id: int | None = None) -> int:
        """Insert a line the reader missed. Returns its id, or 0 if empty
        or if the text already exists in the block.

        It lands directly after *after_id*, or directly before *before_id*,
        and belongs to the same sheet as that line. The sheet matters: the
        month is ordered by the date in review_ref (see sheet_order), so a
        line added with no sheet used to sort to the bottom of the block
        under "sin hoja", nowhere near where the person put it.

        It is hand-edited from birth: nobody but a person types one.
        """
        cleaned = (text or "").strip()
        if not cleaned:
            return 0
        anchor_id = before_id or after_id
        anchor = self._connection.execute(
            "SELECT position, review_ref FROM memoria_entries WHERE rowid = ?",
            (anchor_id,),
        ).fetchone() if anchor_id else None
        if anchor is None:
            position, review_ref = 0, ""
        elif before_id:
            position, review_ref = anchor[0], anchor[1]
        else:
            position, review_ref = anchor[0] + 1, anchor[1]
        paper = (self._paper_beside(anchor_id, before=bool(before_id))
                 if anchor is not None else 0.0)

        self._connection.execute(
            "UPDATE memoria_entries SET position = position + 1 "
            "WHERE year = ? AND month = ? AND block = ? AND position >= ?",
            (year, month, block, position),
        )
        now = self._now()
        cursor = self._connection.execute(
            "INSERT OR IGNORE INTO memoria_entries "
            "(year, month, block, position, text, source, flagged, review_ref, "
            "added_at, dedupe_key, original_text, hand_edited, edited_at, paper_order) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, '', 1, ?, ?)",
            (year, month, block, position, cleaned, HAND_SOURCE, review_ref, now,
             dedupe_key(cleaned), now, paper),
        )
        self._connection.commit()
        # OR IGNORE means a colliding insert leaves rowid untouched and
        # lastrowid stale from whatever the connection inserted last --
        # rowcount is the only thing that says whether a row actually landed.
        if cursor.rowcount == 0:
            return 0
        new_id = int(cursor.lastrowid)
        self._record("add", new_id, None, self._event_row(new_id))
        return new_id

    def add_to_sheet(self, year: str, month: str, block: str, review_ref: str,
                     text: str) -> int:
        """Add a line to a sheet that has none yet. Returns its id, or 0.

        add_entry places a line beside another; an empty sheet has no line
        to stand beside. The month is ordered by sheet first (sheet_order),
        so the line only needs its sheet's reference to land in the right
        place, and a position after everything else in the block.
        """
        cleaned = (text or "").strip()
        if not cleaned or not review_ref:
            return 0
        position = self._connection.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM memoria_entries "
            "WHERE year = ? AND month = ? AND block = ?", (year, month, block)
        ).fetchone()[0]
        paper = self._connection.execute(
            "SELECT COALESCE(MAX(paper_order), -1) + 1 FROM memoria_entries "
            "WHERE year = ? AND month = ? AND review_ref = ?", (year, month, review_ref)
        ).fetchone()[0]
        now = self._now()
        cursor = self._connection.execute(
            "INSERT OR IGNORE INTO memoria_entries "
            "(year, month, block, position, text, source, flagged, review_ref, "
            "added_at, dedupe_key, original_text, hand_edited, edited_at, paper_order) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, '', 1, ?, ?)",
            (year, month, block, position, cleaned, HAND_SOURCE, review_ref, now,
             dedupe_key(cleaned), now, paper),
        )
        self._connection.commit()
        if not cursor.rowcount:
            return 0
        new_id = int(cursor.lastrowid)
        self._record("add", new_id, None, self._event_row(new_id), host_action="add_to_sheet")
        return new_id

    def sheet_blocks(self, year: str, month: str, default: str) -> dict[str, str]:
        """The block each sheet of the month belongs to.

        A sheet's block is where its scan's lines went -- the security batch
        to Intervenciones Seguridad, the maintenance sheet to its own. A scan
        with no lines at all gets *default*.
        """
        by_source: dict[str, str] = {}
        for source, block, _ in self._connection.execute(
            "SELECT source, block, COUNT(*) AS n FROM memoria_entries "
            f"WHERE year = ? AND month = ? AND source != '{HAND_SOURCE}' "
            "GROUP BY source, block ORDER BY n DESC", (year, month)
        ):
            by_source.setdefault(source, block)
        blocks: dict[str, str] = {}
        for source, ref in self._connection.execute(
            "SELECT source, review_ref FROM scan_sheets WHERE year = ? AND month = ?",
            (year, month),
        ):
            blocks[ref] = by_source.get(source, default)
        for block, ref in self._connection.execute(
            "SELECT block, review_ref FROM memoria_entries "
            "WHERE year = ? AND month = ? AND review_ref != ''", (year, month)
        ):
            blocks.setdefault(ref, block)
        return blocks

    def sheet_sections(self, year: str, month: str) -> dict[str, str]:
        """Every sheet of the month and its section, seguridad or mantenimiento.

        The one rule the dashboard's tabs and the ready email both go by. A
        maintenance sheet's mark settles it; a sheet from before the mark
        goes by where its scan's lines went (sheet_blocks).
        """
        blocks = self.sheet_blocks(year, month, "")
        return {
            ref: (MANTENIMIENTO_SECTION if is_maintenance_ref(ref)
                  else section_of_block(blocks.get(ref, "")))
            for ref in self.all_pages(year, month)
        }

    def remove_entry(self, entry_id: int) -> bool:
        """Delete an entry the reader invented. False if there is none."""
        before = self._event_row(entry_id)
        changed = self._connection.execute(
            "DELETE FROM memoria_entries WHERE rowid = ?", (entry_id,)
        ).rowcount
        self._connection.commit()
        if changed:
            self._record("delete", entry_id, before, None)
        return bool(changed)

    def hand_edited_count(self, year: str, month: str) -> int:
        return self._connection.execute(
            "SELECT COUNT(*) FROM memoria_entries "
            "WHERE year = ? AND month = ? AND hand_edited = 1",
            (year, month),
        ).fetchone()[0]

    def clear_month(self, year: str, month: str) -> tuple[int, int]:
        """Empty a month before reading its scans again.

        Returns (removed, kept). Only entries nobody has touched are removed:
        a correction made by hand outranks anything the reader produced, and
        a reprocess is the reader speaking again. A line moved to another
        subheading by hand is kept too, but kept counts corrections only.
        """
        # Counted as corrections: text somebody changed. A line only moved to
        # another subheading is kept as well, but it is not a "corrección
        # hecha a mano" in the report (main.kept_corrections_report).
        kept = self.hand_edited_count(year, month)
        removed = self._connection.execute(
            "DELETE FROM memoria_entries "
            "WHERE year = ? AND month = ? AND hand_edited = 0 AND hand_block = 0",
            (year, month),
        ).rowcount
        self._connection.commit()
        return removed, kept

    def _corrected_sources(self, year: str, month: str, block: str) -> dict[str, int]:
        """Row id of the correction each dedupe key of superseded text points to.

        A sheet read again produces what it produced before. Without this the
        original would land beside its own correction as a second entry
        saying the same thing badly. The row id is kept, not just the key, so
        the correction can be moved back to its source's sheet position when
        the re-read line is dropped (see `add`).

        A key is checked for being non-empty after computing it, not on
        `original_text` itself: a person's `add_entry` leaves `original_text`
        empty and must never suppress anything, but a hand-edited row whose
        `original_text` was punctuation-only also folds to the empty key and
        needs the same exclusion.
        """
        rows = self._connection.execute(
            "SELECT rowid, original_text FROM memoria_entries "
            "WHERE year = ? AND month = ? AND block = ? AND hand_edited = 1",
            (year, month, block),
        ).fetchall()
        superseded = {}
        for rowid, original_text in rows:
            key = dedupe_key(original_text)
            if key:
                superseded[key] = rowid
        return superseded

    def _place_in_block(self, year: str, month: str, block: str, entry_id: int) -> int:
        """Where a line moved into *block* goes in that block's position order.

        A line on a dated sheet sorts by its own sheet, so the end will do. A
        line with no sheet, or on one with no readable date, is filed under
        the day of the line before it in its block (_sheet_keys), so at the
        end it would join the block's last day. It goes after the new block's
        last line of the day it is on now -- or of the nearest day before it
        -- and the lines after that move down one.
        """
        ref, current = self._connection.execute(
            "SELECT review_ref, block FROM memoria_entries WHERE rowid = ?", (entry_id,),
        ).fetchone()
        end = self._connection.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM memoria_entries "
            "WHERE year = ? AND month = ? AND block = ?", (year, month, block),
        ).fetchone()[0]
        if ref and sheet_order(ref)[0] == 0:
            return end

        def rows_of(name):
            return self._connection.execute(
                "SELECT rowid, review_ref, position FROM memoria_entries "
                "WHERE year = ? AND month = ? AND block = ?", (year, month, name),
            ).fetchall()

        def keys_of(rows):
            return _sheet_keys(rows, ref_of=lambda r: r[1], position_of=lambda r: r[2],
                               block_of=lambda r: "")

        mine = rows_of(current)
        day = keys_of(mine)[id(next(r for r in mine if r[0] == entry_id))]
        target = rows_of(block)
        keys = keys_of(target)
        earlier = [keys[id(r)] for r in target if keys[id(r)] <= day]
        if not earlier:
            place = 0
        else:
            nearest = max(earlier)
            place = max(r[2] for r in target if keys[id(r)] == nearest) + 1
        self._connection.execute(
            "UPDATE memoria_entries SET position = position + 1 "
            "WHERE year = ? AND month = ? AND block = ? AND position >= ?",
            (year, month, block, place),
        )
        return place

    def _retagged_elsewhere(self, year: str, month: str, block: str,
                            review_ref: str) -> dict[str, int]:
        """Row id of each line on this sheet a person moved out of the
        reader's choice.

        Keyed on what the reader would produce again: the line's text, and
        its original text when that was corrected too. A rescan files the
        line under the model's block, where the dedupe index cannot see the
        moved copy, so without this it would come back as a second line.
        Only this sheet's lines: the same words on another day are another
        line, which the person never moved.
        """
        if block not in MANTENIMIENTO_BLOCKS:
            return {}
        found = {}
        for rowid, key, original, other_block in self._connection.execute(
            "SELECT rowid, dedupe_key, original_text, block FROM memoria_entries "
            "WHERE year = ? AND month = ? AND hand_block = 1 AND block != ? "
            "AND review_ref IN (?, '')",
            (year, month, block, review_ref),
        ).fetchall():
            if other_block not in MANTENIMIENTO_BLOCKS:
                continue
            for candidate in (key, dedupe_key(original)):
                if candidate:
                    found[candidate] = rowid
        return found

    def review_pages(self, year: str, month: str) -> dict[str, int]:
        """Sheets with something to check, and how much, in reading order.

        Keyed by the locator the review image is named after, so the line in
        the memoria and the file in the revision folder always agree.
        """
        rows = self._connection.execute(
            "SELECT review_ref, COUNT(*), MIN(position) FROM memoria_entries "
            "WHERE year = ? AND month = ? AND flagged = 1 AND review_ref != '' "
            "GROUP BY review_ref",
            (year, month),
        ).fetchall()
        rows = sorted(rows, key=lambda r: (sheet_order(r[0]), r[2]))
        return {ref: count for ref, count, _ in rows}

    def all_pages(self, year: str, month: str) -> dict[str, int]:
        """Every sheet of the month, and how many doubtful entries each still
        has -- zero included.

        review_pages() answers "what is left to check", which is the right
        list for someone working through the flags. This answers "what came
        in", which is the list for someone who wants to read the whole batch
        against the paper rather than trust the flags to have caught
        everything. A sheet whose every line was confirmed disappears from
        review_pages() and stays here.
        """
        rows = self._connection.execute(
            "SELECT review_ref, SUM(flagged), MIN(position) FROM memoria_entries "
            "WHERE year = ? AND month = ? AND review_ref != '' "
            "GROUP BY review_ref",
            (year, month),
        ).fetchall()
        known = {r[0] for r in rows}
        extra = [
            (ref, 0, 10**9) for (ref,) in self._connection.execute(
                "SELECT review_ref FROM scan_sheets WHERE year = ? AND month = ?",
                (year, month),
            ) if ref not in known
        ]
        rows = sorted(rows + extra, key=lambda r: (sheet_order(r[0]), r[2]))
        return {ref: int(flagged or 0) for ref, flagged, _ in rows}

    def to_check(self, year: str, month: str) -> dict[str, int]:
        """The dashboard's "Por revisar": doubtful sheets, empty ones, and
        ones whose date does not fit the scan.

        review_pages() stays the list the memoria prints -- sheets with a
        doubtful line. For the person working through the month, a sheet
        with no lines at all needs a look too: the reading finding nothing
        does not mean nothing is written on it. So does a date that does not
        fit (date_checks) until someone answers it. Those come with a count
        of 0.
        """
        with_lines = {ref for (ref,) in self._connection.execute(
            "SELECT DISTINCT review_ref FROM memoria_entries "
            "WHERE year = ? AND month = ? AND review_ref != ''", (year, month))}
        confirmed_empty = self.confirmed_empty(year, month)
        # And a sheet whose date does not fit the scan, until a person has
        # confirmed or corrected it: its lines are not flagged for the date
        # any more, so the date has to hold the sheet here by itself.
        questioned = self.date_checks(year, month)
        return {
            ref: count for ref, count in self.all_pages(year, month).items()
            if count or ref in questioned
            or (ref not in with_lines and ref not in confirmed_empty)
        }

    def confirmed_empty(self, year: str, month: str) -> set[str]:
        """Sheets a person confirmed have nothing to add."""
        return {ref for (ref,) in self._connection.execute(
            "SELECT review_ref FROM scan_sheets WHERE year = ? AND month = ? "
            "AND empty_checked = 1", (year, month))}

    def confirm_empty(self, year: str, month: str, review_ref: str) -> bool:
        """Record that an empty sheet was looked at and has nothing to add."""
        changed = self._connection.execute(
            "UPDATE scan_sheets SET empty_checked = 1 "
            "WHERE year = ? AND month = ? AND review_ref = ?",
            (year, month, review_ref),
        ).rowcount
        self._connection.commit()
        return bool(changed)

    def counts(self, year: str, month: str) -> dict[str, int]:
        rows = self._connection.execute(
            "SELECT block, COUNT(*) FROM memoria_entries WHERE year = ? AND month = ? "
            "GROUP BY block",
            (year, month),
        ).fetchall()
        return dict(rows)

    def flagged_count(self, year: str, month: str) -> int:
        return self._connection.execute(
            "SELECT COUNT(*) FROM memoria_entries WHERE year = ? AND month = ? AND flagged = 1",
            (year, month),
        ).fetchone()[0]

    def close(self) -> None:
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
