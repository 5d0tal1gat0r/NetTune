"""Retries scans whose processing failed, with exponential backoff.

Without this a transient OpenAI outage strands a scan in the incoming tree
until somebody restarts the service, which on an unattended Raspberry Pi means
"until somebody notices". Failures are retried a few times, with a widening
gap, then reported as abandoned so they show up in the journal.
"""

import time


class RetryScheduler:
    def __init__(
        self,
        base_delay: float = 60.0,
        max_delay: float = 900.0,
        max_attempts: int = 4,
        clock=time.monotonic,
    ):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.max_attempts = max_attempts
        self._clock = clock
        self._pending: dict[str, tuple[float, int]] = {}
        self.abandoned: list[str] = []

    def record_failure(self, path: str) -> None:
        """Schedule *path* for another attempt, or abandon it."""
        _, attempts = self._pending.get(path, (0.0, 0))
        attempts += 1
        if attempts >= self.max_attempts:
            self._pending.pop(path, None)
            if path not in self.abandoned:
                self.abandoned.append(path)
            return
        delay = min(self.base_delay * (2 ** (attempts - 1)), self.max_delay)
        self._pending[path] = (self._clock() + delay, attempts)

    def forget(self, path: str) -> None:
        """Drop a path entirely: it is no longer this scheduler's problem.

        Every branch of the main loop that stops handling a path must call
        this (or record_failure), or the entry parked by due() leaks forever.
        """
        self._pending.pop(path, None)
        if path in self.abandoned:
            self.abandoned.remove(path)

    def record_success(self, path: str) -> None:
        """Forget a path's failure history."""
        self.forget(path)

    def attempts_for(self, path: str) -> int:
        return self._pending.get(path, (0.0, 0))[1]

    def due(self) -> list[str]:
        """Paths whose retry time has arrived; each is returned only once."""
        now = self._clock()
        ready = [p for p, (when, _) in self._pending.items() if when <= now]
        for path in ready:
            attempts = self._pending[path][1]
            # Park it far out; record_failure reschedules if it fails again.
            self._pending[path] = (float("inf"), attempts)
        return ready
