"""Consensus across independent reads of the same page.

Handwriting cannot be read perfectly, so the goal is not a perfect answer but
an honest one: lines every read agrees on are trusted, lines they differ on are
flagged for a human. Proven necessary by a real page where the word "aire" was
read as "cobre" by most passes.
"""

import pytest

from consensus import consolidate, normalize


def read(fecha="02-07-2026", operarios=("A. Ejemplo",), trabajos=()):
    return {"fecha": fecha, "operarios": list(operarios), "trabajos": list(trabajos)}


# --- normalisation --------------------------------------------------------


@pytest.mark.parametrize(
    "a,b",
    [
        ("Revisando cuadros eléctricos", "revisando cuadros electricos"),
        ("Conectando mg de aire.", "Conectando mg de aire"),
        ("  Conectando   mg  de aire ", "Conectando mg de aire"),
        ("* Conectando mg de aire", "Conectando mg de aire"),
    ],
)
def test_cosmetic_differences_are_not_disagreements(a, b):
    assert normalize(a) == normalize(b)


def test_different_words_are_disagreements():
    assert normalize("mg de aire") != normalize("mg de cobre")


# --- the date -------------------------------------------------------------


def test_unanimous_date_is_confident():
    out = consolidate([read(), read(), read()])
    assert out["fecha"] == "02-07-2026"
    assert out["fecha_confident"] is True


def test_majority_date_wins_but_is_flagged():
    out = consolidate([read(), read(), read(fecha="12-07-2016")])
    assert out["fecha"] == "02-07-2026"
    assert out["fecha_confident"] is False
    assert "12-07-2016" in out["fecha_variants"]


# --- entries --------------------------------------------------------------


def test_entries_all_reads_agree_are_confident():
    e = ["Revisando cuadros eléctricos", "Conectando mg de aire"]
    out = consolidate([read(trabajos=e), read(trabajos=e), read(trabajos=e)])
    assert [t["text"] for t in out["trabajos"]] == e
    assert all(t["confident"] for t in out["trabajos"])


def test_the_aire_cobre_case_is_flagged():
    """The real failure: most passes said 'cobre', one said 'aire'."""
    out = consolidate([
        read(trabajos=["Conectando mg de cobre"]),
        read(trabajos=["Conectando mg de cobre"]),
        read(trabajos=["Conectando mg de aire"]),
    ])
    entry = out["trabajos"][0]
    assert entry["confident"] is False
    assert len(entry["variants"]) == 2
    assert any("aire" in v for v in entry["variants"])
    assert any("cobre" in v for v in entry["variants"])


def test_flagged_entry_keeps_the_majority_as_primary_text():
    out = consolidate([
        read(trabajos=["Conectando mg de cobre"]),
        read(trabajos=["Conectando mg de cobre"]),
        read(trabajos=["Conectando mg de aire"]),
    ])
    assert "cobre" in out["trabajos"][0]["text"]


def test_a_read_that_misses_an_entry_flags_it_rather_than_dropping_it():
    """Cropped passes lost the 4th entry; it must survive, marked uncertain."""
    full = ["uno", "dos", "tres", "cuatro"]
    out = consolidate([read(trabajos=full), read(trabajos=full), read(trabajos=["uno", "dos", "tres"])])
    assert len(out["trabajos"]) == 4
    assert out["trabajos"][3]["confident"] is False


def test_entry_count_comes_from_the_majority_of_reads():
    out = consolidate([
        read(trabajos=["uno", "dos"]),
        read(trabajos=["uno", "dos"]),
        read(trabajos=["uno", "dos", "espurio"]),
    ])
    assert len(out["trabajos"]) == 2


def test_near_identical_wording_is_matched_not_duplicated():
    out = consolidate([
        read(trabajos=["Revisando cuadros eléctricos"]),
        read(trabajos=["Revisando cuadro eléctricos"]),
        read(trabajos=["Revisando cuadros electricos"]),
    ])
    assert len(out["trabajos"]) == 1


def test_single_read_is_never_marked_confident():
    """One pass cannot corroborate anything."""
    out = consolidate([read(trabajos=["Conectando mg de aire"])])
    assert out["trabajos"][0]["confident"] is False
    assert out["fecha_confident"] is False


def test_empty_reads_do_not_crash():
    out = consolidate([])
    assert out["trabajos"] == []
    assert out["fecha"] is None


def test_reads_that_all_failed_produce_nothing_confident():
    out = consolidate([read(fecha=None, trabajos=[]), read(fecha=None, trabajos=[])])
    assert out["trabajos"] == []


def test_operarios_consensus():
    out = consolidate([read(), read(), read(operarios=["B. Ejemplo"])])
    assert out["operarios"] == ["A. Ejemplo"]
    assert out["operarios_confident"] is False


# --- keeping invented lines out -------------------------------------------


def test_a_line_only_one_reading_saw_is_dropped():
    """An invented line is worse in this document than a missing one."""
    out = consolidate([
        read(trabajos=["uno", "dos"]),
        read(trabajos=["uno", "dos", "inventada por una sola lectura"]),
    ], min_seen=2)
    assert [t["text"] for t in out["trabajos"]] == ["uno", "dos"]


def test_a_line_both_readings_saw_is_kept():
    out = consolidate([read(trabajos=["uno"]), read(trabajos=["uno"])], min_seen=2)
    assert [t["text"] for t in out["trabajos"]] == ["uno"]


def test_min_seen_one_keeps_a_line_only_one_reading_saw():
    """Two of three readings saw three lines, so three is the canonical count;
    the third line was seen by only one of them."""
    out = consolidate([
        read(trabajos=["uno", "dos", "solo en una"]),
        read(trabajos=["uno", "dos", "tambien aqui"]),
        read(trabajos=["uno", "dos"]),
    ], min_seen=1)
    assert len(out["trabajos"]) == 3


def test_min_seen_two_drops_that_uncorroborated_line():
    out = consolidate([
        read(trabajos=["uno", "dos", "solo en una"]),
        read(trabajos=["uno", "dos", "distinta del todo"]),
        read(trabajos=["uno", "dos"]),
    ], min_seen=2)
    assert [t["text"] for t in out["trabajos"]] == ["uno", "dos"]


def test_corroboration_tolerates_slightly_different_wording():
    """Both saw the line; they just read one word differently."""
    out = consolidate([
        read(trabajos=["Se abren torreones Z2"]),
        read(trabajos=["Se abren torreones Z3"]),
    ], min_seen=2)
    assert len(out["trabajos"]) == 1
    assert out["trabajos"][0]["confident"] is False
