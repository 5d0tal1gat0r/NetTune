"""What a host implements, and what the package hands it."""

from typing import Protocol

from .model import FinalLine, Page, ReviewEvent, Run, StageOutput


class Recorder(Protocol):
    enabled: bool

    def record_run(self, run: Run) -> None: ...
    def record_page(self, page: Page) -> None: ...
    def record_stage(self, output: StageOutput) -> None: ...
    def record_event(self, event: ReviewEvent) -> None: ...


class TruthSource(Protocol):
    """The host's reviewed state, read from a copy of its database."""

    def pages(self) -> list[Page]: ...
    def final_lines(self, page_id: str) -> list[FinalLine]: ...
