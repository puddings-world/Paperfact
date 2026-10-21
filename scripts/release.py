"""Cut a release: set the version, commit, tag, and (with --push) send it to GitHub.

    python scripts/release.py 0.2.0          # bump, commit, tag locally
    python scripts/release.py 0.2.0 --push   # ...and push, which starts the build

The pushed tag starts .github/workflows/release.yml, which builds the three
installers and leaves a draft release to write the notes on. See docs/releasing.md.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "src" / "paper_daily" / "__init__.py"
VERSION_LINE = re.compile(r'^__version__ = "([^"]+)"', re.MULTILINE)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def parse(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise SystemExit(f"{version!r} is not X.Y.Z")
    return tuple(int(p) for p in match.groups())


def set_version(text: str, version: str) -> str:
    if not VERSION_LINE.search(text):
        raise SystemExit(f"no __version__ line in {INIT}")
    return VERSION_LINE.sub(f'__version__ = "{version}"', text, count=1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="the new version, X.Y.Z")
    parser.add_argument("--push", action="store_true", help="push the commit and the tag")
    args = parser.parse_args()

    raw = INIT.read_bytes().decode()
    current = VERSION_LINE.search(raw).group(1)
    if parse(args.version) <= parse(current):
        raise SystemExit(f"{args.version} is not above the current {current}")
    if git("status", "--porcelain"):
        raise SystemExit("the working tree has uncommitted changes; commit or set them aside first")
    tag = f"v{args.version}"
    if git("tag", "--list", tag):
        raise SystemExit(f"{tag} already exists")

    INIT.write_bytes(set_version(raw, args.version).encode())
    git("add", str(INIT))
    git("commit", "-m", f"Release {tag}")
    git("tag", "-a", tag, "-m", f"Paperfact {args.version}")
    print(f"tagged {tag}")
    if args.push:
        branch = git("rev-parse", "--abbrev-ref", "HEAD")
        git("push", "origin", branch)
        git("push", "origin", tag)
        print("pushed; the build runs at https://github.com/puddings-world/Paperfact/actions")
    else:
        print(f"push when ready: git push origin HEAD {tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
