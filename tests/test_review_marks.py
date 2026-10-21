"""Marking the entries a human has to check, and pointing at the page image."""

import pytest

from review_marks import IMAGE_SUFFIX, image_name, locator, mark, needs_review


class TestLocator:
    def test_the_sheet_date_names_the_page(self):
        assert locator("22-6-2026", 2, "SKM_C30826081908350.pdf") == "22-06-2026 p2"

    def test_a_slash_or_dot_date_reads_the_same(self):
        assert locator("3/7/2026", 1, "x.pdf") == "03-07-2026 p1"

    def test_an_illegible_date_falls_back_to_the_scan(self):
        assert locator(None, 2, "SKM_C30826091714020.pdf") == "SKM_C30826091714020 p2"

    def test_the_fallback_keeps_the_name_short_enough_to_read(self):
        long_name = "SCAN_" + "0" * 60 + ".pdf"
        assert len(locator("", 1, long_name)) <= 40


class TestImageName:
    def test_the_file_is_named_exactly_as_the_marker_reads(self):
        assert image_name("22-06-2026 p2") == "22-06-2026_p2" + IMAGE_SUFFIX

    def test_nothing_in_a_name_can_escape_the_review_folder(self):
        assert "/" not in image_name("../../etc/passwd p1")
        assert ".." not in image_name("../../etc/passwd p1")


class TestNeedsReview:
    def test_an_entry_the_readings_disagreed_on_needs_review(self):
        assert needs_review({"text": "Se abre Z6.", "confident": False}, page={})

    def test_an_entry_the_model_marked_itself_needs_review(self):
        assert needs_review({"text": "Con la obra de Cargobre[?]."}, page={})

    def test_a_doubtful_date_does_not_flag_the_lines_under_it(self):
        """It flagged every line of the sheet -- 136 of September's 194 flags
        sat on sheets where every line was flagged. The date is questioned by
        itself in the dashboard (EntryStore.date_checks) and keeps the sheet
        in Por revisar until someone answers it."""
        page = {"fecha_confident": False}
        assert not needs_review({"text": "Se abre Z6.", "confident": True}, page)

    def test_an_agreed_entry_on_a_dated_page_does_not(self):
        page = {"fecha_confident": True}
        assert not needs_review({"text": "Se abre Z6.", "confident": True}, page)

    def test_a_missing_confident_field_is_treated_as_agreed(self):
        assert not needs_review({"text": "Se abre Z6."}, page={})


class TestMark:
    def test_the_locator_is_appended_where_the_reader_will_see_it(self):
        assert mark("Se abre Z6.", "22-06-2026 p2") == "Se abre Z6. [22-06-2026 p2]"

    def test_marking_twice_does_not_stack(self):
        once = mark("Se abre Z6.", "22-06-2026 p2")
        assert mark(once, "22-06-2026 p2") == once

    def test_the_model_s_own_question_marks_are_left_alone(self):
        marked = mark("Con la obra de Cargobre[?].", "22-06-2026 p2")
        assert marked == "Con la obra de Cargobre[?]. [22-06-2026 p2]"

    @pytest.mark.parametrize("text", ["", "   "])
    def test_an_empty_entry_is_not_marked(self, text):
        assert mark(text, "22-06-2026 p2") == text


class TestIncoherentNeedsReview:
    def test_a_line_the_model_called_incoherent_is_flagged(self):
        assert needs_review(
            {"text": "Corte de carril grande en zona 3.", "coherent": False}, page={}
        )

    def test_a_dangling_fragment_is_flagged_without_the_model(self):
        assert needs_review({"text": "Se incorpora el vigilante. Se procede."}, page={})

    def test_a_floor_that_does_not_exist_is_flagged(self):
        assert needs_review(
            {"text": "Se llama la atención a varias personas en planta P."}, page={}
        )

    def test_a_sound_line_the_model_approved_is_not(self):
        assert not needs_review(
            {"text": "Se llama la atención a dos personas.", "coherent": True}, page={}
        )
