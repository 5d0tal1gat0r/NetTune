"""The capture database: one file, the same tables for every system.

Writes open a short connection per call, so one recorder can be shared by
every thread of a host (the NetTune dashboard serves each request on its own
thread). WAL lets the pipeline and the dashboard write side by side; a write
still locked after *timeout* raises, and SafeRecorder turns that into a
warning, so the host never waits longer than that.
"""

import json
import os
import shutil
import sqlite3
import tempfile
import weakref
from contextlib import closing
from datetime import datetime, timezone

from .model import Line, Page, ReviewEvent, StageOutput

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    system      TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    meta_json   TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pages (
    page_id     TEXT PRIMARY KEY,
    system      TEXT NOT NULL,
    image_ref   TEXT NOT NULL,
    meta_json   TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stage_outputs (
    page_id     TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    stage       TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    lines_json  TEXT NOT NULL,
    raw_json    TEXT,
    cached      INTEGER NOT NULL,
    at          TEXT NOT NULL,
    PRIMARY KEY (page_id, run_id, stage, seq)
);
CREATE TABLE IF NOT EXISTS events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id     TEXT NOT NULL,
    line_ref    TEXT NOT NULL,
    action      TEXT NOT NULL,
    before_text TEXT,
    after_text  TEXT,
    before_tag  TEXT,
    after_tag   TEXT,
    meta_json   TEXT NOT NULL,
    at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_page ON events (page_id);
CREATE INDEX IF NOT EXISTS stage_outputs_page ON stage_outputs (page_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _lines_json(lines) -> str:
    return _dump([{"text": line.text, "meta": line.meta} for line in lines])


def _lines(raw: str) -> list:
    return [Line(item["text"], item.get("meta") or {}) for item in json.loads(raw)]


class SqliteRecorder:
    enabled = True

    def __init__(self, path: str, system: str, timeout: float = 0.5):
        self._path = path
        self._system = system
        self._timeout = timeout
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with closing(self._connect()) as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(_SCHEMA)
            with c:
                # One atomic statement: two processes starting together must
                # not both insert a version row.
                c.execute("INSERT INTO schema_version (version) SELECT ? "
                          "WHERE NOT EXISTS (SELECT 1 FROM schema_version)",
                          (SCHEMA_VERSION,))

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._path, timeout=self._timeout)
        c.execute(f"PRAGMA busy_timeout = {int(self._timeout * 1000)}")
        return c

    def _write(self, sql: str, params: tuple) -> None:
        with closing(self._connect()) as c:
            with c:
                c.execute(sql, params)

    def record_run(self, run) -> None:
        self._write(
            "INSERT OR REPLACE INTO runs (run_id, system, config_hash, meta_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (run.run_id, self._system, run.config_hash, _dump(run.meta),
             run.created_at or _now()),
        )

    def record_page(self, page) -> None:
        now = _now()
        self._write(
            "INSERT INTO pages (page_id, system, image_ref, meta_json, first_seen, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(page_id) DO UPDATE SET "
            "image_ref = excluded.image_ref, meta_json = excluded.meta_json, "
            "updated_at = excluded.updated_at",
            (page.page_id, self._system, page.image_ref, _dump(page.meta), now, now),
        )

    def record_stage(self, output) -> None:
        self._write(
            "INSERT OR REPLACE INTO stage_outputs "
            "(page_id, run_id, stage, seq, lines_json, raw_json, cached, at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (output.page_id, output.run_id, output.stage, output.seq,
             _lines_json(output.lines),
             None if output.raw is None else _dump(output.raw),
             int(bool(output.cached)), _now()),
        )

    def record_event(self, event) -> None:
        self._write(
            "INSERT INTO events (page_id, line_ref, action, before_text, after_text, "
            "before_tag, after_tag, meta_json, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event.page_id, event.line_ref, event.action, event.before_text,
             event.after_text, event.before_tag, event.after_tag, _dump(event.meta),
             event.at or _now()),
        )


def private_copy(path: str) -> tuple[str, str]:
    """Snapshot a SQLite database into a fresh temp folder, via the backup API.

    The backup API takes a consistent snapshot even while a writer is active
    (copying the main file and its -wal separately can tear if a checkpoint
    lands between the two copies). The original's main file and -wal are never
    modified; SQLite may create a -shm beside it, which is harmless.
    Returns (folder, copied database path).
    """
    folder = tempfile.mkdtemp(prefix="ocr_feedback_")
    try:
        target = os.path.join(folder, os.path.basename(path))
        try:
            source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        except sqlite3.Error:
            source = None
        try:
            if source is None:
                source = sqlite3.connect(path)
            dest = sqlite3.connect(target)
        except BaseException:
            if source is not None:
                source.close()
            raise
        try:
            try:
                source.backup(dest)
            except sqlite3.OperationalError:
                # A read-only open of a WAL database with no -shm can fail on
                # first read; retry with a plain connection used only for the
                # backup (reads only, so the original's bytes stay as they are
                # unless this is the last connection and SQLite checkpoints).
                source.close()
                source = sqlite3.connect(path)
                source.backup(dest)
        finally:
            dest.close()
            source.close()
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return folder, target


def _discard(connection, folder: str) -> None:
    connection.close()
    shutil.rmtree(folder, ignore_errors=True)


class FeedbackReader:
    """Read view of a capture database, through a private copy of it.

    The copy holds real data, so it goes as soon as the reader does: on
    close(), at the end of a with block, when the reader is dropped, or at
    interpreter exit, whichever comes first.
    """

    def __init__(self, path: str | None):
        self._c = None
        self._finalizer = None
        if path and os.path.isfile(path):
            folder, copy = private_copy(path)
            try:
                self._c = sqlite3.connect(copy)
            except BaseException:
                shutil.rmtree(folder, ignore_errors=True)
                raise
            self._finalizer = weakref.finalize(self, _discard, self._c, folder)

    def close(self) -> None:
        if self._finalizer is not None:
            self._finalizer()
        self._c = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _rows(self, sql: str, params: tuple = ()) -> list:
        if self._c is None:
            return []
        return self._c.execute(sql, params).fetchall()

    def page_ids(self) -> list:
        return [r[0] for r in self._rows("SELECT page_id FROM pages ORDER BY page_id")]

    def page(self, page_id: str):
        rows = self._rows("SELECT image_ref, meta_json FROM pages WHERE page_id = ?",
                          (page_id,))
        if not rows:
            return None
        return Page(page_id, rows[0][0], json.loads(rows[0][1]))

    def latest_stages(self, page_id: str) -> dict:
        rows = self._rows(
            "SELECT s.stage, s.run_id, s.seq, s.lines_json, s.raw_json, s.cached "
            "FROM stage_outputs s LEFT JOIN runs r ON r.run_id = s.run_id "
            "WHERE s.page_id = ? ORDER BY COALESCE(r.created_at, s.at) DESC, s.seq",
            (page_id,),
        )
        chosen: dict = {}
        result: dict = {}
        for stage, run_id, seq, lines_json, raw_json, cached in rows:
            if chosen.setdefault(stage, run_id) != run_id:
                continue
            result.setdefault(stage, []).append(StageOutput(
                page_id, run_id, stage, _lines(lines_json), seq=seq,
                raw=None if raw_json is None else json.loads(raw_json),
                cached=bool(cached)))
        for outputs in result.values():
            outputs.sort(key=lambda o: o.seq)
        return result

    def events(self, page_id: str) -> list:
        return [
            ReviewEvent(page_id, line_ref, action, before_text, after_text, before_tag,
                        after_tag, json.loads(meta_json), at)
            for (line_ref, action, before_text, after_text, before_tag, after_tag,
                 meta_json, at) in self._rows(
                "SELECT line_ref, action, before_text, after_text, before_tag, after_tag, "
                "meta_json, at FROM events WHERE page_id = ? ORDER BY event_id",
                (page_id,))
        ]
