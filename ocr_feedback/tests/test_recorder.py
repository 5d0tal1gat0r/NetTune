import logging

from ocr_feedback.model import Page, ReviewEvent
from ocr_feedback.recorder import NullRecorder, SafeRecorder, make_recorder
from ocr_feedback.store import FeedbackReader


class Exploding:
    enabled = True

    def record_run(self, run):
        raise RuntimeError("boom")

    record_page = record_stage = record_event = record_run


def test_safe_recorder_never_raises_and_warns(caplog):
    rec = SafeRecorder(Exploding())
    with caplog.at_level(logging.WARNING, logger="ocr_feedback"):
        assert rec.record_event(ReviewEvent("p", "1", "confirm")) is None
        assert rec.record_page(Page("p")) is None
    assert rec.enabled is True
    assert sum("boom" in r.getMessage() for r in caplog.records) == 2


def test_null_recorder_is_disabled():
    rec = NullRecorder()
    assert rec.enabled is False
    rec.record_event(ReviewEvent("p", "1", "confirm"))


def test_make_recorder_disabled_writes_nothing(tmp_path):
    path = tmp_path / "f.sqlite3"
    rec = make_recorder(str(path), "toy", enabled=False)
    rec.record_event(ReviewEvent("p", "1", "confirm"))
    assert rec.enabled is False
    assert not path.exists()


def test_make_recorder_enabled_writes(tmp_path):
    path = str(tmp_path / "f.sqlite3")
    rec = make_recorder(path, "toy")
    rec.record_event(ReviewEvent("p", "1", "confirm"))
    assert [e.action for e in FeedbackReader(path).events("p")] == ["confirm"]


def test_unwritable_path_falls_back_to_null(tmp_path, caplog):
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory")
    with caplog.at_level(logging.WARNING, logger="ocr_feedback"):
        rec = make_recorder(str(blocker / "f.sqlite3"), "toy")
    assert rec.enabled is False
    rec.record_event(ReviewEvent("p", "1", "confirm"))
    assert any("capture off" in r.getMessage() for r in caplog.records)
