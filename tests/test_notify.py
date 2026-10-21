"""The email that says a batch is ready, or could not be read."""

import smtplib

import pytest

from nettune.config import config
from nettune.ops import notify
from nettune.report.entry_store import EntryStore
from nettune.report.memoria import SEGURIDAD_BLOCK


@pytest.fixture
def mail(monkeypatch):
    monkeypatch.setattr(config, "notify_to", "revisor@example.com")
    monkeypatch.setattr(config, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(config, "dashboard_url", "http://192.168.50.10:8080/")
    sent = []
    return sent


@pytest.fixture
def store(tmp_path):
    with EntryStore(str(tmp_path / "e.sqlite3")) as s:
        for page, ref in enumerate(("01-10-2026 p1", "01-10-2026 p2", "01-10-2026 p3"), 1):
            s.record_sheet("2026", "OCTUBRE", "SKM.pdf", page, ref)
        s.add("2026", "OCTUBRE", SEGURIDAD_BLOCK,
              [{"text": "Se observa humo.", "confident": False}], "SKM.pdf", "01-10-2026 p1")
        s.add("2026", "OCTUBRE", SEGURIDAD_BLOCK,
              [{"text": "Se abre el torreón a un técnico."}], "SKM.pdf", "01-10-2026 p2")
        yield s


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def notifier(store, sent, clock, send=None):
    return notify.Notifier(store, settle_seconds=120, clock=clock,
                           send=send or (lambda subject, body: sent.append((subject, body))))


def test_nothing_goes_until_the_share_has_been_quiet(mail, store):
    clock = Clock()
    n = notifier(store, mail, clock)
    n.filed([("2026", "OCTUBRE")])
    clock.now = 60
    assert n.tick() == 0
    # A second PDF of the same month resets the wait and joins the email.
    n.filed([("2026", "OCTUBRE")])
    clock.now = 179
    assert n.tick() == 0
    clock.now = 181
    assert n.tick() == 1
    assert n.tick() == 0
    subject, body = mail[0]
    assert subject == "NetTune: Octubre 2026 listo para revisar"
    # 3 sheets: p1 has a doubtful line, p3 was read as empty.
    assert "Seguridad: 3 hojas; 2 necesitan revisión." in body
    assert "http://192.168.50.10:8080/mes/2026/OCTUBRE" in body
    assert "Mantenimiento" not in body, "no maintenance sheets, no section"
    assert "Guardar" in body


def test_one_email_per_month(mail, store):
    clock = Clock()
    n = notifier(store, mail, clock)
    n.filed([("2026", "SEPTIEMBRE"), ("2026", "OCTUBRE")])
    clock.now = 200
    assert n.tick() == 2


def test_a_scan_that_could_not_be_read_is_reported(mail, store):
    clock = Clock()
    n = notifier(store, mail, clock)
    n.problem("SKM_1.pdf", "se ha agotado el presupuesto mensual de lectura.")
    n.already_read("SKM_2.pdf")
    clock.now = 200
    assert n.tick() == 2
    assert "no se ha podido leer SKM_1.pdf" in mail[0][0]
    assert "presupuesto" in mail[0][1]
    assert "ya estaba leído" in mail[1][0]
    # The folder it went to is hidden on the share: not named, not looked for.
    assert "carpeta" not in mail[1][1]


def test_without_settings_nothing_is_sent(mail, store, monkeypatch):
    monkeypatch.setattr(config, "notify_to", "")
    clock = Clock()
    n = notifier(store, mail, clock)
    n.filed([("2026", "OCTUBRE")])
    clock.now = 200
    assert n.tick() == 0 and mail == []


def test_a_failed_send_is_tried_again_then_dropped(mail, store):
    clock = Clock()
    tries = []

    def broken(subject, body):
        tries.append(subject)
        raise smtplib.SMTPServerDisconnected("down")

    n = notifier(store, mail, clock, send=broken)
    n.filed([("2026", "OCTUBRE")])
    clock.now = 200
    n.tick()
    clock.now = 300
    n.tick()                       # too soon to try again
    for step in (600, 1000, 1400):
        clock.now = step
        n.tick()
    assert len(tries) == notify.MAX_SEND_ATTEMPTS


def test_send_mail_uses_starttls_and_logs_in(mail, monkeypatch):
    monkeypatch.setattr(config, "smtp_user", "cuenta@example.com")
    monkeypatch.setattr(config, "smtp_password", "app-password")
    monkeypatch.setattr(config, "smtp_port", 587)
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context):
            calls.append(("starttls",))

        def login(self, user, password):
            calls.append(("login", user))

        def send_message(self, message):
            calls.append(("send", message["To"], message["From"], message["Subject"]))

    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    notify.send_mail("Asunto", "Cuerpo")
    assert calls == [("connect", "smtp.example.com", 587), ("starttls",),
                     ("login", "cuenta@example.com"),
                     ("send", "revisor@example.com", "cuenta@example.com", "Asunto")]


def test_each_section_is_counted_and_linked_on_its_own(mail, store):
    """September 30's email said "109 hojas; 105 necesitan revisión", both
    sections added together, and linked only to Seguridad."""
    store.record_sheet("2026", "OCTUBRE", "S25C.pdf", 1, "mant 01-10-2026 p1")
    store.record_sheet("2026", "OCTUBRE", "S25C.pdf", 2, "mant 02-10-2026 p2")
    store.add("2026", "OCTUBRE", "Otros",
              [{"text": "Con Digi para local 17.", "confident": True}],
              "S25C.pdf", "mant 01-10-2026 p1")
    clock = Clock()
    n = notifier(store, mail, clock)
    n.filed([("2026", "OCTUBRE")])
    clock.now = 200
    assert n.tick() == 1
    _, body = mail[0]
    assert "Seguridad: 3 hojas; 2 necesitan revisión." in body
    # p1 is confirmed; p2 has no lines, so it still needs a look.
    assert "Mantenimiento: 2 hojas; 1 necesita revisión." in body
    assert "http://192.168.50.10:8080/mes/2026/OCTUBRE" in body
    assert "http://192.168.50.10:8080/mantenimiento/2026/OCTUBRE" in body
    assert body.index("Seguridad:") < body.index("/mes/2026/OCTUBRE") \
        < body.index("Mantenimiento:") < body.index("/mantenimiento/2026/OCTUBRE")


def test_guardar_is_described_as_it_now_works(mail, store):
    _, body = notify.ready_message("2026", "OCTUBRE", {"seguridad": (3, 0)})
    assert "Ninguna necesita revisión." in body
    assert "borrador" in body and "documento final" in body
