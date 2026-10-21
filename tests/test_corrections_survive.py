"""A correction outranks the reader, and survives the sheet being read again.

The binding principle of the design: nothing may silently overwrite a
correction made by hand. A reprocess deletes only what nobody has touched,
and the re-read original is recognised and dropped rather than landing beside
the correction as a second entry saying the same thing badly.
"""

import pytest

from nettune.report.entry_store import EntryStore


@pytest.fixture
def store(tmp_path):
    with EntryStore(str(tmp_path / "e.sqlite3")) as s:
        yield s


def test_clearing_a_month_keeps_what_was_corrected(store):
    store.add("2026", "SEPTIEMBRE", "Parking",
              [{"text": "Se retiran pelonas.", "confident": False},
               {"text": "Se abren torreones."}], "s.pdf", "01-09 p1")
    rows = store.month_entries("2026", "SEPTIEMBRE")
    store.edit_entry(rows[0]["id"], "Se retiran pilonas.")

    removed, kept = store.clear_month("2026", "SEPTIEMBRE")

    assert (removed, kept) == (1, 1)
    assert [r["text"] for r in store.month_entries("2026", "SEPTIEMBRE")] == [
        "Se retiran pilonas."
    ]


def test_the_reread_original_does_not_come_back_beside_the_correction(store):
    """The whole point: reading the sheet again must not undo the fix."""
    store.add("2026", "SEPTIEMBRE", "Parking",
              [{"text": "Se retiran pelonas.", "confident": False}],
              "s.pdf", "01-09 p1")
    rows = store.month_entries("2026", "SEPTIEMBRE")
    store.edit_entry(rows[0]["id"], "Se retiran pilonas.")
    store.clear_month("2026", "SEPTIEMBRE")

    # The sheet is read again and produces exactly what it produced before.
    store.add("2026", "SEPTIEMBRE", "Parking",
              [{"text": "Se retiran pelonas.", "confident": False}],
              "s.pdf", "01-09 p1")

    assert [r["text"] for r in store.month_entries("2026", "SEPTIEMBRE")] == [
        "Se retiran pilonas."
    ], "the correction replaced its own source"


def test_punctuation_does_not_let_the_original_back_in(store):
    store.add("2026", "SEPTIEMBRE", "Parking",
              [{"text": "Se retiran pelonas.", "confident": False}], "s.pdf", "p1")
    rows = store.month_entries("2026", "SEPTIEMBRE")
    store.edit_entry(rows[0]["id"], "Se retiran pilonas.")
    store.clear_month("2026", "SEPTIEMBRE")

    store.add("2026", "SEPTIEMBRE", "Parking",
              [{"text": "se  retiran pelonas", "confident": False}], "s.pdf", "p1")

    assert len(store.month_entries("2026", "SEPTIEMBRE")) == 1


def test_a_genuinely_new_entry_still_arrives(store):
    store.add("2026", "SEPTIEMBRE", "Parking",
              [{"text": "Se retiran pelonas.", "confident": False}], "s.pdf", "p1")
    rows = store.month_entries("2026", "SEPTIEMBRE")
    store.edit_entry(rows[0]["id"], "Se retiran pilonas.")
    store.clear_month("2026", "SEPTIEMBRE")

    store.add("2026", "SEPTIEMBRE", "Parking",
              [{"text": "Se retiran pelonas."},
               {"text": "Salta la alarma en zona 1."}], "s.pdf", "p1")

    assert sorted(r["text"] for r in store.month_entries("2026", "SEPTIEMBRE")) == [
        "Salta la alarma en zona 1.", "Se retiran pilonas."
    ]


def test_another_month_is_untouched(store):
    store.add("2026", "AGOSTO", "Parking", [{"text": "De agosto."}], "s.pdf")
    store.add("2026", "SEPTIEMBRE", "Parking", [{"text": "De septiembre."}], "s.pdf")
    store.clear_month("2026", "SEPTIEMBRE")
    assert [r["text"] for r in store.month_entries("2026", "AGOSTO")] == ["De agosto."]


def test_a_reread_correction_moves_back_to_its_own_sheet_position(store):
    """The correction does not float to the top of the block after a reprocess.

    A reprocess keeps a corrected row at whatever position survived the
    delete, which is not where it sat on the sheet once its neighbours are
    re-inserted after it. The fix moves the correction back onto the slot its
    own source line reclaims, so line order matches the sheet again.
    """
    store.add("2026", "SEPTIEMBRE", "Parking",
              [{"text": "Uno."}, {"text": "Dos."},
               {"text": "Tres original."}, {"text": "Cuatro."}], "s.pdf")
    rows = store.month_entries("2026", "SEPTIEMBRE")
    third = next(r for r in rows if r["text"] == "Tres original.")
    store.edit_entry(third["id"], "Tres corregido.")

    store.clear_month("2026", "SEPTIEMBRE")
    store.add("2026", "SEPTIEMBRE", "Parking",
              [{"text": "Uno."}, {"text": "Dos."},
               {"text": "Tres original."}, {"text": "Cuatro."}], "s.pdf")

    assert [r["text"] for r in store.month_entries("2026", "SEPTIEMBRE")] == [
        "Uno.", "Dos.", "Tres corregido.", "Cuatro."
    ]


def test_a_correction_in_one_block_does_not_suppress_another_block(store):
    """Suppression is scoped to the block the correction was made in."""
    store.add("2026", "SEPTIEMBRE", "Parking",
              [{"text": "Se retiran pelonas.", "confident": False}], "s.pdf", "p1")
    rows = store.month_entries("2026", "SEPTIEMBRE")
    store.edit_entry(rows[0]["id"], "Se retiran pilonas.")
    store.clear_month("2026", "SEPTIEMBRE")

    # The same wrong text, genuinely, in an unrelated block.
    store.add("2026", "SEPTIEMBRE", "Almacen",
              [{"text": "Se retiran pelonas."}], "s.pdf", "p1")

    assert [r["text"] for r in store.month_entries("2026", "SEPTIEMBRE")
            if r["block"] == "Almacen"] == ["Se retiran pelonas."]


def test_a_correction_in_one_month_does_not_suppress_another_month(store):
    """Suppression is scoped to the month the correction was made in."""
    store.add("2026", "AGOSTO", "Parking",
              [{"text": "Se retiran pelonas.", "confident": False}], "s.pdf", "p1")
    rows = store.month_entries("2026", "AGOSTO")
    store.edit_entry(rows[0]["id"], "Se retiran pilonas.")
    store.clear_month("2026", "AGOSTO")

    # The same wrong text, genuinely, in a different month.
    store.add("2026", "SEPTIEMBRE", "Parking",
              [{"text": "Se retiran pelonas."}], "s.pdf", "p1")

    assert [r["text"] for r in store.month_entries("2026", "SEPTIEMBRE")] == [
        "Se retiran pelonas."
    ]


def test_a_hand_typed_line_never_suppresses_anything(store):
    """add_entry leaves original_text empty; it must not block a real line."""
    store.add_entry("2026", "SEPTIEMBRE", "Parking", "Anadido a mano.")

    added = store.add("2026", "SEPTIEMBRE", "Parking",
                       [{"text": "Salta la alarma en zona 1."}], "s.pdf")

    assert added == 1
    assert "Salta la alarma en zona 1." in [
        r["text"] for r in store.month_entries("2026", "SEPTIEMBRE")
    ]


def test_a_punctuation_only_correction_does_not_suppress_other_punctuation(store):
    """A hand-edited row whose original_text was punctuation-only folds to the
    empty dedupe key; it must not swallow every future punctuation-only line."""
    store.add("2026", "SEPTIEMBRE", "Parking",
              [{"text": "---", "confident": False}], "s.pdf", "p1")
    rows = store.month_entries("2026", "SEPTIEMBRE")
    store.edit_entry(rows[0]["id"], "Sin incidencias.")
    store.clear_month("2026", "SEPTIEMBRE")

    added = store.add("2026", "SEPTIEMBRE", "Parking",
                       [{"text": "..."}], "s.pdf", "p1")

    assert added == 1
    assert "..." in [r["text"] for r in store.month_entries("2026", "SEPTIEMBRE")]
