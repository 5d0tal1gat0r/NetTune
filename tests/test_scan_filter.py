import os

import pytest

from nettune.intake.scan_filter import is_processable_scan, iter_pending_scans


@pytest.fixture
def root(tmp_path):
    for month in ("ENERO", "MARZO"):
        (tmp_path / month / "archive").mkdir(parents=True)
    return str(tmp_path)


def touch(root, *parts):
    p = os.path.join(root, *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:
        fh.write(b"x")
    return p


# --- accepted -------------------------------------------------------------


@pytest.mark.parametrize("name", ["s.jpg", "s.jpeg", "s.png", "s.JPG", "s.tif", "s.tiff", "s.webp", "s.bmp"])
def test_accepts_image_extensions(root, name):
    assert is_processable_scan(touch(root, "MARZO", name), root)


def test_accepts_image_at_incoming_root(root):
    assert is_processable_scan(touch(root, "loose.png"), root)


def test_accepts_name_containing_spaces_and_accents(root):
    assert is_processable_scan(touch(root, "MARZO", "Escaneo 03 marzo.jpg"), root)


# --- rejected: the self-trigger loop --------------------------------------


def test_rejects_generated_docx_report(root):
    """The report written next to the scan must never be re-ingested."""
    name = "20260306_172039_Security_Log_Report.docx"
    assert not is_processable_scan(touch(root, "MARZO", name), root)


def test_rejects_word_lock_file(root):
    assert not is_processable_scan(touch(root, "MARZO", "~$report.docx"), root)


# --- rejected: archive ----------------------------------------------------


def test_rejects_file_already_archived(root):
    assert not is_processable_scan(touch(root, "MARZO", "archive", "s.jpg"), root)


# --- rejected: partial writes and OS noise --------------------------------


@pytest.mark.parametrize(
    "name",
    [".hidden.jpg", "s.jpg.tmp", "s.crdownload", "s.part", "Thumbs.db", ".DS_Store", "s.txt", "s.odt"],
)
def test_rejects_noise_and_unsupported(root, name):
    assert not is_processable_scan(touch(root, "MARZO", name), root)


def test_rejects_directory(root):
    assert not is_processable_scan(os.path.join(root, "MARZO"), root)


def test_rejects_missing_file(root):
    assert not is_processable_scan(os.path.join(root, "MARZO", "ghost.jpg"), root)


def test_rejects_zero_byte_file(root):
    p = os.path.join(root, "MARZO", "empty.jpg")
    open(p, "wb").close()
    assert not is_processable_scan(p, root)


# --- backfill -------------------------------------------------------------


def test_iter_pending_scans_finds_images_in_month_folders(root):
    a = touch(root, "MARZO", "a.jpg")
    b = touch(root, "ENERO", "b.png")
    touch(root, "MARZO", "archive", "old.jpg")
    touch(root, "MARZO", "report.docx")
    assert sorted(iter_pending_scans(root)) == sorted([a, b])


def test_iter_pending_scans_empty_when_nothing_waiting(root):
    assert list(iter_pending_scans(root)) == []


def test_iter_pending_scans_tolerates_missing_root(tmp_path):
    assert list(iter_pending_scans(str(tmp_path / "nope"))) == []


def test_scan_extensions_exclude_generated_reports():
    """The pipeline writes .docx into the watched tree; it must never re-read them."""
    from nettune.intake.scan_filter import SCAN_EXTENSIONS

    assert ".docx" not in SCAN_EXTENSIONS
    assert ".jpg" in SCAN_EXTENSIONS
    assert ".pdf" in SCAN_EXTENSIONS


def test_the_memoria_beside_the_scans_is_never_read(tmp_path):
    root = str(tmp_path)
    memoria = touch(root, "2026", "MARZO", "MEMORIA 2026 MARZO.docx")
    assert not is_processable_scan(memoria, root)


@pytest.mark.parametrize("folder", [".escaneos_originales", ".revision", ".duplicados",
                                    "1_escaneos_originales", "2_duplicados",
                                    "archive", "processed", "revision", "duplicados"])
def test_output_folders_old_and_new_are_never_read(tmp_path, folder):
    root = str(tmp_path)
    assert not is_processable_scan(touch(root, "2026", "MARZO", folder, "s.pdf"), root)
    assert list(iter_pending_scans(root)) == []
