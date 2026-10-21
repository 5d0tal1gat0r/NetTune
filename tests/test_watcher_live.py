"""Live watcher tests: a real observer against a real temp directory."""

import os
import time

import pytest

from scanner_monitor import ScannerMonitor


def collect(monitor, expected, timeout=15.0):
    """Drain the queue until *expected* appears or we run out of patience."""
    deadline = time.time() + timeout
    seen = set()
    while time.time() < deadline:
        path = monitor.get_new_file(timeout=0.5)
        if path:
            seen.add(os.path.realpath(path))
            if os.path.realpath(expected) in seen:
                return seen
    return seen


@pytest.fixture(params=["inotify", "polling"])
def monitor(tmp_path, request):
    (tmp_path / "MARZO" / "archive").mkdir(parents=True)
    mon = ScannerMonitor(str(tmp_path), mode=request.param, poll_interval=0.3)
    mon.start()
    time.sleep(0.6)  # let the observer settle before we write
    yield mon
    mon.stop()


def test_detects_file_created_in_month_subfolder(monitor, tmp_path):
    """The regression: recursive=False meant month folders were never watched."""
    target = tmp_path / "MARZO" / "scan.jpg"
    target.write_bytes(b"data")
    assert os.path.realpath(str(target)) in collect(monitor, str(target))


def test_detects_file_renamed_into_place(monitor, tmp_path):
    """SMB clients and scanners often write a temp file then rename it."""
    temp = tmp_path / "MARZO" / "scan.jpg.tmp"
    temp.write_bytes(b"data")
    final = tmp_path / "MARZO" / "scan.jpg"
    temp.rename(final)
    assert os.path.realpath(str(final)) in collect(monitor, str(final))


def test_detects_file_at_watch_root(monitor, tmp_path):
    target = tmp_path / "loose.png"
    target.write_bytes(b"data")
    assert os.path.realpath(str(target)) in collect(monitor, str(target))
