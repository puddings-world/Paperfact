"""Run the complete local checks, including desktop action stress tests."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

# Credential shapes that must never reach the public repo, whoever is committing.
SECRET_PATTERNS = {
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "Anthropic key": r"sk-ant-[A-Za-z0-9_-]{20,}",
    "OpenAI key": r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}",
    "GitHub token": r"\b(?:gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40,})",
    "Google API key": r"\bAIza[0-9A-Za-z_-]{35}",
    "Google OAuth secret": r"\bGOCSPX-[A-Za-z0-9_-]{20,}",
    "Google access token": r"\bya29\.[A-Za-z0-9_-]{20,}",
    "Slack token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    "AWS access key": r"\bAKIA[0-9A-Z]{16}\b",
}


def committable_files(root):
    """Every file a commit could pick up: tracked, plus new files not ignored."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
    )
    if listed.returncode:
        return None
    names = {n for n in listed.stdout.decode("utf-8").split("\0") if n}
    return sorted(root / n for n in names if (root / n).is_file())


def private_terms(root):
    """A maintainer's own identifiers (an address, a username), listed in the ignored
    .env so that the check guarding them does not publish them itself."""
    sys.path.insert(0, str(root / "src"))
    from paper_daily.runtime import read_env_file

    raw = os.environ.get("PAPERFACT_PRIVATE_TERMS") or read_env_file(root / ".env").get(
        "PAPERFACT_PRIVATE_TERMS", ""
    )
    return [t.strip() for t in raw.split(",") if t.strip()]


def scan_privacy(root, files, terms):
    """Findings as `path:line: kind`, never echoing the matched text, so the report
    itself is safe to paste anywhere."""
    rules = [(name, re.compile(rx)) for name, rx in SECRET_PATTERNS.items()]
    rules += [
        (f"private term #{i}", re.compile(re.escape(t), re.IGNORECASE))
        for i, t in enumerate(terms, 1)
    ]
    found = []
    for path in files:
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        text = data.decode("utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            found += [
                f"{path.relative_to(root).as_posix()}:{number}: {name}"
                for name, rule in rules
                if rule.search(line)
            ]
    return found


def run_checks(root, execute=subprocess.run, files=None):
    node = shutil.which("node")
    if not node:
        print("Node.js is required for the frontend tests; no checks were skipped.")
        return 1
    print("Checking: Privacy scan", flush=True)
    files = committable_files(root) if files is None else files
    if files is None:
        print("FAILED: Privacy scan (not a git checkout; cannot tell what would be committed)")
        return 1
    findings = scan_privacy(root, files, private_terms(root))
    if findings:
        print("\n".join(findings))
        print(f"FAILED: Privacy scan ({len(findings)} finding(s); remove them before committing)")
        return 1
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PAPERFACT_PLAIN_VIEWS": "1"}
    # pytest creates --basetemp but not its parent; a fresh clone has no build/.
    (root / "build").mkdir(exist_ok=True)
    checks = [
        ("Ruff", [sys.executable, "-m", "ruff", "check", "."]),
        (
            "Python and desktop stress tests",
            [
                sys.executable,
                "-X",
                "faulthandler",
                "-m",
                "pytest",
                "tests",
                "-q",
                "--tb=short",
                "-p",
                "no:cacheprovider",
                "--basetemp",
                str(root / "build" / ("check-" + uuid4().hex[:8])),
            ],
        ),
        (
            "Frontend tests",
            [node, "--test", *map(str, sorted((root / "tests").glob("test_*.mjs")))],
        ),
    ]
    for name, command in checks:
        print(f"Checking: {name}", flush=True)
        result = execute(command, cwd=root, env=env)
        if result.returncode:
            print(f"FAILED: {name} (exit {result.returncode})", flush=True)
            return result.returncode
    print("All checks passed.", flush=True)
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        import ctypes

        # Child tests report native failures to the terminal instead of opening
        # a blocking Windows crash dialog on the user's desktop.
        ctypes.windll.kernel32.SetErrorMode(0x8003)
    raise SystemExit(run_checks(Path(__file__).resolve().parents[1]))
