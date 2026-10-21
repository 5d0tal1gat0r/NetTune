"""A reprocess says how many corrections it kept."""

from entry_store import EntryStore
from main import kept_corrections_report


def test_it_says_nothing_when_there_are_none():
    assert kept_corrections_report(0, "2026", "SEPTIEMBRE") is None


def test_it_names_the_month_and_the_count():
    line = kept_corrections_report(12, "2026", "SEPTIEMBRE")
    assert "12" in line and "SEPTIEMBRE" in line


def test_one_correction_reads_in_the_singular():
    assert "1 corrección" in kept_corrections_report(1, "2026", "SEPTIEMBRE")


def test_the_store_reports_what_it_kept(tmp_path):
    with EntryStore(str(tmp_path / "e.sqlite3")) as store:
        store.add("2026", "SEPTIEMBRE", "Parking",
                  [{"text": "Uno."}, {"text": "Dos."}], "s.pdf")
        rows = store.month_entries("2026", "SEPTIEMBRE")
        store.edit_entry(rows[0]["id"], "Uno corregido.")
        assert store.clear_month("2026", "SEPTIEMBRE") == (1, 1)
