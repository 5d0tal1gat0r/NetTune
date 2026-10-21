# Prompt regression suites

Prompt wording has had large, measurable effects on this pipeline -- reframing
the OCR prompt took model refusals from 4-in-6 to 0-in-6, and adding a glossary
took date accuracy from 0/6 to 6/6. These suites turn "this wording feels
better" into a number.

```bash
npm run eval          # OCR prompt  (prompts/transcription.md)
npm run eval:filter   # stage 2     (prompts/report_filter.md)
npm run eval:all      # both
npm run view          # browse results in a browser
```

Both read the **live prompt files**, so edit `prompts/*.md`, re-run, and compare.

## What is asserted

Every expectation is **ground truth read off the page by eye**, not model
output. Zoom into `fixtures/*.jpg` and check any of them yourself.

| Fixture | Ground truth |
|---|---|
| `junio_22` | 22-6-2026, A. Ejemplo, 5 anotaciones |
| `julio_02` | 2-7-2026, A. Ejemplo, 4 anotaciones, "cargadores" (not "Carrefour") |
| `julio_04` | 4-7-2026, B. Ejemplo, 1 anotación: "Conectando mg de aire" |

## Current baseline

| Suite | Cases | Assertions |
|---|---|---|
| OCR | 1/3 | 20/22 |
| Filter (both types) | 11/11 | 51/51 |

The filter suite covers both document types. The `seguridad` cases use wording
taken from the three real March service reports, since no scanned security
sheet is available yet -- see the caveat below.

> **No real seguridad scan has been tested.** The security vocabulary in
> `prompts/transcription.md` was derived from the March reports, which are
> *output* of an earlier run, not images. Until a real security sheet is run
> through, its OCR accuracy is unverified. Drop one into `fixtures/` and add a
> test block to close that gap.

**The OCR failures are real and expected.** `julio_04` is the page every model
tested reads as "cobre" where the sheet says "aire", and whose date drifts
between 04-07-2026, 04-02-2026 and 04-07-2016 between runs. That assertion is
deliberately left failing: the day a prompt change fixes it, the suite says so.

Because the failures come from run-to-run variance rather than a fixed bug,
**run the suite two or three times before concluding a prompt change helped.**
A single green run is not evidence.

## Cost

About $0.01 per full OCR run (3 pages), well under a cent for the filter suite.
These calls are **not** counted against the pipeline's `MONTHLY_BUDGET_EUR`
cap -- that guard only covers the service itself.

## Supplying the fixtures

`fixtures/` is **not in git**: the pages are real scanned sheets carrying staff
names and company detail. Put them there yourself and the suite runs; without
them it fails to find the files, which is the intended signal rather than a
silent pass.

```bash
pdftoppm -jpeg -r 300 -f 2 -l 2 scan.pdf promptfoo/fixtures/julio_02
mv promptfoo/fixtures/julio_02-*.jpg promptfoo/fixtures/julio_02.jpg
```

The assertions name the pages they expect: `junio_22`, `julio_02`, `julio_04`.

## Adding a fixture

1. `pdftoppm -jpeg -r 300 -f <page> -l <page> scan.pdf fixtures/<name>`
2. Rename to `fixtures/<name>.jpg`
3. **Read the page yourself** and write assertions from what you see
4. Add a test block with `vars: {page: <name>}`
