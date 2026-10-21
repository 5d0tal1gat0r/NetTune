"""Where a doubtful entry is recorded, and that old databases still open.

The locator used to be appended to the entry itself. On a real batch four
entries in five came back doubtful, so the pages are now listed once each
instead and the entries are left as read.
"""

import sqlite3

import pytest

from entry_store import EntryStore


@pytest.fixture
def store(tmp_path):
    return EntryStore(str(tmp_path / "entries.sqlite3"))


def test_a_doubtful_entry_is_left_as_read_and_its_page_recorded(store):
    store.add("2026", "JUNIO", "Parking",
              [{"text": "Se abre Z6.", "confident": False}],
              "scan.pdf", review_ref="22-06-2026 p2")
    assert store.entries("2026", "JUNIO", "Parking") == ["Se abre Z6."]
    assert store.review_pages("2026", "JUNIO") == {"22-06-2026 p2": 1}


def test_an_agreed_entry_is_left_exactly_as_written(store):
    store.add("2026", "JUNIO", "Parking",
              [{"text": "Se abre Z6.", "confident": True}],
              "scan.pdf", review_ref="22-06-2026 p2")
    assert store.entries("2026", "JUNIO", "Parking") == ["Se abre Z6."]


def test_the_page_is_still_listed_when_the_memoria_is_rebuilt(store):
    store.add("2026", "JUNIO", "Parking",
              [{"text": "Se abre Z6.", "confident": False}],
              "scan.pdf", review_ref="22-06-2026 p2")
    store.add("2026", "JUNIO", "Parking",
              [{"text": "Otra cosa.", "confident": True}], "later.pdf")
    assert store.review_pages("2026", "JUNIO") == {"22-06-2026 p2": 1}


def test_redropping_the_same_scan_does_not_count_the_page_twice(store):
    for _ in range(2):
        store.add("2026", "JUNIO", "Parking",
                  [{"text": "Se abre Z6.", "confident": False}],
                  "scan.pdf", review_ref="22-06-2026 p2")
    assert store.entries("2026", "JUNIO", "Parking") == ["Se abre Z6."]
    assert store.review_pages("2026", "JUNIO") == {"22-06-2026 p2": 1}


def test_calling_add_without_a_locator_still_works(store):
    store.add("2026", "JUNIO", "Parking",
              [{"text": "Se abre Z6.", "confident": False}], "scan.pdf")
    assert store.entries("2026", "JUNIO", "Parking") == ["Se abre Z6."]


def test_a_database_written_before_this_column_existed_still_opens(tmp_path):
    """The Pi's database has 12 rows and no review_ref; it must not be lost."""
    path = str(tmp_path / "old.sqlite3")
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE memoria_entries ("
        "year TEXT NOT NULL, month TEXT NOT NULL, block TEXT NOT NULL, "
        "position INTEGER NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL, "
        "flagged INTEGER NOT NULL DEFAULT 0, added_at TEXT NOT NULL, "
        "PRIMARY KEY (year, month, block, text))"
    )
    old.execute(
        "INSERT INTO memoria_entries VALUES "
        "('2026','SEPTIEMBRE','Intervenciones Seguridad:',0,'Se produce un seísmo.',"
        "'scan.pdf',1,'2026-09-17T00:00:00+00:00')"
    )
    old.commit()
    old.close()

    store = EntryStore(path)
    assert store.entries("2026", "SEPTIEMBRE", "Intervenciones Seguridad:") == [
        "Se produce un seísmo."
    ]
    store.add("2026", "SEPTIEMBRE", "Intervenciones Seguridad:",
              [{"text": "Nueva.", "confident": False}], "x.pdf",
              review_ref="18-09-2026 p1")
    assert "Nueva." in store.entries(
        "2026", "SEPTIEMBRE", "Intervenciones Seguridad:"
    )
    assert store.review_pages("2026", "SEPTIEMBRE") == {"18-09-2026 p1": 1}
