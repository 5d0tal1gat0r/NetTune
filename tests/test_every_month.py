"""A whole month's batch, run end to end for every month of several years.

Nothing in the pipeline may assume September 2026: 28, 29, 30 and 31 day
months, a leap February, and the turn of the year must all file, date,
number, render and build a memoria the same way.
"""

import calendar
import os
from datetime import date, datetime

import pytest
from PIL import Image, ImageDraw

import main
import month_folders
from config import config
from dashboard import handle
from document_type import SEGURIDAD
from entry_store import EntryStore
from month_folders import MONTH_FOLDERS, memoria_name, processed_dir_for, revision_dir_for
from processed_ledger import ProcessedLedger
from spend_guard import SpendGuard

TEMPLATE = os.path.abspath("templates/MEMORIA.docx")
LAN = "192.168.50.41"
# The scanner's order within a day, which is not the shifts' order.
SCAN_HOURS = ("15:00", "07:00", "18:00", "22:00")

CASES = [(2026, m) for m in range(1, 13)] + [(2027, 2), (2027, 12), (2028, 2), (2028, 1)]


class _Clock(datetime):
    """The calendar as it will be when the case's month is current."""
    year_now = 2026

    @classmethod
    def now(cls, tz=None):
        return datetime(cls.year_now, 12, 31, 12, 0, tzinfo=tz)


@pytest.fixture
def run(tmp_path, monkeypatch):
    if not os.path.exists(TEMPLATE):
        pytest.skip("template absent")
    monkeypatch.setattr(config, "incoming_dir", str(tmp_path / "incoming"))
    monkeypatch.setattr(config, "template_path", TEMPLATE)
    monkeypatch.setattr(config, "enable_filter_stage", False)
    monkeypatch.setattr(main, "wait_for_file_stable", lambda p, timeout=0: True)
    monkeypatch.setattr(month_folders, "datetime", _Clock)

    def go(year, month_number, days=None, folder=None, first=1):
        _Clock.year_now = year
        month = MONTH_FOLDERS[month_number - 1]
        days = days or calendar.monthrange(year, month_number)[1]
        sheets, pages = [], []
        workdir = tmp_path / "sheets" / f"{year}-{month_number}"
        workdir.mkdir(parents=True, exist_ok=True)
        for offset in range(days):
            day = date(year, month_number, first) + (date(2000, 1, 2) - date(2000, 1, 1)) * offset
            for hour in SCAN_HOURS:
                path = str(workdir / f"{len(sheets)}.jpg")
                image = Image.new("L", (300, 420), 255)
                draw = ImageDraw.Draw(image)
                # Written where the handwriting goes, different on every sheet.
                for line in range(8):
                    draw.text((30 + (len(sheets) * 7 + line * 13) % 90, 100 + line * 26),
                              f"{day} {hour} {line * len(sheets)}", fill=0)
                image.save(path)
                sheets.append(path)
                pages.append({
                    "fecha": day.strftime("%d-%m-%Y"), "fecha_confident": True,
                    "fecha_variants": [day.strftime("%d-%m-%Y")], "horario": hour,
                    "tipo": SEGURIDAD, "operarios": [], "readings": 2,
                    "trabajos": [{"text": f"Se observa humo en zona 4 el {day:%d-%m-%Y} "
                                          f"turno {hour}", "confident": True, "variants": []}],
                })
        readings = iter(pages)
        monkeypatch.setattr(main, "page_images", lambda path, workdir: list(sheets))
        monkeypatch.setattr(main, "read_page_with_consensus", lambda *a, **k: next(readings))

        parts = folder if folder is not None else (str(year), month)
        scan = os.path.join(config.incoming_dir, *parts, f"SKM_{year}{month_number:02d}.pdf")
        os.makedirs(os.path.dirname(scan), exist_ok=True)
        with open(scan, "wb") as handle_:
            handle_.write(f"{year}-{month_number}".encode())
        state = tmp_path / "state"
        state.mkdir(exist_ok=True)
        ledger = ProcessedLedger(str(state / "p.sqlite3"))
        guard = SpendGuard(str(state / "s.sqlite3"), 5, 1.1)
        store = EntryStore(str(state / "e.sqlite3"))
        outcome = main.process_scan(scan, ledger, guard, store)
        return outcome, store, str(year), month, days

    return go


def _save(store, year, month):
    body = handle("GET", f"/mes/{year}/{month}", address=LAN, store=store).body.decode()
    start = body.index('name="csrf" value="') + len('name="csrf" value="')
    token = body[start:body.index('"', start)]
    return handle("POST", f"/guardar/{year}/{month}", address=LAN, store=store,
                  form={"csrf": token})


@pytest.mark.parametrize("year,month_number", CASES)
def test_a_whole_month_files_dates_and_builds(run, year, month_number):
    outcome, store, year_s, month, days = run(year, month_number)
    try:
        assert outcome == "processed"
        # Four sheets a day, every day, named by date and numbered in shift
        # order across the month.
        refs = [ref for _, ref in sorted(store.scan_positions(year_s, month, f"SKM_{year}"
                                                               f"{month_number:02d}.pdf").items())]
        assert len(refs) == days * 4
        expected = {f"{d:02d}-{month_number:02d}-{year} p{(d - 1) * 4 + k}"
                    for d in range(1, days + 1) for k in range(1, 5)}
        assert set(refs) == expected
        revision = revision_dir_for(config.incoming_dir, year_s, month)
        assert len(os.listdir(revision)) == days * 4
        # The document lists the month's lines in the order the shifts ran.
        lines = store.month_entries(year_s, month)
        assert len(lines) == days * 4
        first_day = [e["text"].split("turno ")[1] for e in lines[:4]]
        assert first_day == ["07:00", "15:00", "18:00", "22:00"]
        assert lines[-1]["text"].startswith(f"Se observa humo en zona 4 el {days:02d}-")
        # No date queried: the batch runs straight through the month.
        assert store.date_checks(year_s, month) == {}
        # No document until the month has been reviewed; every sheet here
        # reads cleanly, so the first Guardar writes it where the colleague
        # looks for it.
        built = os.path.join(processed_dir_for(config.incoming_dir, year_s, month),
                             memoria_name(year_s, month))
        assert not os.path.exists(built)
        assert store.to_check(year_s, month) == {}
        assert _save(store, year_s, month).status == 303
        assert os.path.isfile(built)
        # And the dashboard serves the month, and every sheet in it.
        page = handle("GET", f"/mes/{year_s}/{month}", address=LAN, store=store)
        assert page.status == 200
        body = page.body.decode()
        assert body.count('class="cabecera-hoja') == days * 4
        last = f"{days:02d}-{month_number:02d}-{year}_p{days * 4}.jpg"
        sheet = handle("GET", f"/mes/{year_s}/{month}?hoja={last}", address=LAN, store=store)
        assert sheet.status == 200 and f"/hoja/{last}" in sheet.body.decode()
        assert handle("GET", f"/hoja/{last}", address=LAN, store=store).status == 200
    finally:
        store.close()


def test_a_scan_in_the_year_folder_only_files_itself_by_its_dates(run):
    outcome, store, *_ = run(2027, 12, folder=("2027",))
    try:
        assert outcome == "processed"
        assert store.months() and ("2027", "DICIEMBRE") in store.months()
    finally:
        store.close()


def test_a_scan_at_the_root_in_january_files_itself(run):
    outcome, store, *_ = run(2027, 1, folder=())
    try:
        assert outcome == "processed"
        assert ("2027", "ENERO") in store.months()
    finally:
        store.close()


class TestABatchOverTheEndOfTheMonth:
    def test_the_new_years_sheets_go_to_january(self, run):
        outcome, store, *_ = run(2026, 12, days=6, first=29)
        try:
            assert outcome == "processed"
            december = {e["review_ref"][:10] for e in store.month_entries("2026", "DICIEMBRE")}
            january = {e["review_ref"][:10] for e in store.month_entries("2027", "ENERO")}
            assert december == {"29-12-2026", "30-12-2026", "31-12-2026"}
            assert january == {"01-01-2027", "02-01-2027", "03-01-2027"}
            for year, month in (("2026", "DICIEMBRE"), ("2027", "ENERO")):
                _save(store, year, month)
                assert os.path.isfile(os.path.join(
                    processed_dir_for(config.incoming_dir, year, month),
                    memoria_name(year, month)))
                assert len(os.listdir(revision_dir_for(config.incoming_dir, year, month))) == 12
                assert store.date_checks(year, month) == {}
                assert handle("GET", f"/mes/{year}/{month}", address=LAN,
                              store=store).status == 200
        finally:
            store.close()

    def test_a_february_batch_into_march_in_a_leap_year(self, run):
        outcome, store, *_ = run(2028, 2, days=3, first=28)
        assert outcome == "processed"
        try:
            assert {e["review_ref"][:10] for e in store.month_entries("2028", "FEBRERO")} == {
                "28-02-2028", "29-02-2028"}
            assert {e["review_ref"][:10] for e in store.month_entries("2028", "MARZO")} == {
                "01-03-2028"}
        finally:
            store.close()


class TestFilingMonths:
    def pages(self, *dates):
        return [{"fecha": d} for d in dates]

    def test_one_misread_date_does_not_move_a_sheet(self):
        from batch_dates import filing_months
        pages = self.pages(*(["01-09-2026"] * 4 + ["31-08-2026"] + ["02-09-2026"] * 3))
        assert set(filing_months(pages, "2026", "SEPTIEMBRE", 4)) == {("2026", "SEPTIEMBRE")}

    def test_a_whole_batch_in_the_wrong_folder_goes_to_its_month(self):
        from batch_dates import filing_months
        pages = self.pages(*(["01-10-2026"] * 4 + ["02-10-2026"] * 4))
        assert set(filing_months(pages, "2026", "SEPTIEMBRE", 4)) == {("2026", "OCTUBRE")}

    def test_a_month_further_away_is_a_misreading_and_stays(self):
        from batch_dates import filing_months
        pages = self.pages(*(["01-09-2026"] * 4 + ["05-11-2026"] * 4))
        assert set(filing_months(pages, "2026", "SEPTIEMBRE", 4)) == {("2026", "SEPTIEMBRE")}

    def test_undated_sheets_stay_in_the_folder(self):
        from batch_dates import filing_months
        pages = self.pages(*(["01-10-2026"] * 4 + [None]))
        assert filing_months(pages, "2026", "SEPTIEMBRE", 4)[-1] == ("2026", "SEPTIEMBRE")


class TestTheDashboardMonths:
    @pytest.mark.parametrize("path", ["/mes/2026/FOO", "/mes/abcd/ENERO", "/mes/26/ENERO",
                                      "/mes/2026/septiembre"])
    def test_a_month_that_is_not_one_is_not_found(self, path, tmp_path):
        with EntryStore(str(tmp_path / "e.sqlite3")) as store:
            assert handle("GET", path, address=LAN, store=store).status == 404

    def test_saving_a_month_that_is_not_one_writes_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "incoming_dir", str(tmp_path / "incoming"))
        with EntryStore(str(tmp_path / "e.sqlite3")) as store:
            body = handle("GET", "/mes/2026/ENERO", address=LAN, store=store).body.decode()
            start = body.index('name="csrf" value="') + len('name="csrf" value="')
            token = body[start:body.index('"', start)]
            response = handle("POST", "/guardar/2026/FOO", address=LAN, store=store,
                              form={"csrf": token})
            assert response.status == 404
            assert not os.path.exists(os.path.join(config.incoming_dir, "2026", "FOO"))

    @pytest.mark.parametrize("month", MONTH_FOLDERS)
    def test_every_month_of_another_year_opens_even_when_empty(self, month, tmp_path):
        with EntryStore(str(tmp_path / "e.sqlite3")) as store:
            assert handle("GET", f"/mes/2031/{month}", address=LAN, store=store).status == 200


class TestThePromptKnowsTheYear:
    @pytest.mark.parametrize("today,now,before", [
        (date(2026, 9, 29), "2026", "2025"), (date(2027, 1, 3), "2027", "2026"),
        (date(2031, 6, 1), "2031", "2030"),
    ])
    def test_the_years_follow_the_calendar(self, today, now, before):
        from transcription_service import load_prompt, with_year
        prompt = with_year(load_prompt("transcription.md"), today)
        assert f"de {now}, o de {before}" in prompt
        assert "{AÑO" not in prompt

    def test_no_year_is_written_into_the_prompt(self):
        with open("prompts/transcription.md", encoding="utf-8") as handle:
            text = handle.read()
        import re
        assert not re.search(r"\b20[0-9]{2}\b", text)


class TestDroppedAnywhere:
    """The PDF can be dropped anywhere in the share; its sheets say where it goes."""

    def test_in_the_wrong_months_folder_it_goes_to_its_own(self, run):
        outcome, store, *_ = run(2026, 9, days=3, folder=("2026", "ENERO"))
        try:
            assert outcome == "processed"
            assert store.months() == [("2026", "SEPTIEMBRE")]
            archive = os.path.join(config.incoming_dir, "2026", "SEPTIEMBRE", ".escaneos_originales")
            assert os.listdir(archive) == ["SKM_202609.pdf"]
            assert not os.path.exists(os.path.join(config.incoming_dir, "2026", "ENERO",
                                                   "SKM_202609.pdf"))
        finally:
            store.close()

    def test_in_a_folder_of_its_own_making(self, run):
        outcome, store, *_ = run(2026, 9, days=2, folder=("Nueva carpeta", "escaneos"))
        try:
            assert outcome == "processed"
            assert store.months() == [("2026", "SEPTIEMBRE")]
            assert os.listdir(os.path.join(config.incoming_dir, "2026", "SEPTIEMBRE",
                                           ".escaneos_originales")) == ["SKM_202609.pdf"]
        finally:
            store.close()

    def test_the_same_file_dropped_again_goes_beside_its_month_unread(self, run, tmp_path):
        from processed_ledger import ProcessedLedger
        outcome, store, *_ = run(2026, 9, days=1, folder=())
        store.close()
        assert outcome == "processed"
        again = os.path.join(config.incoming_dir, "SKM_202609.pdf")
        with open(again, "wb") as handle_:
            handle_.write(b"2026-9")            # byte for byte the same file

        class Loose:
            def forget(self, path):
                pass
            record_failure = forget

        sent = []

        class Notes:
            def busy(self):
                pass

            def already_read(self, name):
                sent.append((name,))

        ledger = ProcessedLedger(str(tmp_path / "state" / "p.sqlite3"))
        with EntryStore(str(tmp_path / "state" / "e.sqlite3")) as store:
            result = main.handle_candidate(again, ledger, Loose(), Loose(), None, store, Notes())
        assert result == "duplicate"
        assert os.listdir(os.path.join(config.incoming_dir, "2026", "SEPTIEMBRE",
                                       ".duplicados")) == ["SKM_202609.pdf"]
        assert sent and sent[0][0] == "SKM_202609.pdf"

    def test_a_rescan_dropped_at_the_top_is_found_in_this_months_sheets(
            self, run, tmp_path, monkeypatch):
        outcome, store, *_ = run(2026, 9, days=1, folder=())
        store.close()
        assert outcome == "processed"

        class September(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 9, 29, 12, tzinfo=tz)

        monkeypatch.setattr(main, "datetime", September)
        # The same paper, scanned again: a different file.
        outcome, store, *_ = run(2026, 9, days=1, folder=("otro",))
        store.close()
        assert outcome == "duplicate-paper"
        assert os.listdir(os.path.join(config.incoming_dir, "2026", "SEPTIEMBRE",
                                       ".duplicados")) == ["SKM_202609.pdf"]
