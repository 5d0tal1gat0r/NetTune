"""deploy/stale_files.sh: what a deploy removes from the Pi, and what it only lists."""

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "stale_files.sh"


def _touch(root: Path, *paths: str) -> None:
    for path in paths:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")


def _run(release: Path, app: Path) -> list[str]:
    out = subprocess.run(["bash", str(SCRIPT), str(release), str(app)],
                         check=True, capture_output=True, text=True).stdout
    return out.splitlines()


def _pi_like(tmp_path: Path) -> tuple[Path, Path]:
    release, app = tmp_path / "release", tmp_path / "app"
    _touch(release, "main.py", "tools/reread_scan.py", "prompts/filter_mantenimiento.md",
           "tests/test_x.py", "deploy/deploy.sh")
    _touch(app, "main.py", "tools/reread_scan.py", "prompts/filter_mantenimiento.md",
           "deploy/deploy.sh",
           # Gone from the repo: the deploy must remove them.
           "jev_shadow.py", "tools/separate_scan_pages.py", "prompts/old_prompt.md",
           "tests/conftest.py", "promptfoo/config.yaml",
           # Runtime data and secrets: never removed, whatever the release holds.
           ".env", "state/memoria_entries.sqlite3", "venv/lib/site.py",
           "logs/run.log", "templates/MEMORIA.docx", "__pycache__/main.cpython-313.pyc",
           "DEPLOYED", "incoming_scans/scan.pdf",
           # Hand-made backups: listed for a person, never removed.
           "main.py.bak", "main.py~", ".env.bak", "prompts/filter_seguridad.md.bak",
           "state.bak-2026-09-22/memoria_entries.sqlite3", "state.bak-2026-09-22/old.py")
    return release, app


def test_removes_code_the_release_dropped_and_the_dev_folders(tmp_path):
    lines = _run(*_pi_like(tmp_path))
    removed = sorted(line.split(" ", 1)[1] for line in lines if line.startswith("remove "))
    assert removed == sorted([
        "jev_shadow.py", "tools/separate_scan_pages.py", "prompts/old_prompt.md",
        "tests", "promptfoo",
    ])


def test_never_removes_data_secrets_or_backups(tmp_path):
    lines = _run(*_pi_like(tmp_path))
    removed = [line.split(" ", 1)[1] for line in lines if line.startswith("remove ")]
    for path in removed:
        assert not path.startswith(("state", "venv", "logs", "templates", ".env",
                                    "incoming_scans", "__pycache__", "DEPLOYED")), path
        assert not path.endswith((".bak", "~")), path


def test_lists_hand_made_backups_for_a_person(tmp_path):
    lines = _run(*_pi_like(tmp_path))
    leftover = sorted(line.split(" ", 1)[1] for line in lines if line.startswith("leftover "))
    assert leftover == sorted([
        "main.py.bak", "main.py~", ".env.bak", "prompts/filter_seguridad.md.bak",
        "state.bak-2026-09-22",
    ])


def test_a_clean_pi_has_nothing_to_say(tmp_path):
    release, app = tmp_path / "release", tmp_path / "app"
    _touch(release, "main.py", "prompts/a.md", "tests/test_x.py")
    _touch(app, "main.py", "prompts/a.md", ".env", "state/x.sqlite3")
    assert _run(release, app) == []


def test_a_relative_release_path_works(tmp_path):
    """deploy.sh calls it as `stale_files.sh app /opt/...` from the upload folder."""
    release, app = _pi_like(tmp_path)
    out = subprocess.run(["bash", str(SCRIPT), "release", str(app)], cwd=tmp_path,
                         check=True, capture_output=True, text=True).stdout
    assert out.splitlines() == _run(release, app)


def test_refuses_a_folder_that_is_not_a_release(tmp_path):
    """Compared against an empty folder, every module would look dropped."""
    _, app = _pi_like(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    done = subprocess.run(["bash", str(SCRIPT), str(empty), str(app)],
                          capture_output=True, text=True)
    assert done.returncode != 0
    assert done.stdout == ""
