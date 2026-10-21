"""Build a colleague source zip; Google must also allow their accounts."""

import argparse
from pathlib import Path

from paper_daily.distribution import package
from paper_daily.google_slides import CLIENT_FILE

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--client", type=Path, default=CLIENT_FILE)
parser.add_argument("--output", type=Path, default=Path("dist/Paperfact-colleagues.zip"))
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
count = package(root, args.output, args.client)
print(f"Packaged {count} source files and the Desktop OAuth application identity: {args.output}")
print("No personal AI settings, login tokens, paper database, or PDFs are included.")
