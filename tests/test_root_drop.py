"""A scan dropped at the top of the share files itself by its own dates.

The colleague drops a batch wherever is convenient. Asking him to pick the
right year and month folder is the one manual step left in the pipeline, and
the sheets already say which they belong to.
"""

import pytest

from nettune.dates.batch_dates import dominant_month, dominant_year


def page(fecha):
    return {"fecha": fecha}


class TestDominantYear:
    def test_the_year_comes_from_the_sheets(self):
        pages = [page("01-09-2026"), page("02-09-2026"), page("03-09-2026")]
        assert dominant_year(pages) == "2026"

    def test_one_misread_date_does_not_move_the_batch(self):
        """A single stray year loses to the rest of the batch."""
        pages = [page("01-09-2026"), page("02-09-2026"), page("03-04-2019")]
        assert dominant_year(pages) == "2026"

    def test_no_legible_date_means_no_year(self):
        assert dominant_year([page(None), page("")]) == ""

    def test_a_year_outside_the_share_is_refused(self):
        """The share holds 2026 to 2030; anything else is a misreading."""
        assert dominant_year([page("01-09-1999"), page("02-09-1999")]) == ""


class TestTogether:
    def test_a_batch_names_both_its_folders(self):
        pages = [page("15-07-2027"), page("16-07-2027"), page("17-07-2027")]
        assert (dominant_year(pages), dominant_month(pages)) == ("2027", "JULIO")

    @pytest.mark.parametrize("fecha,expected", [
        ("05-01-2026", "ENERO"),
        ("05-12-2030", "DICIEMBRE"),
    ])
    def test_the_month_name_matches_the_folder(self, fecha, expected):
        assert dominant_month([page(fecha)]) == expected


class TestTheWholeWay:
    """process_scan itself, with the reading stubbed: no API, no template."""

    def _run(self, app, tmp_path, monkeypatch, relative, fecha="16-09-2026"):
        import os

        from conftest import a_page

        from nettune.intake.processed_ledger import ProcessedLedger
        from nettune.ops.spend_guard import SpendGuard
        from nettune.report.entry_store import EntryStore

        monkeypatch.setattr(app, "page_images", lambda path, workdir: [path])
        monkeypatch.setattr(
            app, "read_page_with_consensus",
            lambda image, **kw: a_page(fecha=fecha, entries=(("Se abre Z6", True),)),
        )
        monkeypatch.setattr(app, "filter_page", lambda page, **kw: page)
        monkeypatch.setattr(app, "rebuild_memoria", lambda store, y, m: "memoria.docx")

        scan = os.path.join(app.incoming, relative)
        os.makedirs(os.path.dirname(scan), exist_ok=True)
        with open(scan, "wb") as handle:
            handle.write(b"scan")

        ledger = ProcessedLedger(str(tmp_path / "state" / "p.sqlite3"))
        guard = SpendGuard(str(tmp_path / "state" / "s.sqlite3"), 5, 1.1)
        with EntryStore(str(tmp_path / "state" / "e.sqlite3")) as store:
            outcome = app.process_scan(scan, ledger, guard, store)
        return outcome, store

    def test_a_scan_at_the_top_of_the_share_files_itself(
            self, app, tmp_path, monkeypatch):
        """The colleague drops it anywhere; the sheets say where it goes."""
        import os

        outcome, _ = self._run(app, tmp_path, monkeypatch, "SKM_0001.pdf")
        assert outcome == "processed"
        archived = os.path.join(app.incoming, "2026", "SEPTIEMBRE", ".escaneos_originales",
                                "SKM_0001.pdf")
        assert os.path.exists(archived), "filed into the month named by its dates"

    def test_every_sheet_and_every_line_keeps_its_page(
            self, app, tmp_path, monkeypatch):
        """A confident line used to be stored with no page, and a sheet with
        no doubtful line was recorded nowhere: 28 lines and 20 sheets of
        September were lost that way."""
        import os

        from nettune.report.entry_store import EntryStore

        self._run(app, tmp_path, monkeypatch, "SKM_0003.pdf")
        with EntryStore(str(tmp_path / "state" / "e.sqlite3")) as store:
            assert store.source_sheets("2026", "SEPTIEMBRE", "SKM_0003.pdf") == {
                1: "16-09-2026 p1"}
            lines = store.month_entries("2026", "SEPTIEMBRE")
            assert lines and all(e["review_ref"] == "16-09-2026 p1" for e in lines)
            assert all(e["flagged"] == 0 for e in lines), "confident, yet it has a page"
        assert os.path.isfile(os.path.join(
            app.incoming, "2026", "SEPTIEMBRE", ".revision", "16-09-2026_p1.jpg"))

    def test_a_scan_in_a_year_folder_still_files_itself(
            self, app, tmp_path, monkeypatch):
        import os

        self._run(app, tmp_path, monkeypatch, os.path.join("2026", "SKM_0002.pdf"))
        assert os.path.exists(os.path.join(
            app.incoming, "2026", "SEPTIEMBRE", ".escaneos_originales", "SKM_0002.pdf"))

    def test_a_scan_with_no_legible_date_anywhere_is_not_guessed_at(
            self, app, tmp_path, monkeypatch):
        import pytest as _pytest

        from nettune.reading.transcription_service import TranscriptionError

        with _pytest.raises(TranscriptionError, match="no date on it could be read"):
            self._run(app, tmp_path, monkeypatch, "SKM_0003.pdf", fecha=None)
