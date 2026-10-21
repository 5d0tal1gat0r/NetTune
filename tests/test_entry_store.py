import sqlite3

import pytest

from entry_store import EntryStore, RetagResult


@pytest.fixture
def store(tmp_path):
    with EntryStore(str(tmp_path / "e.sqlite3")) as s:
        yield s


def e(text, confident=True):
    return {"text": text, "confident": confident}


def test_starts_empty(store):
    assert store.entries("2026", "JUNIO", "Parking") == []


def test_adds_entries_in_order(store):
    store.add("2026", "JUNIO", "Parking", [e("uno"), e("dos")], "a.pdf")
    assert store.entries("2026", "JUNIO", "Parking") == ["uno", "dos"]


def test_a_second_drop_appends(store):
    store.add("2026", "JUNIO", "Parking", [e("uno")], "a.pdf")
    store.add("2026", "JUNIO", "Parking", [e("dos")], "b.pdf")
    assert store.entries("2026", "JUNIO", "Parking") == ["uno", "dos"]


def test_redropping_the_same_scan_does_not_duplicate(store):
    store.add("2026", "JUNIO", "Parking", [e("uno")], "a.pdf")
    added = store.add("2026", "JUNIO", "Parking", [e("uno")], "a.pdf")
    assert added == 0
    assert store.entries("2026", "JUNIO", "Parking") == ["uno"]


def test_months_are_separate(store):
    store.add("2026", "JUNIO", "Parking", [e("junio")], "a.pdf")
    store.add("2026", "JULIO", "Parking", [e("julio")], "b.pdf")
    assert store.entries("2026", "JUNIO", "Parking") == ["junio"]
    assert store.entries("2026", "JULIO", "Parking") == ["julio"]


def test_years_are_separate(store):
    store.add("2026", "JUNIO", "Parking", [e("a")], "x.pdf")
    store.add("2027", "JUNIO", "Parking", [e("b")], "y.pdf")
    assert store.entries("2027", "JUNIO", "Parking") == ["b"]


def test_blocks_are_separate(store):
    store.add("2026", "JUNIO", "Parking", [e("p")], "a.pdf")
    store.add("2026", "JUNIO", "Otros", [e("o")], "a.pdf")
    assert store.entries("2026", "JUNIO", "Parking") == ["p"]
    assert store.entries("2026", "JUNIO", "Otros") == ["o"]


def test_blank_entries_are_skipped(store):
    store.add("2026", "JUNIO", "Parking", [e("  "), e("real")], "a.pdf")
    assert store.entries("2026", "JUNIO", "Parking") == ["real"]


def test_counts_per_block(store):
    store.add("2026", "JUNIO", "Parking", [e("a"), e("b")], "x.pdf")
    store.add("2026", "JUNIO", "Otros", [e("c")], "x.pdf")
    assert store.counts("2026", "JUNIO") == {"Parking": 2, "Otros": 1}


def test_flagged_entries_are_counted(store):
    store.add("2026", "JUNIO", "Parking", [e("a"), e("b", confident=False)], "x.pdf")
    assert store.flagged_count("2026", "JUNIO") == 1


def test_survives_reopen(tmp_path):
    db = str(tmp_path / "e.sqlite3")
    with EntryStore(db) as s:
        s.add("2026", "JUNIO", "Parking", [e("uno")], "a.pdf")
    with EntryStore(db) as s:
        assert s.entries("2026", "JUNIO", "Parking") == ["uno"]


class TestPaperOrderMigration:
    OLD = (
        "CREATE TABLE memoria_entries (year TEXT NOT NULL, month TEXT NOT NULL, "
        "block TEXT NOT NULL, position INTEGER NOT NULL, text TEXT NOT NULL, "
        "source TEXT NOT NULL, flagged INTEGER NOT NULL DEFAULT 0, "
        "added_at TEXT NOT NULL, PRIMARY KEY (year, month, block, text))"
    )

    def old_db(self, tmp_path):
        path = str(tmp_path / "old.sqlite3")
        with sqlite3.connect(path) as db:
            db.execute(self.OLD)
            for block, position, text in (
                ("Electricidad y Alumbrado", 3, "luz"),
                ("Parking", 1, "cargador"),
                ("Otros", 0, "riego"),
                ("Intervenciones Seguridad:", 5, "pilonas"),
            ):
                db.execute("INSERT INTO memoria_entries VALUES "
                           "('2026', 'SEPTIEMBRE', ?, ?, ?, 'a.pdf', 0, 'x')",
                           (block, position, text))
        return path

    def test_existing_rows_are_backfilled_grouped_by_block(self, tmp_path):
        path = self.old_db(tmp_path)
        with EntryStore(path) as store:
            rows = dict(store._connection.execute(
                "SELECT text, paper_order FROM memoria_entries").fetchall())
        assert rows == {"luz": 3.0, "cargador": 20001.0, "riego": 30000.0,
                        "pilonas": 5.0}

    def test_nobody_has_chosen_a_tag_yet(self, tmp_path):
        path = self.old_db(tmp_path)
        with EntryStore(path) as store:
            assert store._connection.execute(
                "SELECT COUNT(*) FROM memoria_entries WHERE hand_block != 0"
            ).fetchone()[0] == 0

    def test_reopening_changes_nothing(self, tmp_path):
        path = self.old_db(tmp_path)
        EntryStore(path).close()
        with sqlite3.connect(path) as db:
            db.execute("UPDATE memoria_entries SET paper_order = 7 WHERE text = 'luz'")
        with EntryStore(path) as store:
            assert store._connection.execute(
                "SELECT paper_order FROM memoria_entries WHERE text = 'luz'"
            ).fetchone()[0] == 7.0


def test_legacy_paper_order():
    from entry_store import legacy_paper_order
    assert legacy_paper_order("Electricidad y Alumbrado", 4) == 4.0
    assert legacy_paper_order("Ascensores, rampas, escaleras y puertas", 4) == 10004.0
    assert legacy_paper_order("Otros", 0) == 30000.0
    assert legacy_paper_order("Intervenciones Seguridad:", 9) == 9.0


ELEC = "Electricidad y Alumbrado"
ASC = "Ascensores, rampas, escaleras y puertas"
PARK = "Parking"


def line(text, orden):
    return {"text": text, "confident": True, "orden": orden}


class TestPaperOrder:
    def test_a_sheet_reads_in_the_order_it_was_written(self, store):
        ref = "mant 02-09-2026 p1"
        store.add("2026", "SEPTIEMBRE", ELEC, [line("luz rampa", 0), line("foco", 2)],
                  "m.pdf", ref)
        store.add("2026", "SEPTIEMBRE", PARK, [line("cargador", 1)], "m.pdf", ref)
        texts = [e["text"] for e in store.month_entries("2026", "SEPTIEMBRE")]
        assert texts == ["luz rampa", "cargador", "foco"]

    def test_sheets_still_go_by_date(self, store):
        store.add("2026", "SEPTIEMBRE", PARK, [line("tarde", 0)], "m.pdf",
                  "mant 05-09-2026 p2")
        store.add("2026", "SEPTIEMBRE", ELEC, [line("pronto", 0)], "m.pdf",
                  "mant 02-09-2026 p1")
        texts = [e["text"] for e in store.month_entries("2026", "SEPTIEMBRE")]
        assert texts == ["pronto", "tarde"]

    def test_the_paper_order_is_returned(self, store):
        store.add("2026", "SEPTIEMBRE", PARK, [line("cargador", 4)], "m.pdf",
                  "mant 02-09-2026 p1")
        entry = store.month_entries("2026", "SEPTIEMBRE")[0]
        assert entry["paper_order"] == 4.0
        assert entry["hand_block"] == 0

    def test_a_line_without_orden_gets_the_legacy_order(self, store):
        store.add("2026", "SEPTIEMBRE", ASC, [e("puerta")], "m.pdf", "mant 02-09-2026 p1")
        assert store.month_entries("2026", "SEPTIEMBRE")[0]["paper_order"] == 10000.0

    def test_the_memoria_block_reads_by_date_then_paper(self, store):
        store.add("2026", "SEPTIEMBRE", ELEC, [line("b", 3), line("a", 1)], "m.pdf",
                  "mant 02-09-2026 p1")
        store.add("2026", "SEPTIEMBRE", ELEC, [line("antes", 9)], "m.pdf",
                  "mant 01-09-2026 p1")
        assert store.entries("2026", "SEPTIEMBRE", ELEC) == ["antes", "a", "b"]

    def test_seguridad_order_is_unchanged(self, store):
        seg = "Intervenciones Seguridad:"
        store.add("2026", "SEPTIEMBRE", seg, [line("dos", 5), line("tres", 0)], "s.pdf",
                  "02-09-2026 p1")
        store.add("2026", "SEPTIEMBRE", seg, [line("uno", 7)], "s.pdf", "01-09-2026 p1")
        assert store.entries("2026", "SEPTIEMBRE", seg) == ["uno", "dos", "tres"]
        texts = [e["text"] for e in store.month_entries("2026", "SEPTIEMBRE")]
        assert texts == ["uno", "dos", "tres"]


OTROS_B = "Otros"


def only(store):
    return [(x["text"], x["block"]) for x in store.month_entries("2026", "SEPTIEMBRE")]


class TestRetag:
    REF = "mant 02-09-2026 p1"

    def one(self, store, block=PARK, text="revisión de cargadores"):
        store.add("2026", "SEPTIEMBRE", block, [line(text, 0)], "m.pdf", self.REF)
        return store.month_entries("2026", "SEPTIEMBRE")[0]["id"]

    def test_moves_the_line(self, store):
        entry_id = self.one(store)
        assert store.retag_entry(entry_id, ELEC) == RetagResult("changed")
        entry = store.month_entries("2026", "SEPTIEMBRE")[0]
        assert (entry["block"], entry["hand_block"]) == (ELEC, 1)
        assert store.entries("2026", "SEPTIEMBRE", ELEC) == ["revisión de cargadores"]
        assert store.entries("2026", "SEPTIEMBRE", PARK) == []

    def test_does_not_confirm_a_doubtful_line(self, store):
        store.add("2026", "SEPTIEMBRE", PARK,
                  [{"text": "dudosa", "confident": False, "orden": 0}], "m.pdf", self.REF)
        entry_id = store.month_entries("2026", "SEPTIEMBRE")[0]["id"]
        store.retag_entry(entry_id, ELEC)
        entry = store.month_entries("2026", "SEPTIEMBRE")[0]
        assert entry["flagged"] == 1 and entry["hand_edited"] == 0

    def test_same_block_is_unchanged(self, store):
        entry_id = self.one(store)
        assert store.retag_entry(entry_id, PARK) == RetagResult("unchanged")
        assert store.month_entries("2026", "SEPTIEMBRE")[0]["hand_block"] == 0

    def test_missing_line(self, store):
        assert store.retag_entry(999, PARK) == RetagResult("not_found")

    def test_a_security_line_has_no_subheading_to_change(self, store):
        store.add("2026", "SEPTIEMBRE", "Intervenciones Seguridad:", [line("x", 0)],
                  "s.pdf", "02-09-2026 p1")
        entry_id = store.month_entries("2026", "SEPTIEMBRE")[0]["id"]
        assert store.retag_entry(entry_id, PARK) == RetagResult("not_maintenance")

    def test_an_unknown_block_is_a_programming_error(self, store):
        entry_id = self.one(store)
        with pytest.raises(ValueError):
            store.retag_entry(entry_id, "Intervenciones Seguridad:")

    def test_collision_changes_nothing_and_names_the_other_line(self, store):
        store.add("2026", "SEPTIEMBRE", ELEC, [line("Revisión de cargadores.", 3)],
                  "m.pdf", "mant 05-09-2026 p2")
        other = store.month_entries("2026", "SEPTIEMBRE")[0]["id"]
        entry_id = self.one(store)
        assert store.retag_entry(entry_id, ELEC) == RetagResult("collision", other)
        assert sorted(only(store)) == sorted([("Revisión de cargadores.", ELEC),
                                              ("revisión de cargadores", PARK)])

    def test_a_reprocess_keeps_the_tag(self, store):
        entry_id = self.one(store)
        store.retag_entry(entry_id, ELEC)
        store.clear_month("2026", "SEPTIEMBRE")
        store.add("2026", "SEPTIEMBRE", PARK, [line("revisión de cargadores", 0)],
                  "m.pdf", self.REF)
        assert only(store) == [("revisión de cargadores", ELEC)]

    def test_a_redrop_without_clearing_keeps_the_tag(self, store):
        entry_id = self.one(store)
        store.retag_entry(entry_id, ELEC)
        added = store.add("2026", "SEPTIEMBRE", PARK,
                          [line("revisión de cargadores", 0)], "m.pdf", self.REF)
        assert added == 0
        assert only(store) == [("revisión de cargadores", ELEC)]

    def test_a_corrected_and_retagged_line_is_not_duplicated(self, store):
        entry_id = self.one(store, text="revison de cargadres")
        store.edit_entry(entry_id, "Revisión de cargadores")
        store.retag_entry(entry_id, ELEC)
        store.clear_month("2026", "SEPTIEMBRE")
        store.add("2026", "SEPTIEMBRE", PARK, [line("revison de cargadres", 0)],
                  "m.pdf", self.REF)
        assert only(store) == [("Revisión de cargadores", ELEC)]

    def test_the_reprocess_refreshes_its_place(self, store):
        entry_id = self.one(store)
        store.retag_entry(entry_id, ELEC)
        store.add("2026", "SEPTIEMBRE", PARK, [line("revisión de cargadores", 6)],
                  "m.pdf", self.REF)
        assert store.month_entries("2026", "SEPTIEMBRE")[0]["paper_order"] == 6.0

    def test_clear_month_still_removes_untouched_lines(self, store):
        self.one(store, block=OTROS_B, text="riego")
        assert store.clear_month("2026", "SEPTIEMBRE") == (1, 0)


class TestHandLinesInPaperOrder:
    REF = "mant 02-09-2026 p1"

    def setup_sheet(self, store):
        store.add("2026", "SEPTIEMBRE", ELEC, [line("luz", 0)], "m.pdf", self.REF)
        store.add("2026", "SEPTIEMBRE", PARK, [line("cargador", 1)], "m.pdf", self.REF)
        return {x["text"]: x["id"] for x in store.month_entries("2026", "SEPTIEMBRE")}

    def texts(self, store):
        return [x["text"] for x in store.month_entries("2026", "SEPTIEMBRE")]

    def test_after_a_line_it_goes_before_the_next_tag(self, store):
        ids = self.setup_sheet(store)
        store.add_entry("2026", "SEPTIEMBRE", ELEC, "nueva", after_id=ids["luz"])
        assert self.texts(store) == ["luz", "nueva", "cargador"]

    def test_before_a_line_it_goes_after_the_previous_tag(self, store):
        ids = self.setup_sheet(store)
        store.add_entry("2026", "SEPTIEMBRE", PARK, "antes", before_id=ids["cargador"])
        assert self.texts(store) == ["luz", "antes", "cargador"]

    def test_repeated_adds_after_the_same_line_stay_in_order(self, store):
        ids = self.setup_sheet(store)
        store.add_entry("2026", "SEPTIEMBRE", ELEC, "dos", after_id=ids["luz"])
        store.add_entry("2026", "SEPTIEMBRE", ELEC, "uno", after_id=ids["luz"])
        assert self.texts(store) == ["luz", "uno", "dos", "cargador"]

    def test_after_the_last_line(self, store):
        ids = self.setup_sheet(store)
        store.add_entry("2026", "SEPTIEMBRE", PARK, "final", after_id=ids["cargador"])
        assert self.texts(store) == ["luz", "cargador", "final"]

    def test_other_blocks_do_not_move(self, store):
        ids = self.setup_sheet(store)
        before = {x["id"]: x["position"] for x in store.month_entries("2026", "SEPTIEMBRE")
                  if x["block"] == PARK}
        store.add_entry("2026", "SEPTIEMBRE", ELEC, "nueva", after_id=ids["luz"])
        after = {x["id"]: x["position"] for x in store.month_entries("2026", "SEPTIEMBRE")
                 if x["block"] == PARK}
        assert before == after

    def test_a_line_on_an_empty_sheet(self, store):
        self.setup_sheet(store)
        store.add_to_sheet("2026", "SEPTIEMBRE", OTROS_B, "mant 03-09-2026 p2", "riego")
        assert self.texts(store) == ["luz", "cargador", "riego"]


class TestReviewFixes:
    def texts(self, store):
        return [x["text"] for x in store.month_entries("2026", "SEPTIEMBRE")]

    def test_an_undated_sheet_stays_in_one_piece_after_the_dated_one(self, store):
        dated, undated = "mant 03-09-2026 p1", "mant SKM_C3082609 p2"
        store.add("2026", "SEPTIEMBRE", ELEC, [line("d0", 0), line("d2", 2)], "m.pdf", dated)
        store.add("2026", "SEPTIEMBRE", PARK, [line("d1", 1)], "m.pdf", dated)
        store.add("2026", "SEPTIEMBRE", ELEC, [line("u0", 0), line("u1", 1)], "m.pdf", undated)
        assert self.texts(store) == ["d0", "d1", "d2", "u0", "u1"]

    def test_a_later_sheet_does_not_move_a_retagged_line_on_its_own_sheet(self, store):
        store.add("2026", "SEPTIEMBRE", PARK, [line("rutina", 1)], "m.pdf",
                  "mant 03-09-2026 p1")
        entry_id = store.month_entries("2026", "SEPTIEMBRE")[0]["id"]
        store.retag_entry(entry_id, ELEC)
        store.add("2026", "SEPTIEMBRE", PARK, [line("rutina", 5)], "m.pdf",
                  "mant 05-09-2026 p2")
        assert store.month_entries("2026", "SEPTIEMBRE")[0]["paper_order"] == 1.0

    def test_a_later_sheet_does_not_move_a_corrected_line_on_its_own_sheet(self, store):
        store.add("2026", "SEPTIEMBRE", PARK, [line("rutna", 1)], "m.pdf",
                  "mant 03-09-2026 p1")
        entry_id = store.month_entries("2026", "SEPTIEMBRE")[0]["id"]
        store.edit_entry(entry_id, "rutina")
        store.add("2026", "SEPTIEMBRE", PARK, [line("rutna", 5)], "m.pdf",
                  "mant 05-09-2026 p2")
        assert store.month_entries("2026", "SEPTIEMBRE")[0]["paper_order"] == 1.0

    def test_an_unreadable_stretch_can_be_retagged_next_to_another(self, store):
        from illegible import ILLEGIBLE_GROUP
        store.add("2026", "SEPTIEMBRE", ELEC, [line(ILLEGIBLE_GROUP, 0)], "m.pdf",
                  "mant 03-09-2026 p1")
        store.add("2026", "SEPTIEMBRE", OTROS_B, [line(ILLEGIBLE_GROUP, 0)], "m.pdf",
                  "mant 09-09-2026 p2")
        moving = next(x["id"] for x in store.month_entries("2026", "SEPTIEMBRE")
                      if x["block"] == ELEC)
        assert store.retag_entry(moving, OTROS_B) == RetagResult("changed")
        assert len(store.entries("2026", "SEPTIEMBRE", OTROS_B)) == 2

    def test_a_retag_does_not_swallow_the_same_words_on_another_day(self, store):
        store.add("2026", "SEPTIEMBRE", ELEC, [line("luces garaje", 0)], "m.pdf",
                  "mant 03-09-2026 p1")
        entry_id = store.month_entries("2026", "SEPTIEMBRE")[0]["id"]
        store.retag_entry(entry_id, OTROS_B)
        store.add("2026", "SEPTIEMBRE", PARK, [line("luces garaje", 0)], "m.pdf",
                  "mant 10-09-2026 p3")
        assert store.entries("2026", "SEPTIEMBRE", PARK) == ["luces garaje"]


class TestDeferredMinors:
    def test_a_retagged_line_without_a_sheet_stays_on_its_day(self, store):
        """It went to the end of its new subheading, and a line with no sheet
        is filed under the day of the line before it there: another day."""
        store.add("2026", "SEPTIEMBRE", ELEC, [line("e1", 0)], "m.pdf", "mant 03-09-2026 p1")
        store.add("2026", "SEPTIEMBRE", ELEC, [line("e2", 0)], "m.pdf", "mant 05-09-2026 p2")
        store.add("2026", "SEPTIEMBRE", OTROS_B, [line("o1", 1)], "m.pdf", "mant 03-09-2026 p1")
        store.add("2026", "SEPTIEMBRE", OTROS_B, [line("sin hoja", 2)], "m.pdf", "")
        store.add("2026", "SEPTIEMBRE", OTROS_B, [line("o2", 1)], "m.pdf", "mant 05-09-2026 p2")
        texts = [x["text"] for x in store.month_entries("2026", "SEPTIEMBRE")]
        assert texts.index("sin hoja") < texts.index("e2"), "on 03-09 before the retag"
        moving = next(x["id"] for x in store.month_entries("2026", "SEPTIEMBRE")
                      if x["text"] == "sin hoja")
        assert store.retag_entry(moving, ELEC) == RetagResult("changed")
        texts = [x["text"] for x in store.month_entries("2026", "SEPTIEMBRE")]
        assert texts.index("sin hoja") < texts.index("e2"), "still on 03-09"
        assert store.entries("2026", "SEPTIEMBRE", ELEC) == ["e1", "sin hoja", "e2"]

    def test_a_retag_alone_is_kept_but_not_counted_as_a_correction(self, store):
        store.add("2026", "SEPTIEMBRE", PARK, [line("cargador", 0)], "m.pdf",
                  "mant 03-09-2026 p1")
        store.retag_entry(store.month_entries("2026", "SEPTIEMBRE")[0]["id"], ELEC)
        assert store.clear_month("2026", "SEPTIEMBRE") == (0, 0)
        assert store.entries("2026", "SEPTIEMBRE", ELEC) == ["cargador"]
