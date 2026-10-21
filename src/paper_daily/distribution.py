"""Source distribution with an application identity, never personal credentials."""

from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

from paper_daily.google_slides import read_client

ROOT_FILES = {
    "README.md",
    "LICENSE",
    "LICENSE.md",
    "pyproject.toml",
    "uv.lock",
    ".gitignore",
    "CLAUDE.md",
}
ROOT_DIRS = {"src", "scripts", "docs", "assets", "reader", "tests"}


def package(root: Path, destination: Path, client: Path) -> int:
    cfg = read_client(client)
    listing = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    names = sorted(set(listing.stdout.decode("utf-8").split("\0")) - {""})
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            relative = Path(name)
            if name not in ROOT_FILES and relative.parts[0] not in ROOT_DIRS:
                continue
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or (name not in ROOT_FILES and any(part.startswith(".") for part in relative.parts))
                or name.endswith((".pyc", "google-client.json"))
            ):
                continue
            path = root / relative
            if not path.is_file() or path.is_symlink():
                continue
            archive.write(path, "Paperfact/" + name)
            count += 1
        archive.writestr(
            "Paperfact/src/paper_daily/google-client.json",
            json.dumps({"installed": cfg}, indent=2),
        )
    return count
