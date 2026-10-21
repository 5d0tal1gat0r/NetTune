"""A month folder on the share shows the memoria and nothing else.

The colleague opens a month folder for the document. The originals already
read and the re-scans set aside are kept beside it, in dot folders Samba
hides, like the page images in .revision. And a final memoria that new
sheets have since made out of date stops looking final.
"""

import os

from month_folders import (
    ARCHIVE_DIR_NAME,
    DUPLICATES_DIR_NAME,
    REVISION_DIR_NAME,
    is_in_archive,
    memoria_name,
)


def test_every_folder_inside_a_month_is_hidden():
    for name in (ARCHIVE_DIR_NAME, DUPLICATES_DIR_NAME, REVISION_DIR_NAME):
        assert name.startswith("."), name


def test_the_numbered_names_are_still_never_read_as_scans():
    """A month laid out before the rename still holds output, not scans."""
    for old in ("1_escaneos_originales", "2_duplicados"):
        assert is_in_archive(f"incoming/2026/SEPTIEMBRE/{old}/SKM_1.pdf", "incoming")


def test_the_rename_tool_moves_the_numbered_folders(tmp_path):
    from tools.rename_month_folders import plan

    month = tmp_path / "2026" / "SEPTIEMBRE"
    for old, name in (("1_escaneos_originales", "SKM_0.pdf"), ("2_duplicados", "SKM_D.pdf")):
        (month / old).mkdir(parents=True)
        (month / old / name).write_bytes(b"x")

    _, moves, clashes, emptied = plan(str(tmp_path))
    assert sorted(moves) == sorted([
        (str(month / "1_escaneos_originales" / "SKM_0.pdf"),
         str(month / ARCHIVE_DIR_NAME / "SKM_0.pdf")),
        (str(month / "2_duplicados" / "SKM_D.pdf"),
         str(month / DUPLICATES_DIR_NAME / "SKM_D.pdf")),
    ])
    assert clashes == []
    assert sorted(emptied) == sorted([str(month / "1_escaneos_originales"),
                                      str(month / "2_duplicados")])


class TestStaleFinal:
    """New sheets in a month whose final memoria was already written."""

    def _run(self, app, tmp_path, monkeypatch, rebuild):
        from conftest import a_page

        from entry_store import EntryStore
        from processed_ledger import ProcessedLedger
        from spend_guard import SpendGuard

        monkeypatch.setattr(app, "page_images", lambda path, workdir: [path])
        monkeypatch.setattr(
            app, "read_page_with_consensus",
            lambda image, **kw: a_page(fecha="16-09-2026",
                                       entries=(("Se observa una puerta forzada", False),)),
        )
        monkeypatch.setattr(app, "filter_page", lambda page, **kw: page)
        monkeypatch.setattr(app, "rebuild_memoria", rebuild)

        scan = os.path.join(app.incoming, "SKM_0001.pdf")
        with open(scan, "wb") as handle:
            handle.write(b"scan")
        ledger = ProcessedLedger(str(tmp_path / "state" / "p.sqlite3"))
        guard = SpendGuard(str(tmp_path / "state" / "s.sqlite3"), 5, 1.1)
        with EntryStore(str(tmp_path / "state" / "e.sqlite3")) as store:
            return app.process_scan(scan, ledger, guard, store)

    def _month(self, app):
        return os.path.join(app.incoming, "2026", "SEPTIEMBRE")

    def test_the_final_becomes_the_draft(self, app, tmp_path, monkeypatch):
        final = os.path.join(self._month(app), memoria_name("2026", "SEPTIEMBRE"))
        draft = os.path.join(self._month(app), memoria_name("2026", "SEPTIEMBRE", draft=True))
        with open(final, "wb") as handle:
            handle.write(b"final")
        calls = []

        def rebuild(store, year, month, draft=False):
            calls.append((year, month, draft))
            path = os.path.join(self._month(app), memoria_name(year, month, draft=draft))
            with open(path, "wb") as handle:
                handle.write(b"draft")
            os.remove(final)
            return path

        assert self._run(app, tmp_path, monkeypatch, rebuild) == "processed"
        assert calls == [("2026", "SEPTIEMBRE", True)]
        assert os.path.exists(draft) and not os.path.exists(final)

    def test_no_final_means_no_document_written(self, app, tmp_path, monkeypatch):
        """The document is still the dashboard's to write, as before."""
        calls = []
        self._run(app, tmp_path, monkeypatch, lambda *a, **kw: calls.append(a))
        assert calls == []
        assert not [n for n in os.listdir(self._month(app)) if n.endswith(".docx")]

    def test_a_failed_draft_still_takes_down_the_final(self, app, tmp_path, monkeypatch):
        """Better a draft with the old text than a final that is not."""
        final = os.path.join(self._month(app), memoria_name("2026", "SEPTIEMBRE"))
        draft = os.path.join(self._month(app), memoria_name("2026", "SEPTIEMBRE", draft=True))
        with open(final, "wb") as handle:
            handle.write(b"final")

        def rebuild(*args, **kwargs):
            raise RuntimeError("no template")

        assert self._run(app, tmp_path, monkeypatch, rebuild) == "processed"
        assert not os.path.exists(final)
        assert open(draft, "rb").read() == b"final"
