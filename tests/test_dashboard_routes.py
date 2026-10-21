"""The routes: who is refused, what is written, and what cannot be traversed."""

import os
import threading

import pytest

from config import config
from dashboard import ROUTES, _dispatch_request, handle
from entry_store import EntryStore
from month_folders import revision_dir_for
from review_marks import image_name

LAN = "192.168.50.41"
TAILNET = "100.64.0.10"
OUTSIDE = "8.8.8.8"


@pytest.fixture
def store(tmp_path):
    with EntryStore(str(tmp_path / "e.sqlite3")) as s:
        s.add("2026", "SEPTIEMBRE", "Intervenciones Seguridad:",
              [{"text": "Se retiran pelonas.", "confident": False}],
              "s.pdf", "01-09-2026 p1")
        yield s


def token_for(store):
    response = handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=store)
    body = response.body.decode()
    start = body.index('name="csrf" value="') + len('name="csrf" value="')
    return body[start:body.index('"', start)]


class TestWhoIsRefused:
    @pytest.mark.parametrize("path", sorted(ROUTES))
    def test_every_route_refuses_an_outside_address(self, path, store):
        for method in ("GET", "POST"):
            response = handle(method, path, address=OUTSIDE, store=store)
            assert response.status == 403, f"{method} {path}"

    def test_the_lan_is_served(self, store):
        assert handle("GET", "/mes/2026/SEPTIEMBRE",
                      address=LAN, store=store).status == 200


class TestCsrf:
    def test_a_post_without_a_token_is_refused(self, store):
        entry = store.month_entries("2026", "SEPTIEMBRE")[0]
        response = handle("POST", f"/entrada/{entry['id']}", address=LAN,
                          form={"texto": "Se retiran pilonas."}, store=store)
        assert response.status == 403
        assert store.month_entries("2026", "SEPTIEMBRE")[0]["text"] == (
            "Se retiran pelonas."
        ), "nothing was written"

    def test_a_post_with_the_token_is_accepted(self, store):
        entry = store.month_entries("2026", "SEPTIEMBRE")[0]
        response = handle("POST", f"/entrada/{entry['id']}", address=LAN,
                          form={"texto": "Se retiran pilonas.",
                                "csrf": token_for(store)}, store=store)
        assert response.status in (200, 303)
        assert store.month_entries("2026", "SEPTIEMBRE")[0]["text"] == (
            "Se retiran pilonas."
        )


class TestSheetImages:
    @pytest.mark.parametrize("reference", [
        "../../../etc/passwd", "/etc/passwd", "..%2f..%2fetc%2fpasswd",
        "01-09-2026_p1.jpg\x00.png",
    ])
    def test_a_path_cannot_be_traversed(self, reference, store):
        response = handle("GET", f"/hoja/{reference}", address=LAN, store=store)
        assert response.status == 404

    def test_a_reference_not_in_the_database_is_not_served(self, store):
        response = handle("GET", "/hoja/31-12-2099_p9.jpg", address=LAN, store=store)
        assert response.status == 404


class TestAdvanced:
    def test_the_lan_is_not_offered_the_numbers(self, store):
        body = handle("GET", "/resumen", address=LAN, store=store).body.decode()
        assert "gpt-5.4" not in body

    def test_the_tailnet_is(self, store):
        body = handle("GET", "/resumen", address=TAILNET, store=store).body.decode()
        assert "gpt-5.4" in body


class TestMaintenance:
    def test_the_bare_path_opens_the_newest_month(self, store):
        response = handle("GET", "/mantenimiento", address=LAN, store=store)
        assert response.status == 303
        assert response.headers["Location"] == "/mantenimiento/2026/SEPTIEMBRE"

    def test_the_month_renders(self, store):
        assert handle("GET", "/mantenimiento/2026/SEPTIEMBRE", address=LAN,
                      store=store).status == 200


class TestUnknown:
    def test_an_unknown_path_is_not_found(self, store):
        assert handle("GET", "/nada", address=LAN, store=store).status == 404


class TestNuevaEntradaDerivesFromAnchor:
    def test_the_block_comes_from_the_after_id_row_not_the_form(self, store):
        """add_entry() places a new line relative to after_id without
        checking they share a block; a request naming an after_id from one
        block but a different block in the form must not be trusted for the
        block (or year/month) -- both are derived from the anchor row.
        """
        anchor = store.month_entries("2026", "SEPTIEMBRE")[0]
        assert anchor["block"] == "Intervenciones Seguridad:"
        token = token_for(store)

        response = handle(
            "POST", "/entrada/nueva", address=LAN, store=store,
            form={
                "texto": "Se revisa el cuadro electrico.",
                "after_id": str(anchor["id"]),
                # A different block, submitted in the form on purpose.
                "block": "Mantenimiento Ascensores:",
                "csrf": token,
            },
        )
        assert response.status in (200, 303)

        entries = store.month_entries("2026", "SEPTIEMBRE")
        added = [e for e in entries if e["text"] == "Se revisa el cuadro electrico."]
        assert len(added) == 1
        assert added[0]["block"] == "Intervenciones Seguridad:"


class TestThreadSafety:
    def test_a_second_thread_can_still_query_the_store(self, store):
        """ThreadingHTTPServer used to hand every request a new OS thread,
        and EntryStore's sqlite connection is check_same_thread=True -- the
        first query on any request but the first raised. Priming the safe
        path from this thread first mirrors how a plain HTTPServer's single
        serving thread would actually be used; the second thread is the
        stray case _resolve_store exists to survive.
        """
        first = handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=store)
        assert first.status == 200

        result = {}

        def worker():
            result["response"] = handle(
                "GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=store
            )

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        assert result["response"].status == 200


class TestConfirmedSheetStillResolves:
    def test_confirming_the_last_doubtful_line_does_not_break_the_image(
        self, store, tmp_path, monkeypatch
    ):
        """review_pages() filters to flagged = 1; confirm_entry() clears the
        flag. Looking the reference up only through review_pages() would
        404 a sheet the instant its last doubtful line is confirmed -- the
        exact moment the colleague is looking at it.
        """
        incoming = tmp_path / "incoming"
        monkeypatch.setattr(config, "incoming_dir", str(incoming))

        entry = store.month_entries("2026", "SEPTIEMBRE")[0]
        reference = image_name(entry["review_ref"])
        revision_dir = revision_dir_for(str(incoming), "2026", "SEPTIEMBRE")
        os.makedirs(revision_dir, exist_ok=True)
        with open(os.path.join(revision_dir, reference), "wb") as sheet_image:
            sheet_image.write(b"fake-jpeg-bytes")

        store.confirm_entry(entry["id"])
        assert store.month_entries("2026", "SEPTIEMBRE")[0]["flagged"] == 0

        response = handle("GET", f"/hoja/{reference}", address=LAN, store=store)
        assert response.status == 200
        assert response.body == b"fake-jpeg-bytes"


class TestCsrfIsMarkedOnTheRoute:
    @pytest.mark.parametrize(
        "path", sorted(path for path, route in ROUTES.items() if route.mutates)
    )
    def test_a_mutating_route_refuses_any_method_without_a_token(self, path, store):
        # GET on purpose: the guard must not depend on the verb, only on
        # whether the route is marked as mutating.
        response = handle("GET", path, address=LAN, form={}, store=store)
        assert response.status == 403, path


class TestHostAllowlist:
    def test_a_foreign_host_is_refused(self, store):
        response = handle(
            "GET", "/mes/2026/SEPTIEMBRE", address=LAN,
            host="attacker.example", store=store,
        )
        assert response.status == 403

    def test_the_pis_own_host_is_served(self, store):
        response = handle(
            "GET", "/mes/2026/SEPTIEMBRE", address=LAN,
            host="192.168.50.5:8000", store=store,
        )
        assert response.status == 200

    def test_no_host_at_all_is_not_checked_when_calling_handle_directly(self, store):
        # handle(host=None) is the "never spoke HTTP" case this whole suite
        # relies on; it must keep working. A request that actually arrived
        # on the wire without a Host header is a different story -- see
        # TestDispatchRequest below, which is where that gap actually was.
        response = handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=store)
        assert response.status == 200


class TestDispatchRequest:
    """_dispatch_request is what serve() actually calls per request; unlike
    handle(), it always turns a request's own headers into a host, so this
    is the level at which "no Host header on the wire" has to be refused --
    calling is_allowed_host("") directly would not have caught the bug,
    since that function was already correct. A plain dict stands in for
    BaseHTTPRequestHandler.headers: only .get(name, default) is used.
    """

    def test_a_request_with_no_host_header_is_refused(self, store):
        response = _dispatch_request(
            "GET", {}, LAN, "/mes/2026/SEPTIEMBRE", b"", store
        )
        assert response.status == 403

    def test_a_request_with_the_pis_own_host_is_served(self, store):
        response = _dispatch_request(
            "GET", {"Host": "192.168.50.5:8000"}, LAN, "/mes/2026/SEPTIEMBRE", b"", store
        )
        assert response.status == 200


class TestSpendIsReal:
    """The advanced view shows the ledger's real figure, or says it has none.

    This used to read whatever spend ledger sat in the working directory and
    assert "0.00 €" never appeared. It passed on the author's laptop only
    because that ledger held September's spend: on the Pi, with no ledger,
    it failed, and it would have failed on the laptop too on 1 October, when
    a new month starts at a real zero. It now owns its ledger.
    """

    def _ledger(self, tmp_path, monkeypatch, usd: float | None):
        from spend_guard import SpendGuard
        db = tmp_path / "spend.sqlite3"
        monkeypatch.setattr(config, "spend_db", str(db))
        if usd is not None:
            with SpendGuard(str(db), monthly_budget_eur=config.monthly_budget_eur,
                            eur_usd=config.eur_usd) as guard:
                guard._connection.execute(
                    "INSERT INTO spend (month, at, model, tokens_in, tokens_out, usd) "
                    "VALUES (?, ?, 'test', 0, 0, ?)",
                    (guard._month(), guard._clock(), usd))
                guard._connection.commit()

    def test_it_shows_what_the_ledger_holds(self, store, tmp_path, monkeypatch):
        self._ledger(tmp_path, monkeypatch, usd=config.eur_usd * 3.22)
        body = handle("GET", "/resumen", address=TAILNET, store=store).body.decode()
        assert "3.22 €" in body

    def test_a_month_with_no_spend_is_a_real_zero(self, store, tmp_path, monkeypatch):
        """Zero is not fabricated when the ledger is readable and empty."""
        self._ledger(tmp_path, monkeypatch, usd=None)
        body = handle("GET", "/resumen", address=TAILNET, store=store).body.decode()
        assert "0.00 €" in body

    def test_an_unreadable_ledger_says_so_instead_of_zero(self, store, tmp_path, monkeypatch):
        folder = tmp_path / "no-es-un-fichero"
        folder.mkdir()
        monkeypatch.setattr(config, "spend_db", str(folder))
        body = handle("GET", "/resumen", address=TAILNET, store=store).body.decode()
        assert "sin datos" in body
        assert "0.00 €" not in body


class TestSheetSelection:
    """The flag's whole purpose end to end: a click must load the image
    without any script running -- the gap the earlier review missed
    entirely, because nothing asserted the <img> ever got a real src.
    """

    def test_the_flag_link_carries_an_href_not_merely_a_data_attribute(self, store):
        entry = store.month_entries("2026", "SEPTIEMBRE")[0]
        filename = image_name(entry["review_ref"])
        body = handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=store).body.decode()
        assert f'href="/mes/2026/SEPTIEMBRE?hoja={filename}#hoja-{filename}"' in body

    def test_selecting_a_sheet_renders_an_img_pointing_at_the_hoja_route(self, store):
        entry = store.month_entries("2026", "SEPTIEMBRE")[0]
        filename = image_name(entry["review_ref"])
        body = handle(
            "GET", f"/mes/2026/SEPTIEMBRE?hoja={filename}", address=LAN, store=store
        ).body.decode()
        assert "<img" in body
        assert f'src="/hoja/{filename}"' in body

    def test_an_unvalidated_reference_selects_nothing(self, store):
        body = handle(
            "GET", "/mes/2026/SEPTIEMBRE?hoja=../../etc/passwd",
            address=LAN, store=store,
        ).body.decode()
        assert "<img" not in body


class TestRootRedirectsToTheLatestMonth:
    def test_it_redirects_to_a_month_with_entries(self, store):
        response = handle("GET", "/", address=LAN, store=store)
        assert response.status == 303
        assert response.headers["Location"] == "/mes/2026/SEPTIEMBRE"

    def test_it_falls_back_to_the_current_month_when_nothing_has_been_read(self, tmp_path):
        from datetime import datetime

        from month_folders import MONTH_FOLDERS

        with EntryStore(str(tmp_path / "empty.sqlite3")) as empty_store:
            response = handle("GET", "/", address=LAN, store=empty_store)
        now = datetime.now()
        expected_month = MONTH_FOLDERS[now.month - 1]
        assert response.status == 303
        assert response.headers["Location"] == f"/mes/{now.year}/{expected_month}"


class TestRotatingASheet:
    """The manual quarter turn, for the sheets OSD declined to straighten."""

    @pytest.fixture
    def sheet(self, store, tmp_path, monkeypatch):
        """A real 40x20 landscape JPEG in the revision folder, plus its
        reference. Real bytes because the route actually decodes and re-encodes
        it; the other sheet tests can get away with b"fake-jpeg-bytes" because
        they only ever read it back."""
        from PIL import Image

        incoming = tmp_path / "incoming"
        monkeypatch.setattr(config, "incoming_dir", str(incoming))
        entry = store.month_entries("2026", "SEPTIEMBRE")[0]
        reference = image_name(entry["review_ref"])
        revision_dir = revision_dir_for(str(incoming), "2026", "SEPTIEMBRE")
        os.makedirs(revision_dir, exist_ok=True)
        path = os.path.join(revision_dir, reference)
        Image.new("RGB", (40, 20), "white").save(path, quality=95)
        return reference, path

    def _size(self, path):
        from PIL import Image

        with Image.open(path) as image:
            return image.size

    @pytest.mark.parametrize("degrees", [90, 270])
    def test_a_quarter_turn_rewrites_the_file(self, sheet, store, degrees):
        reference, path = sheet
        assert self._size(path) == (40, 20)
        response = handle("POST", f"/hoja/{reference}/girar", address=LAN,
                          form={"grados": str(degrees), "csrf": token_for(store)},
                          store=store)
        assert response.status in (200, 303)
        assert self._size(path) == (20, 40)

    def test_half_a_turn_keeps_the_shape(self, sheet, store):
        reference, path = sheet
        response = handle("POST", f"/hoja/{reference}/girar", address=LAN,
                          form={"grados": "180", "csrf": token_for(store)},
                          store=store)
        assert response.status in (200, 303)
        assert self._size(path) == (40, 20)

    def test_it_returns_to_the_sheet_it_turned(self, sheet, store):
        reference, _ = sheet
        response = handle("POST", f"/hoja/{reference}/girar", address=LAN,
                          form={"grados": "90", "csrf": token_for(store)},
                          store=store)
        assert response.status == 303
        location = response.headers["Location"]
        assert location == f"/mes/2026/SEPTIEMBRE?hoja={reference}"

    @pytest.mark.parametrize("grados", ["45", "360", "0", "-90", "", "noventa"])
    def test_anything_but_a_quarter_turn_is_refused(self, sheet, store, grados):
        reference, path = sheet
        response = handle("POST", f"/hoja/{reference}/girar", address=LAN,
                          form={"grados": grados, "csrf": token_for(store)},
                          store=store)
        assert response.status == 400
        assert self._size(path) == (40, 20)

    @pytest.mark.parametrize("reference", [
        "../../../etc/passwd", "/etc/passwd", "..%2f..%2fetc%2fpasswd",
        "31-12-2099_p9.jpg",
    ])
    def test_a_reference_that_matches_nothing_turns_nothing(
        self, reference, store, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(config, "incoming_dir", str(tmp_path / "incoming"))
        response = handle("POST", f"/hoja/{reference}/girar", address=LAN,
                          form={"grados": "90", "csrf": token_for(store)},
                          store=store)
        assert response.status == 404

    def test_a_get_does_not_turn_the_sheet(self, sheet, store):
        reference, path = sheet
        response = handle("GET", f"/hoja/{reference}/girar", address=LAN,
                          form={"grados": "90", "csrf": token_for(store)},
                          store=store)
        assert response.status == 405
        assert self._size(path) == (40, 20)

    def test_the_served_image_is_not_cached(self, sheet, store):
        # The rotate buttons change the file under a URL that never changes.
        reference, _ = sheet
        response = handle("GET", f"/hoja/{reference}", address=LAN, store=store)
        assert response.status == 200
        assert response.headers.get("Cache-Control") == "no-store"

    @pytest.mark.parametrize("degrees, corner", [
        # A mark in the top-left, and where a clockwise turn of that many
        # degrees must put it. Shape alone cannot tell 90 from 270 -- both
        # turn 40x20 into 20x40 -- so the mark is what pins the direction,
        # which is the half of this that is easy to get backwards.
        (90, "top-right"),
        (270, "bottom-left"),
        (180, "bottom-right"),
    ])
    def test_the_turn_goes_clockwise(self, sheet, store, degrees, corner):
        from PIL import Image

        reference, path = sheet
        with Image.open(path) as image:
            marked = image.copy()
        marked.putpixel((0, 0), (255, 0, 0))
        marked.save(path, quality=95)

        response = handle("POST", f"/hoja/{reference}/girar", address=LAN,
                          form={"grados": str(degrees), "csrf": token_for(store)},
                          store=store)
        assert response.status in (200, 303)

        with Image.open(path) as image:
            width, height = image.size
            corners = {
                "top-left": (0, 0),
                "top-right": (width - 1, 0),
                "bottom-left": (0, height - 1),
                "bottom-right": (width - 1, height - 1),
            }
            # JPEG is lossy, so the mark is found by which corner is reddest
            # rather than by an exact (255, 0, 0).
            reddest = max(
                corners, key=lambda name: image.getpixel(corners[name])[0]
                - image.getpixel(corners[name])[2]
            )
        assert reddest == corner


class TestTheSectionTabs:
    """Both tabs used to be href="?seccion=..." -- a query parameter nothing
    reads, so clicking either reloaded the same page. The regression is
    invisible in the markup unless the hrefs are asserted."""

    def test_the_tabs_open_the_same_month_in_each_section(self, store):
        body = handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN,
                      store=store).body.decode()
        assert 'href="/mantenimiento/2026/SEPTIEMBRE"' in body
        assert 'href="/mes/2026/SEPTIEMBRE"' in body
        assert "?seccion=" not in body

    def test_mantenimiento_marks_its_own_tab_active(self, store):
        body = handle("GET", "/mantenimiento/2026/SEPTIEMBRE", address=LAN,
                      store=store).body.decode()
        marker = body.index('href="/mantenimiento/2026/SEPTIEMBRE"')
        assert 'class="activo"' in body[marker:marker + 120]


class TestEachSectionShowsItsOwnSheets:
    """September 30: the maintenance batch landed in the same month as the
    vigilantes' sheets, and the Seguridad view showed both, mixed."""

    @pytest.fixture
    def both(self, store):
        store.record_sheet("2026", "SEPTIEMBRE", "s.pdf", 1, "01-09-2026 p1")
        store.record_sheet("2026", "SEPTIEMBRE", "m.pdf", 1, "02-09-2026 p2")
        store.record_sheet("2026", "SEPTIEMBRE", "m.pdf", 2, "03-09-2026 p3")
        store.add("2026", "SEPTIEMBRE", "Parking",
                  [{"text": "Con la obra de la rampa del parking.", "confident": False}],
                  "m.pdf", "02-09-2026 p2")
        return store

    def test_seguridad_has_no_maintenance(self, both):
        body = handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=both).body.decode()
        assert "Se retiran pelonas." in body
        assert "rampa del parking" not in body
        assert "02-09-2026_p2.jpg" not in body
        assert "03-09-2026_p3.jpg" not in body, "an empty maintenance sheet too"

    def test_mantenimiento_has_no_security(self, both):
        body = handle("GET", "/mantenimiento/2026/SEPTIEMBRE", address=LAN,
                      store=both).body.decode()
        assert "rampa del parking" in body
        assert "03-09-2026_p3.jpg" in body
        assert "Se retiran pelonas." not in body
        assert "01-09-2026_p1.jpg" not in body

    def test_links_in_mantenimiento_stay_in_mantenimiento(self, both):
        body = handle("GET", "/mantenimiento/2026/SEPTIEMBRE", address=LAN,
                      store=both).body.decode()
        assert 'href="/mantenimiento/2026/SEPTIEMBRE?hoja=02-09-2026_p2.jpg' in body
        assert 'href="/mes/2026/SEPTIEMBRE?hoja=' not in body

    def test_a_write_from_mantenimiento_comes_back_to_it(self, both):
        body = handle("GET", "/mantenimiento/2026/SEPTIEMBRE", address=LAN,
                      store=both).body.decode()
        assert '<input type="hidden" name="seccion" value="mantenimiento">' in body
        csrf = token_for(both)
        entry = next(e for e in both.month_entries("2026", "SEPTIEMBRE")
                     if e["block"] == "Parking")
        response = handle("POST", f"/entrada/{entry['id']}", address=LAN, store=both,
                          form={"csrf": csrf, "texto": "Con la obra de la rampa.",
                                "seccion": "mantenimiento"})
        assert response.headers["Location"].startswith("/mantenimiento/2026/SEPTIEMBRE")

    def test_an_unknown_section_goes_back_to_seguridad(self, both):
        csrf = token_for(both)
        entry = both.month_entries("2026", "SEPTIEMBRE")[0]
        response = handle("POST", f"/entrada/{entry['id']}", address=LAN, store=both,
                          form={"csrf": csrf, "texto": "x y z", "seccion": "//evil"})
        assert response.headers["Location"].startswith("/mes/2026/SEPTIEMBRE")


class TestBrowsingTheWholeBatch:
    """The flags are a shortlist. Someone checking the month against the
    paper has to be able to reach a sheet nothing was flagged on."""

    @pytest.fixture
    def two_sheets(self, tmp_path):
        with EntryStore(str(tmp_path / "b.sqlite3")) as s:
            s.add("2026", "SEPTIEMBRE", "Intervenciones Seguridad:",
                  [{"text": "Linea dudosa.", "confident": False}],
                  "s.pdf", "01-09-2026 p1")
            s.add("2026", "SEPTIEMBRE", "Intervenciones Seguridad:",
                  [{"text": "Linea limpia.", "confident": True}],
                  "s.pdf", "02-09-2026 p2")
            yield s

    def test_a_clean_sheet_is_absent_from_the_shortlist(self, two_sheets):
        assert list(two_sheets.review_pages("2026", "SEPTIEMBRE")) == [
            "01-09-2026 p1"
        ]

    def test_but_present_in_the_whole_batch(self, two_sheets):
        assert two_sheets.all_pages("2026", "SEPTIEMBRE") == {
            "01-09-2026 p1": 1, "02-09-2026 p2": 0,
        }

    def test_a_confident_entry_still_knows_its_sheet(self, two_sheets):
        """add() used to blank review_ref unless the entry was doubtful, so a
        clean line could not be traced back to the paper it came from."""
        limpia = next(e for e in two_sheets.month_entries("2026", "SEPTIEMBRE")
                  if e["text"] == "Linea limpia.")
        assert limpia["review_ref"] == "02-09-2026 p2"
        assert limpia["flagged"] == 0

    def test_the_default_list_is_every_sheet(self, two_sheets):
        body = handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN,
                      store=two_sheets).body.decode()
        assert 'data-hoja="02-09-2026_p2.jpg"' in body
        assert 'class="activo">Todas (2)' in body

    def test_the_shortlist_is_asked_for(self, two_sheets):
        body = handle("GET", "/mes/2026/SEPTIEMBRE?hojas=pendientes", address=LAN,
                      store=two_sheets).body.decode()
        assert 'data-hoja="01-09-2026_p1.jpg"' in body
        assert 'data-hoja="02-09-2026_p2.jpg"' not in body
        assert "Por revisar (1)" in body
        assert "Todas (2)" in body

    def test_hojas_todas_lists_every_sheet(self, two_sheets):
        body = handle("GET", "/mes/2026/SEPTIEMBRE?hojas=todas", address=LAN,
                      store=two_sheets).body.decode()
        assert 'data-hoja="02-09-2026_p2.jpg"' in body
        # The clean sheet is marked done with a tick, not a sentence.
        assert 'class="hoja-pendiente revisada"' in body
        assert '<span class="estado-hoja revisada">' in body

    def test_a_clean_sheet_can_be_opened(self, two_sheets, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "incoming_dir", str(tmp_path / "incoming"))
        revision = revision_dir_for(str(tmp_path / "incoming"), "2026", "SEPTIEMBRE")
        os.makedirs(revision, exist_ok=True)
        with open(os.path.join(revision, "02-09-2026_p2.jpg"), "wb") as f:
            f.write(b"clean-sheet")
        response = handle("GET", "/hoja/02-09-2026_p2.jpg", address=LAN,
                          store=two_sheets)
        assert response.status == 200
        assert response.body == b"clean-sheet"

    def test_the_arrows_step_through_the_whole_batch(self, two_sheets):
        body = handle("GET", "/mes/2026/SEPTIEMBRE?hoja=01-09-2026_p1.jpg&hojas=todas",
                      address=LAN, store=two_sheets).body.decode()
        assert "1 / 2" in body
        # Forward to the clean sheet; back is a dead button at the first one.
        assert "?hoja=02-09-2026_p2.jpg#hoja-02-09-2026_p2.jpg" in body


class TestTheOpenSheetSurvivesAWrite:
    """Every write redirected to the bare month page, so pressing Guardar
    línea with a sheet open closed the sheet and scrolled to the top."""

    def _ref(self, store):
        entry = store.month_entries("2026", "SEPTIEMBRE")[0]
        return entry["id"], image_name(entry["review_ref"])

    def test_saving_a_line_keeps_the_sheet_open(self, store):
        entry_id, ref = self._ref(store)
        response = handle("POST", f"/entrada/{entry_id}", address=LAN,
                          form={"texto": "Se retiran pilonas.", "hoja": ref,
                                "csrf": token_for(store)}, store=store)
        assert response.status == 303
        assert response.headers["Location"] == (
            f"/mes/2026/SEPTIEMBRE?hoja={ref}#entrada-{entry_id}"
        )

    def test_confirming_keeps_the_sheet_and_the_list(self, store):
        entry_id, ref = self._ref(store)
        response = handle("POST", f"/entradas/{entry_id}", address=LAN,
                          form={"accion": "confirmar", "hoja": ref, "hojas": "pendientes",
                                "csrf": token_for(store)}, store=store)
        assert response.headers["Location"] == (
            f"/mes/2026/SEPTIEMBRE?hoja={ref}&hojas=pendientes#entrada-{entry_id}"
        )

    def test_marking_for_review_flags_the_line_and_returns_to_it(self, store):
        entry_id, ref = self._ref(store)
        store.confirm_entry(entry_id)
        response = handle("POST", f"/entradas/{entry_id}", address=LAN,
                          form={"accion": "revisar", "hoja": ref,
                                "csrf": token_for(store)}, store=store)
        assert response.headers["Location"] == (
            f"/mes/2026/SEPTIEMBRE?hoja={ref}#entrada-{entry_id}"
        )
        entry = next(e for e in store.month_entries("2026", "SEPTIEMBRE")
                     if e["id"] == entry_id)
        assert entry["flagged"] and entry["hand_edited"]

    def test_deleting_keeps_the_sheet_but_has_no_row_to_return_to(self, store):
        entry_id, ref = self._ref(store)
        response = handle("POST", f"/entradas/{entry_id}", address=LAN,
                          form={"accion": "eliminar", "hoja": ref,
                                "csrf": token_for(store)}, store=store)
        location = response.headers["Location"]
        assert "#entrada-" not in location

    def test_guardar_keeps_the_sheet_open(self, store, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "incoming_dir", str(tmp_path / "incoming"))
        _, ref = self._ref(store)
        response = handle("POST", "/guardar/2026/SEPTIEMBRE", address=LAN,
                          form={"hoja": ref, "csrf": token_for(store)}, store=store)
        assert response.status == 303
        assert response.headers["Location"] == f"/mes/2026/SEPTIEMBRE?hoja={ref}"

    def test_no_sheet_open_means_the_plain_month(self, store):
        entry_id, _ = self._ref(store)
        response = handle("POST", f"/entrada/{entry_id}", address=LAN,
                          form={"texto": "Otra cosa.", "csrf": token_for(store)},
                          store=store)
        assert response.headers["Location"] == f"/mes/2026/SEPTIEMBRE#entrada-{entry_id}"

    @pytest.mark.parametrize("hoja", [
        "../../../etc/passwd", "31-12-2099_p9.jpg",
        "x\r\nSet-Cookie: a=b", "//evil.example/", "01-09-2026_p1.jpg?hojas=todas",
    ])
    def test_a_forged_sheet_is_dropped_not_echoed(self, store, hoja):
        """hoja goes through the same database lookup as the query string."""
        entry_id, _ = self._ref(store)
        response = handle("POST", f"/entrada/{entry_id}", address=LAN,
                          form={"texto": "Otra cosa.", "hoja": hoja,
                                "csrf": token_for(store)}, store=store)
        location = response.headers["Location"]
        assert location == f"/mes/2026/SEPTIEMBRE#entrada-{entry_id}"
        assert "\r" not in location and "\n" not in location

    @pytest.mark.parametrize("hojas", ["PENDIENTES", "pendientes&x=1", "todas", "1"])
    def test_hojas_is_only_ever_the_literal_pendientes(self, store, hojas):
        entry_id, _ = self._ref(store)
        response = handle("POST", f"/entrada/{entry_id}", address=LAN,
                          form={"texto": "Otra cosa.", "hojas": hojas,
                                "csrf": token_for(store)}, store=store)
        assert "hojas" not in response.headers["Location"]

    def test_every_form_carries_the_open_sheet(self, store):
        _, ref = self._ref(store)
        body = handle("GET", f"/mes/2026/SEPTIEMBRE?hoja={ref}&hojas=pendientes",
                      address=LAN, store=store).body.decode()
        formularios = body.count("<form")
        assert formularios >= 4  # line, actions, three turns, guardar
        assert body.count(f'<input type="hidden" name="hoja" value="{ref}">') == formularios
        assert body.count('<input type="hidden" name="hojas" value="pendientes">') == formularios


class TestNoTypedLineIsLost:
    """Each line is its own form. Editing three boxes and pressing Guardar
    línea on one used to throw the other two away on the reload."""

    @pytest.fixture
    def tres(self, tmp_path):
        with EntryStore(str(tmp_path / "t.sqlite3")) as s:
            s.add("2026", "SEPTIEMBRE", "Intervenciones Seguridad:",
                  [{"text": "Uno.", "confident": False},
                   {"text": "Dos.", "confident": False},
                   {"text": "Tres.", "confident": False}],
                  "s.pdf", "01-09-2026 p1")
            s.add("2026", "OCTUBRE", "Intervenciones Seguridad:",
                  [{"text": "Otro mes.", "confident": True}],
                  "s.pdf", "01-10-2026 p1")
            yield s

    def _ids(self, store, month="SEPTIEMBRE"):
        return {e["text"]: e["id"] for e in store.month_entries("2026", month)}

    def _texts(self, store, month="SEPTIEMBRE"):
        return sorted(e["text"] for e in store.month_entries("2026", month))

    def test_guardar_linea_carries_the_other_edited_boxes(self, tres):
        ids = self._ids(tres)
        handle("POST", f"/entrada/{ids['Uno.']}", address=LAN, store=tres, form={
            "texto": "Uno bien.", f"texto-{ids['Dos.']}": "Dos bien.",
            "csrf": token_for(tres)})
        assert self._texts(tres) == ["Dos bien.", "Tres.", "Uno bien."]

    def test_correcto_carries_them_too(self, tres):
        ids = self._ids(tres)
        handle("POST", f"/entradas/{ids['Uno.']}", address=LAN, store=tres, form={
            "accion": "confirmar", f"texto-{ids['Tres.']}": "Tres bien.",
            "csrf": token_for(tres)})
        assert "Tres bien." in self._texts(tres)

    def test_guardar_saves_every_edited_line_then_the_document(
        self, tres, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(config, "incoming_dir", str(tmp_path / "incoming"))
        ids = self._ids(tres)
        response = handle("POST", "/guardar/2026/SEPTIEMBRE", address=LAN, store=tres,
                          form={f"texto-{ids['Uno.']}": "Uno bien.",
                                f"texto-{ids['Dos.']}": "Dos bien.",
                                "csrf": token_for(tres)})
        assert response.status == 303
        assert self._texts(tres) == ["Dos bien.", "Tres.", "Uno bien."]

    def test_an_unchanged_box_is_not_marked_as_corrected(self, tres, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "incoming_dir", str(tmp_path / "incoming"))
        ids = self._ids(tres)
        handle("POST", "/guardar/2026/SEPTIEMBRE", address=LAN, store=tres,
               form={f"texto-{ids['Tres.']}": "Tres.", "csrf": token_for(tres)})
        tres_row = next(e for e in tres.month_entries("2026", "SEPTIEMBRE")
                    if e["text"] == "Tres.")
        assert tres_row["hand_edited"] == 0
        assert tres_row["flagged"] == 1

    def test_an_id_from_another_month_is_ignored(self, tres, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "incoming_dir", str(tmp_path / "incoming"))
        otro = self._ids(tres, "OCTUBRE")["Otro mes."]
        handle("POST", "/guardar/2026/SEPTIEMBRE", address=LAN, store=tres,
               form={f"texto-{otro}": "Reescrito desde septiembre.",
                     "csrf": token_for(tres)})
        assert self._texts(tres, "OCTUBRE") == ["Otro mes."]

    @pytest.mark.parametrize("clave", ["texto-abc", "texto-", "texto-1-2", "xtexto-1"])
    def test_a_malformed_key_is_ignored(self, tres, clave, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "incoming_dir", str(tmp_path / "incoming"))
        antes = self._texts(tres)
        response = handle("POST", "/guardar/2026/SEPTIEMBRE", address=LAN, store=tres,
                          form={clave: "Basura.", "csrf": token_for(tres)})
        assert response.status == 303
        assert self._texts(tres) == antes

    def test_a_refused_line_is_reported_not_swallowed(self, tres, tmp_path, monkeypatch):
        """Duplicating a sibling's text is refused by the dedupe index.
        Redirecting as if all went well would look exactly like success."""
        monkeypatch.setattr(config, "incoming_dir", str(tmp_path / "incoming"))
        ids = self._ids(tres)
        response = handle("POST", "/guardar/2026/SEPTIEMBRE", address=LAN, store=tres,
                          form={f"texto-{ids['Uno.']}": "Dos.", "csrf": token_for(tres)})
        assert response.status == 200
        body = response.body.decode()
        assert "1 línea no se pudo guardar" in body
        assert "no se pudieron" not in body
        assert "Volver al documento" in body

    def test_a_pending_edit_still_needs_the_token(self, tres):
        ids = self._ids(tres)
        response = handle("POST", "/guardar/2026/SEPTIEMBRE", address=LAN, store=tres,
                          form={f"texto-{ids['Uno.']}": "Sin token."})
        assert response.status == 403
        assert "Sin token." not in self._texts(tres)


class TestCtrlS:
    def test_the_page_offers_it(self):
        from dashboard_html import _SCRIPT
        assert "evento.ctrlKey || evento.metaKey" in _SCRIPT
        assert "formGuardar.requestSubmit" in _SCRIPT

    def test_every_form_submission_carries_the_edited_boxes(self):
        from dashboard_html import _SCRIPT
        assert "document.addEventListener('submit'" in _SCRIPT
        assert "'texto-' + caja.getAttribute('data-id')" in _SCRIPT

    def test_leaving_with_unsaved_lines_asks_first(self):
        from dashboard_html import _SCRIPT
        assert "beforeunload" in _SCRIPT


class TestAddingALineAnywhere:
    @pytest.fixture
    def dos_hojas(self, tmp_path):
        with EntryStore(str(tmp_path / "a.sqlite3")) as s:
            s.add("2026", "SEPTIEMBRE", "Intervenciones Seguridad:",
                  [{"text": "A1.", "confident": True}, {"text": "A2.", "confident": True}],
                  "s.pdf", "01-09-2026 p1")
            s.add("2026", "SEPTIEMBRE", "Intervenciones Seguridad:",
                  [{"text": "B1.", "confident": True}], "s.pdf", "02-09-2026 p2")
            yield s

    def _ids(self, store):
        return {e["text"]: e["id"] for e in store.month_entries("2026", "SEPTIEMBRE")}

    def _order(self, store):
        return store.entries("2026", "SEPTIEMBRE", "Intervenciones Seguridad:")

    def test_below_a_line(self, dos_hojas):
        ids = self._ids(dos_hojas)
        response = handle("POST", "/entrada/nueva", address=LAN, store=dos_hojas, form={
            "after_id": str(ids["A1."]), "texto": "Nueva.", "csrf": token_for(dos_hojas)})
        assert response.status == 303
        assert self._order(dos_hojas) == ["A1.", "Nueva.", "A2.", "B1."]

    def test_above_the_first_line_of_a_sheet(self, dos_hojas):
        ids = self._ids(dos_hojas)
        handle("POST", "/entrada/nueva", address=LAN, store=dos_hojas, form={
            "before_id": str(ids["B1."]), "texto": "Nueva.", "csrf": token_for(dos_hojas)})
        assert self._order(dos_hojas) == ["A1.", "A2.", "Nueva.", "B1."]

    def test_it_belongs_to_the_sheet_it_was_added_to(self, dos_hojas):
        """add_entry stored review_ref='', and the month is sorted by the
        date in review_ref, so a new line sank to the bottom of the block."""
        ids = self._ids(dos_hojas)
        handle("POST", "/entrada/nueva", address=LAN, store=dos_hojas, form={
            "after_id": str(ids["A2."]), "texto": "Nueva.", "csrf": token_for(dos_hojas)})
        nueva = next(e for e in dos_hojas.month_entries("2026", "SEPTIEMBRE")
                 if e["text"] == "Nueva.")
        assert nueva["review_ref"] == "01-09-2026 p1"
        assert self._order(dos_hojas) == ["A1.", "A2.", "Nueva.", "B1."]

    def test_it_lands_back_on_the_new_line(self, dos_hojas):
        ids = self._ids(dos_hojas)
        response = handle("POST", "/entrada/nueva", address=LAN, store=dos_hojas, form={
            "after_id": str(ids["A1."]), "texto": "Nueva.", "csrf": token_for(dos_hojas)})
        nueva = self._ids(dos_hojas)["Nueva."]
        assert response.headers["Location"].endswith(f"#entrada-{nueva}")

    @pytest.mark.parametrize("form", [
        {}, {"after_id": "1", "before_id": "1"}, {"after_id": "x"}, {"before_id": ""},
    ])
    def test_exactly_one_anchor(self, dos_hojas, form):
        response = handle("POST", "/entrada/nueva", address=LAN, store=dos_hojas,
                          form={**form, "texto": "Nueva.", "csrf": token_for(dos_hojas)})
        assert response.status == 400

    def test_a_duplicate_is_reported(self, dos_hojas):
        ids = self._ids(dos_hojas)
        response = handle("POST", "/entrada/nueva", address=LAN, store=dos_hojas, form={
            "after_id": str(ids["A1."]), "texto": "A2.", "csrf": token_for(dos_hojas)})
        assert response.status == 200
        assert "ya existe una igual" in response.body.decode()

    def test_every_row_and_every_sheet_offers_it(self, dos_hojas):
        body = handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN,
                      store=dos_hojas).body.decode()
        assert body.count('name="after_id"') == 3
        assert body.count('name="before_id"') == 2
        assert body.count('<details class="anadir-linea">') == 5


class TestTheSummaryIsInTheCommandBar:
    def test_it_renders_inside_the_header(self, store):
        body = handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=store).body.decode()
        cabecera = body[body.index('<header class="barra-comandos">'):body.index("</header>")]
        assert 'class="resumen"' in cabecera
        # Anchored on the element: the stylesheet mentions "<main>" in a comment.
        principal = body[body.index("\n<main>\n"):body.index("\n</main>\n")]
        assert 'class="resumen"' not in principal


class TestEveryMonthAndYearWorks:
    """Nothing in the dashboard may be tied to September or to a list of
    years: it used to loop over a fixed 2026-2030 tuple, so a sheet filed
    under any other year 404'd and its month could never be the newest."""

    @pytest.fixture
    def repartido(self, tmp_path, monkeypatch):
        incoming = tmp_path / "incoming"
        monkeypatch.setattr(config, "incoming_dir", str(incoming))
        with EntryStore(str(tmp_path / "r.sqlite3")) as s:
            for year, month, ref in (("2025", "MARZO", "14-03-2025 p1"),
                                     ("2026", "SEPTIEMBRE", "01-09-2026 p1"),
                                     ("2027", "ENERO", "08-01-2027 p3")):
                s.add(year, month, "Intervenciones Seguridad:",
                      [{"text": f"Linea de {month}.", "confident": False}], "s.pdf", ref)
                revision = revision_dir_for(str(incoming), year, month)
                os.makedirs(revision, exist_ok=True)
                with open(os.path.join(revision, image_name(ref)), "wb") as f:
                    f.write(month.encode())
            yield s

    def test_the_root_goes_to_the_newest_month_whatever_its_year(self, repartido):
        response = handle("GET", "/", address=LAN, store=repartido)
        assert response.headers["Location"] == "/mes/2027/ENERO"

    def test_months_come_back_in_calendar_order(self, repartido):
        assert repartido.months() == [
            ("2025", "MARZO"), ("2026", "SEPTIEMBRE"), ("2027", "ENERO")]

    @pytest.mark.parametrize("ref, esperado", [
        ("14-03-2025_p1.jpg", b"MARZO"),
        ("01-09-2026_p1.jpg", b"SEPTIEMBRE"),
        ("08-01-2027_p3.jpg", b"ENERO"),
    ])
    def test_every_months_sheet_is_served(self, repartido, ref, esperado):
        response = handle("GET", f"/hoja/{ref}", address=LAN, store=repartido)
        assert response.status == 200
        assert response.body == esperado

    @pytest.mark.parametrize("year, month", [("2025", "MARZO"), ("2027", "ENERO")])
    def test_a_line_in_any_month_can_be_saved_and_comes_back_there(
        self, repartido, year, month
    ):
        entry = repartido.month_entries(year, month)[0]
        response = handle("POST", f"/entrada/{entry['id']}", address=LAN, store=repartido,
                          form={"texto": "Corregida.", "csrf": token_for(repartido)})
        assert response.headers["Location"].startswith(f"/mes/{year}/{month}")
        assert repartido.month_entries(year, month)[0]["text"] == "Corregida."

    def test_a_sheet_in_any_month_can_be_turned(self, repartido):
        from PIL import Image
        revision = revision_dir_for(config.incoming_dir, "2025", "MARZO")
        path = os.path.join(revision, "14-03-2025_p1.jpg")
        Image.new("RGB", (40, 20), "white").save(path)
        response = handle("POST", "/hoja/14-03-2025_p1.jpg/girar", address=LAN,
                          store=repartido,
                          form={"grados": "90", "csrf": token_for(repartido)})
        assert response.headers["Location"].startswith("/mes/2025/MARZO?hoja=")
        with Image.open(path) as image:
            assert image.size == (20, 40)


class TestAHandTurnSticks:
    """The turn used to live only in the file, and two things rewrite that
    file: a re-dropped scan (save_review_image overwrites) and
    tools/straighten_revision.py."""

    @pytest.fixture
    def hoja(self, store, tmp_path, monkeypatch):
        from PIL import Image
        incoming = tmp_path / "incoming"
        monkeypatch.setattr(config, "incoming_dir", str(incoming))
        entry = store.month_entries("2026", "SEPTIEMBRE")[0]
        ref = image_name(entry["review_ref"])
        revision = revision_dir_for(str(incoming), "2026", "SEPTIEMBRE")
        os.makedirs(revision, exist_ok=True)
        path = os.path.join(revision, ref)
        Image.new("RGB", (40, 20), "white").save(path)
        return ref, path, revision

    def _turn(self, store, ref, degrees):
        return handle("POST", f"/hoja/{ref}/girar", address=LAN, store=store,
                      form={"grados": str(degrees), "csrf": token_for(store)})

    def test_it_is_recorded(self, store, hoja):
        ref, _, _ = hoja
        self._turn(store, ref, 90)
        self._turn(store, ref, 90)
        assert store.hand_turn(ref) == 180

    def test_turning_back_clears_it(self, store, hoja):
        ref, _, _ = hoja
        self._turn(store, ref, 90)
        self._turn(store, ref, 270)
        assert store.hand_turn(ref) == 0
        assert ref not in store.hand_turned()

    def test_a_re_dropped_scan_keeps_the_turn(self, store, hoja, tmp_path):
        from PIL import Image

        from main import save_review_image
        ref, path, revision = hoja
        self._turn(store, ref, 90)
        # The pipeline writes a fresh, unturned copy of the same page.
        fresh = tmp_path / "pagina.jpg"
        Image.new("RGB", (40, 20), "white").save(fresh)
        save_review_image(str(fresh), "01-09-2026 p1", revision,
                          hand_turn=store.hand_turn(ref))
        with Image.open(path) as image:
            assert image.size == (20, 40)

    def test_the_straighten_tool_leaves_it_alone(self, store, hoja, monkeypatch):
        import importlib.util
        ref, _, revision = hoja
        self._turn(store, ref, 90)
        spec = importlib.util.spec_from_file_location(
            "straighten_revision", os.path.join(os.path.dirname(__file__), "..",
                                                "tools", "straighten_revision.py"))
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        tocados = []
        monkeypatch.setattr(tool, "straighten",
                            lambda p, **k: tocados.append(os.path.basename(p)) or p)
        monkeypatch.setattr(tool, "to_portrait", lambda p: p)
        tool.straighten_folder(revision, store.hand_turned())
        assert ref not in tocados

    def test_pages_are_not_cached(self, store):
        response = handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=store)
        assert response.headers.get("Cache-Control") == "no-store"


class TestGuardarIsAlwaysInSight:
    """It sat at the top of the middle pane, which scrolls -- and opening a
    sheet scrolls that pane to the sheet's heading -- so it was out of view
    nearly every time."""

    def test_it_is_in_the_command_bar(self, store):
        body = handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=store).body.decode()
        cabecera = body[body.index('<header class="barra-comandos">'):body.index("</header>")]
        assert 'id="form-guardar"' in cabecera
        assert 'action="/guardar/2026/SEPTIEMBRE"' in cabecera
        assert 'id="estado-guardado"' in cabecera

    def test_it_is_not_in_the_scrolling_pane(self, store):
        body = handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=store).body.decode()
        documento = body[body.index('<section class="panel-documento">'):]
        documento = documento[:documento.index("</section>")]
        assert "form-guardar" not in documento

    def test_it_keeps_the_open_sheet(self, store):
        entry = store.month_entries("2026", "SEPTIEMBRE")[0]
        ref = image_name(entry["review_ref"])
        body = handle("GET", f"/mes/2026/SEPTIEMBRE?hoja={ref}", address=LAN,
                      store=store).body.decode()
        guardar = body[body.index('id="form-guardar"'):]
        guardar = guardar[:guardar.index("</form>")]
        assert f'name="hoja" value="{ref}"' in guardar

    def test_only_the_month_page_has_it(self, store):
        assert 'id="form-guardar"' not in handle("GET", "/resumen", address=LAN,
                                                 store=store).body.decode()


class TestEveryFeatureInAnotherMonth:
    """Everything built for the September batch, run against March 2025 and
    January 2027 instead, so nothing can quietly depend on the month it was
    written against."""

    @pytest.fixture
    def meses(self, tmp_path, monkeypatch):
        from PIL import Image
        incoming = tmp_path / "incoming"
        monkeypatch.setattr(config, "incoming_dir", str(incoming))
        with EntryStore(str(tmp_path / "m.sqlite3")) as s:
            for year, month, refs in (
                ("2025", "MARZO", ("20-03-2025 p2", "03-03-2025 p1")),
                ("2026", "SEPTIEMBRE", ("01-09-2026 p1",)),
                ("2027", "ENERO", ("08-01-2027 p3",)),
            ):
                for ref in refs:
                    s.add(year, month, "Intervenciones Seguridad:",
                          [{"text": f"Duda {ref}.", "confident": False},
                           {"text": f"Clara {ref}.", "confident": True}], "s.pdf", ref)
                    revision = revision_dir_for(str(incoming), year, month)
                    os.makedirs(revision, exist_ok=True)
                    Image.new("RGB", (40, 20), "white").save(
                        os.path.join(revision, image_name(ref)))
            yield s

    def _get(self, store, url):
        return handle("GET", url, address=LAN, store=store).body.decode()

    def test_every_month_is_listed_and_reachable(self, meses):
        body = self._get(meses, "/mes/2026/SEPTIEMBRE")
        assert 'href="/mes/2025/MARZO"' in body
        assert 'href="/mes/2027/ENERO"' in body
        assert '<span class="mes-actual" aria-current="page">Septiembre</span>' in body

    def test_date_order_and_grouping(self, meses):
        body = self._get(meses, "/mes/2025/MARZO")
        assert body.index("03-03-2025 · página 1") < body.index("20-03-2025 · página 2")
        assert body.count('class="cabecera-hoja') == 2

    def test_whole_batch_and_shortlist(self, meses):
        body = self._get(meses, "/mes/2025/MARZO?hojas=todas")
        assert "Por revisar (2)" in body and "Todas (2)" in body

    def test_opening_a_sheet_lands_on_its_heading(self, meses):
        body = self._get(meses, "/mes/2025/MARZO?hoja=20-03-2025_p2.jpg")
        assert 'id="hoja-20-03-2025_p2.jpg"' in body
        assert 'src="/hoja/20-03-2025_p2.jpg"' in body
        assert "cabecera-hoja actual" in body

    def test_add_a_line_where_it_is_wanted(self, meses):
        ancla = next(e for e in meses.month_entries("2025", "MARZO")
                 if e["text"] == "Duda 03-03-2025 p1.")
        handle("POST", "/entrada/nueva", address=LAN, store=meses, form={
            "after_id": str(ancla["id"]), "texto": "Nueva en marzo.",
            "csrf": token_for(meses)})
        assert meses.entries("2025", "MARZO", "Intervenciones Seguridad:")[:3] == [
            "Duda 03-03-2025 p1.", "Nueva en marzo.", "Clara 03-03-2025 p1."]

    def test_guardar_saves_pending_lines_and_writes_that_months_docx(self, meses):
        from month_folders import memoria_name, processed_dir_for
        linea = meses.month_entries("2027", "ENERO")[0]
        response = handle("POST", "/guardar/2027/ENERO", address=LAN, store=meses, form={
            f"texto-{linea['id']}": "Corregida en enero.", "hoja": "08-01-2027_p3.jpg",
            "csrf": token_for(meses)})
        assert response.status == 303
        assert response.headers["Location"] == "/mes/2027/ENERO?hoja=08-01-2027_p3.jpg"
        assert "Corregida en enero." in meses.entries("2027", "ENERO",
                                                       "Intervenciones Seguridad:")
        docx = os.path.join(processed_dir_for(config.incoming_dir, "2027", "ENERO"),
                            memoria_name("2027", "ENERO"))
        assert os.path.isfile(docx)

    def test_a_turn_is_kept_for_that_month(self, meses):
        handle("POST", "/hoja/08-01-2027_p3.jpg/girar", address=LAN, store=meses,
               form={"grados": "90", "csrf": token_for(meses)})
        assert meses.hand_turn("08-01-2027_p3.jpg") == 90


ELEC = "Electricidad y Alumbrado"
PARK = "Parking"
MREF = "mant 02-09-2026 p1"


def maint_lines(store):
    store.add("2026", "SEPTIEMBRE", ELEC,
              [{"text": "luz rampa", "confident": True, "orden": 0}], "m.pdf", MREF)
    store.add("2026", "SEPTIEMBRE", PARK,
              [{"text": "cargador", "confident": True, "orden": 1}], "m.pdf", MREF)
    return {e["text"]: e["id"] for e in store.month_entries("2026", "SEPTIEMBRE")}


class TestMantenimientoPage:
    def test_whole_month_with_a_filter_bar(self, store):
        maint_lines(store)
        body = handle("GET", "/mantenimiento/2026/SEPTIEMBRE", address=LAN,
                      store=store).body.decode()
        assert "luz rampa" in body and "cargador" in body
        assert 'Todas <span class="cuenta">2</span>' in body

    def test_a_filter_shows_one_tag_and_keeps_the_counts(self, store):
        maint_lines(store)
        body = handle("GET", "/mantenimiento/2026/SEPTIEMBRE?bloque=parking",
                      address=LAN, store=store).body.decode()
        assert "cargador" in body and "luz rampa" not in body
        assert 'Todas <span class="cuenta">2</span>' in body

    def test_an_unknown_filter_shows_everything(self, store):
        maint_lines(store)
        body = handle("GET", "/mantenimiento/2026/SEPTIEMBRE?bloque=%3Cscript%3E",
                      address=LAN, store=store).body.decode()
        assert "luz rampa" in body and "cargador" in body
        assert "&lt;script" not in body and "<script>alert" not in body


class TestRetagRoute:
    def post(self, store, entry_id, **form):
        form.setdefault("csrf", token_for(store))
        form.setdefault("seccion", "mantenimiento")
        return handle("POST", f"/entrada/{entry_id}/bloque", address=LAN,
                      form=form, store=store)

    def test_without_a_token_nothing_changes(self, store):
        ids = maint_lines(store)
        response = handle("POST", f"/entrada/{ids['cargador']}/bloque", address=LAN,
                          form={"etiqueta": "electricidad"}, store=store)
        assert response.status == 403
        assert store.entries("2026", "SEPTIEMBRE", PARK) == ["cargador"]

    def test_moves_the_line_and_returns_to_it(self, store):
        ids = maint_lines(store)
        response = self.post(store, ids["cargador"], etiqueta="electricidad")
        assert response.status in (302, 303)
        location = response.headers["Location"]
        assert location.startswith("/mantenimiento/2026/SEPTIEMBRE")
        assert location.endswith(f"#entrada-{ids['cargador']}")
        assert store.entries("2026", "SEPTIEMBRE", ELEC) == ["luz rampa", "cargador"]

    def test_the_filter_and_the_open_sheet_survive(self, store):
        ids = maint_lines(store)
        hoja = image_name(MREF)
        response = self.post(store, ids["cargador"], etiqueta="otros",
                             bloque="parking", hoja=hoja)
        location = response.headers["Location"]
        assert "bloque=parking" in location
        assert "hoja=" in location

    def test_a_bad_tag_is_refused(self, store):
        ids = maint_lines(store)
        assert self.post(store, ids["cargador"], etiqueta="seguridad").status == 400
        assert store.entries("2026", "SEPTIEMBRE", PARK) == ["cargador"]

    def test_a_security_line_is_refused(self, store):
        entry = store.month_entries("2026", "SEPTIEMBRE")[0]  # the fixture's line
        assert self.post(store, entry["id"], etiqueta="parking").status == 400

    def test_a_missing_line_is_not_found(self, store):
        assert self.post(store, 999999, etiqueta="parking").status == 404

    def test_pending_edits_ride_along(self, store):
        ids = maint_lines(store)
        self.post(store, ids["cargador"], etiqueta="otros",
                  **{f"texto-{ids['luz rampa']}": "luz de la rampa"})
        texts = [e["text"] for e in store.month_entries("2026", "SEPTIEMBRE")]
        assert "luz de la rampa" in texts

    def test_a_collision_changes_nothing_and_explains(self, store):
        ids = maint_lines(store)
        store.add("2026", "SEPTIEMBRE", ELEC,
                  [{"text": "Cargador.", "confident": True, "orden": 0}], "m.pdf",
                  "mant 05-09-2026 p3")
        response = self.post(store, ids["cargador"], etiqueta="electricidad")
        body = response.body.decode()
        assert response.status == 200
        assert "ya hay una línea igual en Electricidad" in body
        assert "05-09-2026 p3" in body
        assert store.entries("2026", "SEPTIEMBRE", PARK) == ["cargador"]


def test_guardar_keeps_the_tag_filter(store):
    maint_lines(store)
    body = handle("GET", "/mantenimiento/2026/SEPTIEMBRE?bloque=parking",
                  address=LAN, store=store).body.decode()
    guardar = body[body.index('action="/guardar/2026/SEPTIEMBRE"'):]
    guardar = guardar[:guardar.index("</form>")]
    assert 'name="bloque" value="parking"' in guardar


class TestMaintenanceMode:
    @pytest.fixture
    def flag(self, tmp_path, monkeypatch):
        import dashboard
        path = tmp_path / "MANTENIMIENTO"
        monkeypatch.setattr(dashboard, "_maintenance_flag", lambda: str(path))
        return path

    def test_off_by_default(self, store, flag):
        assert handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=store).status == 200

    def test_the_lan_sees_the_message(self, store, flag):
        flag.touch()
        response = handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=store)
        body = response.body.decode()
        assert response.status == 503
        assert response.headers.get("Retry-After") == "30"
        assert "Panel en mantenimiento" in body
        assert 'http-equiv="refresh" content="30"' in body
        assert "Se retiran pelonas." not in body, "no data behind the message"

    def test_every_route_is_closed_to_the_lan(self, store, flag):
        flag.touch()
        for path in ("/", "/mantenimiento", "/resumen", "/hoja/x.jpg"):
            assert handle("GET", path, address=LAN, store=store).status == 503, path

    def test_a_write_from_the_lan_is_refused_and_said_so(self, store, flag):
        entry = store.month_entries("2026", "SEPTIEMBRE")[0]
        token = token_for(store)
        flag.touch()
        response = handle("POST", f"/entrada/{entry['id']}", address=LAN,
                          form={"texto": "Se retiran pilonas.", "csrf": token}, store=store)
        assert response.status == 503
        assert "no se ha guardado" in response.body.decode()
        assert store.month_entries("2026", "SEPTIEMBRE")[0]["text"] == "Se retiran pelonas."

    def test_tailscale_sees_the_dashboard_with_a_reminder(self, store, flag):
        flag.touch()
        response = handle("GET", "/mes/2026/SEPTIEMBRE", address=TAILNET, store=store)
        body = response.body.decode()
        assert response.status == 200
        assert "Se retiran pelonas." in body
        assert "Modo mantenimiento activo" in body

    def test_no_reminder_when_off(self, store, flag):
        body = handle("GET", "/mes/2026/SEPTIEMBRE", address=TAILNET, store=store).body.decode()
        assert "Modo mantenimiento activo" not in body

    def test_an_outside_address_is_still_refused_first(self, store, flag):
        flag.touch()
        assert handle("GET", "/", address=OUTSIDE, store=store).status == 403

    def test_turning_it_off_brings_the_dashboard_back(self, store, flag):
        flag.touch()
        assert handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=store).status == 503
        flag.unlink()
        assert handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=store).status == 200


def test_the_flag_lives_beside_the_database(monkeypatch):
    import dashboard
    monkeypatch.setattr(config, "entry_db", "/opt/app/state/memoria_entries.sqlite3")
    assert dashboard._maintenance_flag() == "/opt/app/state/MANTENIMIENTO"


class TestDeferredMinorRoutes:
    def post(self, store, entry_id, **form):
        form.setdefault("csrf", token_for(store))
        form.setdefault("seccion", "mantenimiento")
        return handle("POST", f"/entrada/{entry_id}/bloque", address=LAN,
                      form=form, store=store)

    def test_the_other_line_link_shows_its_own_tag(self, store):
        ids = maint_lines(store)
        store.add("2026", "SEPTIEMBRE", ELEC,
                  [{"text": "Cargador.", "confident": True, "orden": 0}], "m.pdf",
                  "mant 05-09-2026 p3")
        body = self.post(store, ids["cargador"], etiqueta="electricidad",
                         bloque="parking").body.decode()
        enlace = body[:body.index(">Ver la otra línea")]
        enlace = enlace[enlace.rindex("href="):]
        assert "bloque=electricidad" in enlace and "bloque=parking" not in enlace

    def test_a_line_moved_out_of_the_filter_lands_on_its_neighbour(self, store):
        store.add("2026", "SEPTIEMBRE", PARK,
                  [{"text": t, "confident": True, "orden": i}
                   for i, t in enumerate(("uno", "dos", "tres"))], "m.pdf", MREF)
        ids = {e["text"]: e["id"] for e in store.month_entries("2026", "SEPTIEMBRE")}
        location = self.post(store, ids["dos"], etiqueta="otros",
                             bloque="parking").headers["Location"]
        assert "bloque=parking" in location and "movida=otros" in location
        assert location.endswith(f"#entrada-{ids['tres']}")
        last = self.post(store, ids["tres"], etiqueta="otros",
                         bloque="parking").headers["Location"]
        assert last.endswith(f"#entrada-{ids['uno']}"), "the last one lands on the one before"

    def test_the_page_says_where_the_line_went(self, store):
        maint_lines(store)
        body = handle("GET", "/mantenimiento/2026/SEPTIEMBRE?bloque=parking&movida=otros",
                      address=LAN, store=store).body.decode()
        assert 'class="aviso-movida"' in body and "Línea movida a <strong>Otros</strong>" in body

    def test_an_unknown_movida_is_ignored(self, store):
        maint_lines(store)
        body = handle("GET", "/mantenimiento/2026/SEPTIEMBRE?movida=%3Cb%3E",
                      address=LAN, store=store).body.decode()
        assert "aviso-movida" not in body.split("<style>")[0] + body.split("</style>")[-1]

    def test_a_retag_within_the_filter_needs_no_notice(self, store):
        ids = maint_lines(store)
        location = self.post(store, ids["cargador"], etiqueta="otros").headers["Location"]
        assert "movida" not in location
