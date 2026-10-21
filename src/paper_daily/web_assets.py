"""The scripts the reading views render with: KaTeX for formulas, highlight.js for
code and pseudocode, Mermaid for diagrams.

Qt's own rich text cannot typeset a formula or draw a diagram, so the explanation
and the answers are shown in a web view. These files are loaded from disk, not a
CDN: the reader works offline and a page never phones out. They are too large for
git (5 MB), so `web-assets` downloads them, pinned to a version and checked by
sha256, into the gitignored `vendor/web`.
"""

from __future__ import annotations

import hashlib
import io
import tarfile

from paper_daily.config import ROOT
from paper_daily.http import fetch

WEB_DIR = ROOT / "vendor" / "web"
_JSDELIVR = "https://cdn.jsdelivr.net/npm/"

ASSETS = (
    {
        "name": "KaTeX 0.16.11",
        # The npm tarball, because KaTeX's CSS needs its font folder beside it.
        "url": "https://registry.npmjs.org/katex/-/katex-0.16.11.tgz",
        "sha256": "8c5494c5f7d8e8bf73ff3fe64d4bd09a340e4878b7eec9bbd9ef8d8f3e24193f",
        "unpack": "package/dist/",
        "into": "katex",
        "check": "katex/katex.min.js",
    },
    {
        "name": "Mermaid 10.9.1",
        "url": _JSDELIVR + "mermaid@10.9.1/dist/mermaid.min.js",
        "sha256": "61b335a46df05a7ce1c98378f60e5f3e77a7fb608a1056997e8a649304a936d6",
        "check": "mermaid.min.js",
    },
    {
        "name": "highlight.js 11.10.0",
        "url": _JSDELIVR + "@highlightjs/cdn-assets@11.10.0/highlight.min.js",
        "sha256": "471ef9ae90c407af440fcdc48edfeeb562106b3267bd12d99071c162fb52ed32",
        "check": "highlight.min.js",
    },
    {
        "name": "highlight.js light theme",
        "url": _JSDELIVR + "@highlightjs/cdn-assets@11.10.0/styles/github.min.css",
        "sha256": "3a9a5def8b9c311e5ae43abde85c63133185eed4f0d9f67fea4b00a8308cf066",
        "check": "hljs-light.css",
    },
    {
        "name": "highlight.js dark theme",
        "url": _JSDELIVR + "@highlightjs/cdn-assets@11.10.0/styles/github-dark.min.css",
        "sha256": "9f208d022102b1d0c7aebfecd8e42ca7997d5de636649d2b31ea63093d809019",
        "check": "hljs-dark.css",
    },
)


def missing() -> list[dict]:
    return [a for a in ASSETS if not (WEB_DIR / a["check"]).exists()]


def _unpack(blob: bytes, prefix: str, into: str) -> None:
    target = (WEB_DIR / into).resolve()
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile() or not member.name.startswith(prefix):
                continue
            dest = (target / member.name[len(prefix) :]).resolve()
            # A pinned hash already vouches for the archive; this keeps a bad entry
            # name from writing outside the folder all the same.
            if not dest.is_relative_to(target):
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(archive.extractfile(member).read())


def install(log=lambda _m: None) -> list[str]:
    """Download what is not yet here. Returns the names installed."""
    done = []
    for spec in missing():
        blob = fetch(spec["url"], cache=False, retries=4)
        if hashlib.sha256(blob).hexdigest() != spec["sha256"]:
            raise ValueError(f"{spec['name']}: download does not match the pinned sha256")
        WEB_DIR.mkdir(parents=True, exist_ok=True)
        if "unpack" in spec:
            _unpack(blob, spec["unpack"], spec["into"])
        else:
            (WEB_DIR / spec["check"]).write_bytes(blob)
        done.append(spec["name"])
        log(f"  {spec['name']}: {len(blob) / 1e6:.1f} MB")
    return done
