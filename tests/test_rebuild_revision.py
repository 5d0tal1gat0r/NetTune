"""tools/rebuild_revision.py: the numbering check, and never overwriting."""

import importlib.util
import os

import pytest
from PIL import Image, ImageDraw

from nettune.config import config
from nettune.report.entry_store import EntryStore
from nettune.report.month_folders import revision_dir_for
from nettune.report.review_marks import image_name

_spec = importlib.util.spec_from_file_location(
    "rebuild_revision",
    os.path.join(os.path.dirname(__file__), "..", "tools", "rebuild_revision.py"))
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)

SRC = "SKM_9.pdf"


def _sheet(path, seed):
    """A sheet distinct from its neighbours: a block at a different height."""
    image = Image.new("L", (200, 280), 255)
    ImageDraw.Draw(image).rectangle((20, 20 + seed * 40, 180, 50 + seed * 40), fill=0)
    image.save(path)
    return str(path)


@pytest.fixture
def batch(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "incoming_dir", str(tmp_path / "incoming"))
    raws = [_sheet(tmp_path / f"raw{n}.png", n) for n in range(1, 6)]
    monkeypatch.setattr(tool, "raw_sheets", lambda scan, workdir: raws)
    monkeypatch.setattr(tool, "straighten", lambda p, **k: p)
    monkeypatch.setattr(tool, "to_portrait", lambda p: p)
    revision = revision_dir_for(config.incoming_dir, "2026", "SEPTIEMBRE")
    os.makedirs(revision, exist_ok=True)
    with EntryStore(str(tmp_path / "r.sqlite3")) as store:
        # Pages 2 and 4 were saved when the batch was read; 1, 3, 5 were not.
        for page in (2, 4):
            ref = f"0{page}-09-2026 p{page}"
            store._connection.execute(
                "INSERT INTO memoria_entries (year, month, block, position, text, source, "
                "flagged, review_ref, added_at, dedupe_key, original_text) "
                "VALUES ('2026','SEPTIEMBRE','B:',?,?,?,1,?,'t',?,?)",
                (page, f"L{page}", SRC, ref, f"l{page}", f"L{page}"))
            Image.open(raws[page - 1]).save(os.path.join(revision, image_name(ref)))
        store._connection.commit()
        yield store, revision, raws


def test_it_writes_only_the_missing_sheets_and_records_all(batch):
    store, _, _ = batch
    result = tool.rebuild("x/" + SRC, "2026", "SEPTIEMBRE", store)
    assert result["kept"] == 2
    assert result["written"] == ["sin-fecha_p1.jpg", "sin-fecha_p3.jpg", "sin-fecha_p5.jpg"]
    assert store.source_sheets("2026", "SEPTIEMBRE", SRC) == {
        1: "SKM_9 p1", 2: "02-09-2026 p2", 3: "SKM_9 p3",
        4: "04-09-2026 p4", 5: "SKM_9 p5"}


def test_an_existing_image_is_never_overwritten(batch):
    """It may have been turned by hand."""
    store, revision, _ = batch
    existing = os.path.join(revision, "02-09-2026_p2.jpg")
    with open(existing, "rb") as f:
        before = f.read()
    tool.rebuild("x/" + SRC, "2026", "SEPTIEMBRE", store)
    with open(existing, "rb") as f:
        assert f.read() == before


def test_a_shifted_numbering_writes_nothing(batch, monkeypatch):
    """If the sheets came out one off, every name would be wrong."""
    store, revision, raws = batch
    monkeypatch.setattr(tool, "raw_sheets", lambda scan, workdir: raws[1:] + raws[:1])
    with pytest.raises(SystemExit, match="Numbering check failed"):
        tool.rebuild("x/" + SRC, "2026", "SEPTIEMBRE", store)
    assert sorted(os.listdir(revision)) == ["02-09-2026_p2.jpg", "04-09-2026_p4.jpg"]
    assert store.source_sheets("2026", "SEPTIEMBRE", SRC) == {
        2: "02-09-2026 p2", 4: "04-09-2026 p4"}


def test_a_dry_run_changes_nothing(batch):
    store, revision, _ = batch
    result = tool.rebuild("x/" + SRC, "2026", "SEPTIEMBRE", store, dry_run=True)
    assert len(result["written"]) == 3
    assert sorted(os.listdir(revision)) == ["02-09-2026_p2.jpg", "04-09-2026_p4.jpg"]


def test_a_prepared_image_is_used_instead_of_straightening(batch, tmp_path, monkeypatch):
    store, revision, _ = batch
    prepared = tmp_path / "ready"
    prepared.mkdir()
    (prepared / "sin-fecha_p3.jpg").write_bytes(b"prepared elsewhere")
    tool.rebuild("x/" + SRC, "2026", "SEPTIEMBRE", store, straightened=str(prepared))
    with open(os.path.join(revision, "sin-fecha_p3.jpg"), "rb") as f:
        assert f.read() == b"prepared elsewhere"
