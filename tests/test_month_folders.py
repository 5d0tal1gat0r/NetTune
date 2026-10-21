import os

from month_folders import (
    MONTH_FOLDERS,
    archive_dir_for,
    get_month_folder,
    is_in_archive,
)


def test_all_twelve_spanish_months_present():
    assert len(MONTH_FOLDERS) == 12
    assert "ENERO" in MONTH_FOLDERS
    assert "DICIEMBRE" in MONTH_FOLDERS


def test_get_month_folder_finds_month_in_nested_path():
    assert get_month_folder(os.path.join("incoming_scans", "MARZO", "s.jpg")) == "MARZO"


def test_get_month_folder_finds_month_in_archive_path():
    p = os.path.join("incoming_scans", "AGOSTO", "archive", "s.jpg")
    assert get_month_folder(p) == "AGOSTO"


def test_get_month_folder_returns_empty_when_no_month():
    assert get_month_folder(os.path.join("incoming_scans", "s.jpg")) == ""


def test_get_month_folder_ignores_lowercase_lookalike():
    assert get_month_folder(os.path.join("incoming_scans", "marzo", "s.jpg")) == ""


def test_is_in_archive_detects_archive_component_only():
    assert is_in_archive(os.path.join("incoming_scans", "MAYO", "archive", "s.jpg"))
    assert not is_in_archive(os.path.join("incoming_scans", "MAYO", "s.jpg"))


def test_is_in_archive_does_not_match_substring_in_filename():
    # A file merely *named* like an archive must still be processed.
    assert not is_in_archive(os.path.join("incoming_scans", "MAYO", "archive_2024.jpg"))


def test_archive_dir_for_month():
    assert archive_dir_for("incoming_scans", "JULIO") == os.path.join(
        "incoming_scans", "JULIO", ".escaneos_originales"
    )


def test_archive_dir_for_no_month_falls_back_to_root_archive():
    assert archive_dir_for("incoming_scans", "") == os.path.join(
        "incoming_scans", ".escaneos_originales"
    )
