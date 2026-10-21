"""The P340 copies the review images and nothing else from the share."""

import os
import shutil
import subprocess

import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "deploy", "pull_revision.sh")


def _share(tmp_path):
    src = tmp_path / "share"
    month = src / "2026" / "SEPTIEMBRE"
    (month / ".revision").mkdir(parents=True)
    (month / ".revision" / "16-09-2026_p1.jpg").write_bytes(b"jpg")
    (month / ".escaneos_originales").mkdir()
    (month / ".escaneos_originales" / "scan.pdf").write_bytes(b"pdf")
    (month / "MEMORIA 2026 SEPTIEMBRE.docx").write_bytes(b"docx")
    (src / "Parking").mkdir()
    (src / "Parking" / "tickets.pdf").write_bytes(b"pdf")
    (src / "Parking" / "2026" / ".revision").mkdir(parents=True)
    (src / "Parking" / "2026" / ".revision" / "should_not_copy.jpg").write_bytes(b"no")
    return src


def _pull(src, dest, **env):
    subprocess.run(["bash", SCRIPT, str(dest)], check=True,
                   env={**os.environ, "NETTUNE_SRC": f"{src}/", **env})
    return sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())


@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not installed")
def test_only_revision_images_come_across(tmp_path):
    src = _share(tmp_path)
    dest = tmp_path / "dest"
    (dest / "2026" / "AGOSTO" / ".revision").mkdir(parents=True)
    (dest / "2026" / "AGOSTO" / ".revision" / "old.jpg").write_bytes(b"old")

    assert _pull(src, dest) == ["2026/AGOSTO/.revision/old.jpg",
                                "2026/SEPTIEMBRE/.revision/16-09-2026_p1.jpg"]


@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not installed")
def test_original_scans_come_across_on_their_own(tmp_path):
    src = _share(tmp_path)

    files = _pull(src, tmp_path / "originals", NETTUNE_FOLDER=".escaneos_originales")

    assert files == ["2026/SEPTIEMBRE/.escaneos_originales/scan.pdf"]
