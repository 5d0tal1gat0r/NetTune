# NetTune: security log processor

> Built for a shopping centre's security and maintenance team and running in
> production on a Raspberry Pi. This public copy has the client's name, its
> shop names, network addresses and all real documents and scans removed; the
> history starts here.

Turns scanned paper security and maintenance logs into the centre's monthly
memoria (`MEMORIA <year> <MES>.docx`), with a person checking
every sheet before the document is written.

## The workflow

1. **Drop the PDF anywhere in the share.** The top of `incoming_scans`, a
   year folder, the wrong month's folder, a folder of its own: the dates on
   the sheets decide where the batch belongs, and the folder is only used
   when too few dates can be read. A batch that runs over a month end puts
   each day in its own month. The PDF ends up in `<year>/<MES>/.escaneos_originales/`.
   A file, or paper, that was already read is set aside in
   `<year>/<MES>/.duplicados/` without being read again. Both folders are
   hidden on the share, like `.revision/`: a month folder shows only its memoria.
2. **The Pi reads it.** Every sheet is read twice by the OpenAI vision
   model, dated, put in shift order, tidied and filtered for routine, and its
   image saved in `<year>/<MES>/.revision/` (hidden on the share) for the dashboard.
3. **An email says it is ready.** Once no scan has come in for a couple of
   minutes, one email per month goes to `NOTIFY_TO`: how many sheets, how
   many need checking, and a link to the month in the dashboard. A scan that
   could not be read (budget spent, no legible date, repeated failures) gets
   an email too.
4. **The colleague reviews in the dashboard.** Each sheet beside its lines:
   correct, confirm, add, delete, fix a date, turn an image, confirm that an
   empty sheet really is empty. Guardar keeps the edits at any point, and
   writes `MEMORIA … (BORRADOR).docx` into the month folder while sheets are
   left to check. The status line in the dashboard says how many.
5. **The final document.** When no sheet is left to check, Guardar writes the
   final memoria into the month folder itself, `<year>/<MES>/`, in place of the
   draft. Should a later scan bring that month new sheets to check, the final
   becomes the draft again, so the share never shows a month as done when it
   is not.

```
incoming_scans/**/batch.pdf
        │
        ├─▶ reading (OpenAI vision, twice per sheet, consensus)
        ├─▶ dating, shift order, filter, routine omitted
        ├─▶ <year>/<MES>/.revision/DD-MM-YYYY_pN.jpg  ← for the dashboard
        ├─▶ <year>/<MES>/.escaneos_originales/batch.pdf  ← original kept
        ├─▶ email: "listo para revisar"
        └─ dashboard review ─▶ Guardar ─▶ <year>/<MES>/MEMORIA … .docx
```

## Scan formats

**PDF** is the normal input: the office scanner produces one multi-page PDF per
batch, one day's sheet per page. Each page is rasterised at 300 dpi and becomes
its own report. Images (JPEG, PNG, WEBP, GIF) are read directly; TIFF and BMP
are converted to PNG first because the Vision API rejects them.

## Accuracy, honestly

Handwritten cursive cannot be transcribed perfectly, and the failure is silent:
measured on a real sheet, the word "aire" was read as "cobre" by five of six
passes across two models -- confidently and unanimously, with both words in the
prompt glossary.

So each page is read `READINGS_PER_PAGE` times independently. Entries every
pass agreed on are printed plainly; entries they disagreed on are marked with
a warning sign and list the alternative readings, so a human checks those lines
and trusts the rest. The report footer says how many need checking.

Dates get a second, free check: a scanned batch is one session covering
contiguous days, so a page dated months from its neighbours has been misread
even when every pass agreed on it. On a real 25-page July batch this caught a
sheet read unanimously as 16-04-2026 that consensus alone could not.

Typed or printed sheets come out essentially perfect; the flagging matters for
handwriting.

## Cost

Measured on real scans with `gpt-5.4-mini` at 300 dpi: about **$0.003 per
reading**, so roughly **$0.010 per page** at three readings. At five pages a
day that is about **EUR1.20/month**. `MONTHLY_BUDGET_EUR` is a hard cap,
checked before every call: when it is reached the service stops calling the API
and leaves scans in the incoming folder rather than overspending.

## Layout

```
main.py, dashboard.py   entry points (what the systemd units run)
nettune/                the application package
├── config.py           settings (Pydantic), all overridable from .env
├── main.py             orchestration: detect → stabilise → dedupe → process → archive
├── intake/             watching the share, what counts as a scan, never twice
├── pages/              orientation, page kind, blank pages, one paper or two
├── reading/            OpenAI vision calls, repeated readings, consensus
├── dates/              dating sheets and checking them against the batch
├── report/             stored lines, routine rules, the monthly memoria (.docx)
├── review/             the review dashboard (server, auth, HTML)
└── ops/                spend cap, email notices, the correction feedback loop
ocr_feedback/           standalone library: OCR dataset export and evaluation
prompts/                prompt text, edited without touching code
tools/                  one-off maintenance scripts for stored months
tests/                  pytest suite, OpenAI stubbed
deploy/                 Raspberry Pi install, systemd units, Samba config
promptfoo/, feedback/   prompt evals and the OCR feedback profile
```

| Module | Responsibility |
|---|---|
| `nettune/main.py` | Orchestration loop: detect → stabilise → dedupe → process → archive |
| `nettune/config.py` | Pydantic settings, all overridable from `.env` |
| `nettune/intake/scanner_monitor.py` | Recursive watcher; picks inotify or polling per filesystem |
| `nettune/intake/scan_filter.py` | Which files are real scans (and which are the app's own output) |
| `nettune/intake/processed_ledger.py` | SHA-256 record of processed scans, plus a cache of paid stages |
| `nettune/intake/retry_scheduler.py` | Exponential-backoff retries so a transient API outage loses nothing |
| `nettune/intake/pdf_pages.py` | Rasterises each PDF page to an image |
| `nettune/reading/page_reader.py` | Reads a page several times for cross-checking |
| `nettune/reading/consensus.py` | Reconciles the readings and flags disagreements |
| `nettune/reading/transcription_service.py` | OpenAI Vision call |
| `nettune/reading/filtering_agents.py` | Analysis agent over the transcription |
| `nettune/dates/batch_dates.py` | Cross-checks page dates against the rest of the batch |
| `nettune/report/month_folders.py` | Spanish month-folder conventions |
| `nettune/report/memoria.py` | Word document output |
| `nettune/review/dashboard.py` | The review dashboard |
| `nettune/ops/spend_guard.py` | Hard monthly budget, enforced before every call |
| `prompts/` | Prompt text, edited without touching code |

## Documents not in this repository

Two things the code needs are deliberately untracked, because they are real
company documents with personal and commercial data:

| Path | What it is |
|---|---|
| `templates/MEMORIA.docx` | the manager's monthly report, used as the template |
| `promptfoo/fixtures/*.jpg` | real scanned sheets, used by the eval suite |

Both are described in `deploy/README.md` and `promptfoo/README.md`. The test
suite skips the cases that need them rather than failing.

## Local development

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env        # then add your OPENAI_API_KEY
./venv/bin/python main.py
```

## Tests

No network access and no API key required — the OpenAI calls are stubbed.

```bash
./venv/bin/python -m pytest
```

The live watcher tests exercise real inotify and polling observers, so the
suite takes a few seconds.

## Deployment

See [`deploy/README.md`](deploy/README.md) for the Raspberry Pi setup, the
Samba topology, and why the Pi must *host* the share rather than mount it.

## Two kinds of sheet

| Type | Sheet | Recognised by |
|---|---|---|
| `mantenimiento` | FICHA DIARIA DE TRABAJO DE MANTENIMIENTO | title; vocabulary (cuadros electricos, mg de aire, cargadores); bay codes 7-4, P-1 |
| `seguridad` | Parte diario del servicio de vigilancia | title; "Inicio/Finaliza el servicio"; vocabulary (pilonas, torreones, rampas); zone codes Z1..Z27 |

The type is identified per page and decides which filter runs. The model is
asked to label the page, but `document_type.decide` checks that label against
the page's own vocabulary -- a label is cheap to get wrong and expensive to act
on. Reports are named `YYYYMMDD_Mantenimiento.docx` / `YYYYMMDD_Seguridad.docx`,
so the two kinds never collide even on the same date.

## The prompts

| Stage | Prompt | Job |
|---|---|---|
| 1 | `prompts/transcription.md` | Image -> literal JSON, including `tipo`. Transcribes everything, removes nothing, marks doubtful words `[?]`. Carries both vocabularies and is told to use only the one matching the sheet. Run `READINGS_PER_PAGE` times per page. |
| 2a | `prompts/filter_mantenimiento.md` | Expands technical abbreviations (mg -> manguera, PK -> parking, (1H) -> (1 hora)) and redacts operarios' names. |
| 2b | `prompts/filter_seguridad.md` | Rewrites into the impersonal wording of a service report, keeps zone codes, takes out people's names but keeps how the log describes them ("unos jóvenes", "una chica"), as the author's memorias do, and **classifies each entry as routine or notable**. Keeps times, which are part of the event in a service log. |

### Routine entries are omitted

Both kinds of sheet are mostly the same checks every day. Measured across a real
25-page batch: `conectando mg de aire` appears on 14 pages and
`revisando cuadros electricos` on about 11, against 114 distinct one-off
entries. Printing all of it buries what actually happened, so routine entries
are left out.

| Type | Routine | Notable |
|---|---|---|
| `mantenimiento` | revision de cuadros electricos, conectar la mg de aire/cobre, comprobar niveles y riego, prueba sin carga, revision de extintores | reparaciones, obras, instalaciones, trabajos con terceros, pintura, desatoros, cualquier hallazgo, anything with a duration `(1H)` |
| `seguridad` | inicio/fin del servicio, aperturas y cierres, pilonas, alumbrado, rondas sin hallazgos, entrada y salida de personal | incidentes, quejas, llamadas de atencion, desperfectos y averias, accesos imprevistos, obras de terceros |

Real example -- a security shift of nine entries becomes three:

```
Anotaciones del servicio
  Se recibe queja de posible pinchazo en las impulsoras, se indica olor
  Se observa que faltan dos mesas en terraza
  Se llama la atencion a una persona en patinete
Generado ... 3 anotacion(es); 0 marcadas. Se omitieron 6 anotacion(es)
rutinaria(s) (aperturas, cierres, pilonas, rondas).
```

The filter **classifies rather than deletes**: the entry count stays aligned
with stage 1, the literal text is kept in the data, and the footer says how many
were omitted, so nothing disappears silently. Two safeguards:

- An entry the OCR passes were unsure about is **never** omitted -- "routine" is
  only a safe call on text we actually read.
- A check that found something is notable even though it starts like a routine
  one: `Revisando cuadros electricos` is routine, `Revisando cuadros
  electricos, se detecta magnetotermico saltado` is not. What decides is
  whether anything happened, not how the sentence begins. Anything the filter
  cannot classify confidently is notable by default.

Set `OMIT_ROUTINE=false` to print every entry instead.

Stage 2 is fenced in: it may only rewrite entries one for one. If it returns a
different number of entries the literal transcription is kept instead, and the
uncertainty flags from stage 1 always survive. Disable with
`ENABLE_FILTER_STAGE=false`; keep names with `REDACT_NAMES=false`.

## Prompt evaluation (promptfoo)

Both prompts have regression suites asserting against ground truth read off
real scans by eye. See [`promptfoo/README.md`](promptfoo/README.md).

```bash
npm install
npm run eval:all
```

## Keeping keys and company documents out of the repository

Install the commit guard once per clone:

```sh
git config core.hooksPath .githooks
```

It refuses to commit an environment file (`.env`, and any backup an editor
leaves beside it), a scan or document (`.docx`, `.pdf`, `.jpg`, ...), a log,
or any staged line that looks like a live credential. `.env.example` is
allowed. `.gitignore` alone proved insufficient: each leak arrived under a
name the ignore list did not yet know.

Real scans, the memoria template and the `.env` file live on disk and are
never committed. `deploy/README.md` says how to supply them.
