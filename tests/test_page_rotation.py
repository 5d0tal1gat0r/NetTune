import shutil

import pytest
from PIL import Image

from nettune.pages import page_rotation
from nettune.pages.page_rotation import detect_rotation, straighten, to_portrait

needs_tesseract = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="tesseract absent"
)

REAL_SECURITY = "/home/al1gat0r/.claude/jobs/39b771a6/tmp/seg/hi-1.jpg"
REAL_MAINTENANCE = "/home/al1gat0r/.claude/jobs/39b771a6/tmp/seg/mant-1.jpg"


def test_missing_file_reports_no_rotation(tmp_path):
    assert detect_rotation(str(tmp_path / "nope.jpg")) == 0


def test_a_blank_image_is_not_rotated(tmp_path):
    p = tmp_path / "blank.png"
    Image.new("RGB", (400, 600), "white").save(p)
    assert detect_rotation(str(p)) == 0


@needs_tesseract
@pytest.mark.skipif(not shutil.os.path.exists(REAL_MAINTENANCE), reason="fixture absent")
def test_an_upright_scan_is_left_alone():
    assert detect_rotation(REAL_MAINTENANCE) == 0


@needs_tesseract
@pytest.mark.skipif(not shutil.os.path.exists(REAL_SECURITY), reason="fixture absent")
def test_the_sideways_security_scan_is_detected():
    """Real scan: the model invented entries until this was corrected."""
    assert detect_rotation(REAL_SECURITY) == 90


@needs_tesseract
@pytest.mark.skipif(not shutil.os.path.exists(REAL_SECURITY), reason="fixture absent")
def test_straighten_swaps_the_dimensions(tmp_path):
    work = tmp_path / "page.jpg"
    shutil.copy(REAL_SECURITY, work)
    with Image.open(work) as before:
        w, h = before.size
    straighten(str(work))
    with Image.open(work) as after:
        assert after.size == (h, w)


def test_straighten_returns_the_path_unchanged_when_upright(tmp_path):
    p = tmp_path / "blank.png"
    Image.new("RGB", (400, 600), "white").save(p)
    assert straighten(str(p)) == str(p)


class TestToPortrait:
    def test_a_landscape_image_becomes_portrait(self, tmp_path, monkeypatch):
        # No tesseract needed: OSD unavailable defaults to a consistent
        # quarter-turn, which is all this test cares about.
        monkeypatch.setattr(page_rotation, "detect_rotation", lambda _p: 0)
        p = tmp_path / "landscape.png"
        Image.new("RGB", (600, 400), "white").save(p)
        to_portrait(str(p))
        with Image.open(p) as image:
            width, height = image.size
        assert width < height

    def test_an_already_portrait_image_is_untouched(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(
            page_rotation, "detect_rotation",
            lambda _p: calls.append(_p) or 0,
        )
        p = tmp_path / "portrait.png"
        Image.new("RGB", (400, 600), "white").save(p)
        with open(p, "rb") as handle:
            before = handle.read()
        to_portrait(str(p))
        with open(p, "rb") as handle:
            after = handle.read()
        assert before == after
        assert calls == [], "aspect ratio alone should decide; OSD not needed"

    def test_osd_confidence_does_not_block_the_quarter_turn(self, tmp_path, monkeypatch):
        # to_portrait trusts OSD's direction at any confidence -- MIN_CONFIDENCE
        # only ever gates straighten()'s own retry loop.
        monkeypatch.setattr(page_rotation, "detect_rotation", lambda _p: 270)
        p = tmp_path / "landscape.png"
        Image.new("RGB", (600, 400), "white").save(p)
        to_portrait(str(p))
        with Image.open(p) as image:
            width, height = image.size
        assert width < height

    def test_it_does_not_loop_forever_when_osd_keeps_calling_it_rotated(
        self, tmp_path, monkeypatch
    ):
        # A blank/unreadable page can make OSD report a rotation every single
        # pass; straighten()'s MAX_PASSES cap must still end the process.
        monkeypatch.setattr(page_rotation, "detect_rotation", lambda _p: 90)
        p = tmp_path / "stubborn.png"
        Image.new("RGB", (400, 600), "white").save(p)
        straighten(str(p))  # must return, not hang

    def test_a_sheet_it_turned_portrait_is_not_turned_back_by_straighten(
        self, tmp_path, monkeypatch
    ):
        # Regression: to_portrait turns a sheet upright on aspect-ratio
        # certainty, then OSD reads a (wrong) 270 on the result. The caller
        # that already knows this is a split sheet passes only_upside_down,
        # so straighten() must not act on that 270 -- a 90/270 reported
        # about an already-portrait sheet can only be OSD's guess overriding
        # a certainty, which is backwards.
        monkeypatch.setattr(page_rotation, "detect_rotation", lambda _p: 0)
        p = tmp_path / "landscape.png"
        Image.new("RGB", (600, 400), "white").save(p)
        to_portrait(str(p))
        with Image.open(p) as image:
            assert image.size[0] < image.size[1]  # now portrait

        monkeypatch.setattr(page_rotation, "detect_rotation", lambda _p: 270)
        straighten(str(p), only_upside_down=True)
        with Image.open(p) as image:
            width, height = image.size
        assert width < height, "straighten() put a known-portrait sheet back sideways"


class TestStraightenNeverGoesLandscape:
    def test_a_portrait_image_never_comes_out_landscape(self, tmp_path, monkeypatch):
        # Whatever OSD claims, a caller that tells straighten() the page is
        # portrait by construction gets only a 180 degree correction back --
        # never a quarter turn that would put it back on its side.
        monkeypatch.setattr(page_rotation, "detect_rotation", lambda _p: 90)
        p = tmp_path / "portrait.png"
        Image.new("RGB", (400, 600), "white").save(p)
        straighten(str(p), only_upside_down=True)
        with Image.open(p) as image:
            width, height = image.size
        assert width < height
