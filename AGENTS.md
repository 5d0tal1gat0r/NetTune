# AGENTS.md - Development Guidelines for Security Log Processor

## Project Overview

This is a Python-based security log processor that:
- Monitors a directory for new scanner images
- Uses OpenAI Vision API to transcribe text from images
- Processes transcribed text through AI agents for security log analysis
- Generates Word document reports

## Environment Setup

```bash
cd security_log_processor
source venv/bin/activate
```

Copy `.env.example` to `.env` and fill it in. Full table in
`deploy/README.md`; the essentials:
- `OPENAI_API_KEY` - OpenAI API key
- `INCOMING_SCANS_DIR` - Directory to monitor for new scans (default: "incoming_scans")
- `TEMPLATE_PATH` - Path to Word template (default: "templates/template.docx")
- `WATCH_MODE` - `auto` | `inotify` | `polling` (default: "auto")
- `STATE_DB` - Dedupe ledger (default: "state/processed.sqlite3")

## Build/Lint/Test Commands

### Running the Application

```bash
./venv/bin/python main.py
```

### Running Tests

`pytest` covers the file-selection rules, the dedupe ledger, observer
selection and an end-to-end pipeline run. OpenAI calls are stubbed, so the
suite needs no API key and no network.

```bash
./venv/bin/python -m pytest              # everything
./venv/bin/python -m pytest tests/test_scan_filter.py -v
./venv/bin/python -m pytest -k dedupe    # single behaviour
```

`tests/test_watcher_live.py` starts real inotify and polling observers against
a temp directory; it is the regression guard for scans in month subfolders.

### Manual Linting

Install tools manually if needed:
```bash
pip install ruff mypy black
ruff check .
black --check .
mypy .
```

## Code Style Guidelines

### General Conventions

- **Language**: Python 3.14+
- **Style**: Follows PEP 8 with some adaptations
- **Line length**: Up to 100 characters preferred

### Imports

```python
# Standard library first
import os
import time
import queue
from datetime import datetime

# Third-party libraries
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from openai import OpenAI
from docx import Document
from pydantic import BaseModel
from dotenv import load_dotenv

# Local imports
from config import config
from scanner_monitor import ScannerMonitor
```

### Naming Conventions

- **Functions/variables**: `snake_case` (e.g., `process_log`, `raw_transcription`)
- **Classes**: `PascalCase` (e.g., `ScannerMonitor`, `ScanEventHandler`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `MAX_RETRIES`)
- **Private functions**: prefix with underscore (e.g., `_internal_function`)

### Type Hints

Use type hints for all function signatures:

```python
def generate_report(analysis_data: dict, output_filename: str) -> None:
    ...

def transcribe_image(image_path: str) -> str:
    ...
```

### Docstrings

Use docstrings for all public functions:

```python
def transcribe_image(image_path: str) -> str:
    """Sends the image to OpenAI's Vision model to transcribe the text."""
    ...
```

### Error Handling

Use try/except blocks with logging:

```python
try:
    response = client.chat.completions.create(...)
    return response.choices[0].message.content
except Exception as e:
    logging.error(f"Failed to transcribe image {image_path}: {e}")
    return ""
```

### Configuration

Use Pydantic `BaseModel` for configuration:

```python
class Config(BaseModel):
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    incoming_dir: str = os.getenv("INCOMING_SCANS_DIR", "incoming_scans")
    model_name: str = "gpt-4o"

config = Config()
```

### Logging

Use the standard `logging` module with appropriate levels:

```python
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[...]
)
```

### Project Structure

```
security_log_processor/
├── main.py                   # Entry point / orchestration loop
├── config.py                 # Configuration (Pydantic)
├── scanner_monitor.py        # Recursive watcher, inotify/polling selection
├── scan_filter.py            # Which files count as scans
├── processed_ledger.py       # SHA-256 dedupe, SQLite
├── month_folders.py          # Spanish month-folder conventions
├── transcription_service.py  # OpenAI Vision integration
├── filtering_agents.py       # AI agent processing
├── report_generator.py       # Word document generation
├── prompts/                  # Prompt text (edit without touching code)
├── tests/                    # pytest suite, OpenAI stubbed
├── deploy/                   # systemd unit, Samba config, install.sh
├── templates/                # Word templates
├── incoming_scans/           # Directory monitored for new scans
└── venv/                     # Virtual environment
```

### Best Practices

1. Always check if directories exist before use (`os.makedirs(dir, exist_ok=True)`)
2. Use `logging` instead of print statements for production code
3. Handle exceptions gracefully with fallback return values
4. Use progress bars (`tqdm`) for long-running operations
5. Archive processed files rather than deleting them
6. Keep sensitive data (API keys) in `.env` files

## Invariants Worth Preserving

1. **The watcher is recursive.** Scans live in month subfolders; a
   non-recursive observer silently loses every one of them.
2. **inotify is blind to remote writes.** If the scan tree is ever a CIFS/NFS
   mount, the observer must poll. `choose_observer_kind` handles this; do not
   hardcode `Observer()`.
3. **Generated reports must never be re-ingested.** They are written into the
   watched tree on purpose. `scan_filter.IMAGE_EXTENSIONS` is the guard, and
   the SHA-256 ledger is the backstop.
4. **Every OpenAI call costs money.** Check the ledger before transcribing and
   record before archiving. Intermediate results are cached against the scan's
   content hash so a local failure downstream never re-pays for the API.
5. **Every exit from `handle_candidate` must resolve the retry scheduler.**
   `RetryScheduler.due()` parks an entry the moment it hands it back; a branch
   that returns without `record_failure` or `forget` strands the scan forever.
6. **A blank transcription is an answer, not a fault.** Retrying it just buys
   the same empty result again. Only `TranscriptionError` is retryable.

7. **Handwriting is never read perfectly, and wrongly *confidently*.** Five of
   six passes agreed on a wrong word in testing. Never collapse the readings to
   a single answer without keeping the disagreement: `consensus.consolidate`
   marks anything the passes differed on, and the report shows the alternatives.
8. **The monthly budget is enforced, not reported.** `SpendGuard.check_affordable`
   runs before every API call and `BudgetExceeded` is deliberately not retryable
   -- retrying when out of money just fails again.
9. **One report per page.** A scanner batch is one PDF holding many days; pages
   sharing a date must not overwrite each other (pass `taken=` to
   `report_filename`).

10. **Two document types, two filters.** `document_type.decide` settles
    mantenimiento vs seguridad from the model's label *checked against the
    page's vocabulary*. Terms both kinds use (muelle, alumbrado, planta) are
    deliberately excluded from the scoring lists. An unknown type falls back to
    the maintenance filter, which rewrites less.

11. **Routine omission is classification, not deletion.** The security filter
    returns a `rutinarias` boolean per entry; `apply_filter` rejects a list that
    does not line up, and never marks an entry routine unless stage 1 was
    confident about it. The report hides routine entries and says how many.
    Maintenance sheets omit nothing.

12. **An unreadable stretch is one flagged line, never dropped.** A run of
    mostly-`[?]` fragments becomes `illegible.ILLEGIBLE_GROUP`; it is always
    flagged, never routine, never noise. Repeats in a month are numbered
    because the entry table's key includes the text.

13. **The memoria is written from the dashboard, not the processor.** The
    processor files sheets and emails that a month is ready; every Guardar
    writes the .docx -- as `MEMORIA ... (BORRADOR).docx` while
    `EntryStore.to_check` is not empty, under the final name once it is, and
    only one of the two is left in the month folder. Where a batch is
    filed comes from its sheets' dates (`batch_dates.batch_month`), not the
    folder it was dropped in.
