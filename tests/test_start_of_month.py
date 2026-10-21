"""A new month lays out its folders and offers held-back scans again."""

import os

from nettune import main
from nettune.report.month_folders import MONTH_FOLDERS, month_dir_for


class _Monitor:
    def __init__(self):
        self.queued = []

    def enqueue(self, path):
        self.queued.append(path)


def test_waiting_scans_are_offered_again_and_folders_exist(tmp_path):
    incoming = str(tmp_path / "incoming")
    waiting = os.path.join(incoming, "2026", "SEPTIEMBRE", "SKM_1.pdf")
    os.makedirs(os.path.dirname(waiting))
    with open(waiting, "wb") as handle:
        handle.write(b"%PDF-1.4 waiting")
    # Not scans: already archived, a set-aside re-scan, a review image.
    for folder, name in ((".escaneos_originales", "SKM_0.pdf"), (".duplicados", "SKM_D.pdf"),
                         (".revision", "01-09-2026_p1.jpg")):
        path = os.path.join(incoming, "2026", "SEPTIEMBRE", folder, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"x")

    monitor = _Monitor()
    assert main.start_of_month(monitor, incoming) == 1
    assert monitor.queued == [waiting]
    from datetime import datetime
    for year in (datetime.now().year, datetime.now().year + 1):
        for month in MONTH_FOLDERS:
            assert os.path.isdir(os.path.join(month_dir_for(incoming, str(year), month),
                                              ".revision"))


def test_the_loop_watches_the_month_the_budget_counts():
    import inspect
    source = inspect.getsource(main.main)
    assert "_utc_month() != this_month" in source
    assert "start_of_month(monitor, config.incoming_dir)" in source
