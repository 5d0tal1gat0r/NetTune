"""The low-budget warning: once a month, not once a second."""

import logging

from spend_guard import SpendGuard


def _guard(tmp_path, spent_usd: float, when: list[str]):
    guard = SpendGuard(str(tmp_path / "s.sqlite3"), monthly_budget_usd=5.50,
                       clock=lambda: when[0])
    guard._connection.execute(
        "INSERT INTO spend (month, at, model, tokens_in, tokens_out, usd) "
        "VALUES (?, ?, 'm', 0, 0, ?)", (when[0][:7], when[0], spent_usd))
    guard._connection.commit()
    return guard


def _warnings(caplog):
    return [r for r in caplog.records
            if r.levelno == logging.WARNING and "Budget past" in r.getMessage()]


def test_the_idle_loop_does_not_repeat_it(tmp_path, caplog):
    """main calls warn_if_low on every idle tick, about once a second. Past
    80% it used to log on every one: 3,423 lines in an hour on the Pi."""
    when = ["2026-09-24T09:00:00+00:00"]
    guard = _guard(tmp_path, 5.495, when)
    with caplog.at_level(logging.WARNING):
        for _ in range(3600):
            guard.warn_if_low()
    assert len(_warnings(caplog)) == 1


def test_a_new_month_warns_again(tmp_path, caplog):
    when = ["2026-09-24T09:00:00+00:00"]
    guard = _guard(tmp_path, 5.0, when)
    with caplog.at_level(logging.WARNING):
        guard.warn_if_low()
        when[0] = "2026-10-20T09:00:00+00:00"
        guard._connection.execute(
            "INSERT INTO spend (month, at, model, tokens_in, tokens_out, usd) "
            "VALUES ('2026-10', ?, 'm', 0, 0, 4.9)", (when[0],))
        guard._connection.commit()
        guard.warn_if_low()
        guard.warn_if_low()
    assert len(_warnings(caplog)) == 2


def test_below_the_threshold_it_stays_quiet(tmp_path, caplog):
    when = ["2026-09-24T09:00:00+00:00"]
    guard = _guard(tmp_path, 1.0, when)
    with caplog.at_level(logging.WARNING):
        guard.warn_if_low()
    assert _warnings(caplog) == []


def test_crossing_later_in_the_month_still_warns(tmp_path, caplog):
    """Quiet below the line must not use up the month's one warning."""
    when = ["2026-09-24T09:00:00+00:00"]
    guard = _guard(tmp_path, 1.0, when)
    with caplog.at_level(logging.WARNING):
        guard.warn_if_low()
        guard._connection.execute(
            "INSERT INTO spend (month, at, model, tokens_in, tokens_out, usd) "
            "VALUES ('2026-09', ?, 'm', 0, 0, 4.0)", (when[0],))
        guard._connection.commit()
        guard.warn_if_low()
    assert len(_warnings(caplog)) == 1


def test_a_restart_does_not_warn_again(tmp_path, caplog):
    """The month it warned in was only kept in memory: the Pi logged it again
    after each of three restarts on 29-30 September. Now it is an email, so
    it has to survive a restart."""
    when = ["2026-09-24T09:00:00+00:00"]
    first = _guard(tmp_path, 5.495, when)
    assert first.warn_if_low() is True
    first.close()
    caplog.clear()
    again = SpendGuard(str(tmp_path / "s.sqlite3"), monthly_budget_usd=5.50,
                       clock=lambda: when[0])
    with caplog.at_level(logging.WARNING):
        assert again.warn_if_low() is False
    assert _warnings(caplog) == []


def test_it_says_when_it_has_just_warned(tmp_path):
    when = ["2026-09-24T09:00:00+00:00"]
    guard = _guard(tmp_path, 1.0, when)
    assert guard.warn_if_low() is False
    guard._connection.execute(
        "INSERT INTO spend (month, at, model, tokens_in, tokens_out, usd) "
        "VALUES ('2026-09', ?, 'm', 0, 0, 4.0)", (when[0],))
    guard._connection.commit()
    assert guard.warn_if_low() is True
    assert guard.warn_if_low() is False


def test_the_warning_is_emailed_once(monkeypatch):
    import notify

    # notify's own config: other tests import the app's modules afresh.
    config = notify.config
    monkeypatch.setattr(config, "notify_to", "admin@example.com")
    monkeypatch.setattr(config, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(config, "monthly_budget_eur", 7.0)
    sent = []
    n = notify.Notifier(store=None, settle_seconds=0, clock=lambda: 0.0,
                        send=lambda subject, body: sent.append((subject, body)))
    n.budget_low("OpenAI spend 2026-10: $6.20 of $7.70 (81%)")
    assert n.tick() == 1
    subject, body = sent[0]
    assert "presupuesto" in subject.lower()
    assert "$6.20 of $7.70" in body
    assert "MONTHLY_BUDGET_EUR" in body
