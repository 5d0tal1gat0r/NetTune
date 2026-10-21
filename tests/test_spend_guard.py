"""Hard monthly spend cap. The budget is a guard rail, not a comment."""

import pytest

from spend_guard import BudgetExceeded, SpendGuard, cost_usd


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "spend.sqlite3")


@pytest.fixture
def clock():
    return {"now": "2026-09-15T10:00:00"}


@pytest.fixture
def guard(db, clock):
    return SpendGuard(db, monthly_budget_usd=1.00, clock=lambda: clock["now"])


# --- pricing --------------------------------------------------------------


def test_cost_matches_published_pricing():
    # gpt-5.4-mini: $0.75 / 1M in, $4.50 / 1M out
    assert cost_usd("gpt-5.4-mini", 1_000_000, 0) == pytest.approx(0.75)
    assert cost_usd("gpt-5.4-mini", 0, 1_000_000) == pytest.approx(4.50)


def test_measured_page_cost_is_a_third_of_a_cent():
    assert cost_usd("gpt-5.4-mini", 3455, 52) == pytest.approx(0.00283, abs=1e-4)


def test_unknown_model_is_charged_at_a_pessimistic_rate():
    """An unpriced model must not read as free."""
    assert cost_usd("some-new-model", 1_000_000, 0) > 0


# --- accounting -----------------------------------------------------------


def test_starts_at_zero(guard):
    assert guard.spent_this_month() == 0.0


def test_records_spend(guard):
    guard.record("gpt-5.4-mini", 3455, 52)
    assert guard.spent_this_month() == pytest.approx(0.00283, abs=1e-4)


def test_spend_accumulates(guard):
    for _ in range(10):
        guard.record("gpt-5.4-mini", 3455, 52)
    assert guard.spent_this_month() == pytest.approx(0.0283, abs=1e-3)


def test_spend_persists_across_restarts(db, clock):
    SpendGuard(db, 1.00, clock=lambda: clock["now"]).record("gpt-5.4-mini", 3455, 52)
    again = SpendGuard(db, 1.00, clock=lambda: clock["now"])
    assert again.spent_this_month() > 0


def test_new_month_resets_the_budget(db, clock):
    g = SpendGuard(db, 1.00, clock=lambda: clock["now"])
    g.record("gpt-5.4-mini", 1_000_000, 0)   # $0.75
    assert g.spent_this_month() == pytest.approx(0.75)
    clock["now"] = "2026-10-01T00:00:00"
    assert g.spent_this_month() == 0.0


# --- the cap --------------------------------------------------------------


def test_allows_calls_under_budget(guard):
    guard.check_affordable("gpt-5.4-mini", 3455, 52)   # must not raise


def test_blocks_when_budget_is_exhausted(guard):
    guard.record("gpt-5.4-mini", 1_400_000, 0)         # $1.05 > $1.00 cap
    with pytest.raises(BudgetExceeded):
        guard.check_affordable("gpt-5.4-mini", 3455, 52)


def test_blocks_a_call_that_would_cross_the_cap(guard):
    guard.record("gpt-5.4-mini", 1_300_000, 0)         # $0.975
    with pytest.raises(BudgetExceeded):
        guard.check_affordable("gpt-5.4-mini", 1_000_000, 0)  # +$0.75 would exceed


def test_error_message_states_the_numbers(guard):
    guard.record("gpt-5.4-mini", 1_400_000, 0)
    with pytest.raises(BudgetExceeded) as exc:
        guard.check_affordable("gpt-5.4-mini", 3455, 52)
    msg = str(exc.value)
    assert "1.05" in msg and "1.00" in msg


def test_remaining_budget_is_reported(guard):
    guard.record("gpt-5.4-mini", 400_000, 0)           # $0.30
    assert guard.remaining() == pytest.approx(0.70)


def test_remaining_never_goes_negative(guard):
    guard.record("gpt-5.4-mini", 2_000_000, 0)
    assert guard.remaining() == 0.0


def test_budget_in_eur_is_converted(db, clock):
    g = SpendGuard(db, monthly_budget_usd=None, monthly_budget_eur=5.0,
                   eur_usd=1.10, clock=lambda: clock["now"])
    assert g.monthly_budget_usd == pytest.approx(5.5)
