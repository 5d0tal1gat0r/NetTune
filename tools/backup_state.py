"""Nightly copy of the databases that hold the review work.

Every correction, confirmation and hand-added line the colleague makes lives
only in SQLite on the Pi's SD card, and nothing copied it anywhere. This
takes a snapshot of each database through SQLite's own backup API -- a
consistent copy even while the processor and the dashboard are writing,
which copying the file (and its -wal beside it) is not -- into a folder
named for the day, checks the copy, and keeps the last KEEP_DAYS days.

The scans and sheet images are not copied: the images are rebuilt from the
archived PDFs (tools/rebuild_revision.py), and the PDFs are the scanner's.

Run nightly by deploy/nettune-backup.timer. A copy on the same SD card
survives a bad write or a wrong click, not the card dying; for that, pull
the folder off the Pi (see deploy/README.md):

    ./venv/bin/python tools/backup_state.py                 # into BACKUP_DIR
    ./venv/bin/python tools/backup_state.py --dest /tmp/b   # somewhere else
"""

import argparse
import logging
import os
import re
import shutil
import sqlite3
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config

KEEP_DAYS = 30


def _today() -> date:
    """The Pi's own calendar day: the folder a 02:30 run writes."""
    return datetime.now().astimezone().date()
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_whole(path: str) -> bool:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()


def backup(databases: list[str], dest_root: str, today: date | None = None,
           folder_name: str = "") -> list[str]:
    """Snapshot each existing database into dest_root/YYYY-MM-DD/.

    *folder_name* names the folder instead, for a copy that must not replace
    an earlier one of the same day. Returns the copies written. Raises if a copy fails its integrity check,
    after removing it, so a bad copy is never mistaken for a good one.
    """
    folder = os.path.join(dest_root, folder_name or (today or _today()).isoformat())
    os.makedirs(folder, exist_ok=True)
    written = []
    for source_path in databases:
        if not os.path.isfile(source_path):
            logging.warning(f"Backup: {source_path} not found, skipped")
            continue
        target = os.path.join(folder, os.path.basename(source_path))
        partial = target + ".partial"
        source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
        copy = sqlite3.connect(partial)
        try:
            source.backup(copy)
            # One self-contained file: the copy inherits WAL mode, which
            # would leave -wal and -shm files beside it.
            copy.execute("PRAGMA journal_mode=DELETE")
        finally:
            copy.close()
            source.close()
        if not _is_whole(partial):
            os.remove(partial)
            raise RuntimeError(f"Backup of {source_path} failed its integrity check")
        os.replace(partial, target)
        # Readable like the live databases in state/ are, so the copies can
        # be pulled off the Pi by the admin account (deploy/pull_backups.sh).
        os.chmod(target, 0o644)
        written.append(target)
    return written


def prune(dest_root: str, keep_days: int = KEEP_DAYS, today: date | None = None) -> list[str]:
    """Remove the day folders older than *keep_days*. Returns what went.

    Only folders named like a date are touched: anything else put there by
    hand stays.
    """
    cutoff = (today or _today()) - timedelta(days=keep_days)
    removed = []
    for name in sorted(os.listdir(dest_root)) if os.path.isdir(dest_root) else []:
        if _DAY.match(name) and date.fromisoformat(name) < cutoff:
            shutil.rmtree(os.path.join(dest_root, name))
            removed.append(os.path.join(dest_root, name))
    return removed


def databases() -> list[str]:
    """Every database the Pi keeps, the review work and its feedback alike."""
    return [config.entry_db, config.state_db, config.spend_db, config.feedback_db]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dest", default=config.backup_dir,
                        help=f"Where the day folders go (default {config.backup_dir})")
    parser.add_argument("--keep-days", type=int, default=KEEP_DAYS)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    written = backup(databases(), args.dest)
    removed = prune(args.dest, args.keep_days)
    for path in written:
        logging.info(f"Backed up {path} ({os.path.getsize(path) // 1024} KB)")
    for path in removed:
        logging.info(f"Removed old backup {path}")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
