"""NetTune's adapter for ocr_feedback.

The package knows nothing about NetTune; this module is the only place the
two meet. Every function a pipeline or a review path calls is safe: it never
raises, so capture cannot fail a scan or a correction.
"""

import hashlib
import json
import logging
import os
import shutil
import threading
import time
import uuid
import weakref
from datetime import datetime, timezone

from nettune import ROOT
from ocr_feedback.model import FinalLine, Line, Page, Run, StageOutput
from ocr_feedback.recorder import make_recorder
from ocr_feedback.store import private_copy

SYSTEM = "nettune"

_cache: dict = {}
_built_at: dict = {}

# A recorder that failed to open (database locked while its schema was created)
# is tried again after this many seconds, never sooner.
RETRY_BACKOFF = 60.0
_clock = time.monotonic
# recorder() runs on every dashboard request thread; the check and the build
# are one step, so a rebuild is never seen half-done or run twice.
_lock = threading.Lock()


def recorder():
    """The process's recorder, rebuilt if the configured path or switch changes.
    With capture on, a recorder that failed to open is retried after
    RETRY_BACKOFF seconds."""
    from nettune.config import config

    key = (config.feedback_db, config.dataset_capture)
    with _lock:
        cached = _cache.get(key)
        stale = (cached is not None and config.dataset_capture and not cached.enabled
                 and _clock() - _built_at.get(key, 0.0) >= RETRY_BACKOFF)
        if cached is not None and not stale:
            return cached
        rec = make_recorder(config.feedback_db, SYSTEM, enabled=config.dataset_capture)
        _cache.clear()
        _built_at.clear()
        _cache[key] = rec
        _built_at[key] = _clock()
        if not config.dataset_capture:
            logging.info("ocr_feedback: DATASET_CAPTURE is off")
        return rec


def page_id(source: str, scan_position: int) -> str:
    """Stable across a redate: the scan and its position do not change."""
    return f"{source}#{scan_position}"


def ref_page_id(year: str, month: str, review_ref: str) -> str:
    """For a sheet scan_sheets does not know (rows from before it existed)."""
    return f"ref:{year}/{month}/{review_ref}"


_PROMPTS = os.path.join(ROOT, "prompts")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def lines_of(page) -> list:
    """A reading's lines. Passes carry plain strings; consensus and filter
    carry dicts whose confident/routine flags become line meta."""
    lines = []
    for item in (page or {}).get("trabajos") or []:
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            meta = {"disagreement": not item.get("confident", True)}
            if item.get("routine"):
                meta["routine"] = True
        else:
            text, meta = str(item).strip(), {}
        if text:
            lines.append(Line(text, meta))
    return lines


def snapshot(page):
    """A deep copy taken before the filter runs, or None if it cannot be."""
    try:
        return json.loads(json.dumps(page, ensure_ascii=False, default=str))
    except Exception:
        return None


def config_hash() -> str:
    from nettune.config import config

    digest = hashlib.sha256(config.model_name.encode())
    for name in sorted(os.listdir(_PROMPTS)):
        path = os.path.join(_PROMPTS, name)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as handle:
            digest.update(name.encode() + b"\0" + handle.read())
    return digest.hexdigest()


def start_run(source_name: str) -> str:
    """A run id for one process_scan call, recorded when capture is on."""
    run_id = uuid.uuid4().hex
    try:
        rec = recorder()
        if rec.enabled:
            from nettune.config import config

            rec.record_run(Run(run_id, config_hash(), _now(),
                               {"source": source_name, "model": config.model_name}))
    except Exception as exc:
        logging.warning(f"ocr_feedback: run for {source_name} not recorded: {exc}")
    return run_id


def record_passes(run_id, source_name, scan_position, passes) -> None:
    """Keep the raw reading passes of one page the moment they are read, so a
    retry that finds the page cached does not lose them. Never raises."""
    try:
        if not passes:
            return
        rec = recorder()
        if not rec.enabled:
            return
        pid = page_id(source_name, scan_position)
        for seq, reading in enumerate(passes, start=1):
            rec.record_stage(StageOutput(pid, run_id, "passes", lines_of(reading),
                                         seq=seq, raw=reading))
    except Exception as exc:
        logging.warning(f"ocr_feedback: passes {source_name}#{scan_position} "
                        f"not recorded: {exc}")


def record_sheet(run_id, source_name, scan_position, review_ref, image, section,
                 consensus, filtered, omit_routine, cached) -> None:
    """Keep the stages of one sheet after consensus (passes are kept by
    record_passes as soon as they are read). Never raises."""
    try:
        rec = recorder()
        if not rec.enabled:
            return
        pid = page_id(source_name, scan_position)
        rec.record_page(Page(pid, image, {"review_ref": review_ref, "section": section}))
        if consensus is not None:
            rec.record_stage(StageOutput(pid, run_id, "consensus", lines_of(consensus),
                                         cached=cached))
        rec.record_stage(StageOutput(pid, run_id, "filtered", lines_of(filtered),
                                     cached=cached))
        hidden = []
        if omit_routine:
            hidden = [t for t in (filtered or {}).get("trabajos") or []
                      if isinstance(t, dict) and t.get("routine")]
        rec.record_stage(StageOutput(pid, run_id, "omitted",
                                     lines_of({"trabajos": hidden}), cached=cached))
    except Exception as exc:
        logging.warning(f"ocr_feedback: sheet {source_name}#{scan_position} "
                        f"not recorded: {exc}")


def label_of(flagged, text, original_text, hand_edited, added, month_final) -> str:
    """How much a line's text can be trusted as truth, strongest first."""
    if flagged:
        return "none"
    if added or text != original_text:
        return "edited"
    if hand_edited:
        return "confirmed"
    if month_final:
        return "accepted"
    return "none"


def _discard_truth(store, folder: str) -> None:
    store.close()
    shutil.rmtree(folder, ignore_errors=True)


class NetTuneTruth:
    """Reads a private copy of an entries database; the file given is never
    opened for writing (EntryStore migrates whatever it opens)."""

    def __init__(self, entries_db: str, year: str | None = None, month: str | None = None):
        from nettune.report.entry_store import EntryStore

        self._dir, copy = private_copy(entries_db)
        try:
            self._store = EntryStore(copy)
        except BaseException:
            shutil.rmtree(self._dir, ignore_errors=True)
            raise
        # The copy holds real data: it goes on close(), when the source is
        # dropped, or at interpreter exit, whichever comes first.
        self._finalizer = weakref.finalize(self, _discard_truth, self._store, self._dir)
        self._db = self._store._connection
        self._year, self._month = year, month
        self._sheets: dict = {}
        self._final: dict = {}

    def _where(self) -> tuple[str, tuple]:
        clauses, params = [], []
        if self._year:
            clauses.append("year = ?")
            params.append(self._year)
        if self._month:
            clauses.append("month = ?")
            params.append(self._month)
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", tuple(params)

    def pages(self) -> list:
        from nettune.report.review_marks import image_name, is_maintenance_ref

        where, params = self._where()
        found = {}
        for year, month, source, position, ref in self._db.execute(
                "SELECT year, month, source, scan_position, review_ref FROM scan_sheets"
                f"{where} ORDER BY year, month, source, scan_position", params):
            found[page_id(source, position)] = (year, month, ref)
        known = {(y, m, r) for y, m, r in found.values()}
        extra = "AND" if where else "WHERE"
        for year, month, ref in self._db.execute(
                f"SELECT DISTINCT year, month, review_ref FROM memoria_entries{where} "
                f"{extra} review_ref != ''", params):
            if (year, month, ref) not in known:
                found[ref_page_id(year, month, ref)] = (year, month, ref)
        self._sheets = found
        return [Page(pid, image_name(ref),
                     {"year": y, "month": m, "review_ref": ref,
                      "section": "mantenimiento" if is_maintenance_ref(ref) else "seguridad"})
                for pid, (y, m, ref) in found.items()]

    def _month_final(self, year: str, month: str) -> bool:
        key = (year, month)
        if key not in self._final:
            self._final[key] = not self._store.to_check(year, month)
        return self._final[key]

    def final_lines(self, page_id_: str) -> list:
        from nettune.report.entry_store import HAND_SOURCE

        if not self._sheets:
            self.pages()
        if page_id_ not in self._sheets:
            return []
        year, month, ref = self._sheets[page_id_]
        final = self._month_final(year, month)
        lines = []
        for rowid, block, text, original, source, flagged, hand_edited in self._db.execute(
                "SELECT rowid, block, text, original_text, source, flagged, hand_edited "
                "FROM memoria_entries WHERE year = ? AND month = ? AND review_ref = ? "
                "ORDER BY COALESCE(paper_order, position), position", (year, month, ref)):
            added = source == HAND_SOURCE
            lines.append(FinalLine(
                line_ref=str(rowid), text=text, tag=block,
                status=label_of(flagged, text, original, hand_edited, added, final),
                source_text=None if added or not original else original,
                meta={"added": True} if added else {}))
        return lines

    def close(self) -> None:
        self._finalizer()


def truth_source(entries_db: str, year: str | None = None,
                 month: str | None = None) -> NetTuneTruth:
    return NetTuneTruth(entries_db, year=year, month=month)
