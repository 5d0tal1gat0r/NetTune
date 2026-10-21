"""Stretches of handwriting nobody can read, kept as one marked line.

A block of several lines the reader cannot make out comes back as a run of
fragments -- "[?] [?] zona [?]", "se [?] [?]" -- that say nothing and fill the
memoria with noise. Dropping them would hide that something was written
there. So the run becomes a single line, ILLEGIBLE_GROUP, that is always
flagged for a person to read against the paper and never counted as routine.
"""

import re

ILLEGIBLE_GROUP = "[?] (grupo de texto ilegible)"

# A fragment with at least this many [?] marks, making up at least this share
# of its words, carries no reading worth keeping.
MIN_MARKS = 2
MIN_SHARE = 0.5
# One line alone must be this bad to stand for a group by itself.
MIN_MARKS_ALONE = 4

_TOKEN = re.compile(r"\S+")
_MARK = "[?]"


def is_group_marker(text: str) -> bool:
    return "grupo de texto ilegible" in (text or "").lower()


def _marks(text: str) -> tuple[int, int]:
    tokens = _TOKEN.findall(text or "")
    return sum(_MARK in t for t in tokens), len(tokens)


def mostly_illegible(text: str) -> bool:
    """True for a fragment made mostly of [?] marks."""
    marks, words = _marks(text)
    return marks >= MIN_MARKS and marks / max(words, 1) >= MIN_SHARE


def collapse(entries: list[dict]) -> list[dict]:
    """Replace each run of illegible fragments with one ILLEGIBLE_GROUP line.

    A run is two or more consecutive mostly-illegible entries, or one with
    MIN_MARKS_ALONE marks or more. A lone line with a word or two unread is
    left as it is: the rest of it is a reading. Every group line, including
    one the model wrote itself, is flagged.
    """
    out: list[dict] = []
    run: list[dict] = []

    def close_run() -> None:
        if len(run) >= 2 or (run and _marks(run[0]["text"])[0] >= MIN_MARKS_ALONE):
            out.append({"text": ILLEGIBLE_GROUP, "confident": False, "variants": []})
        else:
            out.extend(run)
        run.clear()

    for entry in entries:
        text = entry.get("text", "")
        if is_group_marker(text):
            close_run()
            if not (out and out[-1]["text"] == ILLEGIBLE_GROUP):
                out.append({**entry, "text": ILLEGIBLE_GROUP, "confident": False})
        elif mostly_illegible(text):
            run.append(entry)
        else:
            close_run()
            out.append(entry)
    close_run()
    return out
