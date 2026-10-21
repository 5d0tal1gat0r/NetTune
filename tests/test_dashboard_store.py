"""The columns a correction needs, and that old databases still open."""

import sqlite3

import pytest

from entry_store import EntryStore


@pytest.fixture
def store(tmp_path):
    with EntryStore(str(tmp_path / "e.sqlite3")) as s:
        yield s


def test_the_correction_columns_exist(store):
    store.add("2026", "SEPTIEMBRE", "Parking",
              [{"text": "Se abre Z6.", "confident": False}], "s.pdf", "01-09-2026 p1")
    rows = store.month_entries("2026", "SEPTIEMBRE")
    assert len(rows) == 1
    row = rows[0]
    assert row["text"] == "Se abre Z6."
    assert row["hand_edited"] == 0
    assert row["original_text"] == "Se abre Z6."
    assert row["flagged"] == 1
    assert row["review_ref"] == "01-09-2026 p1"
    assert isinstance(row["id"], int)


def test_month_entries_comes_back_in_document_order(store):
    store.add("2026", "SEPTIEMBRE", "Parking",
              [{"text": "Uno."}, {"text": "Dos."}], "s.pdf")
    assert [r["text"] for r in store.month_entries("2026", "SEPTIEMBRE")] == [
        "Uno.", "Dos."
    ]


def test_a_database_without_the_columns_still_opens(tmp_path):
    """The Pi's store predates them and holds entries already in a memoria."""
    path = str(tmp_path / "old.sqlite3")
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE memoria_entries ("
        "year TEXT NOT NULL, month TEXT NOT NULL, block TEXT NOT NULL, "
        "position INTEGER NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL, "
        "flagged INTEGER NOT NULL DEFAULT 0, review_ref TEXT NOT NULL DEFAULT '', "
        "added_at TEXT NOT NULL, dedupe_key TEXT NOT NULL DEFAULT '', "
        "PRIMARY KEY (year, month, block, text))"
    )
    old.execute(
        "INSERT INTO memoria_entries VALUES "
        "('2026','SEPTIEMBRE','Parking',0,'Se abre Z6.','s.pdf',1,'01-09 p1','t','se abre z6')"
    )
    old.commit()
    old.close()

    with EntryStore(path) as store:
        rows = store.month_entries("2026", "SEPTIEMBRE")
    assert len(rows) == 1
    assert rows[0]["original_text"] == "Se abre Z6.", "backfilled from text"
    assert rows[0]["hand_edited"] == 0


def test_editing_marks_the_entry_and_clears_its_flag(store):
    store.add("2026", "SEPTIEMBRE", "Parking",
              [{"text": "Se retiran pelonas.", "confident": False}],
              "s.pdf", "01-09-2026 p1")
    entry = store.month_entries("2026", "SEPTIEMBRE")[0]

    assert store.edit_entry(entry["id"], "Se retiran pilonas.") is True

    after = store.month_entries("2026", "SEPTIEMBRE")[0]
    assert after["text"] == "Se retiran pilonas."
    assert after["hand_edited"] == 1
    assert after["flagged"] == 0
    assert after["original_text"] == "Se retiran pelonas.", "the reader's text is kept"


def test_editing_to_the_same_text_still_counts_as_checked(store):
    store.add("2026", "SEPTIEMBRE", "Parking",
              [{"text": "Se abre Z6.", "confident": False}], "s.pdf", "01-09 p1")
    entry = store.month_entries("2026", "SEPTIEMBRE")[0]
    store.edit_entry(entry["id"], "Se abre Z6.")
    assert store.month_entries("2026", "SEPTIEMBRE")[0]["hand_edited"] == 1


def test_an_empty_edit_is_refused(store):
    store.add("2026", "SEPTIEMBRE", "Parking", [{"text": "Se abre Z6."}], "s.pdf")
    entry = store.month_entries("2026", "SEPTIEMBRE")[0]
    assert store.edit_entry(entry["id"], "   ") is False
    assert store.month_entries("2026", "SEPTIEMBRE")[0]["text"] == "Se abre Z6."


def test_confirming_clears_the_flag_without_touching_the_text(store):
    store.add("2026", "SEPTIEMBRE", "Parking",
              [{"text": "Se abre Z6.", "confident": False}], "s.pdf", "01-09 p1")
    entry = store.month_entries("2026", "SEPTIEMBRE")[0]

    assert store.confirm_entry(entry["id"]) is True

    after = store.month_entries("2026", "SEPTIEMBRE")[0]
    assert after["text"] == "Se abre Z6."
    assert after["flagged"] == 0
    assert after["hand_edited"] == 1


def test_an_added_entry_lands_after_the_one_it_follows(store):
    store.add("2026", "SEPTIEMBRE", "Parking",
              [{"text": "Uno."}, {"text": "Tres."}], "s.pdf")
    first = store.month_entries("2026", "SEPTIEMBRE")[0]

    new_id = store.add_entry("2026", "SEPTIEMBRE", "Parking", "Dos.", after_id=first["id"])

    assert isinstance(new_id, int)
    assert [r["text"] for r in store.month_entries("2026", "SEPTIEMBRE")] == [
        "Uno.", "Dos.", "Tres."
    ]
    added = next(r for r in store.month_entries("2026", "SEPTIEMBRE") if r["id"] == new_id)
    assert added["hand_edited"] == 1, "a line a person typed is theirs"
    assert added["flagged"] == 0


def test_a_removed_entry_is_gone(store):
    store.add("2026", "SEPTIEMBRE", "Parking",
              [{"text": "Uno."}, {"text": "Dos."}], "s.pdf")
    entry = store.month_entries("2026", "SEPTIEMBRE")[0]
    assert store.remove_entry(entry["id"]) is True
    assert [r["text"] for r in store.month_entries("2026", "SEPTIEMBRE")] == ["Dos."]


def test_removing_an_entry_that_is_not_there_changes_nothing(store):
    assert store.remove_entry(999) is False


def test_the_corrections_are_counted(store):
    store.add("2026", "SEPTIEMBRE", "Parking",
              [{"text": "Uno."}, {"text": "Dos."}], "s.pdf")
    rows = store.month_entries("2026", "SEPTIEMBRE")
    store.edit_entry(rows[0]["id"], "Uno corregido.")
    assert store.hand_edited_count("2026", "SEPTIEMBRE") == 1


def test_editing_into_another_entrys_text_is_refused(store):
    """The dedupe index is on (year, month, block, dedupe_key); a rewritten
    dedupe_key that collides with a sibling entry must not take the store
    down -- it must simply refuse the edit and leave both entries alone."""
    store.add("2026", "SEPTIEMBRE", "Parking",
              [{"text": "Uno."}, {"text": "Dos."}], "s.pdf")
    rows = store.month_entries("2026", "SEPTIEMBRE")
    first, second = rows[0], rows[1]

    assert store.edit_entry(first["id"], second["text"]) is False

    after = store.month_entries("2026", "SEPTIEMBRE")
    assert after[0]["text"] == "Uno."
    assert after[0]["hand_edited"] == 0
    assert after[1]["text"] == "Dos."


@pytest.mark.parametrize("method", ["edit_entry", "rewrite_entry"])
def test_a_refused_edit_leaves_no_write_lock(tmp_path, method):
    """The refused UPDATE opened a transaction; left open, it holds the
    database's write lock and every other connection's first write waits
    out its timeout with "database is locked" -- the dashboard hung like
    that on 2026-10-09 after one colliding edit."""
    path = str(tmp_path / "e.sqlite3")
    with EntryStore(path) as store:
        store.add("2026", "SEPTIEMBRE", "Parking",
                  [{"text": "Uno."}, {"text": "Dos."}], "s.pdf")
        first, second = store.month_entries("2026", "SEPTIEMBRE")[:2]

        assert getattr(store, method)(first["id"], second["text"]) is False

        other = sqlite3.connect(path, timeout=0)
        try:
            other.execute("UPDATE memoria_entries SET flagged = flagged")
            other.commit()
        finally:
            other.close()


def test_adding_a_duplicate_line_inserts_nothing(store):
    """INSERT OR IGNORE means a colliding insert leaves lastrowid pointing at
    whatever the connection last inserted, not at nothing; rowcount is the
    only reliable signal that nothing landed."""
    store.add("2026", "SEPTIEMBRE", "Parking", [{"text": "Uno."}], "s.pdf")
    entry = store.month_entries("2026", "SEPTIEMBRE")[0]

    new_id = store.add_entry("2026", "SEPTIEMBRE", "Parking", "Uno.", after_id=entry["id"])

    assert new_id == 0
    assert [r["text"] for r in store.month_entries("2026", "SEPTIEMBRE")] == ["Uno."]
