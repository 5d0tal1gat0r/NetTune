"""The generic records every system's feedback is expressed in."""

from dataclasses import dataclass, field

ACTIONS = ("edit", "confirm", "flag", "delete", "add", "retag")
STATUSES = ("edited", "confirmed", "accepted", "none")
STAGE_KINDS = ("reads", "select", "drop")


@dataclass
class Line:
    """One line of one stage's output. meta carries flags such as disagreement."""
    text: str
    meta: dict = field(default_factory=dict)


@dataclass
class Page:
    """One scanned sheet. meta is free host data: section, date, reference."""
    page_id: str
    image_ref: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class Run:
    """One processing run of the host pipeline."""
    run_id: str
    config_hash: str
    created_at: str
    meta: dict = field(default_factory=dict)


@dataclass
class StageOutput:
    """What one stage produced for one page in one run. seq numbers the
    readings of a reads stage (1..n); 0 for select and drop stages."""
    page_id: str
    run_id: str
    stage: str
    lines: list
    seq: int = 0
    raw: object = None
    cached: bool = False


@dataclass
class ReviewEvent:
    """One thing a person did to one line."""
    page_id: str
    line_ref: str
    action: str
    before_text: str | None = None
    after_text: str | None = None
    before_tag: str | None = None
    after_tag: str | None = None
    meta: dict = field(default_factory=dict)
    at: str = ""

    def __post_init__(self):
        if self.action not in ACTIONS:
            raise ValueError(f"unknown action {self.action!r}; expected one of {ACTIONS}")


@dataclass
class FinalLine:
    """The host's current reviewed line. source_text is what the pipeline
    delivered before any person touched it (None for a line a person added)."""
    line_ref: str
    text: str
    tag: str | None
    status: str
    source_text: str | None = None
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}; expected one of {STATUSES}")
