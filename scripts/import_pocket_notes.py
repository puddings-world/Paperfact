"""Bring notes written on the shared page back into papers.db.

The shared page keeps its notes in the artifact's own store, which only a Claude
session can read. So the round trip is: ask Claude to pull them (`/paper-pull-notes`),
which writes the documents to a JSON file, then this script files each one against
its paper -- where the desktop reader shows it as a card that jumps to the passage,
and where the next deep dive can see it.

    python scripts/import_pocket_notes.py data/pocket/notes.json

Idempotent: a note already filed is skipped, so pulling the same export twice is
harmless.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from paper_daily import pocket  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="JSON array of note documents, or {id: data} map")
    args = ap.parse_args()

    raw = json.loads(Path(args.path).read_text(encoding="utf-8"))
    notes = list(raw.values()) if isinstance(raw, dict) else raw
    notes = [n.get("data", n) for n in notes]
    added, skipped = pocket.file_notes(notes)
    print(f"{added} note(s) filed, {skipped} already there")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
