"""Measures the system against a memoria the author wrote by hand.

The only honest measure of this pipeline is a month where both exist: the
paper sheets, and the document the author produced from them. Every entry in
his version is correct by definition, so anything the system missed is a
miss, anything extra is noise, and the pairs that match can be compared word
by word.

    ./venv/bin/python tools/accuracy.py \\
        --truth "/path/MEMORIA 2026 MAYO.docx" \\
        --entries state/memoria_entries.sqlite3 --year 2026 --month MAYO

Nothing is written and no API is called: it reads a document and a database.
"""

import argparse
import difflib
import os
import sqlite3
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memoria import MANTENIMIENTO_BLOCKS, SEGURIDAD_BLOCK, block_contents

# Two entries describing the same event, allowing for a misread word or two.
SAME_ENTRY = 0.65


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in folded if not unicodedata.combining(c))


def similarity(left: str, right: str) -> float:
    return difflib.SequenceMatcher(None, _fold(left), _fold(right)).ratio()


def pair_up(truth: list[str], produced: list[str]):
    """Match each hand-written entry to its closest produced one, once each."""
    unclaimed = list(range(len(produced)))
    pairs, missed = [], []
    for entry in truth:
        best, score = None, 0.0
        for index in unclaimed:
            ratio = similarity(entry, produced[index])
            if ratio > score:
                best, score = index, ratio
        if best is not None and score >= SAME_ENTRY:
            unclaimed.remove(best)
            pairs.append((entry, produced[best], score))
        else:
            missed.append(entry)
    return pairs, missed, [produced[i] for i in unclaimed]


def read_entries(db_path: str, year: str, month: str) -> list[str]:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = connection.execute(
        "SELECT text FROM memoria_entries WHERE year = ? AND month = ? "
        "ORDER BY block, position", (year, month),
    ).fetchall()
    return [row[0] for row in rows]


def report(truth: list[str], produced: list[str], label: str) -> None:
    pairs, missed, extra = pair_up(truth, produced)
    exact = sum(1 for _, _, s in pairs if s >= 0.995)
    close = sum(1 for _, _, s in pairs if 0.85 <= s < 0.995)
    rough = len(pairs) - exact - close
    words = sum(s for _, _, s in pairs) / len(pairs) if pairs else 0.0

    print(f"\n=== {label} ===")
    print(f"  the author wrote      {len(truth)}")
    print(f"  the system produced   {len(produced)}")
    print(f"  recovered             {len(pairs)}"
          f"  ({100 * len(pairs) / len(truth):.0f}% of his entries)" if truth else "")
    print(f"     word-for-word      {exact}")
    print(f"     close (>=0.85)     {close}")
    print(f"     rough              {rough}")
    print(f"  missed entirely       {len(missed)}")
    print(f"  produced but not his  {len(extra)}")
    print(f"  mean similarity on the pairs: {words:.2f}")

    if missed:
        print("\n  MISSED (his entry, nothing like it produced):")
        for entry in missed[:10]:
            print(f"    - {entry[:92]}")
    if extra:
        print("\n  EXTRA (produced, nothing like it in his memoria):")
        for entry in extra[:10]:
            print(f"    + {entry[:92]}")
    worst = sorted(pairs, key=lambda p: p[2])[:8]
    if worst:
        print("\n  WORST MATCHES (recovered, but read badly):")
        for his, ours, score in worst:
            print(f"    {score:.2f}")
            print(f"      his: {his[:88]}")
            print(f"      our: {ours[:88]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth", required=True, help="the hand-written memoria")
    parser.add_argument("--entries", required=True, help="memoria_entries.sqlite3")
    parser.add_argument("--year", required=True)
    parser.add_argument("--month", required=True)
    args = parser.parse_args()

    blocks = block_contents(args.truth)
    produced = read_entries(args.entries, args.year, args.month)
    produced = [p for p in produced if not p.startswith("Revisar la hoja")]

    truth_seguridad = blocks.get(SEGURIDAD_BLOCK) or []
    truth_mantenimiento = [e for b in MANTENIMIENTO_BLOCKS for e in (blocks.get(b) or [])]

    report(truth_seguridad + truth_mantenimiento, produced, f"{args.month} {args.year}")
    print("\n  Note: the author omits routine entries, and so does the system,")
    print("  so 'missed' counts only entries he judged worth keeping.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
