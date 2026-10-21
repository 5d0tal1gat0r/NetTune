"""Every stage of a reading is kept, and keeping it changes nothing."""

import json
import os
import sqlite3

import pytest
from conftest import a_page

from ocr_feedback.store import FeedbackReader

ENTRIES = (("Se abre Z6", True), ("Conectando mq de aire", True), ("Puerta forzada", False))
PASSES = [{"trabajos": ["Se abre Z6", "Conectando mq de aire", "Puerta forzada"]},
          {"trabajos": ["Se abre 26", "Conectando mq de aire"]}]


def _routine(page, **kw):
    page = json.loads(json.dumps(page))
    for t in page["trabajos"]:
        t["routine"] = t["text"].startswith("Conectando")
    return page


@pytest.fixture
def process(app, tmp_path, monkeypatch):
    from entry_store import EntryStore
    from processed_ledger import ProcessedLedger
    from spend_guard import SpendGuard

    def reading(image, collector=None, **kw):
        if collector is not None:
            collector.extend(json.loads(json.dumps(PASSES)))
        return a_page(fecha="16-09-2026", entries=ENTRIES)

    monkeypatch.setattr(app, "page_images", lambda path, workdir: [path])
    monkeypatch.setattr(app, "already_read", lambda *a, **k: [])
    monkeypatch.setattr(app, "read_page_with_consensus", reading)
    monkeypatch.setattr(app, "filter_page", _routine)

    def go(tag, capture=True, cache=None):
        app.config.dataset_capture = capture
        scan = os.path.join(app.incoming, f"SKM_{tag}.pdf")
        with open(scan, "wb") as handle:
            handle.write(f"scan {tag}".encode())
        ledger = ProcessedLedger(str(tmp_path / "state" / f"p-{tag}.sqlite3"))
        if cache is not None:
            ledger.cache_put(ledger.digest(scan), "page:1", json.dumps(cache))
        guard = SpendGuard(str(tmp_path / "state" / f"s-{tag}.sqlite3"), 5, 1.1)
        db = str(tmp_path / "state" / f"e-{tag}.sqlite3")
        with EntryStore(db) as store:
            outcome = app.process_scan(scan, ledger, guard, store)
        ledger.close()
        guard.close()
        return outcome, db, f"SKM_{tag}.pdf#1"

    return go


def _rows(db):
    c = sqlite3.connect(db)
    entries = c.execute(
        "SELECT block, position, text, flagged, review_ref, hand_edited, original_text, "
        "paper_order, hand_block FROM memoria_entries ORDER BY block, position").fetchall()
    sheets = c.execute("SELECT year, month, page, review_ref, scan_position "
                       "FROM scan_sheets ORDER BY page").fetchall()
    schema = sorted(c.execute("SELECT type, name, sql FROM sqlite_master").fetchall())
    return entries, sheets, schema


def test_capture_on_and_off_produce_the_same_memoria(process, app, monkeypatch):
    from processed_ledger import ProcessedLedger

    # clear_cache runs at the end of a scan; record what the cache held first.
    held = {}
    real_clear = ProcessedLedger.clear_cache

    def spying_clear(self, digest):
        rows = self._connection.execute(
            "SELECT kind, value FROM stage_cache ORDER BY kind").fetchall()
        held.setdefault(self._tag, rows)
        real_clear(self, digest)

    monkeypatch.setattr(ProcessedLedger, "clear_cache", spying_clear)
    real_init = ProcessedLedger.__init__

    def tagged_init(self, path, *a, **k):
        real_init(self, path, *a, **k)
        self._tag = "on" if "p-on" in path else "off"

    monkeypatch.setattr(ProcessedLedger, "__init__", tagged_init)
    on = process("on", capture=True)
    off = process("off", capture=False)
    assert on[0] == off[0] == "processed"
    assert _rows(on[1]) == _rows(off[1])
    assert held["on"] and held["on"] == held["off"]


def test_all_four_stages_are_kept(process, app):
    _, _, pid = process("a")
    reader = FeedbackReader(app.config.feedback_db)
    stages = reader.latest_stages(pid)
    assert [[l.text for l in o.lines] for o in stages["passes"]] == [
        PASSES[0]["trabajos"], PASSES[1]["trabajos"]]
    assert [l.text for l in stages["consensus"][0].lines] == [t for t, _ in ENTRIES]
    assert stages["consensus"][0].lines[2].meta["disagreement"] is True
    assert [l.text for l in stages["filtered"][0].lines] == [t for t, _ in ENTRIES]
    assert [l.text for l in stages["omitted"][0].lines] == ["Conectando mq de aire"]
    page = reader.page(pid)
    assert page.image_ref == "16-09-2026_p1.jpg"
    assert page.meta == {"review_ref": "16-09-2026 p1", "section": "seguridad"}


def test_capture_off_writes_no_file(process, app):
    process("x", capture=False)
    assert not os.path.exists(app.config.feedback_db)


def test_a_cache_hit_keeps_no_passes(process, app):
    _, _, pid = process("c", cache=a_page(fecha="16-09-2026", entries=ENTRIES))
    stages = FeedbackReader(app.config.feedback_db).latest_stages(pid)
    assert "passes" not in stages
    assert stages["consensus"][0].cached is True


def test_a_recorder_that_raises_changes_nothing(process, monkeypatch):
    import nettune_feedback

    class Exploding:
        enabled = True

        calls = 0

        def record_run(self, *_):
            Exploding.calls += 1
            raise RuntimeError("boom")

        record_page = record_stage = record_event = record_run

    good = process("good")
    monkeypatch.setattr(nettune_feedback, "recorder", lambda: Exploding())
    bad = process("bad")
    assert bad[0] == "processed"
    assert Exploding.calls > 0
    assert _rows(good[1]) == _rows(bad[1])


def test_reader_without_collector_is_unchanged(monkeypatch):
    import page_reader

    calls = iter([{"tipo": None, "titulo": "T", "fecha": "16-09-2026", "horario": None,
                   "operarios": [], "trabajos": ["Se abre Z6"]}] * 2)
    monkeypatch.setattr(page_reader, "read_page", lambda *a, **k: next(calls))
    plain = page_reader.read_page_with_consensus("x.png", readings=2)
    calls = iter([{"tipo": None, "titulo": "T", "fecha": "16-09-2026", "horario": None,
                   "operarios": [], "trabajos": ["Se abre Z6"]}] * 2)
    got = []
    with_collector = page_reader.read_page_with_consensus("x.png", readings=2, collector=got)
    assert plain == with_collector
    assert len(got) == 2 and got[0]["trabajos"] == ["Se abre Z6"]


def test_stages_are_snapshots_taken_before_later_mutation(process, app, monkeypatch):
    def mutating(page, **kw):
        for t in page["trabajos"]:
            t["routine"] = t["text"].startswith("Conectando")
        return page

    # coherent=False makes needs_review flag the entry after the filter ran.
    page = a_page(fecha="16-09-2026", entries=ENTRIES)
    for t in page["trabajos"]:
        t["coherent"] = False
    monkeypatch.setattr(app, "filter_page", mutating)
    monkeypatch.setattr(app, "read_page_with_consensus",
                        lambda image, collector=None, **kw: json.loads(json.dumps(page)))
    outcome, db, pid = process("snap")
    assert outcome == "processed"
    stages = FeedbackReader(app.config.feedback_db).latest_stages(pid)
    assert not any("routine" in l.meta for l in stages["consensus"][0].lines)
    assert [l.meta["disagreement"] for l in stages["filtered"][0].lines] == [
        not c for _, c in ENTRIES]
    assert [l.text for l in stages["omitted"][0].lines] == ["Conectando mq de aire"]


def test_passes_survive_a_failed_scan_that_is_retried(app, tmp_path, monkeypatch):
    from entry_store import EntryStore
    from processed_ledger import ProcessedLedger
    from spend_guard import SpendGuard
    from transcription_service import TranscriptionError

    page_a, page_b = "page-a.png", "page-b.png"
    monkeypatch.setattr(app, "page_images", lambda path, workdir: [page_a, page_b])
    monkeypatch.setattr(app, "already_read", lambda *a, **k: [])
    monkeypatch.setattr(app, "filter_page", _routine)
    fail = {"on": True}
    seen = []

    def reading(image, collector=None, **kw):
        seen.append(image)
        if image == page_b and fail["on"]:
            raise TranscriptionError("api down")
        if collector is not None:
            collector.extend(json.loads(json.dumps(PASSES)))
        return a_page(fecha="16-09-2026", entries=ENTRIES)

    monkeypatch.setattr(app, "read_page_with_consensus", reading)
    app.config.dataset_capture = True
    scan = os.path.join(app.incoming, "SKM_retry.pdf")
    with open(scan, "wb") as handle:
        handle.write(b"scan retry")
    ledger = ProcessedLedger(str(tmp_path / "state" / "p-retry.sqlite3"))
    guard = SpendGuard(str(tmp_path / "state" / "s-retry.sqlite3"), 5, 1.1)
    db = str(tmp_path / "state" / "e-retry.sqlite3")
    with EntryStore(db) as store:
        try:
            app.process_scan(scan, ledger, guard, store)
        except TranscriptionError:
            pass
        first = seen.count(page_a)
        fail["on"] = False
        outcome = app.process_scan(scan, ledger, guard, store)
    ledger.close()
    guard.close()
    assert outcome == "processed"
    assert seen.count(page_a) == first  # the retry read page 1 from the cache
    stages = FeedbackReader(app.config.feedback_db).latest_stages("SKM_retry.pdf#1")
    assert [[l.text for l in o.lines] for o in stages["passes"]] == [
        PASSES[0]["trabajos"], PASSES[1]["trabajos"]]
    assert stages["consensus"][0].cached is True
