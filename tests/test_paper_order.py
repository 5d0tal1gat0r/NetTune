"""A maintenance page keeps the order it was written in across subheadings."""

from nettune.main import number_lines, split_by_block
from nettune.report.memoria_blocks import ELECTRICIDAD, OTROS, PARKING


def lines(*pairs):
    return [{"text": t, "bloque": b} for t, b in pairs]


def test_lines_are_numbered_in_page_order():
    page = number_lines(lines(("a", PARKING), ("b", OTROS)))
    assert [x["orden"] for x in page] == [0, 1]


def test_the_split_keeps_each_line_its_place_on_the_paper():
    page = number_lines(lines(("luz", ELECTRICIDAD), ("cargador", PARKING),
                              ("foco", ELECTRICIDAD)))
    split = split_by_block(page)
    assert [(x["text"], x["orden"]) for x in split[ELECTRICIDAD]] == [("luz", 0), ("foco", 2)]
    assert [(x["text"], x["orden"]) for x in split[PARKING]] == [("cargador", 1)]


def test_a_line_without_bloque_goes_to_otros():
    split = split_by_block(number_lines([{"text": "x"}]))
    assert list(split) == [OTROS]


def test_empty_blocks_are_left_out():
    split = split_by_block(number_lines(lines(("a", PARKING))))
    assert list(split) == [PARKING]
