"""The page images a human has to look at, saved beside the month's scans."""

import os

from nettune.main import save_review_image
from nettune.report.month_folders import REVISION_DIR_NAME, revision_dir_for


def make_image(path: str) -> str:
    from PIL import Image
    Image.new("RGB", (40, 40), "white").save(path)
    return path


def test_the_folder_sits_inside_the_month_beside_archive_and_processed():
    assert revision_dir_for("/srv/incoming", "2026", "JUNIO") == os.path.join(
        "/srv/incoming", "2026", "JUNIO", REVISION_DIR_NAME
    )


def test_the_image_is_saved_under_the_name_the_marker_reads(tmp_path):
    source = make_image(str(tmp_path / "page-2.jpg"))
    saved = save_review_image(source, "22-06-2026 p2", str(tmp_path / "out"))
    assert os.path.basename(saved) == "22-06-2026_p2.jpg"
    assert os.path.exists(saved)


def test_the_original_page_is_not_moved(tmp_path):
    source = make_image(str(tmp_path / "page-2.jpg"))
    save_review_image(source, "22-06-2026 p2", str(tmp_path / "out"))
    assert os.path.exists(source)


def test_saving_the_same_page_again_overwrites_rather_than_piling_up(tmp_path):
    source = make_image(str(tmp_path / "page-2.jpg"))
    out = str(tmp_path / "out")
    for _ in range(3):
        save_review_image(source, "22-06-2026 p2", out)
    assert os.listdir(out) == ["22-06-2026_p2.jpg"]


def test_a_page_that_cannot_be_copied_does_not_stop_the_run(tmp_path):
    """The memoria matters more than the review copy."""
    assert save_review_image(
        str(tmp_path / "missing.jpg"), "22-06-2026 p2", str(tmp_path / "out")
    ) == ""


def test_the_month_tree_creates_the_folder(tmp_path):
    from nettune.report.month_folders import ensure_month_tree
    ensure_month_tree(str(tmp_path))
    assert os.path.isdir(revision_dir_for(str(tmp_path), "2026", "JUNIO"))
