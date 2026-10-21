"""Routine lines are classified, then kept out of the memoria.

Both kinds of sheet are mostly the same checks every day. Those are omitted so
the events stand out. The filter classifies rather than deletes: the entry
count stays aligned with the reading passes and the literal text stays in the
data, so nothing is lost -- it is simply not written into the document.
"""

import os

import pytest

from nettune.reading.filtering_agents import apply_filter
from nettune.report.entry_store import EntryStore
from nettune.report.memoria import SEGURIDAD_BLOCK, block_contents, fill_memoria

TEMPLATE = "templates/MEMORIA.docx"


def page(entries, tipo="seguridad"):
    return {
        "tipo": tipo,
        "titulo": "INFORME DIARIO",
        "fecha": "16-09-2026",
        "trabajos": [{"text": t, "confident": c, "variants": []} for t, c in entries],
    }


ROUTINE_PAGE = [
    ("Inicio del servicio", True),
    ("Se quitan pilonas Z1, Z2 y Z3", True),
    ("Se llama la atencion a una persona en patinete", True),
    ("Se abre Z6-1", True),
    ("Finaliza el servicio", True),
]


# --- classification -------------------------------------------------------


def test_routine_flags_are_applied():
    out = apply_filter(page(ROUTINE_PAGE), None, routine=[True, True, False, True, True])
    assert [t["routine"] for t in out["trabajos"]] == [True, True, False, True, True]


def test_entry_count_is_unchanged_by_classification():
    out = apply_filter(page(ROUTINE_PAGE), None, routine=[True, True, False, True, True])
    assert len(out["trabajos"]) == 5, "classification must not delete anything"


def test_a_mismatched_routine_list_falls_back_to_the_text():
    out = apply_filter(page(ROUTINE_PAGE), None, routine=[True, False])
    flags = [t["routine"] for t in out["trabajos"]]
    assert flags[0] is True, "'Inicio del servicio' reads as routine"
    assert flags[2] is False, "the llamada de atencion is an event"


def test_the_text_decides_even_when_the_reading_was_agreed():
    """Either signal is enough. The model kept calling 'Se colocan pilonas' an
    event on text the readings agreed on, so the patterns must still apply."""
    entries = [
        ("Inicio del servicio", True),
        ("Se abre Z6-1", False),
        ("Se llama la atencion a una persona", False),
    ]
    out = apply_filter(page(entries), None, routine=[True, True, True])
    assert out["trabajos"][0]["routine"] is True
    assert out["trabajos"][1]["routine"] is True
    assert out["trabajos"][2]["routine"] is False, "an incident is never hidden"


def test_a_confident_routine_line_the_model_missed_is_still_hidden():
    entries = [("Se colocan pilonas Z3 y Z1", True), ("Se abren los accesos", True)]
    out = apply_filter(page(entries), None, routine=[False, False])
    assert [t["routine"] for t in out["trabajos"]] == [True, True]


def test_an_incident_the_model_called_routine_is_still_kept():
    out = apply_filter(page([("Se expulsa a un individuo del centro", False)]),
                       None, routine=[True])
    assert out["trabajos"][0]["routine"] is False


def test_times_are_stripped_whatever_the_type():
    """A page typed 'desconocido' must not carry 07:00 into the memoria."""
    for tipo in ("seguridad", "mantenimiento", "desconocido", None):
        out = apply_filter(page([("07:00 COMIENZO EL SERVICIO", True)], tipo=tipo), None)
        assert not out["trabajos"][0]["text"].startswith("07:00"), tipo


# --- what reaches the document -------------------------------------------


@pytest.mark.skipif(not os.path.exists(TEMPLATE), reason="template absent")
def test_routine_entries_never_reach_the_memoria(tmp_path):
    out = apply_filter(page(ROUTINE_PAGE), None, routine=[True, True, False, True, True])
    visible = [t for t in out["trabajos"] if not t["routine"]]

    with EntryStore(str(tmp_path / "e.sqlite3")) as store:
        store.add("2026", "SEPTIEMBRE", SEGURIDAD_BLOCK, visible, "s.pdf")
        entries = store.entries("2026", "SEPTIEMBRE", SEGURIDAD_BLOCK)

    path = fill_memoria(TEMPLATE, str(tmp_path / "m.docx"), {}, entries)
    written = block_contents(path)[SEGURIDAD_BLOCK]
    assert written == ["Se llama la atencion a una persona en patinete"]
    body = " ".join(written)
    assert "Inicio del servicio" not in body
    assert "pilonas" not in body


@pytest.mark.skipif(not os.path.exists(TEMPLATE), reason="template absent")
def test_an_incident_survives_even_if_every_line_was_called_routine(tmp_path):
    """The model marking everything routine must not hide the one real event."""
    out = apply_filter(page(ROUTINE_PAGE), None, routine=[True] * 5)
    visible = [t["text"] for t in out["trabajos"] if not t["routine"]]
    assert visible == ["Se llama la atencion a una persona en patinete"]
