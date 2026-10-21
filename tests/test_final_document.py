"""Guardar always writes the memoria; its name says whether it is final.

Until every sheet of the month has been checked it is the draft,
"MEMORIA ... (BORRADOR).docx"; after, the final name. Only one of the two
is ever in the month folder, so an out-of-date final cannot sit there
looking current.
"""

import os

import pytest

from nettune.config import config
from nettune.report.entry_store import EntryStore
from nettune.report.memoria import SEGURIDAD_BLOCK, block_contents
from nettune.report.month_folders import memoria_name, processed_dir_for, revision_dir_for
from nettune.report.review_marks import image_name
from nettune.review.dashboard import handle

LAN = "192.168.50.41"
TEMPLATE = os.path.abspath("templates/MEMORIA.docx")
pytestmark = pytest.mark.skipif(not os.path.exists(TEMPLATE), reason="template absent")


@pytest.fixture
def month(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "incoming_dir", str(tmp_path / "incoming"))
    monkeypatch.setattr(config, "template_path", TEMPLATE)
    revision = revision_dir_for(config.incoming_dir, "2026", "OCTUBRE")
    os.makedirs(revision)
    with EntryStore(str(tmp_path / "e.sqlite3")) as store:
        for page, ref in enumerate(("01-10-2026 p1", "01-10-2026 p2"), start=1):
            store.record_sheet("2026", "OCTUBRE", "SKM.pdf", page, ref)
            with open(os.path.join(revision, image_name(ref)), "wb") as handle_:
                handle_.write(b"jpg")
        # p1 has a doubtful line; p2 was read as empty.
        store.add("2026", "OCTUBRE", SEGURIDAD_BLOCK,
                  [{"text": "Se observa humo en zona 4.", "confident": False}],
                  "SKM.pdf", "01-10-2026 p1")
        yield store


def token(store):
    body = handle("GET", "/mes/2026/OCTUBRE", address=LAN, store=store).body.decode()
    start = body.index('name="csrf" value="') + len('name="csrf" value="')
    return body[start:body.index('"', start)]


def document(draft=False):
    return os.path.join(processed_dir_for(config.incoming_dir, "2026", "OCTUBRE"),
                        memoria_name("2026", "OCTUBRE", draft=draft))


def status(store):
    return handle("GET", "/mes/2026/OCTUBRE", address=LAN, store=store).body.decode()


def test_saving_before_the_review_is_done_writes_the_draft(month):
    assert "falta revisar 2 hojas" in status(month)
    response = handle("POST", "/guardar/2026/OCTUBRE", address=LAN, store=month,
                      form={"csrf": token(month)})
    assert response.status == 303
    assert os.path.isfile(document(draft=True))
    assert not os.path.exists(document())
    assert block_contents(document(draft=True))[SEGURIDAD_BLOCK][0] == \
        "Se observa humo en zona 4."
    body = status(month)
    assert "Borrador guardado el" in body
    assert "falta revisar 2 hojas" in body


def test_the_draft_replaces_an_out_of_date_final(month):
    os.makedirs(os.path.dirname(document()), exist_ok=True)
    with open(document(), "wb") as stale:
        stale.write(b"written before the latest sheets came in")
    handle("POST", "/guardar/2026/OCTUBRE", address=LAN, store=month,
           form={"csrf": token(month)})
    assert os.path.isfile(document(draft=True))
    assert not os.path.exists(document())


def test_once_every_sheet_is_checked_saving_writes_the_final_document(month):
    csrf = token(month)
    handle("POST", "/guardar/2026/OCTUBRE", address=LAN, store=month, form={"csrf": csrf})
    assert os.path.isfile(document(draft=True))
    entry = month.month_entries("2026", "OCTUBRE")[0]
    handle("POST", f"/entradas/{entry['id']}", address=LAN, store=month,
           form={"csrf": csrf, "accion": "confirmar"})
    assert "falta revisar 1 hoja" in status(month)
    assert handle("POST", "/hoja/01-10-2026_p2.jpg/vacia", address=LAN, store=month,
                  form={"csrf": csrf}).status == 303
    assert month.to_check("2026", "OCTUBRE") == {}
    assert "pulse Guardar" in status(month)

    handle("POST", "/guardar/2026/OCTUBRE", address=LAN, store=month, form={"csrf": csrf})
    assert os.path.isfile(document())
    assert not os.path.exists(document(draft=True)), "the draft goes once final"
    lines = block_contents(document())[SEGURIDAD_BLOCK]
    assert lines == ["Se observa humo en zona 4."]
    assert "Documento final generado" in status(month)


def test_an_empty_sheet_confirmed_shows_as_reviewed(month):
    handle("POST", "/hoja/01-10-2026_p2.jpg/vacia", address=LAN, store=month,
           form={"csrf": token(month)})
    body = status(month)
    assert "Revisada: no hay nada que añadir" in body
    assert "Revisada: hoja vacía" in body


def test_confirming_an_empty_sheet_needs_the_token(month):
    assert handle("POST", "/hoja/01-10-2026_p2.jpg/vacia", address=LAN, store=month,
                  form={}).status == 403
    assert "01-10-2026 p2" in month.to_check("2026", "OCTUBRE")
