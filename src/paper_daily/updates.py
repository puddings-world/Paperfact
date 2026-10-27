"""New versions, announced from GitHub Releases and installed in place.

A release's notes are the announcement: the reader shows their first lines in a
banner, so what changed reaches people without a separate notice board. Only tags
shaped vX.Y.Z count -- the same Releases page also carries data bundles, such as a
reading list, that are not versions of the app.

An installed build replaces itself: the Windows installer runs over the old one,
the macOS app bundle and the Linux AppImage are swapped by a small script once the
app has quit. A source checkout is updated with git, which the app leaves to its
owner.
"""

from __future__ import annotations

import hashlib
import os
import platform as system_platform
import re
import shlex
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from paper_daily import __version__, runtime
from paper_daily.store import get_kv, set_kv

REPO = "puddings-world/Paperfact"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"

LAST_CHECK = "update.last_check"
FOUND = "update.found"
SNOOZED = "update.snoozed"
CACHE_PREFIX = "update.cache."
CACHE_SECONDS = 15 * 60

# What each platform's build is called on a release (see .github/workflows/release.yml).
ASSET_SUFFIX = {
    "win32": "-windows-x64-setup.exe",
    "darwin": "-macos-arm64.dmg",
    "linux": "-linux-x86_64.AppImage",
}

VERSION_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True)
class Release:
    version: str
    title: str
    notes: str
    page: str
    assets: dict[str, str]
    prerelease: bool = False
    digests: dict[str, str] = field(default_factory=dict)


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = VERSION_TAG.match(text if text.startswith("v") else "v" + text)
    return tuple(int(part) for part in match.groups()) if match else None


def default_channel(current: str = __version__, env=os.environ) -> str:
    """0.x previews receive beta releases; stable builds default to stable only."""
    configured = env.get("PAPERFACT_UPDATE_CHANNEL", "").strip().lower()
    if configured in ("stable", "beta"):
        return configured
    version = parse_version(current)
    return "beta" if version and version[0] == 0 else "stable"


def newest(
    releases: list[dict], current: str, *, include_prerelease: bool = False
) -> Release | None:
    """The highest published version above `current`, if there is one."""
    have = parse_version(current) or (0, 0, 0)
    best: tuple[tuple[int, int, int], dict] | None = None
    for item in releases:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        if item.get("prerelease") and not include_prerelease:
            continue
        version = parse_version(item.get("tag_name") or "")
        if version is None or version <= have:
            continue
        if best is None or version > best[0]:
            best = (version, item)
    if best is None:
        return None
    item = best[1]
    return Release(
        version=".".join(map(str, best[0])),
        title=item.get("name") or item["tag_name"],
        notes=item.get("body") or "",
        page=item.get("html_url") or RELEASES_PAGE,
        assets={a["name"]: a["browser_download_url"] for a in item.get("assets") or []},
        prerelease=bool(item.get("prerelease")),
        digests={a["name"]: a.get("digest", "") for a in item.get("assets") or []},
    )


def asset_for(
    release: Release, platform: str = sys.platform, *, machine=None
) -> tuple[str, str] | None:
    """(file name, download url) of this platform's build on the release."""
    key = "linux" if platform.startswith("linux") else platform
    suffix = ASSET_SUFFIX.get(key)
    machine = (
        machine
        or (
            system_platform.machine()
            if platform == sys.platform
            else "arm64"
            if key == "darwin"
            else "x86_64"
        )
    ).lower()
    if key == "darwin" and machine in {"x86_64", "amd64"}:
        suffix = "-macos-x86_64.dmg"
    elif (
        key == "darwin"
        and machine not in {"arm64", "aarch64"}
        or key in {"win32", "linux"}
        and machine not in {"amd64", "x86_64"}
    ):
        return None
    if suffix is None:
        return None
    for name, url in release.assets.items():
        if name.endswith(suffix) and "/" not in name and "\\" not in name:
            return name, url
    return None


def headline(notes: str, limit: int = 140) -> str:
    """The first lines of the notes as one line of plain text, for the banner."""
    parts: list[str] = []
    # The draft's reminder to the person publishing it is not for readers.
    notes = re.sub(r"<!--.*?-->", "", notes, flags=re.DOTALL)
    for line in notes.splitlines():
        text = re.sub(r"^\s*(?:#+|[-*+]|\d+\.)\s*", "", line)
        text = re.sub(r"[*_`]", "", text).strip()
        if text:
            parts.append(text)
    joined = " · ".join(parts)
    return joined if len(joined) <= limit else joined[: limit - 1].rstrip(" ·") + "…"


def fetch_releases(timeout: float = 10.0) -> list[dict] | None:
    """The repository's releases, or None when GitHub could not be reached."""
    try:
        response = httpx.get(
            RELEASES_API,
            timeout=timeout,
            follow_redirects=True,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"Paperfact/{__version__}",
            },
        )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    return data if isinstance(data, list) else None


def check(
    conn,
    current: str = __version__,
    fetch: Callable[[], list[dict] | None] = fetch_releases,
    today: date | None = None,
    *,
    channel: str = "stable",
    force: bool = False,
    now: float | None = None,
) -> Release | None:
    """A newer release than this copy, using a 15-minute cache unless explicitly refreshed.

    A failed request is not remembered as a check, so being offline at launch only
    postpones it to the next background check or launch.
    """
    if channel not in ("stable", "beta"):
        raise ValueError("Unknown update channel")
    stamp = (
        now
        if now is not None
        else (
            datetime.combine(today, datetime.min.time(), tzinfo=UTC).timestamp()
            if today is not None
            else time.time()
        )
    )
    today = today or date.today()
    cache_key = f"{CACHE_PREFIX}{current}|{channel}"
    cached = get_kv(conn, cache_key) or {}
    cached = cached if isinstance(cached, dict) else {}
    checked = cached.get("checked_at")
    age = stamp - checked if type(checked) in {int, float} else float("inf")
    if force or not 0 <= age < CACHE_SECONDS:
        releases = fetch()
        if releases is not None:
            found = newest(releases, current, include_prerelease=channel == "beta")
            cached = {
                "checked": today.isoformat(),
                "checked_at": stamp,
                "found": asdict(found) if found else None,
            }
            set_kv(conn, cache_key, cached)
        elif force:
            raise OSError("Update service unavailable")
    stored = cached.get("found")
    if not stored:
        return None
    release = Release(**stored)
    # Found before this copy was itself updated: no longer news.
    if (parse_version(release.version) or (0, 0, 0)) <= (parse_version(current) or (0, 0, 0)):
        return None
    return release


def snooze(conn, release: Release, today: date | None = None) -> None:
    set_kv(conn, SNOOZED, f"{release.version}|{(today or date.today()).isoformat()}")


def snoozed(conn, release: Release, today: date | None = None) -> bool:
    """「稍後」 hides one version for the rest of the day."""
    return get_kv(conn, SNOOZED) == f"{release.version}|{(today or date.today()).isoformat()}"


# ---- installing ------------------------------------------------------------


def can_install(
    platform: str = sys.platform, env=os.environ, frozen: bool = runtime.FROZEN
) -> bool:
    """Whether this copy can replace itself: an installed build, and on Linux an AppImage."""
    if not frozen:
        return False
    if platform.startswith("linux"):
        return bool(env.get("APPIMAGE"))
    return platform in ("win32", "darwin")


def download(
    url: str,
    dest: Path,
    progress: Callable[[int, int], None] = lambda done, total: None,
) -> Path:
    """Stream `url` to `dest`; a partial file never takes the final name."""
    partial = dest.with_name(dest.name + ".part")
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or 0)
            done = 0
            with partial.open("wb") as out:
                for chunk in response.iter_bytes(1 << 16):
                    out.write(chunk)
                    done += len(chunk)
                    progress(done, total)
            if not done or (total and done != total):
                raise OSError("Incomplete update download")
        partial.replace(dest)
    finally:
        partial.unlink(missing_ok=True)
    return dest


def verify_download(path: Path, digest: str) -> None:
    """Missing metadata is not verified; never execute an unchecked installer."""
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        raise ValueError("此版本缺少 SHA-256 驗證資訊，請從發布頁下載。")
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != digest[7:].lower():
        raise ValueError("下載檔案驗證失敗，請重新下載。")


def app_bundle(executable: str = sys.executable) -> Path:
    """/Applications/Paperfact.app for …/Paperfact.app/Contents/MacOS/Paperfact."""
    return Path(executable).resolve().parents[2]


def mac_script(dmg: Path, app: Path, pid: int) -> str:
    """Swap the app bundle for the one on the disk image once this process has quit.

    The old bundle is kept until the copy has finished, so a failed copy leaves the
    previous version in place rather than no app at all.
    """
    q = shlex.quote
    old = q(str(app) + ".old")
    return f"""#!/bin/sh
while kill -0 {pid} 2>/dev/null; do sleep 0.3; done
mnt=$(mktemp -d)
test -n "$mnt" || exit 1
if ! hdiutil attach -nobrowse -readonly -mountpoint "$mnt" {q(str(dmg))}; then
  open {q(str(dmg))}; exit 1
fi
trap 'hdiutil detach "$mnt" -quiet; rmdir "$mnt" 2>/dev/null' EXIT
test -d "$mnt/{app.name}" || exit 1
# A previous recovery copy must never be overwritten.
test ! -e {old} || exit 1
# If the old bundle cannot be moved, leave it intact.
mv {q(str(app))} {old} || exit 1
if ditto "$mnt/{app.name}" {q(str(app))}; then
  rm -rf {old}
else
  rm -rf {q(str(app))}
  mv {old} {q(str(app))} || exit 1
fi
open {q(str(app))}
"""


def linux_script(new: Path, target: Path, pid: int) -> str:
    q = shlex.quote
    return f"""#!/bin/sh
while kill -0 {pid} 2>/dev/null; do sleep 0.3; done
chmod +x {q(str(new))} && mv -f {q(str(new))} {q(str(target))}
nohup {q(str(target))} >/dev/null 2>&1 &
"""


def windows_command(setup: Path) -> list[str]:
    # The installer closes what is left of this copy, installs over it and starts
    # the new one (its [Run] entry runs in silent mode too).
    return [str(setup), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]


def download_dir(platform: str = sys.platform, env=os.environ) -> Path:
    if platform.startswith("linux") and env.get("APPIMAGE"):
        # Beside the AppImage, so the final move is a rename on one filesystem.
        return Path(env["APPIMAGE"]).parent
    folder = Path(tempfile.gettempdir()) / "paperfact-update"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def launch_installer(downloaded: Path, platform: str = sys.platform, env=os.environ) -> list[str]:
    """Start whatever finishes the update after the app quits; returns the command run."""
    if platform == "win32":
        command = windows_command(downloaded)
        subprocess.Popen(command, close_fds=True)
        return command
    if platform == "darwin":
        script = mac_script(downloaded, app_bundle(), os.getpid())
    else:
        script = linux_script(downloaded, Path(env["APPIMAGE"]), os.getpid())
    path = downloaded.with_name("paperfact-update.sh")
    path.write_text(script, encoding="utf-8")
    command = ["/bin/sh", str(path)]
    subprocess.Popen(command, start_new_session=True, close_fds=True)
    return command
