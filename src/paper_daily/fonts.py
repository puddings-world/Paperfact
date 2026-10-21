"""The typefaces the app ships with.

Windows and macOS have different CJK and monospace system fonts, and they differ in
width: the same note, slide text box or table wraps at different places on each, so
a deck laid out on one machine overflows on the other. Shipping one sans and one
mono makes both platforms measure text the same way. Noto Sans TC is also the face
the slide export names, so the canvas shows what the exported deck will look like.

The files are too large for git (12 MB), so `fonts` downloads them, pinned to a
google/fonts commit and checked by sha256.
"""

from __future__ import annotations

import hashlib

from paper_daily.config import ROOT
from paper_daily.http import fetch

FONT_DIR = ROOT / "fonts"

FONTS = (
    {
        "family": "Noto Sans TC",
        "file": "NotoSansTC[wght].ttf",
        "url": "https://raw.githubusercontent.com/google/fonts/"
        "3be1884c48c3e45b52ecc725676a08f87776373e/ofl/notosanstc/NotoSansTC%5Bwght%5D.ttf",
        "sha256": "864727d210d54f2537bbe23b3a839436c3992af72de9322af5270897246bd44f",
    },
    {
        "family": "JetBrains Mono",
        "file": "JetBrainsMono[wght].ttf",
        "url": "https://raw.githubusercontent.com/google/fonts/"
        "6e4b84c976cadb3c49a40fd9a1c203e4f7fcf2da/ofl/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf",
        "sha256": "48715a42ec242c21e9f02692891e147d022299a52e48d5e413e1a942193ffeda",
    },
)


def _sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def missing() -> list[dict]:
    return [f for f in FONTS if not (FONT_DIR / f["file"]).exists()]


def install(log=lambda _m: None) -> list[str]:
    """Download the fonts not yet here. Returns the families installed."""
    done = []
    for spec in missing():
        blob = fetch(spec["url"], cache=False, retries=4)
        if _sha256(blob) != spec["sha256"]:
            raise ValueError(f"{spec['file']}: download does not match the pinned sha256")
        FONT_DIR.mkdir(exist_ok=True)
        (FONT_DIR / spec["file"]).write_bytes(blob)
        done.append(spec["family"])
        log(f"  {spec['family']}: {len(blob) / 1e6:.1f} MB")
    return done
