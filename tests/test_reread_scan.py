"""tools/reread_scan.py: one scan of a month read again, the person's work kept."""

import os

import pytest


@pytest.fixture
def setup(app, tmp_path, monkeypatch):
    """A maintenance scan of three sheets, read once with the old reading."""
    from conftest import a_page

    from entry_store import EntryStore
    from processed_ledger import ProcessedLedger
    from spend_guard import SpendGuard

    reading = {"text": "Reparando luz P/C"}
    dates = ["31-08-2026", "01-09-2026", "02-09-2026"]

    monkeypatch.setattr(app, "page_images",
                        lambda path, workdir: [f"{path}#{i}" for i in range(3)])
    monkeypatch.setattr(
        app, "read_page_with_consensus",
        lambda image, **kw: dict(
            a_page(fecha=dates[int(image.rsplit("#", 1)[1])],
                   entries=((f'{reading["text"]} {dates[int(image.rsplit("#", 1)[1])]}',
                             False),)),
            tipo="mantenimiento"),
    )
    monkeypatch.setattr(app, "filter_page", lambda page, **kw: page)
    monkeypatch.setattr(app, "save_review_image",
                        lambda image, ref, folder, hand_turn=0: _touch(folder, ref))
    monkeypatch.setattr(app, "already_read", lambda pages, months: [])

    scan = os.path.join(app.incoming, "2026", "SEPTIEMBRE", "SKM_MANT.pdf")
    with open(scan, "wb") as handle:
        handle.write(b"scan")
    store = EntryStore(str(tmp_path / "state" / "e.sqlite3"))
    ledger = ProcessedLedger(str(tmp_path / "state" / "p.sqlite3"))
    guard = SpendGuard(str(tmp_path / "state" / "s.sqlite3"), 5, 1.1)
    app.process_scan(scan, ledger, guard, store)
    yield app, store, ledger, guard, reading
    store.close()


def _touch(folder, ref):
    from review_marks import image_name

    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, image_name(ref)), "wb").close()


def _refs(store):
    return sorted(ref for (ref,) in store._connection.execute(
        "SELECT review_ref FROM scan_sheets WHERE source = 'SKM_MANT.pdf'"))


def _texts(store):
    return sorted(t for (t,) in store._connection.execute(
        "SELECT text FROM memoria_entries WHERE month = 'SEPTIEMBRE'"))


def test_the_new_reading_replaces_the_old_and_the_scan_comes_back(setup):
    from tools.reread_scan import reread

    app, store, ledger, guard, reading = setup
    month = os.path.join(app.incoming, "2026", "SEPTIEMBRE")
    reading["text"] = "Reparando luz planta 1"

    reread(store, ledger, guard, "2026", "SEPTIEMBRE", "SKM_MANT.pdf")

    assert not [t for t in _texts(store) if "P/C" in t]
    assert "Reparando luz planta 1 01-09-2026" in _texts(store)
    assert os.listdir(os.path.join(month, ".escaneos_originales")) == ["SKM_MANT.pdf"]


def test_drop_page_takes_out_one_sheet_and_keeps_the_numbering(setup):
    from tools.reread_scan import reread

    app, store, ledger, guard, _ = setup
    revision = os.path.join(app.incoming, "2026", "SEPTIEMBRE", ".revision")
    before = _refs(store)

    reread(store, ledger, guard, "2026", "SEPTIEMBRE", "SKM_MANT.pdf", drop_pages=(1,))

    after = _refs(store)
    assert len(after) == len(before) - 1
    assert set(after) <= set(before), "every other sheet keeps its pN"
    assert not [n for n in os.listdir(revision) if "31-08" in n]


def test_what_a_person_did_survives(setup):
    from tools.reread_scan import reread

    app, store, ledger, guard, reading = setup
    sheet = "mant 02-09-2026 p3"
    assert sheet in _refs(store)
    # A line corrected by hand, a sheet confirmed empty, a date confirmed.
    store._connection.execute(
        "UPDATE memoria_entries SET text = 'Corregido a mano', hand_edited = 1, "
        "original_text = 'Reparando luz P/C 02-09-2026' WHERE review_ref = ?", (sheet,))
    store._connection.commit()
    store.confirm_empty("2026", "SEPTIEMBRE", "mant 01-09-2026 p2")
    store.redate_sheet("2026", "SEPTIEMBRE", sheet, "02-09-2026")
    reading["text"] = "Reparando luz planta 1"

    reread(store, ledger, guard, "2026", "SEPTIEMBRE", "SKM_MANT.pdf")

    assert "Corregido a mano" in _texts(store)
    assert "mant 01-09-2026 p2" in store.confirmed_empty("2026", "SEPTIEMBRE")
    checked = store._connection.execute(
        "SELECT date_checked FROM scan_sheets WHERE review_ref = ?", (sheet,)).fetchone()
    assert checked == (1,)


def test_a_failed_reading_puts_the_scan_back(setup, monkeypatch):
    from tools.reread_scan import reread

    app, store, ledger, guard, _ = setup

    def broken(*args, **kwargs):
        raise RuntimeError("API down")

    monkeypatch.setattr(app, "process_scan", broken)
    with pytest.raises(RuntimeError):
        reread(store, ledger, guard, "2026", "SEPTIEMBRE", "SKM_MANT.pdf")
    assert os.path.isfile(os.path.join(app.incoming, "2026", "SEPTIEMBRE",
                                       ".escaneos_originales", "SKM_MANT.pdf"))


def _images(app):
    folder = os.path.join(app.incoming, "2026", "SEPTIEMBRE", ".revision")
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


def test_a_failed_reading_leaves_the_month_as_it_was(setup, monkeypatch):
    """2026-10-19: the API refused the key on the first sheet, and Agosto had
    already lost every sheet, untouched line and review image of the scan."""
    from tools.reread_scan import reread

    app, store, ledger, guard, _ = setup
    store._connection.execute(
        "UPDATE scan_sheets SET empty_checked = 1 WHERE source = 'SKM_MANT.pdf'")
    store._connection.commit()
    sheets = store._connection.execute(
        "SELECT * FROM scan_sheets ORDER BY review_ref").fetchall()
    lines, images = _texts(store), _images(app)
    real = app.process_scan

    def half_done(scan, ledger, guard, store):
        # Files some sheets of its own, then fails, as a reading can.
        real(scan, ledger, guard, store)
        raise RuntimeError("Error code: 401 - invalid_api_key")

    monkeypatch.setattr(app, "process_scan", half_done)
    with pytest.raises(RuntimeError):
        reread(store, ledger, guard, "2026", "SEPTIEMBRE", "SKM_MANT.pdf")

    assert store._connection.execute(
        "SELECT * FROM scan_sheets ORDER BY review_ref").fetchall() == sheets
    assert _texts(store) == lines
    assert _images(app) == images


def test_two_rereads_on_one_day_keep_both_backups(app, tmp_path, monkeypatch):
    """The second run's backup must not overwrite the first: on 2026-10-19 the
    second copied the month the first had already emptied, over the good one."""
    import tools.reread_scan as tool
    from config import config

    monkeypatch.setattr(tool, "processor_running", lambda: False)
    monkeypatch.setattr(config, "backup_dir", str(tmp_path / "backups"))
    monkeypatch.setattr(config, "entry_db", str(tmp_path / "e.sqlite3"))
    monkeypatch.setattr(config, "state_db", str(tmp_path / "p.sqlite3"))
    monkeypatch.setattr(config, "spend_db", str(tmp_path / "s.sqlite3"))
    stamps = iter(["2026-10-19-180500", "2026-10-19-182600"])
    monkeypatch.setattr(tool, "_stamp", lambda: next(stamps))
    monkeypatch.setattr(tool, "reread", lambda *a, **k: [])
    monkeypatch.setattr("sys.argv", ["reread_scan.py", "2026", "SEPTIEMBRE", "X.pdf"])
    import sqlite3
    sqlite3.connect(config.entry_db).close()

    assert tool.main_cli() == 0
    assert tool.main_cli() == 0
    assert sorted(os.listdir(tmp_path / "backups" / "before-reread")) == [
        "2026-10-19-180500", "2026-10-19-182600"]


def test_it_refuses_while_the_processor_runs(monkeypatch):
    import tools.reread_scan as tool

    monkeypatch.setattr(tool, "processor_running", lambda: True)
    monkeypatch.setattr("sys.argv", ["reread_scan.py", "2026", "SEPTIEMBRE", "X.pdf"])
    assert tool.main_cli() == 2


def test_a_corrected_date_is_put_back_when_misread_again(setup):
    from review_marks import image_name
    from tools.reread_scan import reread

    app, store, ledger, guard, _ = setup
    revision = os.path.join(app.incoming, "2026", "SEPTIEMBRE", ".revision")
    corrected = store.redate_sheet("2026", "SEPTIEMBRE", "mant 02-09-2026 p3", "03-09-2026")
    assert corrected == "mant 03-09-2026 p3"
    os.replace(os.path.join(revision, image_name("mant 02-09-2026 p3")),
               os.path.join(revision, image_name(corrected)))

    notes = reread(store, ledger, guard, "2026", "SEPTIEMBRE", "SKM_MANT.pdf")

    assert corrected in _refs(store) and "mant 02-09-2026 p3" not in _refs(store)
    assert os.path.isfile(os.path.join(revision, image_name(corrected)))
    assert not os.path.exists(os.path.join(revision, image_name("mant 02-09-2026 p3")))
    assert not [n for n in notes if "without its sheet" in n]


def test_drop_page_finds_the_sheet_in_another_month(setup):
    """Dated 31-08, the sheet may be filed under AGOSTO; it goes all the same."""
    from tools.reread_scan import _drop

    app, store, *_ = setup
    store._connection.execute(
        "UPDATE scan_sheets SET month = 'AGOSTO' WHERE source = 'SKM_MANT.pdf' "
        "AND scan_position = 1")
    store._connection.commit()

    assert _drop(store, "SKM_MANT.pdf", 1)
    assert not store._connection.execute(
        "SELECT 1 FROM scan_sheets WHERE source = 'SKM_MANT.pdf' AND scan_position = 1"
    ).fetchone()
