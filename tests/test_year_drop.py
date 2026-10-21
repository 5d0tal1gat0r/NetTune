"""A scan dropped straight into the year folder is filed by its own dates."""

import pytest

from nettune.dates.batch_dates import dominant_month


def page(fecha):
    return {"fecha": fecha, "fecha_confident": True, "fecha_variants": [fecha], "trabajos": []}


def test_month_comes_from_the_sheets():
    assert dominant_month([page("02-07-2026"), page("04-07-2026")]) == "JULIO"


def test_the_majority_month_wins_for_a_batch_crossing_a_boundary():
    pages = [page(f"{d:02d}-06-2026") for d in (28, 29, 30)] + [page("01-07-2026")]
    assert dominant_month(pages) == "JUNIO"


@pytest.mark.parametrize("fecha,expected", [
    ("15-01-2026", "ENERO"), ("15-09-2026", "SEPTIEMBRE"), ("15-12-2026", "DICIEMBRE"),
])
def test_every_month_maps_to_its_folder(fecha, expected):
    assert dominant_month([page(fecha)]) == expected


def test_no_legible_date_gives_nothing():
    assert dominant_month([page(None), page("no es fecha")]) == ""


def test_an_outlier_does_not_decide_the_month():
    pages = [page(f"{d:02d}-09-2026") for d in (1, 2, 3)] + [page("16-04-2026")]
    assert dominant_month(pages) == "SEPTIEMBRE"
