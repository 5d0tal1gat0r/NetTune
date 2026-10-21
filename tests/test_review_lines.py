"""One review line per page, instead of a marker on every doubtful entry.

Measured on a 42 page batch: 119 of 149 entries came back flagged, 80 per
cent. A marker on four entries in five says little more than "this is
handwriting", and markers that fire that often are ignored. The page is the
unit a person actually checks -- they open the image and read the whole sheet
-- so the document names the pages, and the entries are left clean.
"""

from entry_store import EntryStore, review_line


class TestReviewLine:
    def test_it_names_the_sheet_and_how_much_to_check(self):
        assert review_line("20-09-2026 p39", 5) == (
            "Revisar la hoja del 20-09-2026 (página 39): "
            "5 anotaciones dudosas."
        )

    def test_one_doubtful_entry_reads_in_the_singular(self):
        assert review_line("19-09-2026 p38", 1).endswith("1 anotación dudosa.")

    def test_a_sheet_whose_date_could_not_be_read_is_named_by_its_scan(self):
        assert review_line("SKM_C3082609 p7", 2) == (
            "Revisar la hoja SKM_C3082609 (página 7): 2 anotaciones dudosas."
        )


class TestStore:
    def test_the_entries_themselves_carry_no_marker(self, tmp_path):
        with EntryStore(str(tmp_path / "e.sqlite3")) as store:
            store.add("2026", "SEPTIEMBRE", "Parking",
                      [{"text": "Se abre Z6.", "confident": False}],
                      "s.pdf", review_ref="20-09-2026 p39")
            assert store.entries("2026", "SEPTIEMBRE", "Parking") == ["Se abre Z6."]

    def test_the_pages_to_check_are_counted_per_sheet(self, tmp_path):
        with EntryStore(str(tmp_path / "e.sqlite3")) as store:
            store.add("2026", "SEPTIEMBRE", "Parking",
                      [{"text": "Uno.", "confident": False},
                       {"text": "Dos.", "confident": False},
                       {"text": "Tres.", "confident": True}],
                      "s.pdf", review_ref="20-09-2026 p39")
            store.add("2026", "SEPTIEMBRE", "Parking",
                      [{"text": "Cuatro.", "confident": False}],
                      "s.pdf", review_ref="21-09-2026 p41")
            assert store.review_pages("2026", "SEPTIEMBRE") == {
                "20-09-2026 p39": 2,
                "21-09-2026 p41": 1,
            }

    def test_a_month_with_nothing_doubtful_lists_no_pages(self, tmp_path):
        with EntryStore(str(tmp_path / "e.sqlite3")) as store:
            store.add("2026", "SEPTIEMBRE", "Parking",
                      [{"text": "Se abre Z6.", "confident": True}], "s.pdf")
            assert store.review_pages("2026", "SEPTIEMBRE") == {}

    def test_the_pages_come_back_in_date_order(self, tmp_path):
        """Supersedes "in the order they were read". The pages come off the
        scanner in whatever order the paper sat in the tray -- a real
        September batch ran 01-09 p2, 11-09 p3, 01-09 p4 -- and a memoria is
        a record of a month, so it has to read in date order."""
        with EntryStore(str(tmp_path / "e.sqlite3")) as store:
            for ref in ("01-09-2026 p1", "20-09-2026 p39", "05-09-2026 p10"):
                store.add("2026", "SEPTIEMBRE", "Parking",
                          [{"text": f"Algo en {ref}.", "confident": False}],
                          "s.pdf", review_ref=ref)
            assert list(store.review_pages("2026", "SEPTIEMBRE")) == [
                "01-09-2026 p1", "05-09-2026 p10", "20-09-2026 p39",
            ]


class TestChronologicalOrder:
    """position is the order the scans were fed to the machine, not the order
    the days happened. The real September batch ran 01-09 p2, 11-09 p3,
    01-09 p4, 02-09 p5 ... 24-09 p7."""

    REVUELTO = ("01-09-2026 p2", "11-09-2026 p3", "01-09-2026 p4",
                "24-09-2026 p7", "03-09-2026 p10")

    def _store(self, tmp_path):
        store = EntryStore(str(tmp_path / "e.sqlite3"))
        for ref in self.REVUELTO:
            store.add("2026", "SEPTIEMBRE", "Parking",
                      [{"text": f"Algo en {ref}.", "confident": False}],
                      "s.pdf", review_ref=ref)
        return store

    def test_the_memoria_reads_in_date_order(self, tmp_path):
        with self._store(tmp_path) as store:
            assert store.entries("2026", "SEPTIEMBRE", "Parking") == [
                "Algo en 01-09-2026 p2.",
                "Algo en 01-09-2026 p4.",
                "Algo en 03-09-2026 p10.",
                "Algo en 11-09-2026 p3.",
                "Algo en 24-09-2026 p7.",
            ]

    def test_the_dashboard_agrees_with_the_memoria(self, tmp_path):
        with self._store(tmp_path) as store:
            filas = store.month_entries("2026", "SEPTIEMBRE")
            assert [f["review_ref"] for f in filas] == [
                "01-09-2026 p2", "01-09-2026 p4", "03-09-2026 p10",
                "11-09-2026 p3", "24-09-2026 p7",
            ]

    def test_two_pages_of_one_day_keep_their_page_order(self, tmp_path):
        with self._store(tmp_path) as store:
            mismo = [e for e in store.entries("2026", "SEPTIEMBRE", "Parking")
                     if "01-09" in e]
            assert mismo == ["Algo en 01-09-2026 p2.", "Algo en 01-09-2026 p4."]

    def test_an_undated_sheet_stays_after_the_page_it_followed(self, tmp_path):
        """Supersedes "undated sorts after everything dated". A sheet named
        after the scan because its date was illegible is still a page with a
        place in the batch; sending it to the end of the month took it away
        from the days around it (September's p27 closed the month)."""
        with self._store(tmp_path) as store:
            store.add("2026", "SEPTIEMBRE", "Parking",
                      [{"text": "Algo sin fecha.", "confident": False}],
                      "s.pdf", review_ref="SKM_C3082609 p9")
            orden = store.entries("2026", "SEPTIEMBRE", "Parking")
            # Written last, so it follows the last dated page before it in
            # the scan: 03-09 p10.
            assert orden.index("Algo sin fecha.") == orden.index("Algo en 03-09-2026 p10.") + 1


class TestLinesWithNoSheetStayInPlace:
    """September's confident lines were stored with no sheet. Sorting them by
    sheet alone moved all of them to the bottom of the month."""

    def _store(self, tmp_path):
        store = EntryStore(str(tmp_path / "s.sqlite3"))
        conn = store._connection
        # Positions as the scan wrote them; review_ref only on doubtful lines,
        # the way add() stored them before every line kept its sheet.
        for pos, ref, text in (
            (0, "", "Antes de todo."),
            (1, "01-09-2026 p2", "Dia uno."),
            (2, "", "Tambien dia uno."),
            (3, "11-09-2026 p3", "Dia once."),
            (4, "", "Tras el once."),
            (5, "02-09-2026 p4", "Dia dos."),
        ):
            conn.execute(
                "INSERT INTO memoria_entries (year, month, block, position, text, source, "
                "flagged, review_ref, added_at, dedupe_key, original_text) "
                "VALUES ('2026','SEPTIEMBRE','B:',?,?,'s.pdf',0,?,'t',?,?)",
                (pos, text, ref, text.lower(), text))
        conn.commit()
        return store

    def test_they_stay_beside_the_line_they_followed(self, tmp_path):
        with self._store(tmp_path) as store:
            assert store.entries("2026", "SEPTIEMBRE", "B:") == [
                "Antes de todo.", "Dia uno.", "Tambien dia uno.",
                "Dia dos.", "Dia once.", "Tras el once.",
            ]

    def test_none_are_left_at_the_bottom(self, tmp_path):
        with self._store(tmp_path) as store:
            filas = store.month_entries("2026", "SEPTIEMBRE")
            assert filas[-1]["text"] == "Tras el once."
            assert filas[0]["text"] == "Antes de todo."
