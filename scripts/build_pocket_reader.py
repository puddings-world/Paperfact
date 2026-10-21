"""Build the phone reader from the command line.

The work lives in `paper_daily.pocket`, because the queue screen's 帶出門 button
builds the same page from whatever is ticked there. With no ids, this rebuilds that
ticked selection.

    python scripts/build_pocket_reader.py ref:abc ref:def
    python scripts/build_pocket_reader.py          # whatever is ticked in the app
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from paper_daily import pocket  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paper_ids", nargs="*")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    ids = args.paper_ids or pocket.marked_ids()
    if not ids:
        raise SystemExit("nothing to build: pass paper ids, or tick some in the app")

    built = pocket.write(ids, Path(args.out) if args.out else None)
    print(
        f"wrote {built['out']} ({built['page_bytes'] // 1024} KB page, "
        f"{built['total_bytes'] / 1e6:.1f} MB of files)"
    )
    for d in built["papers"]:
        pdf = f"{d['pdf_bytes'] / 1e6:.1f} MB PDF" if d["pdf"] else "no PDF"
        print(
            f"  {d['title'][:46]:46s} {pdf:>11s}, {len(d['figures'])} figures, "
            f"{len(d['cites'])} references, "
            f"{'close reading' if d['close'] else 'no close reading'}, "
            f"{len(d['decks'])} deck(s), {len(d['desk_notes'])} desk notes"
        )
    for s in built["surveys"]:
        print(f"  survey of {s['name']}: {len(s['papers'])} of these papers")
    print(f"files map: {built['out'].parent / 'files.json'} ({len(built['files'])} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
