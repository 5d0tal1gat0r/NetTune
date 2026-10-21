"""Reads one archived scan again, with the rules as they are now.

Lines already stored keep the rules they were read with: September's
maintenance sheets were read the day before the crew's conventions went in
(P/C is planta 1, PØ planta 0, the parking mark...), and only a new reading
applies them. This re-reads one scan of one month and leaves the rest of the
month alone -- the security batches are not touched, nor paid for again.

What a person did is kept: a line edited or moved by hand, a line added by
hand, a date confirmed or corrected (put back on the re-read sheet), an
empty sheet confirmed. Lines nobody touched, the sheet records and the
review images of that scan are replaced by the new reading.

--drop-page N throws away the sheet at position N of the scan once it has
been read: a sheet that does not belong in the month. Reading it and then
dropping it, rather than not reading it, keeps every other sheet's pN.

Stop the processor first: it must not file a scan, or find this one, while
the month is being rewritten. The databases are backed up before anything
changes, into a folder of their own for every run. If the reading fails --
the API refuses the key, the budget runs out -- the scan's sheets, lines and
review images are put back as they were.

    sudo systemctl stop security-log-processor
    sudo -u scanproc ./venv/bin/python tools/reread_scan.py \\
        2026 SEPTIEMBRE S25C-0i26093013070.pdf --drop-page 1
    sudo systemctl start security-log-processor
"""

import argparse
import contextlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def processor_running() -> bool:
    return subprocess.run(
        ["systemctl", "is-active", "--quiet", "security-log-processor"],
        check=False,
    ).returncode == 0


def _sheets(store, year: str, month: str, source: str) -> dict[int, dict]:
    """Scan position -> what the sheet was called and what a person checked."""
    rows = store._connection.execute(
        "SELECT scan_position, page, review_ref, date_checked, empty_checked "
        "FROM scan_sheets WHERE year = ? AND month = ? AND source = ?",
        (year, month, source),
    ).fetchall()
    return {
        position: {"page": page, "ref": ref, "date_checked": bool(date_checked),
                   "empty_checked": bool(empty_checked)}
        for position, page, ref, date_checked, empty_checked in rows
    }


def _stamp() -> str:
    """Names this run's backup folder: two runs a day keep two copies."""
    return datetime.now().astimezone().strftime("%Y-%m-%d-%H%M%S")


def _snapshot(store, source: str) -> dict[str, tuple[list[str], list[tuple]]]:
    """Every row *source* has, in every month: what a failed reading restores."""
    taken = {}
    for table in ("memoria_entries", "scan_sheets"):
        columns = [row[1] for row in store._connection.execute(f"PRAGMA table_info({table})")]
        rows = store._connection.execute(
            f"SELECT {', '.join(columns)} FROM {table} WHERE source = ?", (source,)
        ).fetchall()
        taken[table] = (columns, rows)
    return taken


def _put_back(store, source: str, taken: dict, held: str, revision_dir: str) -> None:
    """Undo a reading that failed part way: rows and review images as before."""
    for table, (columns, rows) in taken.items():
        store._connection.execute(f"DELETE FROM {table} WHERE source = ?", (source,))
        store._connection.executemany(
            f"INSERT INTO {table} ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' * len(columns))})", rows)
    store._connection.commit()
    for name in os.listdir(held):
        os.replace(os.path.join(held, name), os.path.join(revision_dir, name))


def _forget(store, revision_dir: str, year: str, month: str, source: str,
            held: str) -> int:
    """Remove what the last reading of *source* left. Returns lines removed.

    The review images are moved into *held*, not deleted, so a reading that
    fails can put them back.
    """
    from review_marks import image_name

    for sheet in _sheets(store, year, month, source).values():
        name = image_name(sheet["ref"])
        with contextlib.suppress(FileNotFoundError):
            os.replace(os.path.join(revision_dir, name), os.path.join(held, name))
    removed = store._connection.execute(
        "DELETE FROM memoria_entries WHERE year = ? AND month = ? AND source = ? "
        "AND hand_edited = 0 AND hand_block = 0",
        (year, month, source),
    ).rowcount
    store._connection.execute(
        "DELETE FROM scan_sheets WHERE year = ? AND month = ? AND source = ?",
        (year, month, source),
    )
    store._connection.commit()
    return removed


def _drop(store, source: str, position: int) -> list[str]:
    """Delete the sheet at scan *position*, its lines and its image.

    Looked for in every month: a sheet's own date files it, so the one
    dropped -- because it does not belong -- may well have gone elsewhere.
    """
    from config import config
    from month_folders import revision_dir_for
    from review_marks import image_name

    rows = store._connection.execute(
        "SELECT year, month, review_ref FROM scan_sheets "
        "WHERE source = ? AND scan_position = ?", (source, position),
    ).fetchall()
    for year, month, ref in rows:
        store._connection.execute(
            "DELETE FROM memoria_entries WHERE year = ? AND month = ? AND review_ref = ?",
            (year, month, ref),
        )
        store._connection.execute(
            "DELETE FROM scan_sheets WHERE year = ? AND month = ? AND source = ? "
            "AND scan_position = ?",
            (year, month, source, position),
        )
        with contextlib.suppress(FileNotFoundError):
            os.remove(os.path.join(revision_dir_for(config.incoming_dir, year, month),
                                   image_name(ref)))
    store._connection.commit()
    return [f"{month} {year}: {ref}" for year, month, ref in rows]


def _restore(store, revision_dir: str, year: str, month: str, source: str,
             before: dict[int, dict]) -> list[str]:
    """Put back the dates and empty sheets a person checked. Returns notes."""
    from review_marks import image_name

    notes = []
    after = _sheets(store, year, month, source)
    for position, old in sorted(before.items()):
        new = after.get(position)
        if new is None:
            continue
        ref = new["ref"]
        if old["date_checked"]:
            old_date = old["ref"].split(" ")[-2]
            moved = store.redate_sheet(year, month, ref, old_date)
            if moved is None:
                notes.append(f"position {position}: could not put back the date "
                             f"{old_date} on {ref}; check it in the dashboard")
            else:
                if moved != ref:
                    with contextlib.suppress(FileNotFoundError):
                        os.replace(os.path.join(revision_dir, image_name(ref)),
                                   os.path.join(revision_dir, image_name(moved)))
                ref = moved
        if old["empty_checked"]:
            store.confirm_empty(year, month, ref)
    return notes


def _orphans(store, year: str, month: str) -> list[tuple[str, str]]:
    """(sheet, line) for lines kept by hand whose sheet no longer exists."""
    return store._connection.execute(
        "SELECT review_ref, text FROM memoria_entries e WHERE year = ? AND month = ? "
        "AND review_ref != '' AND NOT EXISTS (SELECT 1 FROM scan_sheets s "
        "WHERE s.year = e.year AND s.month = e.month AND s.review_ref = e.review_ref)",
        (year, month),
    ).fetchall()


def reread(store, ledger, guard, year: str, month: str, source: str,
           drop_pages: tuple[int, ...] = ()) -> list[str]:
    """Re-read *source* into year/month. Returns notes for the person.

    The scan is read from the month folder and filed back into the month's
    archive under its own name; if the reading fails it is put back where it
    was, and the error raised.
    """
    import main
    from config import config
    from month_folders import archive_dir_for, memoria_name, processed_dir_for, revision_dir_for

    archived = os.path.join(archive_dir_for(config.incoming_dir, year, month), source)
    if not os.path.isfile(archived):
        raise FileNotFoundError(f"{archived} is not there")
    revision_dir = revision_dir_for(config.incoming_dir, year, month)

    before = _sheets(store, year, month, source)
    taken = _snapshot(store, source)
    os.makedirs(revision_dir, exist_ok=True)
    held = tempfile.mkdtemp(prefix=".reread-", dir=revision_dir)
    try:
        removed = _forget(store, revision_dir, year, month, source, held)
        notes = [f"{removed} line(s) and {len(before)} sheet(s) of the last reading removed"]

        # Read from the month folder itself, as if just dropped there: the
        # folder decides the month when too few dates can be read, and the
        # processor, stopped, will not pick it up meanwhile.
        reading = os.path.join(processed_dir_for(config.incoming_dir, year, month), source)
        if os.path.exists(reading):
            raise FileExistsError(f"{reading} is in the way")
        shutil.move(archived, reading)
        try:
            outcome = main.process_scan(reading, ledger, guard, store)
        finally:
            if os.path.exists(reading):
                # Failed, or not filed (blank, every sheet already read): back
                # where it was.
                shutil.move(reading, archived)
    except BaseException:
        _put_back(store, source, taken, held, revision_dir)
        raise
    finally:
        shutil.rmtree(held, ignore_errors=True)
    notes.append(f"read again: {outcome}")

    for position in drop_pages:
        dropped = _drop(store, source, position)
        notes.append(f"position {position}: "
                     + (f"dropped {', '.join(dropped)}" if dropped else "no such sheet"))
    notes += _restore(store, revision_dir, year, month, source, before)
    for ref, text in _orphans(store, year, month):
        notes.append(f"line left without its sheet ({ref}): {text}")

    folder = processed_dir_for(config.incoming_dir, year, month)
    if any(os.path.exists(os.path.join(folder, memoria_name(year, month, draft=d)))
           for d in (False, True)):
        main.rebuild_memoria(store, year, month, draft=bool(store.to_check(year, month)))
        notes.append("memoria rewritten")
    return notes


def main_cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("year")
    parser.add_argument("month")
    parser.add_argument("scan", help="file name in the month's .escaneos_originales/")
    parser.add_argument("--drop-page", type=int, action="append", default=[],
                        help="scan position of a sheet to throw away after reading")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    if processor_running():
        print("security-log-processor is running; stop it first.")
        return 2

    from config import config
    from entry_store import EntryStore
    from processed_ledger import ProcessedLedger
    from spend_guard import SpendGuard
    from tools.backup_state import backup

    dest = os.path.join(config.backup_dir, "before-reread")
    print("backed up:", ", ".join(backup([config.entry_db, config.state_db], dest,
                                         folder_name=_stamp())))

    guard = SpendGuard(config.spend_db, monthly_budget_eur=config.monthly_budget_eur,
                       eur_usd=config.eur_usd)
    with EntryStore(config.entry_db) as store:
        notes = reread(store, ProcessedLedger(config.state_db), guard,
                       args.year, args.month, args.scan, tuple(args.drop_page))
    for note in notes:
        print(note)
    print(guard.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())
