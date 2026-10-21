import pytest

from ocr_feedback.model import (
    ACTIONS,
    STAGE_KINDS,
    STATUSES,
    FinalLine,
    Line,
    Page,
    ReviewEvent,
    StageOutput,
)


def test_constants():
    assert ACTIONS == ("edit", "confirm", "flag", "delete", "add", "retag")
    assert STATUSES == ("edited", "confirmed", "accepted", "none")
    assert STAGE_KINDS == ("reads", "select", "drop")


def test_defaults_are_independent():
    a, b = Line("x"), Line("y")
    a.meta["k"] = 1
    assert b.meta == {}
    assert Page("p").image_ref == ""
    assert StageOutput("p", "r", "s", [Line("t")]).seq == 0


def test_unknown_action_is_refused():
    with pytest.raises(ValueError):
        ReviewEvent(page_id="p", line_ref="1", action="rewrite")


def test_unknown_status_is_refused():
    with pytest.raises(ValueError):
        FinalLine(line_ref="1", text="t", tag="b", status="maybe")
