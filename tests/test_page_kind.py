"""Which form a scanned page is, told from its printed header, for free.

Three forms arrive in the same share: the vigilantes' security sheets, two
to a page; the maintenance crew's daily sheet, one to a page; and the
parking-ticket log, which is not read at all but set aside in Parking/.
"""

import os

import pytest

from nettune.pages import page_kind
from nettune.pages.page_kind import MANTENIMIENTO, PARKING, SEGURIDAD, kind_from_text

# What tesseract made of the real forms' printed text, September 2026.
PARKING_HEADER = (
    "2 HORAS GRATIS POR COMPRAS IGUALES O SUPERIORES A 20€ "
    "TODA LA NOCHE 4 € ... CAJA DE PARKING FECHA TICKET COMPRA COMERCIO "
    "Nº TICKET COMPRA IMPORTE TICKETS"
)
MANTENIMIENTO_HEADER = (
    "CENTRO COMERCIAL NETTUNE FICHA DIARIA DE TRABAJO DE MANTENIMIENTO "
    "CENTRO COMERCIAL NETTUNE FECHA HORA ENTRADA DESCRIPCION DE LOS TRABAJOS"
)


class TestKindFromText:
    def test_the_parking_log(self):
        assert kind_from_text(PARKING_HEADER) == PARKING

    def test_the_maintenance_sheet(self):
        assert kind_from_text(MANTENIMIENTO_HEADER) == MANTENIMIENTO

    def test_anything_else_is_a_security_sheet_as_before(self):
        assert kind_from_text("") == SEGURIDAD
        assert kind_from_text("INFORME DIARIO Servicio Direccion") == SEGURIDAD

    def test_one_word_is_not_enough(self):
        """A vigilante writing 'parking' in an entry is not a ticket log."""
        assert kind_from_text("Se revisa el parking P-2") == SEGURIDAD
        assert kind_from_text("mantenimiento avisado") == SEGURIDAD

    @pytest.mark.parametrize("read", [
        # Tesseract on four real sheets of September's maintenance batch.
        "entr o comercial fiicha diaria de trabajo de mantenimiento centro",
        "nettune ficha diaria de trabajo.de mantenimiento centro comercial",
        "nettune ficha diaria de trabajo de mantenim!ento centro comercial",
        "centro comercial 2:nettune ficha daria de trabajo de mantenimiento",
    ])
    def test_the_header_misread_is_still_the_maintenance_sheet(self, read):
        assert kind_from_text(read) == MANTENIMIENTO

    def test_the_security_header_is_not_mistaken_for_it(self):
        """'Informe diario' is one letter from 'diaria'."""
        assert kind_from_text("INFORME DIARIO Fecha Servicio mantenimiento") == SEGURIDAD

    def test_case_and_accents_do_not_matter(self):
        assert kind_from_text("ficha diaria de trabajo de mantenimiento") == MANTENIMIENTO
        assert kind_from_text("Comercio  Importe tickets") == PARKING


class TestClassify:
    def test_without_tesseract_every_page_is_read_as_before(self, monkeypatch, tmp_path):
        monkeypatch.setattr(page_kind, "tesseract_available", lambda: False)
        assert page_kind.classify(str(tmp_path / "p.jpg")) == SEGURIDAD

    def test_a_sideways_page_is_turned_until_its_header_reads(self, monkeypatch, tmp_path):
        from PIL import Image

        path = str(tmp_path / "p.jpg")
        Image.new("L", (200, 300), 255).save(path)
        passes = []

        def ocr(image):
            passes.append(image)
            # Upright finds nothing; the first turn finds the ticket log.
            return PARKING_HEADER if len(passes) == 2 else ""

        monkeypatch.setattr(page_kind, "tesseract_available", lambda: True)
        monkeypatch.setattr(page_kind, "_ocr", ocr)
        assert page_kind.classify(path) == PARKING
        assert len(passes) == 2

    def test_a_page_nothing_recognises_is_tried_all_four_ways(self, monkeypatch, tmp_path):
        from PIL import Image

        path = str(tmp_path / "p.jpg")
        Image.new("L", (200, 300), 255).save(path)
        passes = []
        monkeypatch.setattr(page_kind, "tesseract_available", lambda: True)
        monkeypatch.setattr(page_kind, "_ocr", lambda image: passes.append(1) or "")
        assert page_kind.classify(path) == SEGURIDAD
        assert len(passes) == 4

    def test_an_upright_maintenance_sheet_needs_one_pass(self, monkeypatch, tmp_path):
        from PIL import Image

        path = str(tmp_path / "p.jpg")
        Image.new("L", (200, 300), 255).save(path)
        calls = []
        monkeypatch.setattr(page_kind, "tesseract_available", lambda: True)
        monkeypatch.setattr(page_kind, "_ocr",
                            lambda image: calls.append(1) or MANTENIMIENTO_HEADER)
        assert page_kind.classify(path) == MANTENIMIENTO
        assert len(calls) == 1


@pytest.mark.skipif(not page_kind.tesseract_available(), reason="needs tesseract")
def test_rendered_text_is_really_read(tmp_path):
    """The whole way through tesseract, on printed text drawn sideways."""
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 40)
    except OSError:
        pytest.skip("no TrueType font to draw with")
    page = Image.new("L", (1400, 1000), 255)
    draw = ImageDraw.Draw(page)
    for row, text in enumerate(("CAJA DE PARKING", "COMERCIO", "IMPORTE TICKETS")):
        draw.text((80, 120 + row * 120), text, fill=0, font=font)
    path = os.path.join(tmp_path, "p.png")
    page.rotate(90, expand=True).save(path)
    assert page_kind.classify(path) == PARKING
