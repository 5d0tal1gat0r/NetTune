"""Saving writes the document, and a document failure never loses the work."""

import os

import pytest

from nettune.config import config
from nettune.report.entry_store import EntryStore
from nettune.report.memoria import SEGURIDAD_BLOCK, block_contents
from nettune.review.dashboard import handle

TEMPLATE = "templates/MEMORIA.docx"
pytestmark = pytest.mark.skipif(not os.path.exists(TEMPLATE), reason="template absent")
LAN = "192.168.50.41"


@pytest.fixture
def store(tmp_path, monkeypatch):
    # config is a singleton built at import time from the environment, so
    # setting INCOMING_SCANS_DIR here would arrive too late; dashboard.py
    # already holds the pre-existing config object, and this is the pattern
    # test_dashboard_routes.py uses for the same reason.
    monkeypatch.setattr(config, "incoming_dir", str(tmp_path / "incoming_scans"))
    from nettune.report.month_folders import ensure_month_tree
    ensure_month_tree(str(tmp_path / "incoming_scans"))
    with EntryStore(str(tmp_path / "e.sqlite3")) as s:
        s.add("2026", "SEPTIEMBRE", SEGURIDAD_BLOCK,
              [{"text": "Se retiran pelonas.", "confident": False}],
              "s.pdf", "01-09-2026 p1")
        yield s


def token_for(store):
    body = handle("GET", "/mes/2026/SEPTIEMBRE", address=LAN, store=store).body.decode()
    start = body.index('name="csrf" value="') + len('name="csrf" value="')
    return body[start:body.index('"', start)]


def test_the_corrected_text_reaches_the_document(store, tmp_path):
    entry = store.month_entries("2026", "SEPTIEMBRE")[0]
    csrf = token_for(store)
    handle("POST", f"/entrada/{entry['id']}", address=LAN,
           form={"texto": "Se retiran pilonas.", "csrf": csrf}, store=store)

    response = handle("POST", "/guardar/2026/SEPTIEMBRE", address=LAN,
                      form={"csrf": csrf}, store=store)
    assert response.status in (200, 303)

    out = (tmp_path / "incoming_scans" / "2026" / "SEPTIEMBRE"
           / "MEMORIA 2026 SEPTIEMBRE.docx")
    assert out.exists()
    assert "Se retiran pilonas." in "\n".join(block_contents(str(out))[SEGURIDAD_BLOCK])


def test_a_document_failure_does_not_lose_the_edit(store, monkeypatch):
    entry = store.month_entries("2026", "SEPTIEMBRE")[0]
    csrf = token_for(store)
    handle("POST", f"/entrada/{entry['id']}", address=LAN,
           form={"texto": "Se retiran pilonas.", "csrf": csrf}, store=store)

    from nettune.review import dashboard
    monkeypatch.setattr(dashboard, "rebuild_memoria",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disco lleno")))
    response = handle("POST", "/guardar/2026/SEPTIEMBRE", address=LAN,
                      form={"csrf": csrf}, store=store)

    assert response.status == 200
    assert "no se pudo" in response.body.decode().lower()
    assert store.month_entries("2026", "SEPTIEMBRE")[0]["text"] == "Se retiran pilonas."
