import pytest

from nettune.intake.scanner_monitor import (
    NETWORK_FILESYSTEMS,
    choose_observer_kind,
    filesystem_type,
)

MOUNTS = """\
/dev/nvme0n1p2 / ext4 rw,relatime 0 0
tmpfs /run tmpfs rw,nosuid 0 0
//100.64.0.10/scans /srv/incoming_scans cifs rw,relatime,vers=3.1.1 0 0
nas:/export/reports /srv/reports nfs4 rw,relatime 0 0
"""


@pytest.fixture
def mounts(tmp_path):
    p = tmp_path / "mounts"
    p.write_text(MOUNTS)
    return str(p)


def test_detects_cifs_mount(mounts):
    assert filesystem_type("/srv/incoming_scans", mounts_file=mounts) == "cifs"


def test_detects_fs_for_path_inside_mount(mounts):
    assert filesystem_type("/srv/incoming_scans/MARZO", mounts_file=mounts) == "cifs"


def test_detects_nfs_mount(mounts):
    assert filesystem_type("/srv/reports", mounts_file=mounts) == "nfs4"


def test_local_path_reports_local_fs(mounts):
    assert filesystem_type("/home/user/scans", mounts_file=mounts) == "ext4"


def test_longest_prefix_wins_not_first_match(mounts):
    """/srv/incoming_scans must not be attributed to / just because / matches."""
    assert filesystem_type("/srv/incoming_scans", mounts_file=mounts) != "ext4"


def test_prefix_match_respects_path_boundary(mounts):
    # /srv/reports-backup is NOT inside the /srv/reports mount.
    assert filesystem_type("/srv/reports-backup", mounts_file=mounts) == "ext4"


def test_missing_mounts_file_is_tolerated(tmp_path):
    assert filesystem_type("/anything", mounts_file=str(tmp_path / "nope")) == ""


# --- observer selection ---------------------------------------------------


def test_auto_picks_polling_on_network_mount(mounts):
    assert choose_observer_kind("auto", "/srv/incoming_scans", mounts_file=mounts) == "polling"


def test_auto_picks_inotify_on_local_disk(mounts):
    assert choose_observer_kind("auto", "/home/user/scans", mounts_file=mounts) == "inotify"


def test_explicit_polling_overrides_local_disk(mounts):
    assert choose_observer_kind("polling", "/home/user/scans", mounts_file=mounts) == "polling"


def test_explicit_inotify_overrides_network_mount(mounts):
    assert choose_observer_kind("inotify", "/srv/incoming_scans", mounts_file=mounts) == "inotify"


def test_mode_is_case_insensitive(mounts):
    assert choose_observer_kind("POLLING", "/home/user/scans", mounts_file=mounts) == "polling"


def test_unknown_mode_falls_back_to_auto_behaviour(mounts):
    assert choose_observer_kind("banana", "/srv/incoming_scans", mounts_file=mounts) == "polling"


def test_cifs_and_nfs_are_known_network_filesystems():
    assert {"cifs", "nfs", "nfs4", "smb3"} <= NETWORK_FILESYSTEMS
