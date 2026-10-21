"""The review work is copied every night, and a copy that is not whole is not kept.

Every correction, confirmation and hand-added line lives only in SQLite on
the Pi's SD card. tools/backup_state.py takes a consistent snapshot of each
database -- through SQLite's backup API, safe while the services write --
into a dated folder, checks it, and keeps the last few weeks.
"""

import importlib.util
import os
import sqlite3
from datetime import date

import pytest


@pytest.fixture
def tool():
    path = os.path.join(os.path.dirname(__file__), "..", "tools", "backup_state.py")
    spec = importlib.util.spec_from_file_location("backup_state", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _db(path, rows):
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE IF NOT EXISTS t (x TEXT)")
    connection.executemany("INSERT INTO t VALUES (?)", [(r,) for r in rows])
    connection.commit()
    return connection


def test_a_snapshot_holds_what_was_committed_even_if_still_in_the_wal(tool, tmp_path):
    live = _db(str(tmp_path / "memoria_entries.sqlite3"), ["corregida", "confirmada"])
    try:
        # The writer is still open: the rows may sit in the -wal file only.
        written = tool.backup([str(tmp_path / "memoria_entries.sqlite3")],
                              str(tmp_path / "backups"), today=date(2026, 9, 30))
    finally:
        live.close()
    assert written == [str(tmp_path / "backups" / "2026-09-30" / "memoria_entries.sqlite3")]
    assert sorted(os.listdir(tmp_path / "backups" / "2026-09-30")) == [
        "memoria_entries.sqlite3"], "one file, nothing beside it"
    copy = sqlite3.connect(written[0])
    assert [r[0] for r in copy.execute("SELECT x FROM t ORDER BY x")] == [
        "confirmada", "corregida"]
    copy.close()


def test_a_missing_database_is_skipped_not_fatal(tool, tmp_path):
    _db(str(tmp_path / "a.sqlite3"), ["x"]).close()
    written = tool.backup([str(tmp_path / "a.sqlite3"), str(tmp_path / "nope.sqlite3")],
                          str(tmp_path / "backups"), today=date(2026, 9, 30))
    assert [os.path.basename(p) for p in written] == ["a.sqlite3"]


def test_running_twice_a_day_replaces_that_days_copy(tool, tmp_path):
    source = str(tmp_path / "a.sqlite3")
    _db(source, ["uno"]).close()
    tool.backup([source], str(tmp_path / "b"), today=date(2026, 9, 30))
    _db(source, ["dos"]).close()
    (copy,) = tool.backup([source], str(tmp_path / "b"), today=date(2026, 9, 30))
    connection = sqlite3.connect(copy)
    assert connection.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    connection.close()


def test_only_the_last_weeks_are_kept(tool, tmp_path):
    root = tmp_path / "b"
    for day in ("2026-08-01", "2026-09-01", "2026-09-29", "not-a-date"):
        (root / day).mkdir(parents=True)
    removed = tool.prune(str(root), keep_days=30, today=date(2026, 9, 30))
    assert sorted(os.path.basename(p) for p in removed) == ["2026-08-01"]
    assert sorted(os.listdir(root)) == ["2026-09-01", "2026-09-29", "not-a-date"]


def test_a_copy_that_fails_its_check_is_not_left_looking_good(tool, tmp_path, monkeypatch):
    source = str(tmp_path / "a.sqlite3")
    _db(source, ["x"]).close()
    monkeypatch.setattr(tool, "_is_whole", lambda path: False)
    with pytest.raises(RuntimeError):
        tool.backup([source], str(tmp_path / "b"), today=date(2026, 9, 30))
    assert not os.path.exists(tmp_path / "b" / "2026-09-30" / "a.sqlite3")


def test_the_feedback_database_is_backed_up_too(tool):
    from config import config

    assert config.feedback_db in tool.databases()
    assert set(tool.databases()) >= {config.entry_db, config.state_db, config.spend_db}
