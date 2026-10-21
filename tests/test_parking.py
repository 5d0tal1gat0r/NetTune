"""The parking-ticket log is set aside in Parking/, never read or paid for.

page_images runs for real here; only rendering, the classifier and the
reading are stubbed, so the pages it keeps and the ones it sets aside are
the ones process_scan acts on.
"""

import os

import pytest
from conftest import a_page
from PIL import Image


@pytest.fixture
def run(app, tmp_path, monkeypatch):
    from entry_store import EntryStore
    from processed_ledger import ProcessedLedger
    from spend_guard import SpendGuard

    reads, splits = [], []

    def go(kinds):
        rendered = []
        for number, kind in enumerate(kinds, start=1):
            path = str(tmp_path / f"render-{number}.png")
            Image.new("L", (200, 280), 255).save(path)
            rendered.append((path, kind))
        monkeypatch.setattr(app, "is_pdf", lambda path: True)
        monkeypatch.setattr(app, "render_pages", lambda *a, **k: [p for p, _ in rendered])
        monkeypatch.setattr(app, "classify", dict(rendered).get)
        monkeypatch.setattr(app, "split_sheets",
                            lambda page, workdir: splits.append(page) or [page])
        monkeypatch.setattr(app, "straighten", lambda page, **k: page)
        monkeypatch.setattr(app, "to_portrait", lambda page: page)
        monkeypatch.setattr(app, "already_read", lambda *a, **k: [])
        monkeypatch.setattr(app, "read_page_with_consensus",
                            lambda image, **kw: reads.append(image) or a_page(fecha="16-09-2026"))
        monkeypatch.setattr(app, "filter_page", lambda page, **kw: page)

        scan = os.path.join(app.incoming, "S25C-0i26093012540.pdf")
        with open(scan, "wb") as handle:
            handle.write(b"%PDF scan")
        ledger = ProcessedLedger(str(tmp_path / "state" / "p.sqlite3"))
        guard = SpendGuard(str(tmp_path / "state" / "s.sqlite3"), 5, 1.1)
        with EntryStore(str(tmp_path / "state" / "e.sqlite3")) as store:
            outcome = app.process_scan(scan, ledger, guard, store)
        return outcome, scan, ledger

    go.reads = reads
    go.splits = splits
    return go


def test_a_scan_of_only_the_ticket_log_moves_whole_and_unread(app, run):
    outcome, scan, ledger = run(["parking", "parking"])
    assert outcome == "parking"
    assert run.reads == [], "not one reading paid for"
    parking = os.path.join(app.incoming, "Parking")
    assert os.listdir(parking) == ["S25C-0i26093012540.pdf"]
    assert not os.path.exists(scan)
    assert ledger.filed_as(ledger.digest(os.path.join(parking, "S25C-0i26093012540.pdf"))) \
        == "Parking"


def test_ticket_pages_in_a_mixed_scan_are_cut_out_and_the_rest_is_read(app, run):
    outcome, *_ = run(["mantenimiento", "parking", "mantenimiento"])
    assert outcome == "processed"
    assert len(run.reads) == 2
    parking = os.path.join(app.incoming, "Parking")
    assert os.listdir(parking) == ["S25C-0i26093012540_parking.pdf"]
    from pdf_pages import page_count
    assert page_count(os.path.join(parking, "S25C-0i26093012540_parking.pdf")) == 1


def test_a_maintenance_page_is_read_whole_and_a_security_page_split(app, run):
    outcome, *_ = run(["mantenimiento", "seguridad"])
    assert outcome == "processed"
    assert len(run.splits) == 1
    assert run.splits[0].endswith("render-2.png")


def test_the_parking_folder_is_never_scanned(app):
    from scan_filter import is_processable_scan

    path = os.path.join(app.incoming, "Parking", "S25C.pdf")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"%PDF")
    assert not is_processable_scan(path, app.incoming)


def test_the_parking_folder_is_laid_out_beside_the_years(app):
    assert os.path.isdir(os.path.join(app.incoming, "Parking"))
