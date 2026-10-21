"""An OpenAI account with no credit left is not a transient fault.

September 30: the account ran dry mid-month, OpenAI answered every call
with 429 credit_balance_exhausted, and the scan went back into the retry
queue -- each retry failing the same way, with a "could not read" email
after the last. Like the monthly cap, it now stops at once with one email
saying what is wrong, and the scan waits for a restart or a new drop.
"""

import os

import pytest

from spend_guard import BudgetExceeded, OutOfCredit


class _QuotaError(Exception):
    """Shaped like openai.RateLimitError for insufficient_quota."""

    code = "insufficient_quota"

    def __init__(self):
        super().__init__(
            "Error code: 429 - {'error': {'message': 'You have no credits remaining.', "
            "'type': 'insufficient_quota', 'code': 'credit_balance_exhausted'}}"
        )


class _Busy(Exception):
    code = "rate_limit_exceeded"


def _client_raising(exc):
    class Completions:
        def create(self, **kw):
            raise exc

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    return Client()


@pytest.fixture
def image(tmp_path):
    from PIL import Image

    path = str(tmp_path / "p.jpg")
    Image.new("L", (40, 60), 255).save(path)
    return path


def test_no_credit_is_its_own_error(monkeypatch, image):
    import transcription_service

    monkeypatch.setattr(transcription_service, "client", _client_raising(_QuotaError()))
    # The class that module raises: other tests may have re-imported spend_guard.
    with pytest.raises(transcription_service.OutOfCredit):
        transcription_service.read_page(image)


def test_it_stops_like_the_monthly_cap_does():
    assert issubclass(OutOfCredit, BudgetExceeded)


def test_a_busy_api_is_still_retried(monkeypatch, image):
    import transcription_service

    monkeypatch.setattr(transcription_service, "client", _client_raising(_Busy("slow down")))
    with pytest.raises(transcription_service.TranscriptionError):
        transcription_service.read_page(image)


def test_the_scan_is_left_waiting_with_one_email(kit, monkeypatch):
    app, ledger, retries, monitor, guard = kit
    from entry_store import EntryStore

    # The app fixture imports its modules afresh: the class main catches is
    # this one, not the one imported at the top of the file.
    from spend_guard import OutOfCredit

    def no_credit(*a, **k):
        raise OutOfCredit("no credit")

    monkeypatch.setattr(app, "process_scan", no_credit)
    scan = os.path.join(app.incoming, "S25C.pdf")
    with open(scan, "wb") as handle:
        handle.write(b"%PDF scan")

    class Notes:
        def __init__(self):
            self.problems = []

        def busy(self):
            pass

        def problem(self, name, why):
            self.problems.append((name, why))

    notes = Notes()
    with EntryStore(str(os.path.join(os.path.dirname(app.incoming), "e.sqlite3"))) as store:
        outcome = app.handle_candidate(scan, ledger, retries, monitor, guard, store, notes)
    assert outcome == "out-of-credit"
    assert os.path.exists(scan), "left where it was dropped"
    assert len(notes.problems) == 1
    assert "saldo" in notes.problems[0][1]
    assert retries.due() == [], "not queued for another attempt"
