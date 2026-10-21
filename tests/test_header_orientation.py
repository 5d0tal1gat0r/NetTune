"""Which way up a sheet is, from its printed header rather than OSD."""

import importlib.util
import os
import shutil

import pytest
from PIL import Image, ImageDraw, ImageFont

from entry_store import EntryStore
from page_rotation import header_orientation, straighten

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None,
                                     reason="tesseract not installed")


def _form(path, upside_down=False):
    """A daily report: printed header on top, ruled lines for the writing."""
    font = ImageFont.load_default(size=48)
    image = Image.new("L", (1200, 1700), 255)
    draw = ImageDraw.Draw(image)
    draw.text((80, 60), "INFORME DIARIO", font=font, fill=0)
    draw.text((80, 160), "Fecha: 01-09-2026", font=font, fill=0)
    draw.text((80, 250), "Servicio: C.C. NETTUNE", font=font, fill=0)
    for y in range(500, 1600, 60):
        draw.line((80, y, 1100, y), fill=0, width=2)
    (image.rotate(180) if upside_down else image).save(path)
    return str(path)


@needs_tesseract
class TestTheHeader:
    def test_upright(self, tmp_path):
        assert header_orientation(_form(tmp_path / "a.png")) == "upright"

    def test_upside_down(self, tmp_path):
        assert header_orientation(_form(tmp_path / "b.png", upside_down=True)) == "upside_down"

    def test_no_header_decides_nothing(self, tmp_path):
        """A maintenance form or a blank page: left to OSD, as before."""
        Image.new("L", (1200, 1700), 255).save(tmp_path / "c.png")
        assert header_orientation(str(tmp_path / "c.png")) is None

    def test_straighten_turns_an_upside_down_form(self, tmp_path):
        path = _form(tmp_path / "d.png", upside_down=True)
        straighten(path, only_upside_down=True)
        assert header_orientation(path) == "upright"

    def test_straighten_leaves_an_upright_form_alone(self, tmp_path):
        import pathlib
        path = _form(tmp_path / "e.png")
        before = pathlib.Path(path).read_bytes()
        straighten(path, only_upside_down=True)
        assert pathlib.Path(path).read_bytes() == before


@needs_tesseract
class TestFixingAMonth:
    @pytest.fixture
    def tool(self):
        spec = importlib.util.spec_from_file_location(
            "fix_upside_down", os.path.join(os.path.dirname(__file__), "..",
                                            "tools", "fix_upside_down.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_upside_down_sheets_are_found_and_hand_turned_ones_are_left(self, tmp_path, tool):
        _form(tmp_path / "01-09-2026_p1.jpg")
        _form(tmp_path / "01-09-2026_p2.jpg", upside_down=True)
        _form(tmp_path / "01-09-2026_p3.jpg", upside_down=True)
        with EntryStore(str(tmp_path / "s.sqlite3")) as store:
            store.record_turn("01-09-2026_p3.jpg", 90)
            turn, kept = tool.upside_down(str(tmp_path), store.hand_turned())
        assert turn == ["01-09-2026_p2.jpg"]
        assert kept == ["01-09-2026_p3.jpg"]
