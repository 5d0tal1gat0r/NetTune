"""Every sheet has its place, even one the reading found nothing on."""

import os

import pytest

from nettune.config import config
from nettune.report.entry_store import EntryStore
from nettune.report.memoria import SEGURIDAD_BLOCK
from nettune.report.month_folders import revision_dir_for
from nettune.report.review_marks import image_name
from nettune.review.dashboard import handle

LAN = "192.168.50.41"
SRC = "SKM_V.pdf"


@pytest.fixture
def month(tmp_path, monkeypatch):
    """Pages 63, 64 and 65 of a scan; nothing was read off 64."""
    monkeypatch.setattr(config, "incoming_dir", str(tmp_path / "incoming"))
    revision = revision_dir_for(config.incoming_dir, "2026", "SEPTIEMBRE")
    os.makedirs(revision, exist_ok=True)
    with EntryStore(str(tmp_path / "v.sqlite3")) as store:
        for page in (63, 64, 65):
            ref = f"16-09-2026 p{page}"
            store.record_sheet("2026", "SEPTIEMBRE", SRC, page, ref)
            with open(os.path.join(revision, image_name(ref)), "wb") as f:
                f.write(ref.encode())
            if page != 64:
                store._connection.execute(
                    "INSERT INTO memoria_entries (year, month, block, position, text, source, "
                    "flagged, review_ref, added_at, dedupe_key, original_text) "
                    "VALUES ('2026','SEPTIEMBRE',?,?,?,?,0,?,'t',?,?)",
                    (SEGURIDAD_BLOCK, page, f"Linea {page}.", SRC, ref, f"linea {page}",
                     f"Linea {page}."))
        store._connection.commit()
        yield store


def _page(store):
    return handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=store).body.decode()


def _token(body):
    start = body.index('name="csrf" value="') + len('name="csrf" value="')
    return body[start:body.index('"', start)]


class TestNoGaps:
    def test_the_empty_sheet_sits_between_its_neighbours(self, month):
        body = _page(month)
        assert body.index("16-09-2026 · página 63") < body.index("16-09-2026 · página 64") \
            < body.index("16-09-2026 · página 65")

    def test_it_says_nothing_was_read_and_offers_a_line(self, month):
        body = _page(month)
        assert "La lectura no encontró ninguna línea en esta hoja" in body
        assert 'action="/hoja/16-09-2026_p64.jpg/linea"' in body

    def test_it_carries_an_anchor_and_a_date_control(self, month):
        body = _page(month)
        assert 'id="hoja-16-09-2026_p64.jpg"' in body
        assert 'action="/hoja/16-09-2026_p64.jpg/fecha"' in body


class TestAddingToAnEmptySheet:
    def _post(self, store, name, **form):
        return handle("POST", f"/hoja/{name}/linea", address=LAN, store=store,
                      form={"csrf": _token(_page(store)), **form})

    def test_the_line_lands_on_that_sheet_in_order(self, month):
        response = self._post(month, "16-09-2026_p64.jpg", texto="Linea escrita a mano.")
        assert response.status == 303
        assert month.entries("2026", "SEPTIEMBRE", SEGURIDAD_BLOCK) == [
            "Linea 63.", "Linea escrita a mano.", "Linea 65."]
        added = next(e for e in month.month_entries("2026", "SEPTIEMBRE")
                     if e["text"] == "Linea escrita a mano.")
        assert added["review_ref"] == "16-09-2026 p64"
        assert response.headers["Location"].endswith(f"#entrada-{added['id']}")

    def test_after_that_it_is_a_sheet_like_any_other(self, month):
        self._post(month, "16-09-2026_p64.jpg", texto="Linea escrita a mano.")
        assert "La lectura no encontró ninguna línea" not in _page(month)

    def test_an_empty_line_is_refused(self, month):
        assert self._post(month, "16-09-2026_p64.jpg", texto="  ").status == 400

    def test_an_unknown_sheet_is_not_found(self, month):
        assert self._post(month, "30-09-2026_p99.jpg", texto="x").status == 404

    def test_it_needs_the_token(self, month):
        response = handle("POST", "/hoja/16-09-2026_p64.jpg/linea", address=LAN,
                          store=month, form={"texto": "x"})
        assert response.status == 403


class TestTheProcessorKeepsBlankSheets:
    def test_a_blank_sheet_is_recorded_with_its_image(self, app, tmp_path, monkeypatch):
        """It used to be skipped: no image, no record, so it could not be
        opened and nothing could be added to it."""
        from conftest import a_page

        from nettune.intake.processed_ledger import ProcessedLedger
        from nettune.ops.spend_guard import SpendGuard

        images = []
        for n in (1, 2):
            path = tmp_path / f"sheet{n}.jpg"
            path.write_bytes(b"x")
            images.append(str(path))
        readings = iter([a_page(fecha="16-09-2026", entries=(("Se abre Z6", True),)),
                         a_page(fecha="16-09-2026", entries=())])
        monkeypatch.setattr(app, "page_images", lambda path, workdir: images)
        monkeypatch.setattr(app, "read_page_with_consensus", lambda image, **kw: next(readings))
        monkeypatch.setattr(app, "filter_page", lambda page, **kw: page)
        monkeypatch.setattr(app, "rebuild_memoria", lambda store, y, m: "memoria.docx")
        scan = os.path.join(app.incoming, "2026", "SEPTIEMBRE", "SKM_B.pdf")
        os.makedirs(os.path.dirname(scan), exist_ok=True)
        with open(scan, "wb") as handle_:
            handle_.write(b"scan")
        with EntryStore(str(tmp_path / "e.sqlite3")) as store:
            app.process_scan(scan, ProcessedLedger(str(tmp_path / "p.sqlite3")),
                             SpendGuard(str(tmp_path / "s.sqlite3"), 5, 1.1), store)
            assert set(store.source_sheets("2026", "SEPTIEMBRE", "SKM_B.pdf")) == {1, 2}
        revision = os.path.join(app.incoming, "2026", "SEPTIEMBRE", ".revision")
        assert os.path.isfile(os.path.join(revision, "16-09-2026_p2.jpg"))


class TestEmptySheetsAreToBeChecked:
    def test_they_are_in_por_revisar(self, month):
        """The reading finding nothing does not mean nothing is written."""
        assert "16-09-2026 p64" in month.to_check("2026", "SEPTIEMBRE")
        body = handle("GET", "/mes/2026/SEPTIEMBRE?hojas=pendientes", address=LAN,
                      store=month).body.decode()
        assert 'data-hoja="16-09-2026_p64.jpg"' in body
        assert "Por revisar (1)" in body

    def test_the_memoria_list_is_unchanged(self, month):
        """review_pages feeds the .docx; an empty sheet has nothing to print."""
        assert "16-09-2026 p64" not in month.review_pages("2026", "SEPTIEMBRE")

    def test_the_top_bar_counts_it(self, month):
        body = handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=month).body.decode()
        assert '<span class="resumen-cifra pendientes">1</span>' in body

    def test_once_a_line_is_added_it_leaves_the_list(self, month):
        body = handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=month).body.decode()
        start = body.index('name="csrf" value="') + len('name="csrf" value="')
        handle("POST", "/hoja/16-09-2026_p64.jpg/linea", address=LAN, store=month,
               form={"texto": "Linea anadida.", "csrf": body[start:body.index('"', start)]})
        assert "16-09-2026 p64" not in month.to_check("2026", "SEPTIEMBRE")
