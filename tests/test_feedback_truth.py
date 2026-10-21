"""NetTune's reviewed state, as ocr_feedback reads it from a database copy."""

import json
import os
import subprocess
import sys

import pytest

from nettune.ops import nettune_feedback
from nettune.report.entry_store import EntryStore
from nettune.report.memoria_blocks import BLOCKS
from ocr_feedback.recorder import make_recorder

Y, M, SRC = "2026", "SEPTIEMBRE", "SKM_1.pdf"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.parametrize("args,expected", [
    ((1, "a", "a", 1, False, True), "none"),        # flagged: unsettled
    ((0, "b", "a", 1, False, False), "edited"),
    ((0, "a", "", 1, True, False), "edited"),        # added by hand
    ((0, "a", "a", 1, False, False), "confirmed"),
    ((0, "a", "a", 0, False, True), "accepted"),
    ((0, "a", "a", 0, False, False), "none"),
])
def test_label_of(args, expected):
    assert nettune_feedback.label_of(*args) == expected


@pytest.fixture
def entries(tmp_path):
    path = str(tmp_path / "e.sqlite3")
    fb = str(tmp_path / "fb.sqlite3")
    with EntryStore(path, recorder=make_recorder(fb, "nettune")) as store:
        store.record_sheet(Y, M, SRC, 1, "16-09-2026 p1", scan_position=2)
        store.add(Y, M, BLOCKS[0], [{"text": "Revision cuadro cobre", "confident": False},
                                    {"text": "Se abre Z6", "confident": True}],
                  SRC, "16-09-2026 p1")
        rows = store.month_entries(Y, M)
        store.edit_entry(rows[0]["id"], "Revision cuadro aire")
        store.add_entry(Y, M, BLOCKS[0], "Puerta forzada", after_id=rows[1]["id"])
    return path, fb


def test_pages_and_final_lines(entries):
    path, _ = entries
    truth = nettune_feedback.truth_source(path, year=Y, month=M)
    pages = truth.pages()
    assert [(p.page_id, p.image_ref, p.meta["section"], p.meta["review_ref"])
            for p in pages] == [("SKM_1.pdf#2", "16-09-2026_p1.jpg", "seguridad",
                                 "16-09-2026 p1")]
    finals = {f.text: f for f in truth.final_lines("SKM_1.pdf#2")}
    assert finals["Revision cuadro aire"].status == "edited"
    assert finals["Revision cuadro aire"].source_text == "Revision cuadro cobre"
    assert finals["Puerta forzada"].meta == {"added": True}
    assert finals["Puerta forzada"].source_text is None
    assert finals["Se abre Z6"].status == "accepted"
    assert finals["Se abre Z6"].tag == BLOCKS[0]
    truth.close()


def test_the_source_database_is_not_touched(entries):
    path, _ = entries
    before = open(path, "rb").read()
    truth = nettune_feedback.truth_source(path)
    truth.pages()
    truth.close()
    assert open(path, "rb").read() == before


def test_export_end_to_end(entries, tmp_path):
    path, fb = entries
    out = subprocess.run(
        [sys.executable, "-m", "ocr_feedback", "export",
         "--profile", os.path.join(REPO, "feedback", "nettune.toml"),
         "--feedback-db", fb, "--adapter", "nettune.ops.nettune_feedback:truth_source",
         "--adapter-arg", f"entries_db={path}", "--adapter-arg", f"year={Y}",
         "--adapter-arg", f"month={M}", "--out", str(tmp_path / "ds"), "--label", "sep"],
        cwd=REPO, capture_output=True, text=True, check=True)
    folder = out.stdout.strip().splitlines()[-1]
    lines = [json.loads(l) for l in open(os.path.join(folder, "lines.jsonl"), encoding="utf-8")]
    by_final = {l["final"]: l for l in lines}
    assert by_final["Revision cuadro aire"]["outcome"] == "edited"
    assert by_final["Puerta forzada"]["outcome"] == "added"


def test_export_without_feedback_db(entries, tmp_path):
    path, _ = entries
    from ocr_feedback.cli import main

    assert main(["export", "--profile", os.path.join(REPO, "feedback", "nettune.toml"),
                 "--adapter", "nettune.ops.nettune_feedback:truth_source",
                 "--adapter-arg", f"entries_db={path}",
                 "--out", str(tmp_path / "ds"), "--label", "old"]) == 0
    folder = str(tmp_path / "ds" / "nettune-old")
    lines = [json.loads(l) for l in open(os.path.join(folder, "lines.jsonl"), encoding="utf-8")]
    edited = next(l for l in lines if l["final"] == "Revision cuadro aire")
    assert edited["stages"]["filtered"] == "Revision cuadro cobre"
    assert edited["pre_capture"] is True


def test_no_temp_copy_left_when_the_store_fails_to_open(entries, tmp_path, monkeypatch):
    import tempfile

    from nettune.report import entry_store
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))

    def boom(*a, **k):
        raise RuntimeError("cannot open")

    monkeypatch.setattr(entry_store, "EntryStore", boom)
    with pytest.raises(RuntimeError):
        nettune_feedback.truth_source(entries[0])
    assert not [n for n in os.listdir(scratch) if n.startswith("ocr_feedback_")]


def test_a_dropped_truth_source_removes_its_copy(entries, tmp_path, monkeypatch):
    import gc
    import tempfile

    path, _ = entries
    folder = tmp_path / "tmpdir"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    truth = nettune_feedback.truth_source(path)
    truth.pages()
    assert any(folder.iterdir())
    del truth
    gc.collect()
    assert not any(folder.iterdir())
