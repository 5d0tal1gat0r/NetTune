"""Lines whose page was never recorded: candidates, choosing, and every
sheet of a scan being known."""

import os

import pytest

from config import config
from dashboard import handle
from entry_store import EntryStore
from month_folders import revision_dir_for
from review_marks import image_name

LAN = "192.168.50.41"
SRC = "SKM_1.pdf"


def _insert(store, pos, ref, text):
    store._connection.execute(
        "INSERT INTO memoria_entries (year, month, block, position, text, source, "
        "flagged, review_ref, added_at, dedupe_key, original_text) "
        "VALUES ('2026','SEPTIEMBRE','B:',?,?,?,0,?,'t',?,?)",
        (pos, text, SRC, ref, text.lower(), text))
    store._connection.commit()


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "incoming_dir", str(tmp_path / "incoming"))
    with EntryStore(str(tmp_path / "u.sqlite3")) as s:
        # Page 2 had a doubtful line, page 3 only confident ones (never
        # recorded by a line), page 4 a doubtful one again.
        _insert(s, 0, "01-09-2026 p2", "Dos.")
        _insert(s, 1, "", "Perdida uno.")
        _insert(s, 2, "", "Perdida dos.")
        _insert(s, 3, "02-09-2026 p4", "Cuatro.")
        for page, ref in ((2, "01-09-2026 p2"), (3, "SKM_1 p3"), (4, "02-09-2026 p4")):
            s.record_sheet("2026", "SEPTIEMBRE", SRC, page, ref)
        revision = revision_dir_for(config.incoming_dir, "2026", "SEPTIEMBRE")
        os.makedirs(revision, exist_ok=True)
        for ref in ("01-09-2026 p2", "SKM_1 p3", "02-09-2026 p4"):
            with open(os.path.join(revision, image_name(ref)), "wb") as f:
                f.write(ref.encode())
        yield s


def _id(store, text):
    return next(e["id"] for e in store.month_entries("2026", "SEPTIEMBRE")
                if e["text"] == text)


def _token(store):
    body = handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=store).body.decode()
    start = body.index('name="csrf" value="') + len('name="csrf" value="')
    return body[start:body.index('"', start)]


class TestCandidates:
    def test_the_pages_either_side_and_between(self, store):
        assert store.candidate_sheets(_id(store, "Perdida uno.")) == [
            "01-09-2026 p2", "SKM_1 p3", "02-09-2026 p4"]

    def test_a_line_with_a_page_has_none(self, store):
        assert store.candidate_sheets(_id(store, "Dos.")) == []

    def test_only_sheets_that_exist_are_offered(self, store):
        store._connection.execute("DELETE FROM scan_sheets WHERE page = 3")
        store._connection.commit()
        assert store.candidate_sheets(_id(store, "Perdida uno.")) == [
            "01-09-2026 p2", "02-09-2026 p4"]

    def test_page_numbers_do_not_cross_scans(self, store):
        """Two scans in a month each have a page 3."""
        store.record_sheet("2026", "SEPTIEMBRE", "OTRO.pdf", 3, "OTRO p3")
        assert "OTRO p3" not in store.candidate_sheets(_id(store, "Perdida uno."))


class TestAssigning:
    def test_a_candidate_is_accepted(self, store):
        linea = _id(store, "Perdida uno.")
        assert store.assign_sheet(linea, "SKM_1 p3")
        assert next(e for e in store.month_entries("2026", "SEPTIEMBRE")
                    if e["id"] == linea)["review_ref"] == "SKM_1 p3"

    def test_anything_else_is_refused(self, store):
        assert not store.assign_sheet(_id(store, "Perdida uno."), "30-09-2026 p99")

    def test_a_line_that_has_a_page_is_never_refiled(self, store):
        assert not store.assign_sheet(_id(store, "Dos."), "SKM_1 p3")

    def test_the_route_files_it_and_returns_to_the_line(self, store):
        linea = _id(store, "Perdida dos.")
        response = handle("POST", f"/entrada/{linea}/hoja", address=LAN, store=store,
                          form={"hoja_elegida": "sin-fecha_p3.jpg", "csrf": _token(store)})
        assert response.status == 303
        assert response.headers["Location"] == (
            f"/mes/2026/SEPTIEMBRE#entrada-{linea}")

    @pytest.mark.parametrize("elegida", [
        "30-09-2026_p99.jpg", "../../etc/passwd", "", "sin-fecha_p3.jpg\r\nX: y"])
    def test_the_route_refuses_what_is_not_a_candidate(self, store, elegida):
        linea = _id(store, "Perdida dos.")
        response = handle("POST", f"/entrada/{linea}/hoja", address=LAN, store=store,
                          form={"hoja_elegida": elegida, "csrf": _token(store)})
        assert response.status == 400
        assert next(e for e in store.month_entries("2026", "SEPTIEMBRE")
                    if e["id"] == linea)["review_ref"] == ""

    def test_the_route_needs_the_token(self, store):
        linea = _id(store, "Perdida dos.")
        response = handle("POST", f"/entrada/{linea}/hoja", address=LAN, store=store,
                          form={"hoja_elegida": "sin-fecha_p3.jpg"})
        assert response.status == 403


class TestThePage:
    def test_the_heading_names_the_candidates(self, store):
        body = handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=store).body.decode()
        assert "Página sin confirmar:" in body
        assert "página 3 (sin fecha)" in body
        assert "página 2 (01-09-2026)" in body
        assert "Hoja sin identificar" not in body

    def test_each_line_can_be_filed(self, store):
        body = handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=store).body.decode()
        for texto in ("Perdida uno.", "Perdida dos."):
            assert f'action="/entrada/{_id(store, texto)}/hoja"' in body
        assert body.count('class="boton-asignar"') == 6

    def test_an_unrecorded_sheet_can_be_opened(self, store):
        """Recorded in scan_sheets, not by any line: still served."""
        response = handle("GET", "/hoja/sin-fecha_p3.jpg", address=LAN, store=store)
        assert response.status == 200
        assert response.body == b"SKM_1 p3"

    def test_the_whole_batch_lists_every_recorded_sheet(self, store):
        assert set(store.all_pages("2026", "SEPTIEMBRE")) == {
            "01-09-2026 p2", "SKM_1 p3", "02-09-2026 p4"}


class TestUndatedSheetsKeepTheirPlace:
    def test_a_line_filed_under_an_undated_page_stays_in_scan_order(self, store):
        store.assign_sheet(_id(store, "Perdida uno."), "SKM_1 p3")
        store.assign_sheet(_id(store, "Perdida dos."), "SKM_1 p3")
        assert store.entries("2026", "SEPTIEMBRE", "B:") == [
            "Dos.", "Perdida uno.", "Perdida dos.", "Cuatro."]


class TestARebuiltSheetOpens:
    def test_it_opens_in_the_panel(self, store):
        """It is recorded by the scan alone, not by any line. The panel used
        to accept only sheets a line pointed at, so it said "no sheet
        selected" for every rebuilt page."""
        body = handle("GET", "/mes/2026/SEPTIEMBRE?hoja=sin-fecha_p3.jpg", address=LAN,
                      store=store).body.decode()
        assert 'src="/hoja/sin-fecha_p3.jpg"' in body
        assert "No hay ninguna hoja seleccionada" not in body


class TestAnUndatedFirstPage:
    def test_filing_the_first_line_under_an_undated_page_keeps_it_first(self, tmp_path):
        """Found by clicking: line 1 of September, filed under page 1 (rebuilt,
        so no date), sorted to the very end of the month."""
        with EntryStore(str(tmp_path / "f.sqlite3")) as s:
            _insert(s, 0, "SKM_1 p1", "Primera.")
            _insert(s, 1, "01-09-2026 p2", "Dos.")
            _insert(s, 2, "15-09-2026 p3", "Tres.")
            assert s.entries("2026", "SEPTIEMBRE", "B:") == ["Primera.", "Dos.", "Tres."]
