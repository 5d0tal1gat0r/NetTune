"""Hard monthly spend cap for OpenAI calls.

The budget is enforced, not documented: every call is priced before it is made
and refused if it would cross the cap, and actual usage is recorded after.
Spend is kept per calendar month in SQLite so a restart cannot lose track.
"""

import logging
import os
import sqlite3
from datetime import datetime, timezone

# USD per 1M tokens (input, output). OpenAI standard tier, checked 2026-09-15.
PRICES = {
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4": (2.50, 15.00),
    "gpt-5.6-terra": (2.00, 12.00),
    "gpt-5.5": (5.00, 30.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1-mini": (0.40, 1.60),
}

# An unpriced model must never look free; assume an expensive one.
_UNKNOWN_PRICE = (10.00, 50.00)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS spend (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    month      TEXT NOT NULL,
    at         TEXT NOT NULL,
    model      TEXT NOT NULL,
    tokens_in  INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL,
    usd        REAL NOT NULL
)
"""

# The months the low-budget warning has gone out in. It is an email now, so
# it has to survive a restart: kept only in memory, it went out again after
# every restart (three on 29-30 September).
_WARNED_SCHEMA = "CREATE TABLE IF NOT EXISTS budget_warnings (month TEXT PRIMARY KEY)"


class BudgetExceeded(RuntimeError):
    """The monthly cap would be crossed by this call."""


class OutOfCredit(BudgetExceeded):
    """The OpenAI account itself has no credit left.

    A BudgetExceeded so everything that stops for the monthly cap stops for
    this too: retrying only fails the same way until someone tops it up.
    """


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = PRICES.get(model, _UNKNOWN_PRICE)
    return tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SpendGuard:
    def __init__(
        self,
        db_path: str,
        monthly_budget_usd: float | None = None,
        monthly_budget_eur: float | None = None,
        eur_usd: float = 1.10,
        clock=_now,
    ):
        if monthly_budget_usd is None:
            if monthly_budget_eur is None:
                raise ValueError("a monthly budget in USD or EUR is required")
            monthly_budget_usd = monthly_budget_eur * eur_usd
        self.monthly_budget_usd = monthly_budget_usd
        self._clock = clock
        # The month warn_if_low last spoke in. It is called on every idle
        # tick of the main loop, about once a second, so without this a
        # month past the threshold logged the same warning ~82,000 times a
        # day into the journal.
        self._warned_for: str | None = None

        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._connection = sqlite3.connect(db_path, timeout=30)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(_SCHEMA)
        self._connection.execute(_WARNED_SCHEMA)
        self._connection.commit()

    def _month(self) -> str:
        return self._clock()[:7]

    def spent_this_month(self) -> float:
        row = self._connection.execute(
            "SELECT COALESCE(SUM(usd), 0) FROM spend WHERE month = ?", (self._month(),)
        ).fetchone()
        return float(row[0])

    def remaining(self) -> float:
        return max(0.0, self.monthly_budget_usd - self.spent_this_month())

    def check_affordable(self, model: str, tokens_in: int, tokens_out: int) -> None:
        """Raise BudgetExceeded if this call would cross the cap."""
        projected = self.spent_this_month() + cost_usd(model, tokens_in, tokens_out)
        if projected > self.monthly_budget_usd:
            raise BudgetExceeded(
                f"Monthly OpenAI budget reached: ${self.spent_this_month():.2f} spent "
                f"of ${self.monthly_budget_usd:.2f}; this call would take it to "
                f"${projected:.2f}. Scans stay in the incoming folder until next month "
                f"or until the budget is raised."
            )

    def record(self, model: str, tokens_in: int, tokens_out: int) -> float:
        usd = cost_usd(model, tokens_in, tokens_out)
        self._connection.execute(
            "INSERT INTO spend (month, at, model, tokens_in, tokens_out, usd) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (self._month(), self._clock(), model, tokens_in, tokens_out, usd),
        )
        self._connection.commit()
        return usd

    def summary(self) -> str:
        spent = self.spent_this_month()
        pct = spent / self.monthly_budget_usd * 100 if self.monthly_budget_usd else 0
        return (f"OpenAI spend {self._month()}: ${spent:.3f} of "
                f"${self.monthly_budget_usd:.2f} ({pct:.0f}%)")

    def warn_if_low(self, threshold: float = 0.8) -> bool:
        """Warn once per month when spend passes *threshold* of the budget.

        True only on the call that warns, so the caller can send the email
        once; the month is recorded, so a restart does not warn again.
        """
        if not self.monthly_budget_usd:
            return False
        month = self._month()
        if self._warned_for == month:
            return False
        if self._connection.execute(
                "SELECT 1 FROM budget_warnings WHERE month = ?", (month,)).fetchone():
            self._warned_for = month
            return False
        if self.spent_this_month() < self.monthly_budget_usd * threshold:
            return False
        logging.warning(f"Budget past {threshold:.0%}. {self.summary()}")
        self._connection.execute(
            "INSERT OR IGNORE INTO budget_warnings (month) VALUES (?)", (month,))
        self._connection.commit()
        self._warned_for = month
        return True

    def close(self) -> None:
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
