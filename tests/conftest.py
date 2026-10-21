import os
import sys

import pytest

_APP_MODULES = {
    "config", "main", "transcription_service",
    "filtering_agents", "processed_ledger", "scan_filter", "scanner_monitor",
    "month_folders", "retry_scheduler", "consensus", "spend_guard",
    "page_reader", "pdf_pages", "nettune_feedback",
}


@pytest.fixture(autouse=True)
def _feedback_db_in_tmp(tmp_path, monkeypatch):
    """Capture writes into the test's own folder, never into the repo's state/."""
    path = str(tmp_path / "feedback" / "feedback.sqlite3")
    monkeypatch.setenv("FEEDBACK_DB", path)
    if "config" in sys.modules:
        monkeypatch.setattr(sys.modules["config"].config, "feedback_db", path)


@pytest.fixture
def app(tmp_path, monkeypatch):
    """The application imported fresh, with every path inside tmp_path."""
    incoming = tmp_path / "incoming_scans"
    incoming.mkdir()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("INCOMING_SCANS_DIR", str(incoming))
    monkeypatch.setenv("TEMPLATE_PATH", str(tmp_path / "templates" / "t.docx"))
    monkeypatch.setenv("STATE_DB", str(tmp_path / "state" / "p.sqlite3"))
    monkeypatch.setenv("SPEND_DB", str(tmp_path / "state" / "s.sqlite3"))
    monkeypatch.setenv("MONTHLY_BUDGET_EUR", "5")
    monkeypatch.setenv("READINGS_PER_PAGE", "3")
    monkeypatch.chdir(tmp_path)
    for module in list(sys.modules):
        if module in _APP_MODULES:
            del sys.modules[module]

    import main
    from month_folders import ensure_month_tree

    ensure_month_tree(str(incoming))
    main.incoming = str(incoming)
    # Keep the real wait_until_ready logic, drop its 1s-per-reading sleeps.
    monkeypatch.setattr(main, "wait_for_file_stable",
                        lambda p, timeout=0: os.path.isfile(p))
    return main


def a_page(fecha="02-07-2026", entries=(("Conectando mg de aire", True),)):
    return {
        "titulo": "FICHA DIARIA DE TRABAJO",
        "fecha": fecha,
        "fecha_confident": True,
        "fecha_variants": [fecha],
        "operarios": ["A. Ejemplo"],
        "operarios_confident": True,
        "trabajos": [{"text": t, "confident": c, "variants": []} for t, c in entries],
        "readings": 3,
    }


@pytest.fixture
def kit(app):
    """app plus a ledger, retry scheduler, monitor and spend guard."""
    from processed_ledger import ProcessedLedger
    from retry_scheduler import RetryScheduler
    from scanner_monitor import ScannerMonitor
    from spend_guard import SpendGuard

    ledger = ProcessedLedger(app.config.state_db)
    guard = SpendGuard(app.config.spend_db, monthly_budget_eur=5.0)
    retries = RetryScheduler(base_delay=10, max_attempts=3, clock=lambda: 0.0)
    monitor = ScannerMonitor(app.incoming, mode="polling", poll_interval=99)
    yield app, ledger, retries, monitor, guard
    ledger.close()
    guard.close()
