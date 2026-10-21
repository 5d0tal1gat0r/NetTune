"""incoming_scans/<YEAR>/<MES>/ with archive and processed inside each month."""

import os

import pytest

from nettune.report.month_folders import (
    MONTH_FOLDERS,
    archive_dir_for,
    ensure_month_tree,
    get_month_folder,
    get_year_folder,
    is_year,
    memoria_name,
    processed_dir_for,
    years_to_lay_out,
)


class TestWhatCountsAsAYear:
    """Supersedes a fixed tuple, 2026-2030, which made a scan filed under
    2031 -- or old paper logs under 2025 -- silently yearless."""

    @pytest.mark.parametrize("year", ["2000", "2025", "2026", "2027"])
    def test_real_years_are_years(self, year):
        assert is_year(year)

    def test_next_year_is_a_year(self):
        from datetime import datetime
        assert is_year(str(datetime.now().year + 1))

    @pytest.mark.parametrize("value", [
        "1999",   # before any of this existed
        "2062",   # a handwritten 2026 misread: still rejected
        "26", "20266", "abcd", "", "MARZO", "2026a",
    ])
    def test_anything_else_is_not(self, value):
        assert not is_year(value)

    def test_there_is_no_expiry_date(self):
        """The rule moves with the clock; nothing to edit in 2031."""
        from datetime import datetime
        assert is_year(str(datetime.now().year))

    def test_a_scan_filed_under_an_older_year_keeps_it(self):
        assert get_year_folder("incoming_scans/2025/MARZO/s.pdf", "incoming_scans") == "2025"


def test_tree_has_this_year_and_next(tmp_path):
    from datetime import datetime
    ensure_month_tree(str(tmp_path))
    this_year = datetime.now().year
    assert years_to_lay_out() == (str(this_year), str(this_year + 1))
    for year in years_to_lay_out():
        for month in MONTH_FOLDERS:
            assert os.path.isdir(tmp_path / year / month), f"{year}/{month}"
    # Not sixty empty folders for years nobody has reached.
    assert not os.path.exists(tmp_path / str(this_year + 4))


def test_each_month_has_numbered_originals_and_hidden_revision(tmp_path):
    ensure_month_tree(str(tmp_path))
    # Whatever this year is, not 2026: the tree follows the clock.
    month = tmp_path / years_to_lay_out()[0] / "JUNIO"
    assert sorted(os.listdir(month)) == [".escaneos_originales", ".revision"]


def test_year_read_from_the_path():
    assert get_year_folder("incoming_scans/2027/MARZO/s.pdf", "incoming_scans") == "2027"


def test_month_read_from_the_path():
    assert get_month_folder("incoming_scans/2027/MARZO/s.pdf", "incoming_scans") == "MARZO"


def test_a_year_above_the_root_is_ignored():
    root = "/srv/2029/incoming_scans"
    assert get_year_folder(f"{root}/2027/MARZO/s.pdf", root) == "2027"


def test_missing_year_returns_empty():
    assert get_year_folder("incoming_scans/MARZO/s.pdf", "incoming_scans") == ""


def test_archive_dir_is_inside_the_month(tmp_path):
    got = archive_dir_for(str(tmp_path), "2026", "JUNIO")
    assert got == os.path.join(str(tmp_path), "2026", "JUNIO", ".escaneos_originales")


def test_the_memoria_is_written_in_the_month_folder_itself(tmp_path):
    got = processed_dir_for(str(tmp_path), "2026", "JUNIO")
    assert got == os.path.join(str(tmp_path), "2026", "JUNIO")


def test_the_draft_says_so_in_its_name():
    assert memoria_name("2026", "JUNIO", draft=True) == \
        "MEMORIA 2026 JUNIO (BORRADOR).docx"


def test_memoria_is_named_for_its_year_and_month():
    assert memoria_name("2026", "JUNIO") == "MEMORIA 2026 JUNIO.docx"


@pytest.mark.parametrize("year,month", [("2030", "DICIEMBRE"), ("2026", "ENERO")])
def test_memoria_name_matches_the_hand_written_convention(year, month):
    assert memoria_name(year, month) == f"MEMORIA {year} {month}.docx"


def test_ensure_tree_is_idempotent(tmp_path):
    ensure_month_tree(str(tmp_path))
    ensure_month_tree(str(tmp_path))
    assert os.path.isdir(tmp_path / "2026" / "JUNIO" / ".escaneos_originales")
