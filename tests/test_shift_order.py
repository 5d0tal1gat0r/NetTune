"""A day's sheets in the order the shifts happened, not the scanner's."""

import importlib.util
import os

import pytest

from batch_dates import chronological_order
from config import config
from consensus import consolidate
from entry_store import HAND_SOURCE, EntryStore
from month_folders import revision_dir_for
from review_marks import image_name
from sheet_dates import renumber_files
from transcription_service import normalise_hour

SRC = "SKM_H.pdf"


class TestReadingTheHour:
    @pytest.mark.parametrize("raw, hour", [
        ("07:00", "07:00"), ("7:00", "07:00"), ("22.00", "22:00"), ("22h00", "22:00"),
        ("15:00 a 23:00", "15:00"), ("24:00", "00:00"),
        (None, None), ("", None), ("de noche", None), ("27:00", None), ("07:75", None),
    ])
    def test_normalised(self, raw, hour):
        assert normalise_hour(raw) == hour

    def test_the_reads_vote_on_it(self):
        reads = [{"fecha": "01-09-2026", "horario": h, "trabajos": ["x"]}
                 for h in ("07:00", "07:00", None)]
        assert consolidate(reads)["horario"] == "07:00"


def _pages(*sheets):
    return [{"fecha": f, "horario": h} for f, h in sheets]


class TestTheOrder:
    def test_september_scan_order_becomes_shift_order(self):
        """Every day came 15:00, 07:00, 18:00, 22:00 off the scanner."""
        pages = _pages(*[(f"0{d}-09-2026", h) for d in (1, 2)
                         for h in ("15:00", "07:00", "18:00", "22:00")])
        assert chronological_order(pages) == [1, 0, 2, 3, 5, 4, 6, 7]

    def test_a_shift_after_midnight_closes_the_day(self):
        pages = _pages(("01-09-2026", "00:00"), ("01-09-2026", "07:00"),
                       ("01-09-2026", "18:00"))
        assert chronological_order(pages) == [1, 2, 0]

    def test_a_day_with_a_missing_hour_keeps_scan_order(self):
        pages = _pages(("01-09-2026", "15:00"), ("01-09-2026", None),
                       ("02-09-2026", "15:00"), ("02-09-2026", "07:00"))
        assert chronological_order(pages) == [0, 1, 3, 2]

    def test_sheets_never_move_between_days(self):
        pages = _pages(("02-09-2026", "07:00"), ("01-09-2026", "22:00"))
        assert chronological_order(pages) == [0, 1]

    def test_the_processor_numbers_by_it(self):
        import inspect

        import main
        source = inspect.getsource(main.process_scan)
        # Security sheets in this order, numbered per section
        # (test_page_numbers_per_month).
        assert "for index in chronological_order(readings):" in source
        assert "scan_position=index + 1" in source


@pytest.fixture
def day(tmp_path, monkeypatch):
    """One day, scanned 15:00, 07:00, 18:00, 22:00, with a line on each."""
    monkeypatch.setattr(config, "incoming_dir", str(tmp_path / "incoming"))
    revision = revision_dir_for(config.incoming_dir, "2026", "SEPTIEMBRE")
    os.makedirs(revision, exist_ok=True)
    with EntryStore(str(tmp_path / "o.sqlite3")) as store:
        for page, shift in enumerate(("tarde", "manana", "auxiliar", "noche"), start=1):
            ref = f"01-09-2026 p{page}"
            store.record_sheet("2026", "SEPTIEMBRE", SRC, page, ref)
            store._connection.execute(
                "INSERT INTO memoria_entries (year, month, block, position, text, source, "
                "flagged, review_ref, added_at, dedupe_key, original_text) "
                "VALUES ('2026','SEPTIEMBRE','B:',?,?,?,0,?,'t',?,?)",
                (page, f"Turno {shift}.", SRC, ref, f"turno {shift}", f"Turno {shift}."))
            with open(os.path.join(revision, image_name(ref)), "w") as f:
                f.write(shift)
        store._connection.execute(
            "INSERT INTO memoria_entries (year, month, block, position, text, source, "
            "flagged, review_ref, added_at, dedupe_key, original_text) "
            "VALUES ('2026','SEPTIEMBRE','B:',9,'A mano, tarde.',?,0,'01-09-2026 p1','t',"
            "'a mano tarde','')", (HAND_SOURCE,))
        store._connection.commit()
        store.record_turn("01-09-2026_p2.jpg", 180)
        yield store, revision


def _content(revision, page):
    with open(os.path.join(revision, f"01-09-2026_p{page}.jpg")) as f:
        return f.read()


class TestRenumbering:
    def test_a_swap_moves_lines_files_and_turns(self, day):
        store, revision = day
        pairs = store.renumber_sheets("2026", "SEPTIEMBRE", SRC, {1: 2, 2: 1})
        renumber_files(store, revision, pairs)
        assert _content(revision, 1) == "manana"
        assert _content(revision, 2) == "tarde"
        refs = {e["text"]: e["review_ref"] for e in store.month_entries("2026", "SEPTIEMBRE")}
        assert refs["Turno manana."] == "01-09-2026 p1"
        assert refs["Turno tarde."] == refs["A mano, tarde."] == "01-09-2026 p2"
        assert store.hand_turn("01-09-2026_p1.jpg") == 180
        assert store.hand_turn("01-09-2026_p2.jpg") == 0
        assert store.scan_positions("2026", "SEPTIEMBRE", SRC)[2] == "01-09-2026 p1"

    def test_the_document_follows_the_shifts(self, day):
        store, revision = day
        renumber_files(store, revision,
                       store.renumber_sheets("2026", "SEPTIEMBRE", SRC, {1: 2, 2: 1}))
        assert store.entries("2026", "SEPTIEMBRE", "B:")[:2] == [
            "Turno manana.", "Turno tarde."]

    def test_not_a_permutation_is_refused(self, day):
        store, _ = day
        with pytest.raises(ValueError):
            store.renumber_sheets("2026", "SEPTIEMBRE", SRC, {1: 2})


class TestTheTool:
    @pytest.fixture
    def tool(self):
        spec = importlib.util.spec_from_file_location(
            "order_by_hour", os.path.join(os.path.dirname(__file__), "..",
                                          "tools", "order_by_hour.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_it_plans_the_swap_and_runs_once(self, day, tool):
        store, revision = day
        plans, skipped = tool.plan(store, "2026", "SEPTIEMBRE", [2, 1, 3, 4])
        assert plans == {SRC: {2: 1, 1: 2}} and skipped == []
        renumber_files(store, revision,
                       store.renumber_sheets("2026", "SEPTIEMBRE", SRC, plans[SRC]))
        # A second run finds the day already in order.
        assert tool.plan(store, "2026", "SEPTIEMBRE", [2, 1, 3, 4]) == ({}, [])

    def test_a_day_with_the_wrong_count_is_skipped(self, day, tool):
        store, _ = day
        plans, skipped = tool.plan(store, "2026", "SEPTIEMBRE", [2, 1, 3])
        assert plans == {} and "4 sheets, not 3" in skipped[0]


class TestCandidatesAfterRenumbering:
    def test_a_line_between_two_swapped_sheets_keeps_its_candidates(self, tmp_path):
        """Candidates were a range of page numbers between the neighbours.
        After a day was renumbered into shift order, "between p5 and p6"
        became "between p6 and p5" -- an empty range -- and five September
        lines showed "Página no registrada". They are scan positions now."""
        with EntryStore(str(tmp_path / "c.sqlite3")) as store:
            for page in (1, 2):
                store.record_sheet("2026", "SEPTIEMBRE", SRC, page, f"02-09-2026 p{page}")
            for position, ref, text in ((10, "02-09-2026 p1", "Tarde."),
                                        (11, "", "Sin hoja."),
                                        (12, "02-09-2026 p2", "Manana.")):
                store._connection.execute(
                    "INSERT INTO memoria_entries (year, month, block, position, text, "
                    "source, flagged, review_ref, added_at, dedupe_key, original_text) "
                    "VALUES ('2026','SEPTIEMBRE','B:',?,?,?,0,?,'t',?,?)",
                    (position, text, SRC, ref, text.lower(), text))
            store._connection.commit()
            store.renumber_sheets("2026", "SEPTIEMBRE", SRC, {1: 2, 2: 1})
            linea = next(e["id"] for e in store.month_entries("2026", "SEPTIEMBRE")
                         if e["text"] == "Sin hoja.")
            assert store.candidate_sheets(linea) == ["02-09-2026 p1", "02-09-2026 p2"]
