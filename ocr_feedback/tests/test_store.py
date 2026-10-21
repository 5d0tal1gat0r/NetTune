import gc
import os
import sqlite3
import tempfile
import threading
import time

import pytest

from ocr_feedback.model import Line, Page, ReviewEvent, Run, StageOutput
from ocr_feedback.store import FeedbackReader, SqliteRecorder, private_copy


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "sub" / "feedback.sqlite3")


def _run(rec, run_id, at):
    rec.record_run(Run(run_id, "cfg", at, {"model": "m"}))


def test_creates_schema_and_wal(db):
    SqliteRecorder(db, "toy")
    c = sqlite3.connect(db)
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"schema_version", "runs", "pages", "stage_outputs", "events"} <= tables
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert c.execute("SELECT version FROM schema_version").fetchall() == [(1,)]


def test_reopening_keeps_one_version_row(db):
    SqliteRecorder(db, "toy")
    SqliteRecorder(db, "toy")
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 1


def test_page_upsert_keeps_first_seen(db):
    rec = SqliteRecorder(db, "toy")
    rec.record_page(Page("p1", "a.jpg", {"ref": "x"}))
    rec.record_page(Page("p1", "b.jpg", {"ref": "y"}))
    page = FeedbackReader(db).page("p1")
    assert page.image_ref == "b.jpg" and page.meta == {"ref": "y"}
    assert FeedbackReader(db).page_ids() == ["p1"]


def test_latest_stage_per_stage_name(db):
    rec = SqliteRecorder(db, "toy")
    _run(rec, "r1", "2026-10-01T00:00:00+00:00")
    _run(rec, "r2", "2026-10-02T00:00:00+00:00")
    rec.record_stage(StageOutput("p1", "r1", "ocr", [Line("old a")], seq=1))
    rec.record_stage(StageOutput("p1", "r1", "ocr", [Line("old b")], seq=2))
    rec.record_stage(StageOutput("p1", "r1", "clean", [Line("old")]))
    # r2 was a cache hit: no ocr readings, a newer clean stage
    rec.record_stage(StageOutput("p1", "r2", "clean", [Line("new", {"f": True})], cached=True))
    stages = FeedbackReader(db).latest_stages("p1")
    assert [o.lines[0].text for o in stages["ocr"]] == ["old a", "old b"]
    assert [o.seq for o in stages["ocr"]] == [1, 2]
    assert stages["clean"][0].lines[0].text == "new"
    assert stages["clean"][0].lines[0].meta == {"f": True}
    assert stages["clean"][0].cached is True


def test_events_in_order_with_meta(db):
    rec = SqliteRecorder(db, "toy")
    rec.record_event(ReviewEvent("p1", "7", "edit", "cobre", "aire", meta={"h": "edit"}))
    rec.record_event(ReviewEvent("p1", "7", "retag", before_tag="A", after_tag="B"))
    events = FeedbackReader(db).events("p1")
    assert [e.action for e in events] == ["edit", "retag"]
    assert events[0].before_text == "cobre" and events[0].after_text == "aire"
    assert events[0].meta == {"h": "edit"} and events[0].at
    assert events[1].before_tag == "A" and events[1].after_tag == "B"


def test_unicode_text_round_trips(db):
    text = 'Revisión "cuadro" P/0 — ñandú\nlínea 2 🚪'
    rec = SqliteRecorder(db, "toy")
    rec.record_event(ReviewEvent("p1", "1", "edit", text, text))
    rec.record_stage(StageOutput("p1", "r", "ocr", [Line(text)], seq=1))
    reader = FeedbackReader(db)
    assert reader.events("p1")[0].after_text == text
    assert reader.latest_stages("p1")["ocr"][0].lines[0].text == text


def test_locked_db_fails_fast(db):
    rec = SqliteRecorder(db, "toy", timeout=0.2)
    blocker = sqlite3.connect(db, isolation_level=None)
    blocker.execute("BEGIN EXCLUSIVE")
    try:
        start = time.monotonic()
        with pytest.raises(sqlite3.OperationalError):
            rec.record_event(ReviewEvent("p1", "1", "confirm"))
        assert time.monotonic() - start < 2.0
    finally:
        blocker.execute("ROLLBACK")


def test_concurrent_threads_all_land(db):
    rec = SqliteRecorder(db, "toy")
    errors = []

    def work(n):
        try:
            for i in range(20):
                rec.record_event(ReviewEvent("p1", f"{n}-{i}", "confirm"))
        except Exception as exc:  # pragma: no cover - the assertion reports it
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(FeedbackReader(db).events("p1")) == 80


def _bytes(path):
    if not os.path.exists(path):
        return b""  # a missing -wal and an empty one hold the same (no) data
    with open(path, "rb") as f:
        return f.read()


def test_reader_never_touches_the_original(db):
    rec = SqliteRecorder(db, "toy")
    rec.record_event(ReviewEvent("p1", "1", "confirm"))
    before = (_bytes(db), _bytes(db + "-wal"))
    reader = FeedbackReader(db)
    assert len(reader.events("p1")) == 1
    reader.close()
    assert (_bytes(db), _bytes(db + "-wal")) == before


def test_reader_sees_uncheckpointed_wal_of_live_writer(db):
    SqliteRecorder(db, "toy")
    writer = sqlite3.connect(db)
    try:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute(
            "INSERT INTO events (page_id, line_ref, action, meta_json, at) "
            "VALUES ('p1', '1', 'confirm', '{}', 'now')")
        writer.commit()
        assert os.path.getsize(db + "-wal") > 0
        before = (_bytes(db), _bytes(db + "-wal"))
        reader = FeedbackReader(db)
        assert [e.line_ref for e in reader.events("p1")] == ["1"]
        reader.close()
        assert (_bytes(db), _bytes(db + "-wal")) == before
    finally:
        writer.close()


def test_private_copy_is_a_separate_readable_snapshot(db):
    rec = SqliteRecorder(db, "toy")
    rec.record_event(ReviewEvent("p1", "1", "confirm"))
    folder, copy = private_copy(db)
    try:
        assert os.path.dirname(copy) == folder and copy != db
        c = sqlite3.connect(copy)
        assert c.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        c.close()
    finally:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)


def test_reader_of_missing_db_is_empty(tmp_path):
    for path in (None, str(tmp_path / "nope.sqlite3")):
        reader = FeedbackReader(path)
        assert reader.page_ids() == [] and reader.events("p") == []
        assert reader.latest_stages("p") == {} and reader.page("p") is None
    assert not (tmp_path / "nope.sqlite3").exists()


def _copies(folder):
    return sorted(p.name for p in folder.iterdir() if p.name.startswith("ocr_feedback_"))


@pytest.fixture
def private_tmp(tmp_path, monkeypatch):
    """Temp copies go into their own folder, so leftovers can be counted."""
    folder = tmp_path / "tmpdir"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    return folder


def test_a_dropped_reader_removes_its_copy(db, private_tmp):
    SqliteRecorder(db, "toy").record_event(ReviewEvent("p1", "1", "confirm"))
    reader = FeedbackReader(db)
    assert len(reader.events("p1")) == 1
    assert len(_copies(private_tmp)) == 1
    del reader
    gc.collect()
    assert _copies(private_tmp) == []


def test_close_and_context_manager_remove_the_copy(db, private_tmp):
    SqliteRecorder(db, "toy").record_event(ReviewEvent("p1", "1", "confirm"))
    with FeedbackReader(db) as reader:
        assert len(reader.events("p1")) == 1
    assert _copies(private_tmp) == []
    reader.close()  # a second close is harmless
    assert reader.events("p1") == []
