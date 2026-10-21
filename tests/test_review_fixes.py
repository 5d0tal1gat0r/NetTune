"""Regression tests for the remaining code-review findings."""


import pytest

from nettune.intake.processed_ledger import ProcessedLedger
from nettune.intake.retry_scheduler import RetryScheduler
from nettune.intake.scan_filter import is_processable_scan
from nettune.report.month_folders import get_month_folder, is_in_archive

# --- #4 off-by-one on max_attempts ---------------------------------------


def test_max_attempts_is_the_total_number_of_attempts():
    clock = {"t": 0.0}
    s = RetryScheduler(base_delay=1, max_attempts=3, clock=lambda: clock["t"])
    attempts = 0
    for _ in range(10):
        attempts += 1
        s.record_failure("/x.jpg")
        clock["t"] += 100_000
        s.due()
        if s.abandoned:
            break
    assert attempts == 3


def test_forget_removes_a_parked_entry():
    s = RetryScheduler(base_delay=1, clock=lambda: 0.0)
    s.record_failure("/x.jpg")
    s.forget("/x.jpg")
    assert s.attempts_for("/x.jpg") == 0
    assert s._pending == {}


# --- #6 month/archive detection must be relative to the incoming root -----


def test_archive_above_the_incoming_root_is_ignored():
    root = "/srv/archive/incoming_scans"
    assert not is_in_archive(f"{root}/MARZO/s.jpg", root)


def test_archive_inside_the_tree_is_still_detected():
    root = "/srv/incoming_scans"
    assert is_in_archive(f"{root}/MARZO/archive/s.jpg", root)


def test_month_name_above_the_root_is_ignored():
    root = "/srv/JULIO/incoming_scans"
    assert get_month_folder(f"{root}/ABRIL/s.jpg", root) == "ABRIL"


def test_month_lookup_without_a_root_still_works():
    assert get_month_folder("incoming_scans/ABRIL/s.jpg") == "ABRIL"


def test_scan_under_an_archive_named_root_is_processable(tmp_path):
    root = tmp_path / "archive" / "incoming_scans"
    (root / "MARZO").mkdir(parents=True)
    scan = root / "MARZO" / "s.jpg"
    scan.write_bytes(b"x")
    assert is_processable_scan(str(scan), str(root))


# --- #5 formats the Vision API cannot read --------------------------------


def test_tiff_and_bmp_are_converted_to_a_supported_format(tmp_path):
    from nettune.reading.transcription_service import encode_image

    pytest.importorskip("PIL")
    from PIL import Image

    for name, expected in (("s.tiff", "image/png"), ("s.bmp", "image/png"),
                           ("s.png", "image/png"), ("s.jpg", "image/jpeg")):
        path = tmp_path / name
        Image.new("RGB", (4, 4), (255, 0, 0)).save(path)
        _, mime = encode_image(str(path))
        assert mime == expected, f"{name} -> {mime}"


def test_converted_payload_is_a_real_png(tmp_path):
    from nettune.reading.transcription_service import encode_image

    pytest.importorskip("PIL")
    import base64

    from PIL import Image

    path = tmp_path / "s.tiff"
    Image.new("RGB", (4, 4), (0, 128, 0)).save(path)
    payload, _ = encode_image(str(path))
    assert base64.b64decode(payload).startswith(b"\x89PNG\r\n\x1a\n")


# --- #7 debounce must not swallow a new scan reusing a filename -----------


def test_forget_lets_a_reused_filename_through():
    import queue

    from nettune.intake.scanner_monitor import ScanEventHandler

    class Event:
        def __init__(self, p):
            self.src_path = p
            self.is_directory = False

    clock = {"t": 0.0}
    q = queue.Queue()
    handler = ScanEventHandler(q, debounce_seconds=5.0, clock=lambda: clock["t"])
    handler.on_created(Event("/scans/MARZO/scan.jpg"))
    handler.forget("/scans/MARZO/scan.jpg")  # consumer archived it
    clock["t"] += 1
    handler.on_created(Event("/scans/MARZO/scan.jpg"))  # printer reuses the name
    assert q.qsize() == 2


# --- #8 ledger robustness -------------------------------------------------


def test_ledger_uses_wal_journal(tmp_path):
    db = str(tmp_path / "p.sqlite3")
    with ProcessedLedger(db) as ledger:
        mode = ledger._connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_digest_is_computed_once_per_scan(tmp_path, monkeypatch):
    from nettune.intake import processed_ledger as pl
    path = tmp_path / "a.jpg"
    path.write_bytes(b"bytes")
    calls = {"n": 0}
    real = pl.file_hash

    def counting(p):
        calls["n"] += 1
        return real(p)

    monkeypatch.setattr(pl, "file_hash", counting)
    with pl.ProcessedLedger(str(tmp_path / "p.sqlite3")) as ledger:
        digest = ledger.digest(str(path))
        ledger.already_processed(str(path), digest=digest)
        ledger.mark_processed(str(path), "r.docx", digest=digest)
    assert calls["n"] == 1


def test_transcript_cache_round_trips(tmp_path):
    path = tmp_path / "a.jpg"
    path.write_bytes(b"bytes")
    db = str(tmp_path / "p.sqlite3")
    with ProcessedLedger(db) as ledger:
        digest = ledger.digest(str(path))
        assert ledger.cache_get(digest, "transcript") is None
        ledger.cache_put(digest, "transcript", "texto")
    with ProcessedLedger(db) as ledger:
        assert ledger.cache_get(ledger.digest(str(path)), "transcript") == "texto"


def test_cache_kinds_do_not_collide(tmp_path):
    with ProcessedLedger(str(tmp_path / "p.sqlite3")) as ledger:
        ledger.cache_put("abc", "transcript", "uno")
        ledger.cache_put("abc", "analysis", "dos")
        assert ledger.cache_get("abc", "transcript") == "uno"
        assert ledger.cache_get("abc", "analysis") == "dos"
