"""A scanned batch covers contiguous days, so an outlier date is a misread.

Found on a real 25-page July batch: one sheet was read as 16-04-2026 by all
three passes -- unanimous, so not flagged by consensus alone -- and another as
03-07-2027. Comparing each page against the batch catches both for free.
"""

from batch_dates import reconcile_batch


def page(fecha, variants=None, confident=True):
    return {
        "fecha": fecha,
        "fecha_confident": confident,
        "fecha_variants": variants or ([fecha] if fecha else []),
        "trabajos": [],
    }


def july():
    return [page(f"{d:02d}-07-2026") for d in (1, 2, 4, 6, 7, 8, 9, 10, 12)]


def test_a_consistent_batch_is_left_alone():
    pages = july()
    out = reconcile_batch(pages)
    assert all(p["fecha_confident"] for p in out)
    assert [p["fecha"] for p in out] == [p["fecha"] for p in pages]


def test_outlier_month_is_flagged_even_when_every_pass_agreed():
    """The real 16-04-2026 case: unanimous, and wrong."""
    pages = [*july(), page("16-04-2026")]
    out = reconcile_batch(pages)
    assert out[-1]["fecha_confident"] is False
    assert "batch" in " ".join(out[-1]["fecha_variants"]).lower() or out[-1]["fecha_note"]


def test_outlier_year_is_flagged():
    pages = [*july(), page("03-07-2027")]
    out = reconcile_batch(pages)
    assert out[-1]["fecha_confident"] is False


def test_a_variant_matching_the_batch_is_preferred():
    """03-07-2027 with 03-07-2026 among the readings: take the one that fits."""
    pages = [*july(), page("03-07-2027", variants=["03-07-2026", "03-07-2027"])]
    out = reconcile_batch(pages)
    assert out[-1]["fecha"] == "03-07-2026"
    assert out[-1]["fecha_confident"] is False, "corrected, but still worth a look"


def test_an_outlier_takes_the_batch_month_and_keeps_its_own_day():
    """The day is read off the sheet; only the month is repaired.

    Six of the 38 sheets in the September batch came back dated in another
    month with the day correct, and a sheet filed under a month that never
    happened is worse than one filed under the batch's own month. The page
    is still marked for review and its image still saved, so a person sees
    it either way.
    """
    pages = [*july(), page("16-04-2026")]
    out = reconcile_batch(pages)
    assert out[-1]["fecha"] == "16-07-2026"
    assert out[-1]["fecha_confident"] is False


def test_a_day_the_batch_month_has_not_got_is_never_invented():
    pages = [page(f"{d:02d}-02-2026") for d in (1, 2, 4)] + [page("31-07-2026")]
    out = reconcile_batch(pages)
    assert out[-1]["fecha"] == "31-07-2026", "31 February is not a date"
    assert out[-1]["fecha_confident"] is False


def test_a_page_with_no_date_is_untouched():
    pages = [*july(), page(None)]
    out = reconcile_batch(pages)
    assert out[-1]["fecha"] is None


def test_a_single_page_batch_has_nothing_to_compare_against():
    out = reconcile_batch([page("16-04-2026")])
    assert out[0]["fecha"] == "16-04-2026"
    assert out[0]["fecha_confident"] is True


def test_a_batch_spanning_two_months_does_not_flag_everything():
    """End-of-month batches legitimately cross a boundary."""
    pages = [page(f"{d:02d}-06-2026") for d in (28, 29, 30)]
    pages = [*pages, *[page(f"{d:02d}-07-2026") for d in (1, 2, 3)]]
    out = reconcile_batch(pages)
    assert sum(1 for p in out if not p["fecha_confident"]) == 0


def test_already_flagged_pages_stay_flagged():
    pages = [*july(), page("05-07-2026", confident=False)]
    out = reconcile_batch(pages)
    assert out[-1]["fecha_confident"] is False


def test_unparseable_dates_do_not_crash():
    out = reconcile_batch([*july(), page("no es fecha")])
    assert len(out) == 10
