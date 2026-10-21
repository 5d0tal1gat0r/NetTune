import os

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no")


class Config(BaseModel):
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    incoming_dir: str = os.getenv("INCOMING_SCANS_DIR", "incoming_scans")
    template_path: str = os.getenv("TEMPLATE_PATH", "templates/MEMORIA.docx")

    # gpt-5.4 is chosen for consistency, not raw accuracy. Measured on a real
    # security sheet: gpt-5.4-mini agreed with itself on 0% of entries across
    # three readings, so every line was flagged and the flags meant nothing.
    # gpt-5.4 agreed on 91%, leaving 2 flags out of 23 that are worth reading.
    model_name: str = os.getenv("OPENAI_MODEL", "gpt-5.4")
    max_output_tokens: int = int(os.getenv("MAX_OUTPUT_TOKENS", "4000"))

    # Independent readings per page. Handwriting cannot be read perfectly, so
    # several passes are compared and disagreements are flagged for a human.
    # Two readings of gpt-5.4 measured better than three: more readings only
    # find more ways to disagree, and two fit the monthly budget.
    readings_per_page: int = int(os.getenv("READINGS_PER_PAGE", "2"))
    # An entry only one reading saw is probably invented. Requiring two
    # independent readings to have seen a line keeps inventions out of the
    # document, at the cost of losing a line one reading missed.
    min_readings_per_entry: int = int(os.getenv("MIN_READINGS_PER_ENTRY", "2"))
    pdf_dpi: int = int(os.getenv("PDF_DPI", "300"))
    # Straighten sideways scans before transcribing. Needs tesseract-ocr.
    auto_rotate: bool = _flag("AUTO_ROTATE", "true")
    # The scanner puts two daily sheets on every page. Reading them together
    # merged entries across shifts, lost one of the two dates, and left the
    # handwriting at half the resolution the model needed. Needs opencv.
    # Tell security, maintenance and parking-ticket pages apart by their
    # printed headers before splitting (page_kind). Needs tesseract.
    classify_pages: bool = _flag("CLASSIFY_PAGES", "true")
    split_sheets: bool = _flag("SPLIT_SHEETS", "true")
    # Daily report sheets per day in a batch, in order. Dates are taken from
    # a sheet's place in the batch when the read dates agree with it; 0 turns
    # that off and leaves every date as read.
    sheets_per_day: int = int(os.getenv("SHEETS_PER_DAY", "4"))

    # Measured on a real 300 dpi page; used to price a call before making it.
    estimated_tokens_in: int = int(os.getenv("ESTIMATED_TOKENS_IN", "5200"))
    estimated_tokens_out: int = int(os.getenv("ESTIMATED_TOKENS_OUT", "400"))

    # Hard monthly cap. Enforced before every call, not merely reported.
    monthly_budget_eur: float = float(os.getenv("MONTHLY_BUDGET_EUR", "5"))
    eur_usd: float = float(os.getenv("EUR_USD", "1.10"))
    spend_db: str = os.getenv("SPEND_DB", "state/spend.sqlite3")

    # Stage 2: tidy the wording and redact names. One cheap call per page.
    enable_filter_stage: bool = _flag("ENABLE_FILTER_STAGE", "true")
    redact_names: bool = _flag("REDACT_NAMES", "true")
    # Hide the checks that repeat almost every day, so the report shows what
    # actually happened. Set false to print every anotacion.
    omit_routine: bool = _flag("OMIT_ROUTINE", "true")

    # Mark an entry the readings disagreed on with the page it came from, and
    # copy every page into the month's revision folder, where the dashboard
    # shows it beside its lines for a colleague to check against the paper.
    mark_uncertain: bool = _flag("MARK_UNCERTAIN", "true")

    watch_mode: str = os.getenv("WATCH_MODE", "auto")
    poll_interval: float = float(os.getenv("POLL_INTERVAL", "5"))
    stability_timeout: int = int(os.getenv("STABILITY_TIMEOUT", "30"))
    state_db: str = os.getenv("STATE_DB", "state/processed.sqlite3")
    # Entries gathered for each month's memoria, so a later scan adds to it.
    entry_db: str = os.getenv("ENTRY_DB", "state/memoria_entries.sqlite3")
    # Every stage of every reading and every correction made in the
    # dashboard, kept for measuring the pipeline (ocr_feedback). Its own
    # file: nothing in the working databases changes. DATASET_CAPTURE=off
    # turns it off and changes nothing else.
    feedback_db: str = os.getenv("FEEDBACK_DB", "state/feedback.sqlite3")
    dataset_capture: bool = os.getenv("DATASET_CAPTURE", "on").strip().lower() \
        not in ("off", "0", "false", "no")
    # Nightly copies of the four databases (tools/backup_state.py).
    backup_dir: str = os.getenv("BACKUP_DIR", "/var/backups/nettune")

    retry_base_delay: float = float(os.getenv("RETRY_BASE_DELAY", "60"))
    retry_max_attempts: int = int(os.getenv("RETRY_MAX_ATTEMPTS", "4"))

    write_report_beside_scan: bool = _flag("WRITE_REPORT_BESIDE_SCAN", "true")

    # Email when a batch is ready to review, or could not be read. Off unless
    # NOTIFY_TO and SMTP_HOST are set. The password lives only in .env.
    notify_to: str = os.getenv("NOTIFY_TO", "")
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "")
    # How the link in the email reaches the dashboard from the colleague's PC.
    dashboard_url: str = os.getenv("DASHBOARD_URL", "http://localhost:8080")
    # Quiet time after the last scan before the email goes: a month often
    # arrives as several PDFs dropped together, and that is one email.
    notify_settle_seconds: float = float(os.getenv("NOTIFY_SETTLE_SECONDS", "120"))


config = Config()

os.makedirs(config.incoming_dir, exist_ok=True)
os.makedirs(os.path.dirname(config.template_path) or "templates", exist_ok=True)
