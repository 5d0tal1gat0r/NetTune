"""A stretch nobody can read becomes one line, flagged, and never hidden."""

from nettune.pages.illegible import ILLEGIBLE_GROUP, collapse
from nettune.reading.filtering_agents import apply_filter
from nettune.report.entry_store import EntryStore
from nettune.report.memoria import SEGURIDAD_BLOCK
from nettune.report.routine_rules import is_noise, is_routine_text, reads_as_event


def e(text, confident=True):
    return {"text": text, "confident": confident, "variants": []}


def texts(entries):
    return [x["text"] for x in entries]


def test_a_run_of_fragments_becomes_one_marked_line():
    out = collapse([e("Comienzo el servicio"), e("[?] [?] zona [?]"), e("se [?] [?] la"),
                    e("[?] [?] [?]"), e("Se cierra el muelle")])
    assert texts(out) == ["Comienzo el servicio", ILLEGIBLE_GROUP, "Se cierra el muelle"]
    assert out[1]["confident"] is False


def test_one_long_unreadable_line_is_a_group_too():
    out = collapse([e("[?] [?] [?] [?] del [?]")])
    assert texts(out) == [ILLEGIBLE_GROUP]


def test_a_line_with_a_word_or_two_unread_is_still_a_reading():
    kept = [e("Se abre el torreón de zona 4 a [?] de telefonía"),
            e("Aviso del [?] [?] por una fuga de agua en aseos")]
    assert texts(collapse(kept)) == texts(kept)


def test_a_lone_short_fragment_is_left_alone():
    assert texts(collapse([e("[?] [?] zona")])) == ["[?] [?] zona"]


def test_the_models_own_marker_is_always_flagged():
    out = collapse([e(ILLEGIBLE_GROUP, confident=True)])
    assert out[0]["confident"] is False


def test_two_groups_stay_two():
    out = collapse([e("[?] [?] [?] [?]"), e("Se cierra el muelle"), e("[?] [?] [?] [?] [?]")])
    assert texts(out) == [ILLEGIBLE_GROUP, "Se cierra el muelle", ILLEGIBLE_GROUP]


def test_the_marker_is_never_routine_and_never_noise():
    assert reads_as_event(ILLEGIBLE_GROUP)
    assert not is_noise(ILLEGIBLE_GROUP)
    page = {"tipo": "seguridad", "trabajos": [e(ILLEGIBLE_GROUP, confident=False)]}
    out = apply_filter(page, ["Algo inventado por el modelo"], routine=[True])
    assert out["trabajos"][0]["text"] == ILLEGIBLE_GROUP
    assert out["trabajos"][0]["routine"] is False
    assert not is_routine_text(ILLEGIBLE_GROUP)


def test_every_group_in_a_month_is_stored_and_flagged(tmp_path):
    with EntryStore(str(tmp_path / "e.sqlite3")) as store:
        store.add("2026", "SEPTIEMBRE", SEGURIDAD_BLOCK,
                  [e(ILLEGIBLE_GROUP, False), e("Se cierra el muelle"), e(ILLEGIBLE_GROUP, False)],
                  source="a.pdf", review_ref="01-09-2026 p1")
        store.add("2026", "SEPTIEMBRE", SEGURIDAD_BLOCK, [e(ILLEGIBLE_GROUP, False)],
                  source="a.pdf", review_ref="01-09-2026 p2")
        # Reading the first sheet again adds nothing.
        store.add("2026", "SEPTIEMBRE", SEGURIDAD_BLOCK,
                  [e(ILLEGIBLE_GROUP, False), e("Se cierra el muelle"), e(ILLEGIBLE_GROUP, False)],
                  source="a.pdf", review_ref="01-09-2026 p1")
        stored = [x["text"] for x in store.month_entries("2026", "SEPTIEMBRE")
                  if x["flagged"]]
        assert stored == [ILLEGIBLE_GROUP, "[?] (grupo de texto ilegible 2)",
                          "[?] (grupo de texto ilegible 3)"]


def test_the_transcription_prompt_asks_for_the_marker():
    with open("prompts/transcription.md", encoding="utf-8") as handle:
        assert ILLEGIBLE_GROUP in handle.read()
