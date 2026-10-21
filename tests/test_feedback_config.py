"""Capture is on by default, off by one line in .env, and never in the way."""

import importlib
import sys

import pytest


def _fresh_config(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("DATASET_CAPTURE", raising=False)
    else:
        monkeypatch.setenv("DATASET_CAPTURE", value)
    monkeypatch.delitem(sys.modules, "nettune.config", raising=False)
    return importlib.import_module("nettune.config").config


@pytest.mark.parametrize("value,expected", [
    (None, True), ("on", True), ("ON", True), ("1", True), ("true", True),
    ("off", False), ("OFF", False), ("Off ", False), ("0", False),
    ("false", False), ("no", False),
])
def test_capture_switch_values(monkeypatch, value, expected):
    assert _fresh_config(monkeypatch, value).dataset_capture is expected


def test_feedback_db_default(monkeypatch):
    monkeypatch.delenv("FEEDBACK_DB", raising=False)
    monkeypatch.delitem(sys.modules, "nettune.config", raising=False)
    assert importlib.import_module("nettune.config").config.feedback_db == "state/feedback.sqlite3"


def test_recorder_follows_config(app, tmp_path):
    from nettune.ops import nettune_feedback
    app.config.dataset_capture = False
    assert nettune_feedback.recorder().enabled is False
    app.config.dataset_capture = True
    app.config.feedback_db = str(tmp_path / "fb" / "f.sqlite3")
    rec = nettune_feedback.recorder()
    assert rec.enabled is True
    assert nettune_feedback.recorder() is rec


def test_ids():
    from nettune.ops import nettune_feedback
    assert nettune_feedback.page_id("SKM_1.pdf", 3) == "SKM_1.pdf#3"
    assert nettune_feedback.ref_page_id("2026", "SEPTIEMBRE", "16-09-2026 p1") == \
        "ref:2026/SEPTIEMBRE/16-09-2026 p1"


def test_failed_open_is_retried_after_the_backoff(app, tmp_path, monkeypatch):
    from nettune.ops import nettune_feedback
    from ocr_feedback.recorder import make_recorder as real_make

    app.config.dataset_capture = True
    app.config.feedback_db = str(tmp_path / "fb" / "retry.sqlite3")
    now = [1000.0]
    monkeypatch.setattr(nettune_feedback, "_clock", lambda: now[0])
    calls = []

    def flaky(db, system, enabled=True):
        calls.append(1)
        if len(calls) == 1:
            return real_make(None, system, enabled=True)  # disabled fallback
        return real_make(db, system, enabled=enabled)

    monkeypatch.setattr(nettune_feedback, "make_recorder", flaky)
    nettune_feedback._cache.clear()
    assert nettune_feedback.recorder().enabled is False
    now[0] += nettune_feedback.RETRY_BACKOFF - 1
    assert nettune_feedback.recorder().enabled is False
    assert len(calls) == 1
    now[0] += 2
    assert nettune_feedback.recorder().enabled is True
    assert len(calls) == 2
    now[0] += 1000
    nettune_feedback.recorder()
    assert len(calls) == 2


def test_kill_switch_off_is_never_retried(app, monkeypatch):
    from nettune.ops import nettune_feedback
    app.config.dataset_capture = False
    now = [0.0]
    monkeypatch.setattr(nettune_feedback, "_clock", lambda: now[0])
    calls = []
    real = nettune_feedback.make_recorder
    monkeypatch.setattr(nettune_feedback, "make_recorder",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    nettune_feedback._cache.clear()
    nettune_feedback.recorder()
    now[0] += 10_000
    nettune_feedback.recorder()
    assert len(calls) == 1


def test_concurrent_callers_share_one_rebuild(app, tmp_path, monkeypatch):
    import threading
    import time

    from nettune.ops import nettune_feedback
    from ocr_feedback.recorder import make_recorder as real_make

    app.config.dataset_capture = True
    app.config.feedback_db = str(tmp_path / "fb" / "race.sqlite3")
    now = [1000.0]
    monkeypatch.setattr(nettune_feedback, "_clock", lambda: now[0])
    calls = []

    def slow(db, system, enabled=True):
        calls.append(1)
        time.sleep(0.05)
        if len(calls) == 1:
            return real_make(None, system, enabled=True)  # disabled fallback
        return real_make(db, system, enabled=enabled)

    monkeypatch.setattr(nettune_feedback, "make_recorder", slow)
    nettune_feedback._cache.clear()
    assert nettune_feedback.recorder().enabled is False
    now[0] += nettune_feedback.RETRY_BACKOFF + 1

    threads_n = 16
    barrier = threading.Barrier(threads_n)
    got, errors = [], []

    def worker():
        barrier.wait()
        try:
            got.append(nettune_feedback.recorder())
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(got) == threads_n and all(r is not None for r in got)
    assert len(calls) == 2  # the first build plus exactly one rebuild
    assert len({id(r) for r in got}) == 1
