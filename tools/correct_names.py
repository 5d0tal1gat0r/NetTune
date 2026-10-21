"""Rewrites the shop names of lines already stored for a month.

New batches have their names settled against the template directory as they
are read (locales.correct_names). Lines stored before a misreading was known
-- September's "Salida clientes Posier" for the Poker -- still carry it; this
applies the same correction to them.

A line a person has edited by hand is left alone: they wrote it that way.

    ./venv/bin/python tools/correct_names.py 2026 SEPTIEMBRE --dry-run
    ./venv/bin/python tools/correct_names.py 2026 SEPTIEMBRE
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from entry_store import EntryStore
from locales import correct_names


def plan(store: EntryStore, year: str, month: str, template: str) -> list[tuple[dict, str]]:
    """(entry, corrected text) for each stored line whose names would change."""
    changes = []
    for entry in store.month_entries(year, month):
        if entry.get("hand_edited"):
            continue
        corrected = correct_names(entry.get("text", ""), template)
        if corrected != entry.get("text", ""):
            changes.append((entry, corrected))
    return changes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("year")
    parser.add_argument("month")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with EntryStore(config.entry_db) as store:
        changes = plan(store, args.year, args.month, config.template_path)
        done = 0
        for entry, corrected in changes:
            if args.dry_run or store.rewrite_entry(entry["id"], corrected):
                done += 1
                print(f"{'would change' if args.dry_run else 'changed'}: "
                      f"{entry['text']} -> {corrected}")
    print(f"{done} line(s) {'to correct' if args.dry_run else 'corrected'}.")


if __name__ == "__main__":
    main()
