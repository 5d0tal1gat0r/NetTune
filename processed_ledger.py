"""Content-addressed record of scans already transcribed, plus a result cache.

Every OpenAI call costs money, so a scan must be processed exactly once even if
the watcher reports it twice, or the service restarts and the startup backfill
sees it again. Keyed by SHA-256 of the file contents rather than by path,
because the archive step renames it.

The same store caches the *intermediate* results (transcript, analysis). A
purely local failure downstream -- a full disk, a corrupt template -- then
resumes from the cache instead of paying for the Vision call a second time.
"""

import hashlib
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Self

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS processed_scans (
        content_hash TEXT PRIMARY KEY,
        source_name  TEXT NOT NULL,
        report_name  TEXT NOT NULL,
        processed_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stage_cache (
        content_hash TEXT NOT NULL,
        kind         TEXT NOT NULL,
        value        TEXT NOT NULL,
        cached_at    TEXT NOT NULL,
        PRIMARY KEY (content_hash, kind)
    )
    """,
)

_CHUNK = 1024 * 1024


def file_hash(path: str) -> str:
    """SHA-256 of a file's contents, or "" if it cannot be read."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while chunk := handle.read(_CHUNK):
                digest.update(chunk)
    except OSError as exc:
        logging.error(f"Could not hash {path}: {exc}")
        return ""
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ProcessedLedger:
    """Small SQLite-backed set of processed scan hashes and cached stages."""

    def __init__(self, db_path: str):
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._connection = sqlite3.connect(db_path, timeout=30)
        # WAL keeps a stray second instance (a manual run alongside the systemd
        # unit) from hard-failing on "database is locked".
        self._connection.execute("PRAGMA journal_mode=WAL")
        for statement in _SCHEMA:
            self._connection.execute(statement)
        self._connection.commit()

    def digest(self, path: str) -> str:
        """Hash a scan once; pass the result to the other methods."""
        return file_hash(path)

    def already_processed(self, path: str, digest: str | None = None) -> bool:
        """True when a file with identical contents has been processed before."""
        digest = digest if digest is not None else file_hash(path)
        if not digest:
            return False
        row = self._connection.execute(
            "SELECT 1 FROM processed_scans WHERE content_hash = ?", (digest,)
        ).fetchone()
        return row is not None

    def filed_as(self, digest: str) -> str:
        """What mark_processed recorded for this content: "2026/SEPTIEMBRE"
        for a scan filed by the current pipeline, a report path for an older
        one, "" if unknown."""
        row = self._connection.execute(
            "SELECT report_name FROM processed_scans WHERE content_hash = ?", (digest,)
        ).fetchone()
        return row[0] if row else ""

    def mark_processed(
        self, path: str, report_name: str, digest: str | None = None
    ) -> None:
        """Record that *path* produced *report_name*."""
        digest = digest if digest is not None else file_hash(path)
        if not digest:
            return
        self._connection.execute(
            "INSERT OR REPLACE INTO processed_scans "
            "(content_hash, source_name, report_name, processed_at) "
            "VALUES (?, ?, ?, ?)",
            (digest, os.path.basename(path), report_name, _now()),
        )
        self._connection.commit()

    # --- intermediate result cache ---------------------------------------

    def cache_get(self, digest: str, kind: str) -> str | None:
        """Cached value for a stage, or None."""
        if not digest:
            return None
        row = self._connection.execute(
            "SELECT value FROM stage_cache WHERE content_hash = ? AND kind = ?",
            (digest, kind),
        ).fetchone()
        return row[0] if row else None

    def cache_put(self, digest: str, kind: str, value: str) -> None:
        if not digest:
            return
        self._connection.execute(
            "INSERT OR REPLACE INTO stage_cache "
            "(content_hash, kind, value, cached_at) VALUES (?, ?, ?, ?)",
            (digest, kind, value, _now()),
        )
        self._connection.commit()

    def clear_cache(self, digest: str) -> None:
        """Drop cached stages once the scan is fully processed."""
        if not digest:
            return
        self._connection.execute(
            "DELETE FROM stage_cache WHERE content_hash = ?", (digest,)
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc_info) -> None:
        self.close()
