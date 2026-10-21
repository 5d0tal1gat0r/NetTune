# OCR probe

Answers one question before any pipeline change is made: does a second,
non-generative OCR engine fail on the same handwritten words the OpenAI model
fails on?

Two passes of one vision-language model are not independent readings. When the
model cannot read a word it produces a plausible Spanish one, and both passes
produce the same plausible word, so they agree and the line is never flagged.
Measured on the real sheets: two entries were wrong in twelve of twelve
attempts across four models, and none was ever marked for review.

Cloud Vision is not a language model. An unreadable word comes back as broken
characters carrying a low confidence, never as a fluent sentence.

## What it measured, 29 real pages, 2026-09-17

Cloud Vision is **not** worth adding as a second transcriber, and is not wired
into the pipeline. Its handwriting output is far worse than the model's
("Decisando codia electieces" for "Revisando cuadros electricos"), and nothing
agreed exactly across all 29 pages. Its confidence separates handwriting from
print cleanly -- 200 handwritten lines scored a median 0.37, 41 printed lines
a median 0.94 -- but it does not separate a correctly read handwritten line
from a misread one, so it cannot say which entry is wrong.

What it did find: two pages of the 29 where the model returned nothing at all,
one a legible printed list of eleven pending works. That is now reported by
`blank_page_report` in main.py, which needs no OCR at all.

The probe stays as a diagnostic: run it when a page looks wrong and you want a
second opinion on what is actually printed on it.

## Credentials

The OpenAI key is already set. Only the Cloud Vision key is needed.

### Google Cloud Vision

1. Sign in at <https://console.cloud.google.com>. Country **Spain**.
2. Project dropdown, top bar, **New Project**, named `nettune`. Switch to it.
3. **Billing**, link a card. New accounts get $300 of credit for 90 days, and
   the first 1000 units a month are free for good. This site uses 150.
4. Search **Cloud Vision API**, then **Enable**.
5. **APIs & Services**, **Credentials**, **Create credentials**, **API key**.
6. **Edit API key**, **API restrictions**, **Restrict key**, tick **Cloud
   Vision API** only, save. An unrestricted Google key is a billing liability
   the moment it leaks.
7. **Billing**, **Budgets & alerts**: a EUR 5 budget alerting at 50, 90 and
   100 per cent, matching the cap the pipeline already enforces in code.

```
GOOGLE_VISION_API_KEY=<the key>
```

`DOCUMENT_TEXT_DETECTION` is the dense-document mode, the only one that scores
confidence by default. It reads Spanish handwriting, and the API key goes on
the query string, so the Raspberry Pi needs no credentials file and no SDK.

It returns paragraphs, not table rows, so entries the sheet keeps in separate
cells can arrive joined.

`.env` is gitignored. Paste keys into the file with an editor. Do not echo one
in a terminal: anything printed there lands in shell history and in any
transcript of the session.

## Running it

```sh
./venv/bin/python tools/ocr_probe.py ~/Downloads/SKM_C30826081908350.pdf \
                                     ~/Downloads/SKM_C30826081908351.pdf
```

`--limit N` stops after N pages while trying things out. Each page costs one
Vision reading against the monthly budget, which the probe checks before
calling, exactly as the pipeline does.

The run prints every line pair and writes `tools/probe_out/probe.json`. That
directory is gitignored: it holds real transcriptions of company documents.

## Reading the result

`gpt` is the OpenAI model the pipeline already uses; the other label names
the second engine.

* **AGREE** - both engines read the line identically. Trustworthy.
* **DIFFER** - same line, different words. Check these by hand; they are the
  lines a single model would have reported with false confidence.
* **GPT-ONLY** - the OpenAI model saw a line the other engine did not.
  Either an invention, or handwriting too faint for the engine.
* **ENGINE-ONLY** - a line the OpenAI model dropped. Usually a real entry lost.
* **engine unsure** - a word scored below 0.80. The engine is saying it could
  not read it, whatever the other engine thinks.

The probe changes nothing in the pipeline, reads no ledger and writes no
document, so it is safe to run against production scans.
