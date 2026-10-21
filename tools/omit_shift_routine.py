"""Removes shift-routine lines already stored for a month.

The rule for new batches is routine_rules._SHIFT_ROUTINE: switching the
evening and night lighting, starting and finishing the closing round, and
putting out or taking in the bollards. Lines stored before that rule existed
-- September's "Conector [?] alumbrado tarde", "Comienzo el cierre",
"Finalizo cierre", "Se colocan pelonas" -- are still in the memoria; this
takes them out.

It applies exactly that rule and nothing wider, so a line the broader
routine rules happen to match today is not swept up with it. A line that
reads as an incident is never matched, and a line a person has edited by
hand is left alone: they kept it on purpose.

    ./venv/bin/python tools/omit_shift_routine.py 2026 SEPTIEMBRE --dry-run
    ./venv/bin/python tools/omit_shift_routine.py 2026 SEPTIEMBRE
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nettune.config import config
from nettune.report.entry_store import EntryStore
from nettune.report.memoria import SEGURIDAD_BLOCK
from nettune.report.routine_rules import is_shift_routine


def plan(store: EntryStore, year: str, month: str) -> list[dict]:
    """The stored lines the shift-routine rule would have kept out.

    Security lines only: a maintenance sheet omits nothing.
    """
    return [
        entry for entry in store.month_entries(year, month)
        if entry.get("block") == SEGURIDAD_BLOCK
        and not entry.get("hand_edited") and is_shift_routine(entry.get("text", ""))
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("year")
    parser.add_argument("month")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with EntryStore(config.entry_db) as store:
        lines = plan(store, args.year, args.month)
        for entry in lines:
            if not args.dry_run:
                store.remove_entry(entry["id"])
            print(f"{'would remove' if args.dry_run else 'removed'}: {entry['text']}")
    print(f"{len(lines)} routine line(s) {'to remove' if args.dry_run else 'removed'}.")


if __name__ == "__main__":
    main()
