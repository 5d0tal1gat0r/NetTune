"""Three defects the 42 page September batch exposed."""

import pytest

from nettune.report.entry_store import EntryStore
from nettune.report.routine_rules import expand_codes, invalid_plantas, is_incoherent


class TestPlAsPlanta:
    """The batch wrote "zona 6 PL. 8", another way of saying planta."""

    @pytest.mark.parametrize("raw,expected", [
        ("Charcos en zona 6 PL. 8.", "Charcos en zona 6 planta 8."),
        ("Trabajos en techo de zona común de P.L. 0.",
         "Trabajos en techo de zona común de planta 0."),
        ("Se revisa PL 1.", "Se revisa planta 1."),
    ])
    def test_pl_is_written_as_planta(self, raw, expected):
        assert expand_codes(raw) == expected

    def test_an_impossible_floor_survives_the_expansion_and_is_caught(self):
        """planta 8 does not exist; the entry must reach a human."""
        expanded = expand_codes("Charcos en zona 6 PL. 8.")
        assert invalid_plantas(expanded) == ["8"]
        assert is_incoherent(expanded)


class TestDedupe:
    """The batch produced the same line twice, differing by a full stop."""

    def test_the_same_entry_with_and_without_a_full_stop_is_one_entry(self, tmp_path):
        with EntryStore(str(tmp_path / "e.sqlite3")) as store:
            store.add("2026", "SEPTIEMBRE", "Parking",
                      [{"text": "Se coloca cartel de salida de zona 4."}], "a.pdf")
            store.add("2026", "SEPTIEMBRE", "Parking",
                      [{"text": "Se coloca cartel de salida de zona 4"}], "b.pdf")
            assert store.entries("2026", "SEPTIEMBRE", "Parking") == [
                "Se coloca cartel de salida de zona 4."
            ]

    def test_case_and_spacing_do_not_make_a_second_entry(self, tmp_path):
        with EntryStore(str(tmp_path / "e.sqlite3")) as store:
            store.add("2026", "SEPTIEMBRE", "Parking",
                      [{"text": "Se abre el muelle."}], "a.pdf")
            store.add("2026", "SEPTIEMBRE", "Parking",
                      [{"text": "se  abre el muelle"}], "b.pdf")
            assert len(store.entries("2026", "SEPTIEMBRE", "Parking")) == 1

    def test_two_genuinely_different_entries_both_survive(self, tmp_path):
        with EntryStore(str(tmp_path / "e.sqlite3")) as store:
            store.add("2026", "SEPTIEMBRE", "Parking",
                      [{"text": "Se abre el muelle."},
                       {"text": "Se cierra el muelle."}], "a.pdf")
            assert len(store.entries("2026", "SEPTIEMBRE", "Parking")) == 2


class TestSlashedZeroFloor:
    """The batch wrote the floor as a slashed zero: "2-4 plø"."""

    @pytest.mark.parametrize("raw,expected", [
        ("Se marcha por 2-4 plø.", "Se marcha por 2-4 planta 0."),
        ("Los trabajadores del c-40, plø, no tienen permiso.",
         "Los trabajadores del c-40, planta 0, no tienen permiso."),
    ])
    def test_the_slashed_zero_is_nought(self, raw, expected):
        assert expand_codes(raw) == expected


class TestTenantNames:
    """Shop names come from the directory table in the template."""

    def test_the_batch_misreads_are_settled_against_the_directory(self):
        import os

        import pytest as _pytest

        from nettune.config import config
        from nettune.report.locales import correct_names
        if not os.path.exists(config.template_path):
            _pytest.skip("template absent")
        assert correct_names(
            'Apertura de torreón zona 4, a "MAC VEST" (gerencia).',
            config.template_path,
        ) == 'Apertura de torreón zona 4, a "Mae Vest" (gerencia).'
        assert correct_names(
            "Parkline estaciona sin autorización.", config.template_path
        ) == "Park Line estaciona sin autorización."


def test_a_store_that_already_holds_duplicates_migrates(tmp_path):
    """The Pi's database predates the key and may hold the duplicates it
    exists to prevent; the migration must not fail on them."""
    import sqlite3

    path = str(tmp_path / "old.sqlite3")
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE memoria_entries ("
        "year TEXT NOT NULL, month TEXT NOT NULL, block TEXT NOT NULL, "
        "position INTEGER NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL, "
        "flagged INTEGER NOT NULL DEFAULT 0, added_at TEXT NOT NULL, "
        "PRIMARY KEY (year, month, block, text))"
    )
    for position, body in enumerate(("Se abre el muelle.", "Se abre el muelle",
                                     "Se cierra el muelle.")):
        old.execute("INSERT INTO memoria_entries VALUES (?,?,?,?,?,?,?,?)",
                    ("2026", "SEPTIEMBRE", "Parking", position, body, "s.pdf", 0, "t"))
    old.commit()
    old.close()

    with EntryStore(path) as store:
        entries = store.entries("2026", "SEPTIEMBRE", "Parking")
    assert entries == ["Se abre el muelle.", "Se cierra el muelle."]
