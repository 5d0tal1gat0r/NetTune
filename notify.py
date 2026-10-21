"""Email when a batch is ready to review, or could not be read.

The workflow is: drop the PDF anywhere in the share, wait for the email,
review in the dashboard, press Guardar. So the email is the signal that the
reading is over. A month usually arrives as several PDFs dropped together;
the email waits until no scan has been handled for a quiet spell, and then
says, per month and per section -- Seguridad and Mantenimiento, the
dashboard's two tabs -- how many sheets are in, how many need checking, and
where to open them.

Sending never stops the pipeline: a failed send is logged and retried a few
times, then dropped. Nothing is sent unless NOTIFY_TO and SMTP_HOST are set.
"""

import logging
import smtplib
import ssl
import time
from email.message import EmailMessage

from config import config
from entry_store import MANTENIMIENTO_SECTION, SEGURIDAD_SECTION

MAX_SEND_ATTEMPTS = 3
RETRY_SECONDS = 300


def enabled() -> bool:
    return bool(config.notify_to.strip() and config.smtp_host.strip())


def send_mail(subject: str, body: str) -> None:
    """Send one plain-text email with the configured SMTP account."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.smtp_from or config.smtp_user
    message["To"] = config.notify_to
    message.set_content(body)
    context = ssl.create_default_context()
    if config.smtp_port == 465:
        server = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, context=context,
                                  timeout=30)
    else:
        server = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30)
    with server:
        if config.smtp_port != 465:
            server.starttls(context=context)
        if config.smtp_user:
            server.login(config.smtp_user, config.smtp_password)
        server.send_message(message)


# Each section's tab in the dashboard, and its name in the email, in order.
_SECTIONS = ((SEGURIDAD_SECTION, "Seguridad", "mes"),
             (MANTENIMIENTO_SECTION, "Mantenimiento", "mantenimiento"))


def month_link(year: str, month: str, section: str = SEGURIDAD_SECTION) -> str:
    path = dict((key, route) for key, _, route in _SECTIONS)[section]
    return f"{config.dashboard_url.rstrip('/')}/{path}/{year}/{month}"


def ready_message(year: str, month: str,
                  counts: dict[str, tuple[int, int]]) -> tuple[str, str]:
    """Subject and body for a month whose sheets are ready to review.

    *counts* is {section: (sheets, sheets to check)}. Each section with
    sheets gets its own line and its own link: the two used to be added
    together ("109 hojas; 105 necesitan revisión") under one link to
    Seguridad, and the maintenance sheets were reached only by knowing to
    switch tabs.
    """
    subject = f"NetTune: {month.capitalize()} {year} listo para revisar"
    parts = []
    for section, name, _ in _SECTIONS:
        sheets, to_check = counts.get(section, (0, 0))
        if not sheets:
            continue
        hojas = "1 hoja" if sheets == 1 else f"{sheets} hojas"
        if to_check:
            pendientes = "1 necesita" if to_check == 1 else f"{to_check} necesitan"
            estado = f"{pendientes} revisión."
        else:
            estado = "Ninguna necesita revisión."
        parts.append(f"{name}: {hojas}; {estado}\n{month_link(year, month, section)}")
    body = (
        f"Ya se han leído las hojas de {month.lower()} de {year}.\n\n"
        + "\n\n".join(parts)
        + "\n\nGuardar guarda un borrador de la memoria en cualquier momento; con "
        "todas las hojas revisadas, genera el documento final en la carpeta del mes.\n"
    )
    return subject, body


def problem_message(scan_name: str, reason: str) -> tuple[str, str]:
    subject = f"NetTune: no se ha podido leer {scan_name}"
    body = (
        f"El escaneo {scan_name} no se ha podido procesar.\n\n"
        f"Motivo: {reason}\n\n"
        "El archivo sigue en la carpeta donde se dejó.\n"
    )
    return subject, body


def budget_message(summary: str) -> tuple[str, str]:
    """The once-a-month warning that the reading budget is nearly spent."""
    subject = "NetTune: presupuesto de lectura casi agotado"
    body = (
        f"Se ha gastado más del 80 % del presupuesto mensual de lectura.\n\n"
        f"{summary}\n\n"
        "Al llegar al 100 %, los escaneos nuevos esperan en la carpeta hasta el "
        "mes que viene. Para seguir leyendo este mes, suba MONTHLY_BUDGET_EUR "
        f"(ahora {config.monthly_budget_eur:g} €) en /opt/security_log_processor/.env "
        "y reinicie el servicio.\n"
    )
    return subject, body


class Notifier:
    """Collects what happened and sends it once things go quiet."""

    def __init__(self, store, settle_seconds: float | None = None,
                 clock=time.monotonic, send=send_mail):
        self._store = store
        self._settle = (config.notify_settle_seconds if settle_seconds is None
                        else settle_seconds)
        self._clock = clock
        self._send = send
        self._months: list[tuple[str, str]] = []
        self._problems: list[tuple[str, str]] = []
        self._notices: list[tuple[str, str]] = []
        self._last_activity = clock()
        self._outbox: list[list] = []   # [subject, body, attempts, next_try]

    def filed(self, months) -> None:
        """Sheets were filed into these (year, month) pairs."""
        for pair in months:
            if pair not in self._months:
                self._months.append(pair)
        self._last_activity = self._clock()

    def budget_low(self, summary: str) -> None:
        """The month's spend has passed 80% of the budget (once a month)."""
        self._notices.append(budget_message(summary))
        self._last_activity = self._clock()

    def problem(self, scan_name: str, reason: str) -> None:
        self._problems.append((scan_name, reason))
        self._last_activity = self._clock()

    def already_read(self, scan_name: str) -> None:
        """A re-scan of paper already read was set aside unread.

        The email names no folder: the scans set aside are kept in a folder
        the share hides, and there is nothing for the colleague to do there.
        """
        self._notices.append((
            f"NetTune: {scan_name} ya estaba leído",
            f"Todas las hojas de {scan_name} ya se habían leído antes, así que no se "
            f"ha vuelto a leer (no ha costado nada) y se ha guardado aparte. "
            f"No hace falta hacer nada.\n",
        ))
        self._last_activity = self._clock()

    def busy(self) -> None:
        """A scan is being handled: hold the email until it is done."""
        self._last_activity = self._clock()

    def tick(self) -> int:
        """Send what is due. Returns how many emails went out."""
        now = self._clock()
        waiting = self._months or self._problems or self._notices
        if waiting and now - self._last_activity >= self._settle:
            for year, month in self._months:
                sections = self._store.sheet_sections(year, month)
                pending = self._store.to_check(year, month)
                counts = {
                    section: (sum(s == section for s in sections.values()),
                              sum(sections.get(ref) == section for ref in pending))
                    for section, _, _ in _SECTIONS
                }
                self._outbox.append([*ready_message(year, month, counts), 0, now])
            for scan_name, reason in self._problems:
                self._outbox.append([*problem_message(scan_name, reason), 0, now])
            for subject, body in self._notices:
                self._outbox.append([subject, body, 0, now])
            self._months, self._problems, self._notices = [], [], []
        if not enabled():
            if self._outbox:
                logging.warning(f"Email not configured; {len(self._outbox)} notice(s) not sent")
                self._outbox = []
            return 0
        sent = 0
        for item in self._outbox[:]:
            subject, body, _, next_try = item
            if now < next_try:
                continue
            try:
                self._send(subject, body)
            except (OSError, smtplib.SMTPException) as exc:
                item[2] += 1
                item[3] = now + RETRY_SECONDS
                if item[2] >= MAX_SEND_ATTEMPTS:
                    logging.error(f"Could not email '{subject}' after {item[2]} tries: {exc}")
                    self._outbox.remove(item)
                else:
                    logging.warning(f"Could not email '{subject}' ({exc}); trying again later")
                continue
            logging.warning(f"Emailed {config.notify_to}: {subject}")
            self._outbox.remove(item)
            sent += 1
        return sent
