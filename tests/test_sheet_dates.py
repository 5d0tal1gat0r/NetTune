"""Sheet names and dates: one naming scheme, misread dates found and fixed."""

import importlib.util
import os

import pytest

from config import config
from dashboard import handle
from entry_store import HAND_SOURCE, EntryStore
from month_folders import revision_dir_for
from review_marks import image_name, legacy_image_name

LAN = "192.168.50.41"
SRC = "SKM_7.pdf"


class TestOneNamingScheme:
    def test_a_dated_sheet(self):
        assert image_name("01-09-2026 p2") == "01-09-2026_p2.jpg"

    def test_an_undated_sheet_takes_the_same_shape(self):
        """It was named after its scan: SKM_C30826092211360_p27.jpg beside
        01-09-2026_p2.jpg in the same folder."""
        assert image_name("SKM_C30826092211360 p27") == "sin-fecha_p27.jpg"
        assert legacy_image_name("SKM_C30826092211360 p27") == "SKM_C30826092211360_p27.jpg"

    def test_nothing_outside_the_folder(self):
        assert "/" not in image_name("../../etc p3")
        assert image_name("") == "pagina.jpg"


def _add(store, pos, ref, text, source=SRC):
    store._connection.execute(
        "INSERT INTO memoria_entries (year, month, block, position, text, source, "
        "flagged, review_ref, added_at, dedupe_key, original_text) "
        "VALUES ('2026','SEPTIEMBRE','B:',?,?,?,0,?,'t',?,?)",
        (pos, text, source, ref, text.lower(), text))
    store._connection.commit()


@pytest.fixture
def batch(tmp_path, monkeypatch):
    """A batch in day order with one misread date: page 3 read as 11-09."""
    monkeypatch.setattr(config, "incoming_dir", str(tmp_path / "incoming"))
    revision = revision_dir_for(config.incoming_dir, "2026", "SEPTIEMBRE")
    os.makedirs(revision, exist_ok=True)
    with EntryStore(str(tmp_path / "d.sqlite3")) as s:
        days = {1: "01", 2: "01", 3: "11", 4: "02", 5: "02", 6: "03", 7: "03"}
        for page, day in days.items():
            ref = f"{day}-09-2026 p{page}"
            s.record_sheet("2026", "SEPTIEMBRE", SRC, page, ref)
            _add(s, page * 10, ref, f"Linea {page}.")
            with open(os.path.join(revision, image_name(ref)), "wb") as f:
                f.write(ref.encode())
        s.record_sheet("2026", "SEPTIEMBRE", SRC, 8, "SKM_7 p8")
        with open(os.path.join(revision, "sin-fecha_p8.jpg"), "wb") as f:
            f.write(b"p8")
        yield s, revision


def _token(store):
    body = handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=store).body.decode()
    start = body.index('name="csrf" value="') + len('name="csrf" value="')
    return body[start:body.index('"', start)]


class TestFindingMisreadDates:
    def test_the_outlier_is_questioned_and_its_neighbours_are_not(self, batch):
        """Comparing with the middle of the neighbours dragged good pages into
        doubt beside a bad one; against the backbone, only the bad one."""
        store, _ = batch
        assert store.date_checks("2026", "SEPTIEMBRE") == {
            "11-09-2026 p3": ["01-09-2026", "02-09-2026"]}

    def test_a_confirmed_date_is_not_questioned_again(self, batch):
        store, _ = batch
        store.redate_sheet("2026", "SEPTIEMBRE", "11-09-2026 p3", "11-09-2026")
        assert store.date_checks("2026", "SEPTIEMBRE") == {}

    def test_lines_added_by_hand_are_not_a_scan_of_their_own(self, tmp_path):
        """Found on the Pi: lines added by hand to sheets of two scans read as
        one scan out of order, so 04-09 p13 was questioned, and confirming it
        could not clear the question."""
        with EntryStore(str(tmp_path / "h.sqlite3")) as s:
            for page, day in {12: "03", 13: "04", 14: "04"}.items():
                s.record_sheet("2026", "SEPTIEMBRE", SRC, page, f"{day}-09-2026 p{page}")
            s.record_sheet("2026", "SEPTIEMBRE", "other.pdf", 9, "18-09-2026 p9")
            _add(s, 10, "18-09-2026 p9", "Anadida en la otra.", source=HAND_SOURCE)
            _add(s, 20, "04-09-2026 p13", "Anadida.", source=HAND_SOURCE)
            assert s.date_checks("2026", "SEPTIEMBRE") == {}

    def test_small_wobbles_are_normal(self, tmp_path):
        with EntryStore(str(tmp_path / "w.sqlite3")) as s:
            for page, day in {1: "12", 2: "13", 3: "12", 4: "12", 5: "13"}.items():
                s.record_sheet("2026", "SEPTIEMBRE", SRC, page, f"{day}-09-2026 p{page}")
            assert s.date_checks("2026", "SEPTIEMBRE") == {}


class TestCorrectingADate:
    def test_every_line_moves_with_the_sheet_including_hand_added_ones(self, batch):
        """Found on the Pi: a line added by hand stayed under the old date."""
        store, _ = batch
        _add(store, 31, "11-09-2026 p3", "Anadida a mano.", source=HAND_SOURCE)
        assert store.redate_sheet("2026", "SEPTIEMBRE", "11-09-2026 p3",
                                  "01-09-2026") == "01-09-2026 p3"
        refs = {e["text"]: e["review_ref"] for e in store.month_entries("2026", "SEPTIEMBRE")}
        assert refs["Linea 3."] == refs["Anadida a mano."] == "01-09-2026 p3"

    @pytest.mark.parametrize("fecha", ["02-10-2026", "31-09-2026", "1-9-2026", "", "hoy"])
    def test_a_date_outside_the_month_or_not_a_date_is_refused(self, batch, fecha):
        store, _ = batch
        assert store.redate_sheet("2026", "SEPTIEMBRE", "11-09-2026 p3", fecha) is None

    def test_an_undated_sheet_can_be_dated(self, batch):
        store, _ = batch
        assert store.redate_sheet("2026", "SEPTIEMBRE", "SKM_7 p8", "04-09-2026") == "04-09-2026 p8"


class TestTheDateRoute:
    def _post(self, store, name, **form):
        return handle("POST", f"/hoja/{name}/fecha", address=LAN, store=store,
                      form={"csrf": _token(store), **form})

    def test_a_correction_renames_the_image_and_keeps_the_turn(self, batch):
        store, revision = batch
        store.record_turn("11-09-2026_p3.jpg", 180)
        response = self._post(store, "11-09-2026_p3.jpg", fecha="01-09-2026",
                              hoja="11-09-2026_p3.jpg")
        assert response.status == 303
        assert response.headers["Location"] == "/mes/2026/SEPTIEMBRE?hoja=01-09-2026_p3.jpg"
        assert os.path.isfile(os.path.join(revision, "01-09-2026_p3.jpg"))
        assert not os.path.exists(os.path.join(revision, "11-09-2026_p3.jpg"))
        assert store.hand_turn("01-09-2026_p3.jpg") == 180

    def test_the_date_input_format_is_accepted(self, batch):
        store, revision = batch
        self._post(store, "sin-fecha_p8.jpg", fecha="2026-09-04")
        assert os.path.isfile(os.path.join(revision, "04-09-2026_p8.jpg"))

    def test_confirming_keeps_the_name(self, batch):
        store, revision = batch
        self._post(store, "11-09-2026_p3.jpg", confirmar="1")
        assert os.path.isfile(os.path.join(revision, "11-09-2026_p3.jpg"))
        assert store.date_checks("2026", "SEPTIEMBRE") == {}

    def test_a_refusal_changes_nothing(self, batch):
        store, revision = batch
        response = self._post(store, "11-09-2026_p3.jpg", fecha="02-10-2026")
        assert response.status == 400
        assert os.path.isfile(os.path.join(revision, "11-09-2026_p3.jpg"))
        assert "11-09-2026 p3" in store.all_pages("2026", "SEPTIEMBRE")

    def test_a_taken_name_is_refused(self, batch):
        store, revision = batch
        with open(os.path.join(revision, "02-09-2026_p3.jpg"), "wb") as f:
            f.write(b"someone else")
        response = self._post(store, "11-09-2026_p3.jpg", fecha="02-09-2026")
        assert response.status == 400
        assert os.path.isfile(os.path.join(revision, "11-09-2026_p3.jpg"))

    def test_the_route_needs_the_token(self, batch):
        store, _ = batch
        response = handle("POST", "/hoja/11-09-2026_p3.jpg/fecha", address=LAN,
                          store=store, form={"fecha": "01-09-2026"})
        assert response.status == 403

    def test_the_page_questions_it_with_the_suggestions(self, batch):
        store, _ = batch
        body = handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=store).body.decode()
        assert "¿Fecha correcta? Se leyó 11-09-2026" in body
        assert "Es el 01-09-2026" in body and "Es el 02-09-2026" in body

    def test_the_sheet_panel_offers_it_for_a_sheet_with_no_lines(self, batch):
        store, _ = batch
        body = handle("GET", "/mes/2026/SEPTIEMBRE?hoja=sin-fecha_p8.jpg", address=LAN,
                      store=store).body.decode()
        panel = body[body.index('<aside class="panel-imagen">'):]
        assert 'action="/hoja/sin-fecha_p8.jpg/fecha"' in panel
        assert "Hoja sin fecha" in panel


class TestRenamingOldFiles:
    @pytest.fixture
    def tool(self):
        spec = importlib.util.spec_from_file_location(
            "rename_revision", os.path.join(os.path.dirname(__file__), "..",
                                            "tools", "rename_revision.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_old_scan_names_are_planned_for_renaming(self, batch, tool):
        store, revision = batch
        os.rename(os.path.join(revision, "sin-fecha_p8.jpg"),
                  os.path.join(revision, "SKM_7_p8.jpg"))
        renames, clashes = tool.plan(store, config.incoming_dir)
        assert clashes == []
        assert [(old, new) for _, old, new in renames] == [("SKM_7_p8.jpg", "sin-fecha_p8.jpg")]

    def test_two_sheets_that_would_share_a_name_stop_everything(self, batch, tool):
        store, _ = batch
        store.record_sheet("2026", "SEPTIEMBRE", "OTRO.pdf", 8, "OTRO p8")
        _, clashes = tool.plan(store, config.incoming_dir)
        assert clashes and clashes[0][2] == "sin-fecha_p8.jpg"
