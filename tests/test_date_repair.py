"""Repairing a date the reader put in the wrong month.

Six of the 38 sheets in the September batch came back dated in April, July,
October or January. In every one the day was right and the month was wrong:
"03-04-2026" on a sheet sitting between two dated 02-09 and 03-09. The batch
is one scanning session of consecutive days, so the month it belongs to is
known even when a page's own reading of it is not.
"""

import pytest

from batch_dates import reconcile_batch


def page(fecha, variants=()):
    return {"fecha": fecha, "fecha_confident": True,
            "fecha_variants": list(variants) or [fecha], "trabajos": []}


def september(days):
    return [page(f"{d:02d}-09-2026") for d in days]


class TestMonthRepair:
    @pytest.mark.parametrize("misread,expected", [
        ("03-04-2026", "03-09-2026"),
        ("07-10-2026", "07-09-2026"),
        ("08-01-2026", "08-09-2026"),
        ("17-01-2026", "17-09-2026"),
    ])
    def test_the_day_is_kept_and_the_month_comes_from_the_batch(
            self, misread, expected):
        pages = [*september([1, 2, 4, 5, 6]), page(misread)]
        assert reconcile_batch(pages)[-1]["fecha"] == expected

    def test_the_repaired_page_is_still_marked_for_review(self):
        pages = [*september([1, 2, 4, 5, 6]), page("03-04-2026")]
        repaired = reconcile_batch(pages)[-1]
        assert repaired["fecha_confident"] is False
        assert "corregida" in repaired["fecha_note"]

    def test_a_reading_of_the_page_itself_is_preferred_over_the_batch(self):
        """Its own passes are better evidence than the batch's shape."""
        pages = [*september([1, 2, 4, 5, 6]),
                 page("03-04-2026", variants=["03-04-2026", "09-09-2026"])]
        assert reconcile_batch(pages)[-1]["fecha"] == "09-09-2026"

    def test_a_day_that_does_not_exist_in_the_batch_month_is_not_invented(self):
        """31 February is not a date; the page is flagged and left alone."""
        pages = [*[page(f"{d:02d}-02-2026") for d in (1, 2, 4, 5, 6)],
                 page("31-07-2026")]
        repaired = reconcile_batch(pages)[-1]
        assert repaired["fecha"] == "31-07-2026"
        assert repaired["fecha_confident"] is False


class TestUnchangedBehaviour:
    def test_a_page_that_fits_the_batch_is_left_alone(self):
        pages = september([1, 2, 3, 4, 5])
        out = reconcile_batch(pages)
        assert [p["fecha"] for p in out] == [p["fecha"] for p in pages]
        assert all(p["fecha_confident"] for p in out)

    def test_too_few_dated_pages_to_judge_anything(self):
        pages = [page("03-04-2026"), page("05-09-2026")]
        assert reconcile_batch(pages)[0]["fecha"] == "03-04-2026"
