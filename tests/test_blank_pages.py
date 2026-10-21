"""A page that produced no entry must be named, not skipped in silence."""

from nettune.main import blank_page_report


def test_nothing_is_said_when_every_page_produced_entries():
    assert blank_page_report([], 4, "SKM_0001.pdf") is None


def test_the_lost_pages_are_named_with_the_batch_size():
    report = blank_page_report([3, 24], 29, "SKM_0001.pdf")
    assert "page(s) 3, 24 of 29" in report
    assert "SKM_0001.pdf" in report
    assert "check them by hand" in report


def test_a_single_lost_page_reads_naturally():
    assert "page(s) 2 of 4" in blank_page_report([2], 4, "SKM_0001.pdf")
