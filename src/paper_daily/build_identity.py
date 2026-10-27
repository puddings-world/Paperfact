"""Small, allowlisted build identity shared by the footer and diagnostic exports."""

import json
import os
import re
import sys
import sysconfig
from pathlib import Path

from paper_daily import __version__, runtime


def _commit(value):
    return (
        value.lower()
        if isinstance(value, str) and re.fullmatch(r"[a-fA-F0-9]{40,64}", value)
        else None
    )


def identity(*, root=None, frozen=None):
    root = Path(root) if root is not None else runtime.bundle_root()
    frozen = runtime.FROZEN if frozen is None else frozen
    commit, dirty = None, None
    development_line = None
    try:
        if frozen:
            path = root / "build-info.json"
            if path.stat().st_size <= 128 * 1024:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    commit = _commit(data.get("commit"))
                    dirty = data.get("dirty") if type(data.get("dirty")) is bool else None
        else:
            git = root / ".git"
            if git.is_file():
                pointer = git.read_text(encoding="utf-8").strip()
                if pointer.startswith("gitdir: "):
                    git = (root / pointer[8:]).resolve()
            head = (git / "HEAD").read_text(encoding="utf-8").strip()
            commit = _commit(head)
            if head.startswith("ref: ") and re.fullmatch(r"refs/[\w./-]+", head[5:]):
                ref = head[5:]
                track = re.match(
                    r"refs/heads/(?:feature|candidate|hotfix)/(\d+\.\d+(?:\.\d+)?)(?:[-/]|$)",
                    ref,
                )
                development_line = track[1] if track else None
                if ".." not in ref.split("/"):
                    common = git
                    if (git / "commondir").is_file():
                        common = (git / (git / "commondir").read_text().strip()).resolve()
                    loose = common / ref
                    if loose.is_file():
                        commit = _commit(loose.read_text().strip())
                    elif (common / "packed-refs").is_file():
                        for line in (common / "packed-refs").read_text().splitlines():
                            parts = line.split(" ")
                            if len(parts) == 2 and parts[1] == ref:
                                commit = _commit(parts[0])
    except (OSError, ValueError, UnicodeError):
        pass
    # platform.machine() can invoke a shell on a cold Windows process. The
    # always-visible footer must not launch commands just to identify the build.
    if sys.platform == "win32":
        machine = sysconfig.get_platform().removeprefix("win-").lower()
        machine = "x86" if machine == "win32" else machine
    else:
        machine = os.uname().machine.lower() if hasattr(os, "uname") else "other"
    return {
        "version": __version__,
        "install": "release" if frozen else "source",
        "commit": commit,
        "dirty": dirty,
        "development_line": development_line,
        "os": {"win32": "Windows", "darwin": "macOS", "linux": "Linux"}.get(sys.platform, "other"),
        "architecture": machine
        if machine in {"amd64", "x86_64", "arm64", "aarch64", "x86", "i686"}
        else "other",
    }


def label(info):
    revision = f" · {info['commit'][:7]}" if info.get("commit") else ""
    if info["install"] == "source":
        track = info.get("development_line")
        return (f"{track} 開發中" if track else "開發版") + revision
    return f"v{info['version']} · 安裝版{revision}"


def describe(info):
    state = (
        "含未提交修改"
        if info.get("dirty")
        else ("乾淨建置" if info.get("dirty") is False else "未確認；開發目錄可能另有修改")
    )
    marker = (
        f"程式內版本標記：v{info['version']}（不代表已發布版本）\n"
        if info["install"] == "source" else ""
    )
    return (
        f"Paperfact {label(info)}\n{marker}"
        f"Commit: {info.get('commit') or 'unknown'}\n"
        f"Build: {state}\n{info['os']} / {info['architecture']}"
    )
