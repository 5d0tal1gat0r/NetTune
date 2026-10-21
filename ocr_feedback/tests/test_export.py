import json
import os

from ocr_feedback.export import build_records, export_snapshot
from ocr_feedback.model import FinalLine, Line, Page, ReviewEvent, Run, StageOutput
from ocr_feedback.profile import parse_profile
from ocr_feedback.store import FeedbackReader, SqliteRecorder

NETTUNE_LIKE = parse_profile({"system": "nep", "stages": [
    {"name": "passes", "kind": "reads"}, {"name": "consensus", "kind": "select"},
    {"name": "filtered", "kind": "select"}, {"name": "omitted", "kind": "drop"}]})
TOY = parse_profile({"system": "toy", "stages": [{"name": "tesseract", "kind": "reads"}]})


class FakeTruth:
    def __init__(self, pages, finals):
        self._pages, self._finals = pages, finals

    def pages(self):
        return self._pages

    def final_lines(self, page_id):
        return self._finals.get(page_id, [])


def _capture(path, stages, events=()):
    rec = SqliteRecorder(path, "nep")
    rec.record_run(Run("r1", "c", "2026-10-01T00:00:00+00:00"))
    for stage, seq, texts in stages:
        rec.record_stage(StageOutput("p1", "r1", stage,
                                     [Line(t, {"disagreement": t.endswith("?")}) for t in texts],
                                     seq=seq))
    for e in events:
        rec.record_event(e)
    return FeedbackReader(path)


def _by_ref(records):
    return {r["line_ref"]: r for r in records}


def test_nettune_like_outcomes(tmp_path):
    reader = _capture(str(tmp_path / "f.sqlite3"), [
        ("passes", 1, ["Revision cuadro cobre", "Se abre Z6", "Linea inventada"]),
        ("passes", 2, ["Revision cuadro aire", "Se abre 26"]),
        ("consensus", 0, ["Revision cuadro cobre?", "Se abre Z6", "Linea inventada"]),
        ("filtered", 0, ["Revisión cuadro cobre", "Se abre Z6", "Linea inventada"]),
        ("omitted", 0, ["Conectando mq de aire", "Ronda rutinaria"]),
    ], events=[
        ReviewEvent("p1", "1", "edit", "Revisión cuadro cobre", "Revisión cuadro aire"),
        ReviewEvent("p1", "9", "delete", "Linea inventada", None, "Otros", None),
        ReviewEvent("p1", "1", "retag", before_tag="Electricidad", after_tag="Parking"),
    ])
    truth = FakeTruth([Page("p1", "a.jpg", {"section": "mantenimiento"})], {"p1": [
        FinalLine("1", "Revisión cuadro aire", "Parking", "edited",
                  source_text="Revisión cuadro cobre"),
        FinalLine("2", "Se abre Z6", "Otros", "accepted", source_text="Se abre Z6"),
        FinalLine("3", "Conectando mq de aire", "Otros", "edited", source_text=None,
                  meta={"added": True}),
        FinalLine("4", "Puerta forzada", "Otros", "edited", source_text=None,
                  meta={"added": True}),
    ]})
    lines, pages = build_records(NETTUNE_LIKE, truth, reader)
    r = _by_ref(lines)

    assert r["1"]["outcome"] == "edited" and r["1"]["label"] == "edited"
    assert r["1"]["final"] == "Revisión cuadro aire"
    assert r["1"]["stages"]["filtered"] == "Revisión cuadro cobre"
    assert r["1"]["stages"]["consensus"] == "Revision cuadro cobre?"
    assert r["1"]["stages"]["passes"] == ["Revision cuadro cobre", "Revision cuadro aire"]
    assert r["1"]["flags"]["consensus"] == {"disagreement": True}
    assert r["1"]["tag_first"] == "Electricidad" and r["1"]["tag_final"] == "Parking"
    assert r["1"]["section"] == "mantenimiento" and r["1"]["image"] == "a.jpg"
    assert r["1"]["line_id"] == "p1/1" and r["1"]["align_score"] == 1.0

    assert r["2"]["outcome"] == "kept" and r["2"]["label"] == "accepted"

    assert r["3"]["outcome"] == "added" and r["3"]["wrongly_dropped"] is True
    assert r["3"]["stages"]["omitted"] == "Conectando mq de aire"
    assert r["4"]["outcome"] == "added" and r["4"]["wrongly_dropped"] is False
    assert r["4"]["stages"] == {"passes": None, "consensus": None, "filtered": None,
                                "omitted": None}

    assert r["9"]["outcome"] == "deleted" and r["9"]["final"] is None
    assert r["9"]["stages"]["filtered"] == "Linea inventada"

    dropped = [x for x in lines if x["outcome"] == "dropped"]
    assert [x["stages"]["omitted"] for x in dropped] == ["Ronda rutinaria"]
    assert dropped[0]["label"] == "none"

    assert pages == [{"page_id": "p1", "image": "a.jpg", "meta": {"section": "mantenimiento"},
                      "captured_stages": ["consensus", "filtered", "omitted", "passes"]}]


def test_below_threshold_is_null_not_forced(tmp_path):
    reader = _capture(str(tmp_path / "f.sqlite3"), [("filtered", 0, ["Totalmente otra"])])
    truth = FakeTruth([Page("p1")], {"p1": [
        FinalLine("1", "Se abre Z6", None, "confirmed", source_text="Se abre Z6")]})
    rec = build_records(NETTUNE_LIKE, truth, reader)[0][0]
    assert rec["stages"]["filtered"] is None and rec["align_score"] < 0.72


def test_pre_capture_page_uses_source_text(tmp_path):
    truth = FakeTruth([Page("p1")], {"p1": [
        FinalLine("1", "Revisión cuadro aire", None, "edited",
                  source_text="Revisión cuadro cobre")]})
    rec = build_records(NETTUNE_LIKE, truth, FeedbackReader(None))[0][0]
    assert rec["stages"] == {"passes": None, "consensus": None,
                             "filtered": "Revisión cuadro cobre", "omitted": None}
    assert rec["outcome"] == "edited" and rec["pre_capture"] is True


def test_single_stage_toy_system(tmp_path):
    rec = SqliteRecorder(str(tmp_path / "t.sqlite3"), "toy")
    rec.record_run(Run("r", "c", "2026-10-01T00:00:00+00:00"))
    rec.record_stage(StageOutput("p1", "r", "tesseract", [Line("he1lo world")], seq=1))
    rec.record_stage(StageOutput("p1", "r", "tesseract", [Line("hexlo wor1d")], seq=2))
    truth = FakeTruth([Page("p1")], {"p1": [
        FinalLine("a", "hello world", None, "edited", source_text="he1lo world")]})
    lines, _ = build_records(TOY, truth, FeedbackReader(str(tmp_path / "t.sqlite3")))
    assert lines[0]["stages"] == {"tesseract": ["he1lo world", "hexlo wor1d"]}
    assert lines[0]["outcome"] == "edited"
    from ocr_feedback.align import ratio
    best = max(ratio("he1lo world", t, TOY) for t in ("he1lo world", "hexlo wor1d"))
    assert lines[0]["align_score"] == round(best, 4)


def _one_stage(tmp_path, stage_text, final_text, source):
    reader = _capture(str(tmp_path / "f.sqlite3"), [("filtered", 0, [stage_text])])
    truth = FakeTruth([Page("p1")], {"p1": [
        FinalLine("1", final_text, None, "accepted", source_text=source)]})
    return build_records(NETTUNE_LIKE, truth, reader)[0][0]


def test_joined_line_contains_anchor(tmp_path):
    rec = _one_stage(tmp_path, "Se abre Z6 y se cierra Z7", "Se abre Z6", "Se abre Z6")
    assert rec["stages"]["filtered"] == "Se abre Z6 y se cierra Z7"
    assert rec["align_score"] < 1


def test_split_line_contained_in_anchor(tmp_path):
    rec = _one_stage(tmp_path, "Se abre Z6", "Se abre Z6 y se cierra Z7",
                     "Se abre Z6 y se cierra Z7")
    assert rec["stages"]["filtered"] == "Se abre Z6"
    assert rec["align_score"] < 1


def test_no_containment_no_threshold_is_none(tmp_path):
    rec = _one_stage(tmp_path, "Otra cosa", "Se abre Z6", "Se abre Z6")
    assert rec["stages"]["filtered"] is None


def test_reads_stage_containment(tmp_path):
    rec = SqliteRecorder(str(tmp_path / "t.sqlite3"), "toy")
    rec.record_run(Run("r", "c", "2026-10-01T00:00:00+00:00"))
    rec.record_stage(StageOutput("p1", "r", "tesseract", [Line("Se abre Z6 y se cierra Z7")], seq=1))
    truth = FakeTruth([Page("p1")], {"p1": [
        FinalLine("a", "Se abre Z6", None, "edited", source_text="Se abre Z6")]})
    lines, _ = build_records(TOY, truth, FeedbackReader(str(tmp_path / "t.sqlite3")))
    assert lines[0]["stages"] == {"tesseract": ["Se abre Z6 y se cierra Z7"]}
    assert lines[0]["align_score"] < 1


def _label(tmp_path, action, status):
    reader = _capture(str(tmp_path / "f.sqlite3"), [("filtered", 0, ["a"])],
                      events=[ReviewEvent("p1", "1", action)])
    truth = FakeTruth([Page("p1")], {"p1": [FinalLine("1", "a", None, status, source_text="a")]})
    return build_records(NETTUNE_LIKE, truth, reader)[0][0]["label"]


def test_confirm_event_refines_label(tmp_path):
    assert _label(tmp_path, "confirm", "accepted") == "confirmed"


def test_flag_event_sets_label_none(tmp_path):
    assert _label(tmp_path, "flag", "accepted") == "none"


def test_pre_capture_reads_profile_gives_list():
    truth = FakeTruth([Page("p1")], {"p1": [
        FinalLine("1", "hello", None, "edited", source_text="he1lo")]})
    rec = build_records(TOY, truth, FeedbackReader(None))[0][0]
    assert rec["stages"] == {"tesseract": ["he1lo"]}


def test_pre_capture_drop_only_profile_does_not_raise():
    drop_only = parse_profile({"system": "d", "stages": [{"name": "x", "kind": "drop"}]})
    truth = FakeTruth([Page("p1")], {"p1": [
        FinalLine("1", "hello", None, "edited", source_text="he1lo")]})
    rec = build_records(drop_only, truth, FeedbackReader(None))[0][0]
    assert rec["stages"] == {"x": None}


def test_unicode_survives_export(tmp_path):
    text = 'Revisión "P/0" — ñ\n🚪'
    truth = FakeTruth([Page("p1")], {"p1": [FinalLine("1", text, None, "confirmed",
                                                      source_text=text)]})
    out = export_snapshot(TOY, truth, FeedbackReader(None), str(tmp_path / "ds"), label="x")
    with open(os.path.join(out, "lines.jsonl"), encoding="utf-8") as handle:
        assert json.loads(handle.readline())["final"] == text


def test_snapshot_files_and_no_overwrite(tmp_path):
    truth = FakeTruth([Page("p1")], {"p1": [FinalLine("1", "a", None, "confirmed",
                                                      source_text="a")]})
    first = export_snapshot(TOY, truth, FeedbackReader(None), str(tmp_path), label="m")
    second = export_snapshot(TOY, truth, FeedbackReader(None), str(tmp_path), label="m")
    assert first != second and os.path.basename(first) == "toy-m"
    for name in ("lines.jsonl", "pages.jsonl", "manifest.json"):
        assert os.path.isfile(os.path.join(first, name))
    with open(os.path.join(first, "manifest.json"), encoding="utf-8") as handle:
        manifest = json.load(handle)
    assert manifest["system"] == "toy" and manifest["counts"]["lines"] == 1
    assert manifest["counts"]["by_label"] == {"confirmed": 1}


def _label_seq(tmp_path, actions, status):
    reader = _capture(str(tmp_path / "f.sqlite3"), [("filtered", 0, ["a"])],
                      events=[ReviewEvent("p1", "1", a) for a in actions])
    truth = FakeTruth([Page("p1")], {"p1": [FinalLine("1", "b", None, status, source_text="a")]})
    return build_records(NETTUNE_LIKE, truth, reader)[0][0]["label"]


def test_flag_then_edit_keeps_the_edited_label(tmp_path):
    assert _label_seq(tmp_path, ["flag", "edit"], "edited") == "edited"


def test_edit_then_flag_is_none(tmp_path):
    assert _label_seq(tmp_path, ["edit", "flag"], "edited") == "none"


def test_edit_then_delete_aligns_to_the_original_text(tmp_path):
    reader = _capture(str(tmp_path / "f.sqlite3"), [("filtered", 0, ["Se abre Z6"])],
                      events=[ReviewEvent("p1", "9", "edit", before_text="Se abre Z6",
                                          after_text="Totalmente distinto ahora"),
                              ReviewEvent("p1", "9", "delete",
                                          before_text="Totalmente distinto ahora")])
    truth = FakeTruth([Page("p1")], {"p1": []})
    rec = build_records(NETTUNE_LIKE, truth, reader)[0][0]
    assert rec["outcome"] == "deleted"
    assert rec["stages"]["filtered"] == "Se abre Z6"


def test_short_anchor_does_not_attach_to_a_longer_line(tmp_path):
    rec = _one_stage(tmp_path, "Se abre Z6 y Z7", "Z6", "Z6")
    assert rec["stages"]["filtered"] is None


def test_containment_is_on_token_boundaries(tmp_path):
    rec = _one_stage(tmp_path, "Se abre Z66 y se cierra", "Se abre Z6", "Se abre Z6")
    assert rec["stages"]["filtered"] is None
