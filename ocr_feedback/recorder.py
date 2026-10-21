"""Recorders a host may hold. SafeRecorder is the only one a host should.

Capture is a side channel: losing a record is acceptable, failing the host's
own work because of one is not. SafeRecorder guarantees no call raises.
"""

import logging

from .store import SqliteRecorder

log = logging.getLogger("ocr_feedback")


class NullRecorder:
    enabled = False

    def record_run(self, run) -> None:
        pass

    def record_page(self, page) -> None:
        pass

    def record_stage(self, output) -> None:
        pass

    def record_event(self, event) -> None:
        pass


class SafeRecorder:
    def __init__(self, inner):
        self._inner = inner
        self.enabled = bool(getattr(inner, "enabled", False))

    def _call(self, name: str, record) -> None:
        try:
            getattr(self._inner, name)(record)
        except Exception as exc:
            log.warning(f"ocr_feedback: {name} dropped: {exc}")

    def record_run(self, run) -> None:
        self._call("record_run", run)

    def record_page(self, page) -> None:
        self._call("record_page", page)

    def record_stage(self, output) -> None:
        self._call("record_stage", output)

    def record_event(self, event) -> None:
        self._call("record_event", event)


def make_recorder(db_path: str | None, system: str, enabled: bool = True) -> SafeRecorder:
    """A recorder that never raises. Disabled, or unable to open its
    database, it records nothing."""
    if not enabled or not db_path:
        return SafeRecorder(NullRecorder())
    try:
        return SafeRecorder(SqliteRecorder(db_path, system))
    except Exception as exc:
        log.warning(f"ocr_feedback: cannot open {db_path} ({exc}); capture off")
        return SafeRecorder(NullRecorder())
