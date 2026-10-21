"""Watches the incoming scan tree and hands new files to the pipeline.

Two facts drive the design:

* Scans arrive in month subfolders, so the observer must be recursive.
* inotify never fires for writes made on the far side of an SMB/NFS mount.
  When the watched directory is a network mount we fall back to polling.
"""

import logging
import os
import queue
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

NETWORK_FILESYSTEMS = frozenset(
    {
        "cifs",
        "smbfs",
        "smb2",
        "smb3",
        "nfs",
        "nfs3",
        "nfs4",
        "fuse.sshfs",
        "fuse.rclone",
        "fuseblk",
        "9p",
        "afs",
        "ncpfs",
    }
)


def filesystem_type(path: str, mounts_file: str = "/proc/mounts") -> str:
    """Filesystem type backing *path*, chosen by longest matching mount point."""
    try:
        with open(mounts_file, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return ""

    target = os.path.abspath(path)
    best_point = ""
    best_type = ""
    for line in lines:
        fields = line.split()
        if len(fields) < 3:
            continue
        point, fs_type = fields[1], fields[2]
        # Match whole path components only: /srv/reports must not claim
        # /srv/reports-backup.
        matches = target == point or target.startswith(point.rstrip("/") + "/")
        if matches and len(point) >= len(best_point):
            best_point, best_type = point, fs_type
    return best_type


def choose_observer_kind(
    mode: str, path: str, mounts_file: str = "/proc/mounts"
) -> str:
    """Return "inotify" or "polling" for the configured *mode*.

    Anything other than an explicit "inotify"/"polling" is treated as "auto",
    which polls only when the path lives on a network filesystem.
    """
    normalised = (mode or "auto").strip().lower()
    if normalised == "polling":
        return "polling"
    if normalised == "inotify":
        return "inotify"
    return "polling" if filesystem_type(path, mounts_file) in NETWORK_FILESYSTEMS else "inotify"


def wait_for_file_stable(filepath: str, timeout: int = 30) -> bool:
    """Wait until a file's size stops changing over 3 consecutive readings.

    Guards against transcribing a scan that is still being copied over SMB.
    """
    start_time = time.time()
    last_size = -1
    stable_count = 0

    while stable_count < 3:
        if time.time() - start_time > timeout:
            return False
        if not os.path.exists(filepath):
            return False
        try:
            current_size = os.path.getsize(filepath)
        except OSError:
            return False

        if current_size == last_size and current_size > 0:
            stable_count += 1
        else:
            stable_count = 0
        last_size = current_size
        time.sleep(1)

    return True


class ScanEventHandler(FileSystemEventHandler):
    """Queues candidate paths; filtering happens in the consumer.

    A single copied file typically raises both a created and a closed event.
    Debouncing collapses them so the scan is not transcribed (and billed) twice.
    """

    def __init__(
        self,
        file_queue: queue.Queue,
        debounce_seconds: float = 5.0,
        clock=time.monotonic,
    ):
        self.file_queue = file_queue
        self.debounce_seconds = debounce_seconds
        self._clock = clock
        self._last_seen: dict[str, float] = {}
        super().__init__()

    def _enqueue(self, path) -> None:
        if isinstance(path, bytes):
            path = path.decode("utf-8", "replace")
        now = self._clock()
        previous = self._last_seen.get(path)
        if previous is not None and now - previous < self.debounce_seconds:
            return
        self._last_seen[path] = now
        if len(self._last_seen) > 4096:  # bound memory on a long-lived service
            cutoff = now - self.debounce_seconds
            self._last_seen = {
                p: t for p, t in self._last_seen.items() if t >= cutoff
            }
        self.file_queue.put(path)

    def forget(self, path: str) -> None:
        """Drop a path's debounce memory once the consumer is done with it.

        Printers reuse filenames constantly; without this, a second scan named
        scan.jpg arriving inside the debounce window would be silently lost.
        """
        self._last_seen.pop(path, None)

    def on_created(self, event):
        if not event.is_directory:
            self._enqueue(event.src_path)

    def on_moved(self, event):
        # Scanners and SMB clients often write a temp file then rename it.
        if not event.is_directory:
            self._enqueue(event.dest_path)

    def on_closed(self, event):
        # inotify IN_CLOSE_WRITE: the most reliable "finished writing" signal.
        if not event.is_directory:
            self._enqueue(event.src_path)


class ScannerMonitor:
    """Recursive directory watcher with an inotify/polling strategy switch."""

    def __init__(
        self,
        directory: str,
        mode: str = "auto",
        poll_interval: float = 5.0,
        debounce_seconds: float = 5.0,
    ):
        self.directory = directory
        self.file_queue: queue.Queue = queue.Queue()
        self.handler = ScanEventHandler(self.file_queue, debounce_seconds=debounce_seconds)
        self.kind = choose_observer_kind(mode, directory)
        self.poll_interval = poll_interval
        if self.kind == "polling":
            self.observer = PollingObserver(timeout=poll_interval)
        else:
            self.observer = Observer()

    def describe(self) -> str:
        detected = filesystem_type(self.directory) or "unknown"
        if self.kind == "polling":
            return (
                f"polling every {self.poll_interval:g}s "
                f"(filesystem: {detected})"
            )
        return f"inotify (filesystem: {detected})"

    def start(self) -> None:
        logging.warning(f"Watching {self.directory} recursively via {self.describe()}")
        self.observer.schedule(self.handler, self.directory, recursive=True)
        self.observer.start()

    def stop(self) -> None:
        self.observer.stop()
        self.observer.join()

    def enqueue(self, path: str) -> None:
        """Inject a path directly, used by the startup backfill and retries.

        Routed through the same debounce as real events so a file that the
        observer already reported between start() and the backfill walk is not
        queued twice.
        """
        self.handler._enqueue(path)

    def forget(self, path: str) -> None:
        """Release a path so a later file of the same name is seen again."""
        self.handler.forget(path)

    def get_new_file(self, timeout=1):
        try:
            return self.file_queue.get(timeout=timeout)
        except queue.Empty:
            return None
