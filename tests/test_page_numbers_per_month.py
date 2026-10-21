"""Seguridad and Mantenimiento number their sheets each on their own.

The month's first maintenance sheet is "DD-MM-YYYY p1", the next day's p2,
whatever the security sheets are numbered -- as the colleague reads them.
Two sheets can then share date and number, so a maintenance sheet carries
a prefix the dashboard never shows: "mant 01-09-2026 p2", image
"mant_01-09-2026_p2.jpg". Without it, September 30's maintenance sheet of
01-09 took the security sheet's name, overwrote its image, and showed in
both sections.
"""

import pytest

from nettune.report.entry_store import EntryStore, review_line, sheet_order
from nettune.report.review_marks import (
    image_name,
    is_maintenance_ref,
    locator,
    plain_ref,
)


class TestTheName:
    def test_a_maintenance_sheet_is_marked(self):
        assert locator("01-09-2026", 1, "S25C.pdf", maintenance=True) == "mant 01-09-2026 p1"
        assert locator("01-09-2026", 1, "SKM.pdf") == "01-09-2026 p1"

    def test_the_two_never_share_an_image(self):
        assert image_name("mant 01-09-2026 p2") == "mant_01-09-2026_p2.jpg"
        assert image_name("01-09-2026 p2") == "01-09-2026_p2.jpg"

    def test_an_undated_maintenance_sheet_keeps_its_mark(self):
        assert image_name("mant S25C-0i26093013070 p4") == "mant_sin-fecha_p4.jpg"

    def test_the_mark_is_recognised_and_removed_for_display(self):
        assert is_maintenance_ref("mant 01-09-2026 p2")
        assert not is_maintenance_ref("01-09-2026 p2")
        assert plain_ref("mant 01-09-2026 p2") == "01-09-2026 p2"
        assert plain_ref("01-09-2026 p2") == "01-09-2026 p2"

    def test_it_sorts_by_date_like_any_sheet(self):
        refs = ["mant 03-09-2026 p3", "mant 01-09-2026 p1", "mant 02-09-2026 p2"]
        assert sorted(refs, key=sheet_order) == [
            "mant 01-09-2026 p1", "mant 02-09-2026 p2", "mant 03-09-2026 p3"]

    def test_the_memoria_says_which_sheet(self):
        assert "hoja de mantenimiento del 01-09-2026" in review_line("mant 01-09-2026 p2", 1)
        assert "hoja del 01-09-2026" in review_line("01-09-2026 p2", 1)


class TestTheNumbering:
    def test_a_month_with_nothing_in_it_starts_at_zero(self, tmp_path):
        with EntryStore(str(tmp_path / "e.sqlite3")) as store:
            assert store.last_page("2026", "SEPTIEMBRE") == 0
            assert store.last_page("2026", "SEPTIEMBRE", maintenance=True) == 0

    def test_each_section_counts_its_own(self, tmp_path):
        with EntryStore(str(tmp_path / "e.sqlite3")) as store:
            store.record_sheet("2026", "SEPTIEMBRE", "SKM.pdf", 84, "21-09-2026 p84")
            store.record_sheet("2026", "SEPTIEMBRE", "S25C.pdf", 3, "mant 02-09-2026 p3")
            assert store.last_page("2026", "SEPTIEMBRE") == 84
            assert store.last_page("2026", "SEPTIEMBRE", maintenance=True) == 3
            # A scan read again numbers as it did the first time.
            assert store.last_page("2026", "SEPTIEMBRE", excluding="S25C.pdf",
                                   maintenance=True) == 0


def test_the_processor_numbers_maintenance_from_one(app, tmp_path, monkeypatch):
    import os

    from conftest import a_page

    from nettune.intake.processed_ledger import ProcessedLedger
    from nettune.ops.spend_guard import SpendGuard
    from nettune.report.entry_store import EntryStore

    fechas = iter(["01-09-2026", "02-09-2026"])

    def reading(image, **kw):
        page = a_page(fecha=next(fechas))
        page["tipo"] = "mantenimiento"
        return page

    monkeypatch.setattr(app, "page_images", lambda path, workdir: [path, path])
    monkeypatch.setattr(app, "read_page_with_consensus", reading)
    monkeypatch.setattr(app, "filter_page", lambda page, **kw: page)
    monkeypatch.setattr(app, "already_read", lambda *a, **k: [])

    with EntryStore(str(tmp_path / "state" / "e.sqlite3")) as store:
        store.record_sheet("2026", "SEPTIEMBRE", "SKM.pdf", 2, "01-09-2026 p2")
        scan = os.path.join(app.incoming, "2026", "SEPTIEMBRE", "S25C.pdf")
        with open(scan, "wb") as handle:
            handle.write(b"%PDF maintenance")
        ledger = ProcessedLedger(str(tmp_path / "state" / "p.sqlite3"))
        guard = SpendGuard(str(tmp_path / "state" / "s.sqlite3"), 5, 1.1)
        assert app.process_scan(scan, ledger, guard, store) == "processed"
        assert sorted(store.source_sheets("2026", "SEPTIEMBRE", "S25C.pdf").values()) == [
            "mant 01-09-2026 p1", "mant 02-09-2026 p2"]
        assert store.source_sheets("2026", "SEPTIEMBRE", "SKM.pdf") == {2: "01-09-2026 p2"}


def test_marking_a_scan_read_before_moves_its_lines_and_leaves_the_other(tmp_path):
    with EntryStore(str(tmp_path / "e.sqlite3")) as store:
        store.record_sheet("2026", "SEPTIEMBRE", "SKM.pdf", 2, "01-09-2026 p2")
        store.record_sheet("2026", "SEPTIEMBRE", "S25C.pdf", 2, "01-09-2026 p2")
        store.add("2026", "SEPTIEMBRE", "Otros",
                  [{"text": "Con Digi para local 17.", "confident": True}],
                  "S25C.pdf", "01-09-2026 p2")
        store.add("2026", "SEPTIEMBRE", "Intervenciones Seguridad:",
                  [{"text": "Se abre Z6.", "confident": True}],
                  "SKM.pdf", "01-09-2026 p2")

        moved = store.mark_maintenance("2026", "SEPTIEMBRE", "S25C.pdf")

        assert moved == [("01-09-2026 p2", "mant 01-09-2026 p2")]
        refs = {e["text"]: e["review_ref"] for e in store.month_entries("2026", "SEPTIEMBRE")}
        assert refs["Con Digi para local 17."] == "mant 01-09-2026 p2"
        assert refs["Se abre Z6."] == "01-09-2026 p2"
        assert store.mark_maintenance("2026", "SEPTIEMBRE", "S25C.pdf") == [], "once only"


def test_redating_a_maintenance_sheet_keeps_its_mark(tmp_path):
    with EntryStore(str(tmp_path / "e.sqlite3")) as store:
        store.record_sheet("2026", "SEPTIEMBRE", "S25C.pdf", 1, "mant 31-07-2026 p1")
        new = store.redate_sheet("2026", "SEPTIEMBRE", "mant 31-07-2026 p1", "01-09-2026")
        assert new == "mant 01-09-2026 p1"


@pytest.mark.parametrize("ref", ["mant 01-09-2026 p2", "01-09-2026 p2"])
def test_dashboard_labels_never_show_the_mark(ref):
    from nettune.review.dashboard_html import _page_label, _sheet_link_label, _sheet_short_label

    for label in (_sheet_link_label(ref), _page_label(ref), _sheet_short_label(ref)):
        assert "mant" not in label


def test_the_open_sheet_shows_no_mark_either(tmp_path):
    import re

    from nettune.review.dashboard import handle

    with EntryStore(str(tmp_path / "e.sqlite3")) as store:
        store.record_sheet("2026", "SEPTIEMBRE", "S25C.pdf", 2, "mant 01-09-2026 p2")
        store.add("2026", "SEPTIEMBRE", "Otros",
                  [{"text": "Con Digi para local 17.", "confident": False}],
                  "S25C.pdf", "mant 01-09-2026 p2")
        body = handle("GET", "/mantenimiento/2026/SEPTIEMBRE?hoja=mant_01-09-2026_p2.jpg",
                      address="192.168.50.41", store=store).body.decode()
    assert 'src="/hoja/mant_01-09-2026_p2.jpg"' in body, "the sheet did open"
    body = re.sub(r"<script.*?</script>|<style.*?</style>", "", body, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", body)
    shown = " ".join([text, *re.findall(r'(?:title|alt|aria-label)="([^"]*)"', body)])
    assert not re.search(r"\bmant[ _]", shown)


def test_each_sections_sheets_to_check_are_listed_in_its_own_part(app, tmp_path):
    import os

    from nettune.report.entry_store import EntryStore
    from nettune.report.memoria import SEGURIDAD_BLOCK, block_contents

    template = os.path.join(os.path.dirname(__file__), "..", "templates", "MEMORIA.docx")
    if not os.path.exists(template):
        import pytest
        pytest.skip("template absent")
    app.config.template_path = os.path.abspath(template)
    with EntryStore(str(tmp_path / "e.sqlite3")) as store:
        store.add("2026", "SEPTIEMBRE", "Otros",
                  [{"text": "Con Digi para local 17.", "confident": False}],
                  "S25C.pdf", "mant 01-09-2026 p2")
        store.add("2026", "SEPTIEMBRE", SEGURIDAD_BLOCK,
                  [{"text": "Se abre Z6.", "confident": False}],
                  "SKM.pdf", "01-09-2026 p2")
        path = app.rebuild_memoria(store, "2026", "SEPTIEMBRE", draft=True)
    blocks = block_contents(path)
    assert any("hoja de mantenimiento del 01-09-2026" in line for line in blocks["Otros"])
    assert not any("mantenimiento" in line for line in blocks[SEGURIDAD_BLOCK])
    assert any("Revisar la hoja del 01-09-2026" in line for line in blocks[SEGURIDAD_BLOCK])


def test_suggested_dates_never_carry_the_mark(tmp_path):
    with EntryStore(str(tmp_path / "e.sqlite3")) as store:
        for page, fecha in enumerate(("01-09-2026", "02-09-2026", "13-09-2026",
                                      "04-09-2026", "05-09-2026"), start=1):
            store.record_sheet("2026", "SEPTIEMBRE", "S25C.pdf", page, f"mant {fecha} p{page}")
        suggestions = store.date_checks("2026", "SEPTIEMBRE")
    assert suggestions, "the misread 13-09 is questioned"
    for dates in suggestions.values():
        assert all(not d.startswith("mant") for d in dates)


def test_every_sheet_has_one_section(tmp_path):
    """The rule the dashboard tabs and the email both use."""
    with EntryStore(str(tmp_path / "e.sqlite3")) as store:
        store.record_sheet("2026", "SEPTIEMBRE", "SKM.pdf", 1, "01-09-2026 p1")
        store.record_sheet("2026", "SEPTIEMBRE", "S25C.pdf", 1, "mant 01-09-2026 p1")
        # From before the mark: a maintenance scan known by where its lines went.
        store.record_sheet("2026", "SEPTIEMBRE", "OLD.pdf", 1, "02-09-2026 p9")
        store.add("2026", "SEPTIEMBRE", "Parking",
                  [{"text": "Con la obra del parking.", "confident": True}],
                  "OLD.pdf", "02-09-2026 p9")
        assert store.sheet_sections("2026", "SEPTIEMBRE") == {
            "01-09-2026 p1": "seguridad",
            "mant 01-09-2026 p1": "mantenimiento",
            "02-09-2026 p9": "mantenimiento",
        }


def test_a_sheet_whose_date_does_not_fit_stays_to_check_until_answered(tmp_path):
    """Its lines are no longer flagged for the date; the date itself keeps the
    sheet in Por revisar -- and the final document waiting -- until a person
    confirms or corrects it."""
    with EntryStore(str(tmp_path / "e.sqlite3")) as store:
        for page, fecha in enumerate(("01-09-2026", "02-09-2026", "13-09-2026",
                                      "04-09-2026", "05-09-2026"), start=1):
            ref = f"mant {fecha} p{page}"
            store.record_sheet("2026", "SEPTIEMBRE", "S25C.pdf", page, ref)
            store.add("2026", "SEPTIEMBRE", "Otros",
                      [{"text": f"Revisando cuadros electricos {page}.", "confident": True}],
                      "S25C.pdf", ref)
        assert list(store.to_check("2026", "SEPTIEMBRE")) == ["mant 13-09-2026 p3"]
        store.redate_sheet("2026", "SEPTIEMBRE", "mant 13-09-2026 p3", "03-09-2026")
        assert store.to_check("2026", "SEPTIEMBRE") == {}


def test_the_sidebar_does_not_tick_a_sheet_whose_date_is_open(tmp_path):
    from nettune.review.dashboard import handle

    with EntryStore(str(tmp_path / "e.sqlite3")) as store:
        for page, fecha in enumerate(("01-09-2026", "02-09-2026", "13-09-2026",
                                      "04-09-2026", "05-09-2026"), start=1):
            ref = f"mant {fecha} p{page}"
            store.record_sheet("2026", "SEPTIEMBRE", "S25C.pdf", page, ref)
            store.add("2026", "SEPTIEMBRE", "Otros",
                      [{"text": f"Revisando cuadros electricos {page}.", "confident": True}],
                      "S25C.pdf", ref)
        body = handle("GET", "/mantenimiento/2026/SEPTIEMBRE", address="192.168.50.41",
                      store=store).body.decode()
    row = body[body.index('data-hoja="mant_13-09-2026_p3.jpg"'):]
    row = row[:row.index("</a>")]
    assert "Fecha por confirmar" in row
    assert "Revisada" not in row
