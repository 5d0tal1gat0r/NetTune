"""What counts as the readings disagreeing, measured on the September batch.

Two passes flagged 323 of 809 entries. Looking at the pairs, most differences
were real -- "ROTURA MUELLE" against "Apertura muelle" -- but two kinds were
noise: a different clock time on the same sentence, and a different article.
Neither reaches the document, so neither is a disagreement about it.
"""

from consensus import comparable


class TestClockTime:
    def test_the_same_line_at_a_different_time_is_the_same_line(self):
        assert comparable("23:10 Se cierran pilonas Z4, Z3") == comparable(
            "22:40 Se cierran pilonas Z4, Z3"
        )

    def test_a_time_written_with_a_dot_counts_too(self):
        assert comparable("21.45h Se abre el muelle") == comparable(
            "07:00 Se abre el muelle"
        )


class TestArticles:
    def test_de_and_del_are_the_same_line(self):
        assert comparable("16:00 Apertura de muelle") == comparable(
            "16:00 Apertura del muelle"
        )

    def test_gender_and_number_of_an_article_do_not_matter(self):
        assert comparable("Se van los cámaras") == comparable("Se van las cámaras")


class TestRealDifferencesSurvive:
    def test_a_different_zone_is_a_real_disagreement(self):
        assert comparable("Se cierran pilonas Z4, Z3") != comparable(
            "Se cierran pilonas Z4, Z2"
        )

    def test_a_different_verb_is_a_real_disagreement(self):
        assert comparable("07:00 Comienzo servicio") != comparable(
            "15:00 Finalizo servicio"
        )

    def test_a_different_noun_is_a_real_disagreement(self):
        assert comparable("ROTURA MUELLE") != comparable("Apertura muelle")

    def test_one_letter_in_a_word_still_counts(self):
        assert comparable("por firma cortes de luz") != comparable(
            "por fibra cortes de luz"
        )

    def test_a_repeated_word_is_a_real_disagreement(self):
        assert comparable("Se abre torreones") != comparable(
            "Se abre torreones y torreones"
        )


class TestTheReadingsAreComparedThatWay:
    """comparable() was added on 2026-09-22 but consolidate() kept comparing
    with normalize(), so the noise it names went on flagging lines."""

    def _consolidated(self, first, second):
        from consensus import consolidate
        return consolidate([{"fecha": "01-09-2026", "trabajos": first},
                            {"fecha": "01-09-2026", "trabajos": second}])["trabajos"]

    def test_a_different_time_or_article_is_agreement(self):
        lines = self._consolidated(["16:00 Apertura de muelle", "Se van los cámaras"],
                                   ["16:05 Apertura del muelle", "Se van las cámaras"])
        assert [line["confident"] for line in lines] == [True, True]
        assert all(line["variants"] == [] for line in lines)

    def test_a_different_fact_is_still_disagreement(self):
        lines = self._consolidated(["Se cierran pilonas Z4, Z3", "Rotura muelle"],
                                   ["Se cierran pilonas Z4, Z5", "Apertura muelle"])
        assert [line["confident"] for line in lines] == [False, False]
