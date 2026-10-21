import os

import pytest

from processed_ledger import ProcessedLedger


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "state" / "processed.sqlite3")


def make(tmp_path, name, data=b"scan-bytes"):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_creates_parent_directory(tmp_path, db):
    ProcessedLedger(db).close()
    assert os.path.exists(db)


def test_unseen_file_is_not_processed(tmp_path, db):
    ledger = ProcessedLedger(db)
    assert not ledger.already_processed(make(tmp_path, "a.jpg"))
    ledger.close()


def test_marked_file_is_reported_processed(tmp_path, db):
    f = make(tmp_path, "a.jpg")
    ledger = ProcessedLedger(db)
    ledger.mark_processed(f, "report.docx")
    assert ledger.already_processed(f)
    ledger.close()


def test_dedupe_is_by_content_not_path(tmp_path, db):
    """The archive step renames the file; identical bytes must not be re-billed."""
    a = make(tmp_path, "a.jpg", b"same")
    b = make(tmp_path, "b.jpg", b"same")
    ledger = ProcessedLedger(db)
    ledger.mark_processed(a, "r.docx")
    assert ledger.already_processed(b)
    ledger.close()


def test_different_content_is_not_deduped(tmp_path, db):
    a = make(tmp_path, "a.jpg", b"one")
    b = make(tmp_path, "b.jpg", b"two")
    ledger = ProcessedLedger(db)
    ledger.mark_processed(a, "r.docx")
    assert not ledger.already_processed(b)
    ledger.close()


def test_state_survives_restart(tmp_path, db):
    f = make(tmp_path, "a.jpg")
    first = ProcessedLedger(db)
    first.mark_processed(f, "r.docx")
    first.close()

    second = ProcessedLedger(db)
    assert second.already_processed(f)
    second.close()


def test_marking_twice_is_idempotent(tmp_path, db):
    f = make(tmp_path, "a.jpg")
    ledger = ProcessedLedger(db)
    ledger.mark_processed(f, "r.docx")
    ledger.mark_processed(f, "r2.docx")
    assert ledger.already_processed(f)
    ledger.close()


def test_missing_file_is_not_processed(tmp_path, db):
    ledger = ProcessedLedger(db)
    assert not ledger.already_processed(str(tmp_path / "ghost.jpg"))
    ledger.close()


def test_works_as_context_manager(tmp_path, db):
    f = make(tmp_path, "a.jpg")
    with ProcessedLedger(db) as ledger:
        ledger.mark_processed(f, "r.docx")
    with ProcessedLedger(db) as ledger:
        assert ledger.already_processed(f)
