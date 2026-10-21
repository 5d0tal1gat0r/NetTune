"""Four sheets a day: dating a batch by position rather than by the reading."""

import importlib.util
import os
from datetime import date, timedelta

import pytest

from nettune.config import config
from nettune.dates.batch_dates import date_pages_by_position, dates_by_position
from nettune.report.entry_store import EntryStore
from nettune.report.month_folders import revision_dir_for
from nettune.report.review_marks import image_name

SRC = "SKM_4.pdf"


def _september(n_sheets, per_day=4, first=1, phase=0):
    return [date(2026, 9, first) + timedelta(days=(i + phase) // per_day)
            for i in range(n_sheets)]


class TestTheFit:
    def test_misread_and_missing_dates_come_back_from_position(self):
        """The September pattern: misreads of 6 as 8, 13 as 15, and a sheet
        whose date was never read at all."""
        truth = _september(16)
        read = list(truth)
        read[0] = None
        read[5] = date(2026, 9, 8)    # should be 02-09
        read[9] = date(2026, 9, 15)   # should be 03-09
        fitted, agreement = dates_by_position(read, 4)
        assert fitted == truth
        assert agreement == pytest.approx(13 / 15)

    def test_a_batch_that_starts_part_way_through_a_day(self):
        truth = _september(12, phase=2)          # starts on sheet 3 of 01-09
        fitted, _ = dates_by_position(list(truth), 4)
        assert fitted == truth

    def test_a_batch_that_does_not_follow_the_pattern_is_left_alone(self):
        read = [date(2026, 9, d) for d in (1, 9, 3, 17, 5, 22, 2, 30)]
        assert dates_by_position(read, 4) is None

    def test_too_few_dates_to_fit(self):
        assert dates_by_position([date(2026, 9, 1), None, None, None], 4) is None

    def test_turned_off(self):
        assert dates_by_position(_september(8), 0) is None


class TestPagesInAPipelineRun:
    def test_only_the_wrong_pages_change_and_they_stay_marked(self):
        pages = [{"fecha": d.strftime("%d-%m-%Y")} for d in _september(8)]
        pages[2]["fecha"] = "11-09-2026"
        date_pages_by_position(pages, 4)
        assert pages[2]["fecha"] == "01-09-2026"
        assert pages[2]["fecha_confident"] is False
        assert "se leyó 11-09-2026" in pages[2]["fecha_note"]
        assert "fecha_note" not in pages[3]

    def test_the_processor_applies_it(self):
        import inspect

        from nettune import main
        assert ("date_security_pages_by_position(readings, config.sheets_per_day)"
                in inspect.getsource(main.process_scan))

    def test_a_maintenance_sheet_keeps_the_date_written_on_it(self):
        """One sheet a working day, weekends missing: position says nothing."""
        from nettune.main import date_security_pages_by_position

        pages = [{"fecha": day.strftime("%d-%m-%Y"), "fecha_confident": True,
                  "tipo": "seguridad", "trabajos": []} for day in _september(8)]
        maintenance = {"fecha": "15-09-2026", "fecha_confident": True,
                       "tipo": "mantenimiento", "trabajos": []}
        pages.insert(4, maintenance)
        dated = date_security_pages_by_position(pages, 4)
        assert dated[4]["fecha"] == "15-09-2026"
        assert "fecha_note" not in dated[4]
        assert [p["fecha"] for p in dated[:4]] == ["01-09-2026"] * 4
        assert [p["fecha"] for p in dated[5:]] == ["02-09-2026"] * 4


class TestTheTool:
    @pytest.fixture
    def tool(self):
        spec = importlib.util.spec_from_file_location(
            "date_by_position", os.path.join(os.path.dirname(__file__), "..",
                                             "tools", "date_by_position.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @pytest.fixture
    def month(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "incoming_dir", str(tmp_path / "incoming"))
        revision = revision_dir_for(config.incoming_dir, "2026", "SEPTIEMBRE")
        os.makedirs(revision, exist_ok=True)
        read = {1: None, 2: "01", 3: "11", 4: "01", 5: "02", 6: "02", 7: "24", 8: "02"}
        with EntryStore(str(tmp_path / "t.sqlite3")) as store:
            for page, day in read.items():
                ref = f"{day}-09-2026 p{page}" if day else f"SKM_4 p{page}"
                store.record_sheet("2026", "SEPTIEMBRE", SRC, page, ref)
                store._connection.execute(
                    "INSERT INTO memoria_entries (year, month, block, position, text, "
                    "source, flagged, review_ref, added_at, dedupe_key, original_text) "
                    "VALUES ('2026','SEPTIEMBRE','B:',?,?,?,0,?,'t',?,?)",
                    (page, f"L{page}", SRC, ref, f"l{page}", f"L{page}"))
                with open(os.path.join(revision, image_name(ref)), "wb") as f:
                    f.write(ref.encode())
            store._connection.commit()
            store.record_turn("24-09-2026_p7.jpg", 180)
            yield store, revision

    def test_it_plans_the_position_dates(self, month, tool):
        store, _ = month
        changes, skipped = tool.plan(store, "2026", "SEPTIEMBRE", 4)
        assert skipped == []
        assert [(p, new) for _, p, _, new in changes] == [
            (1, "01-09-2026"), (3, "01-09-2026"), (7, "02-09-2026")]

    def test_applying_moves_lines_files_and_turns(self, month, tool):
        from nettune.dates.sheet_dates import set_sheet_date
        store, revision = month
        for _, _, old_ref, new in tool.plan(store, "2026", "SEPTIEMBRE", 4)[0]:
            assert set_sheet_date(store, "2026", "SEPTIEMBRE", old_ref, new, revision)[0]
        assert sorted(os.listdir(revision)) == sorted(
            f"{'01' if p <= 4 else '02'}-09-2026_p{p}.jpg" for p in range(1, 9))
        assert store.hand_turn("02-09-2026_p7.jpg") == 180
        assert tool.plan(store, "2026", "SEPTIEMBRE", 4)[0] == []
        assert store.date_checks("2026", "SEPTIEMBRE") == {}
