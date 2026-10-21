import os
import shutil

import pytest

from pdf_pages import PdfRenderError, is_pdf, page_count, render_pages

REAL_PDF = "/home/al1gat0r/Downloads/SKM_C30826081908350.pdf"
needs_pdf = pytest.mark.skipif(not os.path.exists(REAL_PDF), reason="sample PDF absent")
needs_poppler = pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="poppler absent")


def test_is_pdf_by_extension(tmp_path):
    p = tmp_path / "a.PDF"
    p.write_bytes(b"%PDF-1.4")
    assert is_pdf(str(p))


def test_non_pdf_is_not_pdf(tmp_path):
    p = tmp_path / "a.jpg"
    p.write_bytes(b"\xff\xd8")
    assert not is_pdf(str(p))


@needs_pdf
@needs_poppler
def test_counts_pages_of_a_real_scan():
    assert page_count(REAL_PDF) == 4


@needs_pdf
@needs_poppler
def test_renders_every_page(tmp_path):
    pages = render_pages(REAL_PDF, str(tmp_path), dpi=100)
    assert len(pages) == 4
    assert all(os.path.exists(p) for p in pages)


@needs_pdf
@needs_poppler
def test_pages_come_back_in_order(tmp_path):
    pages = render_pages(REAL_PDF, str(tmp_path), dpi=100)
    assert pages == sorted(pages)


@needs_pdf
@needs_poppler
def test_higher_dpi_gives_a_bigger_image(tmp_path):
    lo = render_pages(REAL_PDF, str(tmp_path / "lo"), dpi=80)[0]
    hi = render_pages(REAL_PDF, str(tmp_path / "hi"), dpi=200)[0]
    assert os.path.getsize(hi) > os.path.getsize(lo)


def test_a_corrupt_pdf_raises_rather_than_returning_nothing(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not really a pdf")
    with pytest.raises(PdfRenderError):
        render_pages(str(bad), str(tmp_path / "out"), dpi=100)
