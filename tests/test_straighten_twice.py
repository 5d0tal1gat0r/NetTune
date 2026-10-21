"""Straightening repeats until the page is upright.

Six of the 42 review images from the September batch were upside down. OSD
can only see the 180 degrees once the 90 has been taken out, so a single
pass leaves a page that was doubly rotated still on its head.
"""

from nettune.pages import page_rotation


def test_it_keeps_going_while_a_rotation_is_reported(monkeypatch, tmp_path):
    from PIL import Image

    path = str(tmp_path / "page.jpg")
    Image.new("RGB", (60, 40), "white").save(path)

    reported = iter([270, 180, 0])
    turned = []
    monkeypatch.setattr(page_rotation, "detect_rotation", lambda p: next(reported, 0))
    # The OSD loop is what is under test: the printed-header check, which
    # runs first and would open the image once more, finds no header here.
    monkeypatch.setattr(page_rotation, "header_orientation", lambda p: None)
    real_open = Image.open

    def spy(p):
        turned.append(p)
        return real_open(p)

    monkeypatch.setattr(Image, "open", spy)
    page_rotation.straighten(path)
    assert len(turned) == 2, "rotated twice, then stopped when OSD said upright"


def test_an_upright_page_is_never_touched(monkeypatch, tmp_path):
    from PIL import Image

    path = str(tmp_path / "page.jpg")
    Image.new("RGB", (60, 40), "white").save(path)
    with open(path, "rb") as handle:
        before = handle.read()

    monkeypatch.setattr(page_rotation, "detect_rotation", lambda p: 0)
    page_rotation.straighten(path)
    with open(path, "rb") as handle:
        assert handle.read() == before


def test_it_gives_up_rather_than_spinning_forever(monkeypatch, tmp_path):
    """A page OSD always calls rotated must not loop."""
    from PIL import Image

    path = str(tmp_path / "page.jpg")
    Image.new("RGB", (60, 40), "white").save(path)
    calls = []
    monkeypatch.setattr(page_rotation, "detect_rotation",
                        lambda p: calls.append(p) or 90)
    page_rotation.straighten(path)
    assert len(calls) <= page_rotation.MAX_PASSES
