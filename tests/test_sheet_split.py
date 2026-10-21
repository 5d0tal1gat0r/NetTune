"""Each scanned page holds two daily sheets; they must be read separately.

Found by looking at the images: a landscape scan is two sheets side by side,
a portrait scan is two stacked, and in the portrait case each is rotated 90
degrees the opposite way, so no single rotation is right for the page. The
system had been reading each page as one sheet, which is why entries merged
across shifts and why one of the two dates on a page went missing.
"""

import numpy as np
import pytest

from sheet_split import find_gutter, split_sheets


def sheet(width, height, ink_rows):
    """A white page with dark bands standing in for writing."""
    page = np.full((height, width), 250, dtype=np.uint8)
    for top, bottom, left, right in ink_rows:
        page[top:bottom, left:right] = 30
    return page


class TestFindGutter:
    def test_two_sheets_side_by_side_split_down_the_middle(self):
        page = sheet(1000, 600, [(100, 500, 50, 440), (100, 500, 560, 950)])
        position, axis = find_gutter(page)
        assert axis == "vertical"
        assert 440 < position < 560

    def test_two_sheets_stacked_split_across(self):
        page = sheet(600, 1000, [(50, 440, 100, 500), (560, 950, 100, 500)])
        position, axis = find_gutter(page)
        assert axis == "horizontal"
        assert 440 < position < 560

    def test_a_sheet_thinning_out_towards_the_gutter_keeps_its_edge(self):
        """Agosto 2026 p76: the ends of the longest lines sit in a wide band of
        faint ink beside a narrow gutter of bare paper. The middle of the faint
        band is inside the sheet; the cut must go through the bare paper."""
        page = sheet(600, 1000, [
            (50, 400, 100, 500),   # first sheet
            (440, 640, 100, 115),  # second sheet: only the ends of its lines
            (640, 950, 100, 500),  # second sheet: the rest
        ])
        position, axis = find_gutter(page)
        assert axis == "horizontal"
        assert 400 < position < 440

    def test_a_single_sheet_is_not_split(self):
        """Ink all the way across the middle: there is no gutter."""
        page = sheet(1000, 600, [(100, 500, 50, 950)])
        assert find_gutter(page) == (0, "")


class TestSplitSheets:
    def _write(self, tmp_path, array, name="page.jpg"):
        import cv2
        path = str(tmp_path / name)
        cv2.imwrite(path, array)
        return path

    def test_a_two_up_page_becomes_two_files(self, tmp_path):
        page = sheet(1000, 600, [(100, 500, 50, 440), (100, 500, 560, 950)])
        parts = split_sheets(self._write(tmp_path, page), str(tmp_path / "out"))
        assert len(parts) == 2
        assert all(p.endswith(".jpg") for p in parts)

    def test_the_halves_are_in_reading_order(self, tmp_path):
        """Left before right, top before bottom: the shifts run in order."""
        import cv2
        page = sheet(1000, 600, [(100, 500, 50, 200), (100, 500, 800, 950)])
        parts = split_sheets(self._write(tmp_path, page), str(tmp_path / "out"))
        first = cv2.imread(parts[0], cv2.IMREAD_GRAYSCALE)
        assert first[:, :300].min() < 100, "the left sheet came first"

    def test_a_single_sheet_passes_through_untouched(self, tmp_path):
        page = sheet(1000, 600, [(100, 500, 50, 950)])
        path = self._write(tmp_path, page)
        assert split_sheets(path, str(tmp_path / "out")) == [path]

    def test_an_unreadable_file_is_left_alone(self, tmp_path):
        path = str(tmp_path / "broken.jpg")
        with open(path, "w") as handle:
            handle.write("not an image")
        assert split_sheets(path, str(tmp_path / "out")) == [path]


@pytest.mark.parametrize("width,height", [(1000, 600), (600, 1000)])
def test_the_two_halves_together_cover_the_page(tmp_path, width, height):
    import cv2
    if width > height:
        page = sheet(width, height, [(100, 500, 50, 440), (100, 500, 560, 950)])
    else:
        page = sheet(width, height, [(50, 440, 100, 500), (560, 950, 100, 500)])
    parts = split_sheets(str(tmp_path / "p.jpg") if cv2.imwrite(
        str(tmp_path / "p.jpg"), page) else "", str(tmp_path / "out"))
    total = sum(cv2.imread(p, cv2.IMREAD_GRAYSCALE).size for p in parts)
    assert total > 0.9 * width * height, "nothing important was thrown away"
