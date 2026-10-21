"""The measuring harness itself, checked against cases with a known answer."""

import sys

sys.path.insert(0, "tools")

from accuracy import pair_up, similarity


class TestPairing:
    def test_identical_entries_pair_at_one(self):
        pairs, missed, extra = pair_up(["Se abre el muelle."], ["Se abre el muelle."])
        assert len(pairs) == 1 and pairs[0][2] == 1.0
        assert not missed and not extra

    def test_a_misread_word_still_pairs(self):
        pairs, missed, _ = pair_up(
            ["Se llama la atención a dos personas."],
            ["Se llama la atención a das personas."],
        )
        assert len(pairs) == 1 and pairs[0][2] > 0.9
        assert not missed

    def test_an_entry_with_no_counterpart_is_missed(self):
        pairs, missed, extra = pair_up(
            ["Schindler repara el ascensor de zona 4."],
            ["Se colocan pilonas en zona 10."],
        )
        assert not pairs and missed and extra

    def test_each_produced_entry_is_used_once(self):
        """Two similar hand-written entries must not both claim one output."""
        pairs, missed, _ = pair_up(
            ["Se abre el muelle.", "Se abre el muelle de carga."],
            ["Se abre el muelle."],
        )
        assert len(pairs) == 1
        assert len(missed) == 1

    def test_nothing_produced_means_everything_missed(self):
        pairs, missed, extra = pair_up(["Uno.", "Dos."], [])
        assert not pairs and len(missed) == 2 and not extra


class TestSimilarity:
    def test_accents_and_case_do_not_count_as_errors(self):
        assert similarity("Atención en Zona 4", "atencion en zona 4") == 1.0

    def test_a_different_zone_lowers_the_score(self):
        assert similarity("pilonas Z4", "pilonas Z3") < 1.0
