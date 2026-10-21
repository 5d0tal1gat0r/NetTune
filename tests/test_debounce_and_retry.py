import queue

import pytest

from nettune.intake.retry_scheduler import RetryScheduler
from nettune.intake.scanner_monitor import ScanEventHandler


class Event:
    def __init__(self, src_path, dest_path=None, is_directory=False):
        self.src_path = src_path
        self.dest_path = dest_path
        self.is_directory = is_directory


def drain(q):
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except queue.Empty:
            return out


# --- debounce -------------------------------------------------------------


def test_create_and_close_for_same_file_enqueue_once():
    """The smoke-test defect: both events fired, so the API was called twice."""
    clock = iter([100.0, 100.2])
    q = queue.Queue()
    handler = ScanEventHandler(q, debounce_seconds=5.0, clock=lambda: next(clock))
    handler.on_created(Event("/scans/MARZO/a.jpg"))
    handler.on_closed(Event("/scans/MARZO/a.jpg"))
    assert drain(q) == ["/scans/MARZO/a.jpg"]


def test_same_file_again_after_window_is_enqueued():
    clock = iter([100.0, 200.0])
    q = queue.Queue()
    handler = ScanEventHandler(q, debounce_seconds=5.0, clock=lambda: next(clock))
    handler.on_created(Event("/scans/MARZO/a.jpg"))
    handler.on_closed(Event("/scans/MARZO/a.jpg"))
    assert drain(q) == ["/scans/MARZO/a.jpg", "/scans/MARZO/a.jpg"]


def test_different_files_are_not_debounced():
    clock = iter([100.0, 100.1])
    q = queue.Queue()
    handler = ScanEventHandler(q, debounce_seconds=5.0, clock=lambda: next(clock))
    handler.on_created(Event("/scans/MARZO/a.jpg"))
    handler.on_created(Event("/scans/MARZO/b.jpg"))
    assert drain(q) == ["/scans/MARZO/a.jpg", "/scans/MARZO/b.jpg"]


def test_move_uses_destination_path():
    q = queue.Queue()
    handler = ScanEventHandler(q, clock=lambda: 1.0)
    handler.on_moved(Event("/scans/MARZO/a.tmp", dest_path="/scans/MARZO/a.jpg"))
    assert drain(q) == ["/scans/MARZO/a.jpg"]


def test_directory_events_are_ignored():
    q = queue.Queue()
    handler = ScanEventHandler(q, clock=lambda: 1.0)
    handler.on_created(Event("/scans/MARZO", is_directory=True))
    assert drain(q) == []


def test_bytes_paths_are_decoded():
    q = queue.Queue()
    handler = ScanEventHandler(q, clock=lambda: 1.0)
    handler.on_created(Event(b"/scans/MARZO/a.jpg"))
    assert drain(q) == ["/scans/MARZO/a.jpg"]


# --- retry scheduler ------------------------------------------------------


@pytest.fixture
def now():
    return {"t": 1000.0}


@pytest.fixture
def scheduler(now):
    return RetryScheduler(
        base_delay=60.0, max_delay=600.0, max_attempts=3, clock=lambda: now["t"]
    )


def test_nothing_due_when_empty(scheduler):
    assert scheduler.due() == []


def test_failed_path_is_not_due_immediately(scheduler):
    scheduler.record_failure("/scans/a.jpg")
    assert scheduler.due() == []


def test_failed_path_becomes_due_after_backoff(scheduler, now):
    scheduler.record_failure("/scans/a.jpg")
    now["t"] += 61
    assert scheduler.due() == ["/scans/a.jpg"]


def test_due_paths_are_returned_once(scheduler, now):
    scheduler.record_failure("/scans/a.jpg")
    now["t"] += 61
    assert scheduler.due() == ["/scans/a.jpg"]
    assert scheduler.due() == []


def test_backoff_grows_exponentially(scheduler, now):
    scheduler.record_failure("/scans/a.jpg")
    now["t"] += 61
    scheduler.due()
    scheduler.record_failure("/scans/a.jpg")
    now["t"] += 61
    assert scheduler.due() == [], "second retry must wait longer than the first"
    now["t"] += 60
    assert scheduler.due() == ["/scans/a.jpg"]


def test_gives_up_after_max_attempts(scheduler, now):
    """max_attempts is the TOTAL number of attempts, not the number of retries."""
    for _ in range(2):
        scheduler.record_failure("/scans/a.jpg")
        now["t"] += 10_000
        scheduler.due()
    scheduler.record_failure("/scans/a.jpg")  # third and final attempt
    now["t"] += 10_000
    assert scheduler.due() == []
    assert scheduler.abandoned == ["/scans/a.jpg"]


def test_delay_is_capped_at_max(now):
    patient = RetryScheduler(
        base_delay=60.0, max_delay=600.0, max_attempts=20, clock=lambda: now["t"]
    )
    for _ in range(6):
        patient.record_failure("/scans/a.jpg")
        now["t"] += 10_000
        patient.due()
    patient.record_failure("/scans/a.jpg")  # uncapped this would be 3840s
    now["t"] += 601
    assert patient.due() == ["/scans/a.jpg"]


def test_success_clears_history(scheduler, now):
    scheduler.record_failure("/scans/a.jpg")
    scheduler.record_success("/scans/a.jpg")
    now["t"] += 10_000
    assert scheduler.due() == []
    scheduler.record_failure("/scans/a.jpg")
    now["t"] += 61
    assert scheduler.due() == ["/scans/a.jpg"], "backoff restarts from base"
