"""What a person does in the dashboard is recorded, and never gets in the way."""

import pytest

from entry_store import EntryStore
from memoria_blocks import BLOCKS
from ocr_feedback.recorder import make_recorder
from ocr_feedback.store import FeedbackReader

Y, M, SRC, REF = "2026", "SEPTIEMBRE", "SKM_1.pdf", "16-09-2026 p1"
PID = "SKM_1.pdf#4"


class Exploding:
    enabled = True

    def record_event(self, event):
        raise RuntimeError("boom")

    record_run = record_page = record_stage = record_event


def _seed(store, block=None):
    block = block or BLOCKS[0]
    store.record_sheet(Y, M, SRC, 1, REF, scan_position=4)
    store.add(Y, M, block, [{"text": "Revision cuadro cobre", "confident": False}],
              SRC, REF)
    return store.month_entries(Y, M)[0]["id"]


@pytest.fixture
def pair(tmp_path):
    fb = str(tmp_path / "fb.sqlite3")
    store = EntryStore(str(tmp_path / "e.sqlite3"), recorder=make_recorder(fb, "nettune"))
    yield store, (lambda: FeedbackReader(fb))
    store.close()


def _events(read):
    return [(e.action, e.before_text, e.after_text, e.before_tag, e.after_tag,
             e.meta.get("host_action")) for e in read().events(PID)]


def test_edit(pair):
    store, read = pair
    eid = _seed(store)
    assert store.edit_entry(eid, "Revision cuadro aire")
    assert _events(read) == [("edit", "Revision cuadro cobre", "Revision cuadro aire",
                              BLOCKS[0], BLOCKS[0], "edit")]
    event = read().events(PID)[0]
    assert event.line_ref == str(eid)
    assert event.meta["review_ref"] == REF and event.meta["year"] == Y


def test_confirm_flag_delete(pair):
    store, read = pair
    eid = _seed(store)
    store.confirm_entry(eid)
    store.flag_entry(eid)
    store.remove_entry(eid)
    assert [e[0] for e in _events(read)] == ["confirm", "flag", "delete"]
    assert _events(read)[2][1:3] == ("Revision cuadro cobre", None)


def test_add_and_add_to_sheet(pair):
    store, read = pair
    eid = _seed(store)
    new = store.add_entry(Y, M, BLOCKS[0], "Linea a mano", after_id=eid)
    other = store.add_to_sheet(Y, M, BLOCKS[0], REF, "Otra linea")
    assert new and other
    events = read().events(PID)
    assert [(e.action, e.after_text, e.meta["host_action"]) for e in events] == [
        ("add", "Linea a mano", "add"), ("add", "Otra linea", "add_to_sheet")]
    assert events[0].line_ref == str(new)


def test_retag(pair):
    store, read = pair
    eid = _seed(store, BLOCKS[0])
    assert store.retag_entry(eid, BLOCKS[1]).status == "changed"
    assert _events(read) == [("retag", "Revision cuadro cobre", "Revision cuadro cobre",
                              BLOCKS[0], BLOCKS[1], "retag")]


def test_rewrite_is_an_edit_by_rule(pair):
    store, read = pair
    eid = _seed(store)
    store.rewrite_entry(eid, "Revision cuadro aire")
    assert _events(read)[0][0] == "edit" and _events(read)[0][5] == "rewrite"


def test_failed_actions_record_nothing(pair):
    store, read = pair
    eid = _seed(store)
    assert not store.edit_entry(eid, "   ")
    assert not store.remove_entry(99999)
    assert store.retag_entry(eid, BLOCKS[0]).status == "unchanged"
    assert _events(read) == []


def test_unknown_sheet_gets_a_ref_page_id(tmp_path):
    fb = str(tmp_path / "fb.sqlite3")
    store = EntryStore(str(tmp_path / "e.sqlite3"), recorder=make_recorder(fb, "nettune"))
    store.add(Y, M, BLOCKS[0], [{"text": "Sin hoja", "confident": True}], SRC, REF)
    eid = store.month_entries(Y, M)[0]["id"]
    store.confirm_entry(eid)
    assert [e.action for e in FeedbackReader(fb).events(f"ref:{Y}/{M}/{REF}")] == ["confirm"]


def test_no_recorder_means_no_change(tmp_path):
    store = EntryStore(str(tmp_path / "e.sqlite3"))
    eid = _seed(store)
    assert store.edit_entry(eid, "Revision cuadro aire")


@pytest.mark.parametrize("action", ["edit", "confirm", "flag", "retag", "delete",
                                    "add", "add_to_sheet", "rewrite"])
def test_a_recorder_that_raises_changes_nothing(tmp_path, action):
    """Same return value and same rows, with or without a broken recorder."""
    results = []
    for rec in (None, Exploding()):
        store = EntryStore(str(tmp_path / f"{action}-{bool(rec)}.sqlite3"), recorder=rec)
        eid = _seed(store, BLOCKS[0])
        result = {
            "edit": lambda: store.edit_entry(eid, "Nuevo texto"),
            "confirm": lambda: store.confirm_entry(eid),
            "flag": lambda: store.flag_entry(eid),
            "retag": lambda: store.retag_entry(eid, BLOCKS[1]).status,
            "delete": lambda: store.remove_entry(eid),
            "add": lambda: bool(store.add_entry(Y, M, BLOCKS[0], "Mano", after_id=eid)),
            "add_to_sheet": lambda: bool(store.add_to_sheet(Y, M, BLOCKS[0], REF, "Mano")),
            "rewrite": lambda: store.rewrite_entry(eid, "Por regla"),
        }[action]()
        rows = [(e["block"], e["text"], e["flagged"], e["hand_edited"])
                for e in store.month_entries(Y, M)]
        results.append((result, rows))
        store.close()
    assert results[0] == results[1]
