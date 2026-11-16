"""Exercise a frozen app using generated research and isolated account/data homes."""

import argparse
import hashlib
import json
import os
import plistlib
import re
import sqlite3
import stat
import subprocess
import sys
import sysconfig
import time
import traceback
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


LEGACY_BASELINE = "3abdf434555583ca4a6827892d54b487e9e40671"
LEGACY_VERSION = "0.4.3"

FORMAT = "paperfact.packaged-acceptance.v1"
STAGES = {
    "legacy-source-preflight", "legacy-source-seed", "legacy-upgrade-snapshot",
    "legacy-source-export", "legacy-upgrade-export", "legacy-upgrade-preservation",
    "legacy-upgrade-compatibility", "legacy-upgrade-init",
    "isolation",
    "version",
    "doctor",
    "first-use",
    "first-use-privacy",
    "seed",
    "share-link",
    "share-link-checksum",
    "import",
    "import-again",
    "fixture-ack",
    "reader",
    "instance-handoff",
    "export",
    "file-fidelity",
    "research-content",
    "lineage-audit",
    "lineage-audit-result",
    "credential-isolation",
    "local-integration",
    "sync-protocol",
    "source-aware-report",
    "appimage-integration",
    "mac-foreground",
    "mac-dmg-preflight", "mac-dmg-mount", "mac-dmg-copy",
    "mac-dmg-verify", "mac-dmg-detach",
    "windows-installer-preflight",
    "windows-install",
    "windows-installed-version",
    "windows-installed-reader",
    "windows-installed-integration",
    "windows-reinstall",
    "windows-uninstall",
}


class OutputExists(FileExistsError):
    """Only the run destination already exists; preserve its earlier report."""


class CheckFailure(RuntimeError):
    def __init__(self, label, code, returncode=None):
        super().__init__(f"{label} failed ({returncode}); inspect the captured local log")
        self.code, self.returncode = code, returncode


def failure_category(error):
    if isinstance(error, CheckFailure):
        return dict(code=error.code, returncode=error.returncode)
    for kind, code in (
        (KeyboardInterrupt, "interrupted"),
        (subprocess.TimeoutExpired, "timeout"),
        (FileNotFoundError, "missing_file"),
        (PermissionError, "permission_denied"),
        (AssertionError, "assertion_failed"),
        (ValueError, "validation_failed"),
        (OSError, "os_error"),
        (RuntimeError, "check_failed"),
    ):
        if isinstance(error, kind):
            return dict(code=code, returncode=None)
    return dict(code="unexpected_error", returncode=None)


def packaged_identity(built):
    # Read only fixed packaged metadata, never the mutable checkout's commit/version.
    result = dict(commit=None, dirty=None, version=None)
    for relative in (
        "_internal/build-info.json",
        "build-info.json",
        "Contents/Resources/build-info.json",
        "Contents/Frameworks/build-info.json",
    ):
        try:
            with (built / relative).open("rb") as stream:
                raw = stream.read(128 * 1024 + 1)
            if len(raw) > 128 * 1024:
                continue
            info = json.loads(raw)
            if not isinstance(info, dict):
                continue
            commit = info.get("commit")
            result["commit"] = (
                commit.lower()
                if isinstance(commit, str) and re.fullmatch(r"[a-fA-F0-9]{40,64}", commit)
                else None
            )
            result["dirty"] = info.get("dirty") if type(info.get("dirty")) is bool else None
            return result
        except (OSError, ValueError, UnicodeError):
            continue
    return result


def host_architecture():
    # Match the app footer: platform.machine can launch cmd on cold Windows.
    if sys.platform == "win32":
        machine = sysconfig.get_platform().removeprefix("win-").lower()
        return "x86" if machine == "win32" else machine
    return os.uname().machine.lower() if hasattr(os, "uname") else "other"


class Acceptance:
    """Durable categorical progress; raw subprocess output stays in local logs."""

    def __init__(self, built, out):
        self.out = out
        machine = host_architecture()
        self.report = dict(
            format=FORMAT,
            passed=False,
            status="running",
            active_check=None,
            completed_checks=[],
            failure=None,
            build=packaged_identity(built),
            host=dict(
                os={"win32": "Windows", "darwin": "macOS", "linux": "Linux"}.get(
                    sys.platform, "other"
                ),
                architecture=machine
                if machine in {"amd64", "x86_64", "arm64", "aarch64", "x86", "i686"}
                else "other",
            ),
        )
        self.write()

    def write(self):
        temporary = self.out / "report.pending.json"
        temporary.write_text(json.dumps(self.report, indent=2), encoding="utf-8")
        temporary.replace(self.out / "report.json")

    def call(self, label, function):
        if label not in STAGES:
            raise ValueError("Unknown acceptance stage")
        self.report["active_check"] = label
        self.write()
        value = function()
        self.report["completed_checks"].append(label)
        self.report["active_check"] = None
        self.write()
        return value

    def failed(self, error):
        self.report.update(
            passed=False,
            status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
            failure=failure_category(error),
        )
        self.write()

    def finish(self, result):
        self.report.update(
            result, format=FORMAT, status="passed", passed=True, active_check=None, failure=None
        )
        self.write()
        return self.report


def isolated_env(folder):
    home = folder / 'home'
    home.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if k.upper() in {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'COMSPEC',
                            'DISPLAY', 'XAUTHORITY', 'QTWEBENGINE_CHROMIUM_FLAGS'}}
    env.update(HOME=str(home), USERPROFILE=str(home),
               APPDATA=str(home / 'roaming'), LOCALAPPDATA=str(home / 'local'),
               XDG_CONFIG_HOME=str(home / '.config'),
               PAPERFACT_DATA=str(folder / 'workspace'), PAPERFACT_SMOKE_SECONDS='5',
               QT_QPA_PLATFORM=("cocoa" if sys.platform == "darwin" else
                                os.environ.get('QT_QPA_PLATFORM', 'offscreen')),
               PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
               HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9')
    system = Path(os.environ.get('SYSTEMROOT', '/usr'))
    env['PATH'] = os.pathsep.join(map(str, [Path(sys.executable).parent, system / 'System32',
                                          system] if os.name == 'nt' else ['/usr/bin', '/bin']))
    return env


def _safe_stamp(path):
    """Reject links/reparse points before executing anything that can remove files."""
    path = Path(path).absolute()
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Installer acceptance refuses linked paths")
    info = path.stat()
    if not info.st_ino:
        raise ValueError("Installer acceptance requires stable filesystem identities")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _file_hash(path, limit):
    before = _safe_stamp(path)
    if not path.is_file() or before[2] > limit:
        raise ValueError("Installer acceptance file exceeds its budget")
    digest = hashlib.sha256()
    used = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                used += len(chunk)
                if used > limit:
                    raise ValueError("Installer acceptance file grew beyond its budget")
                digest.update(chunk)
    except OSError as error:
        # Only the separate private traceback includes this diagnostic path.
        error.add_note("Acceptance file read: " + str(path)[:2048])
        raise
    if before != _safe_stamp(path):
        raise ValueError("Installer acceptance file changed while checking")
    return digest.hexdigest()


def _data_hash(root):
    """Exact bounded fixture content; no traversal of a linked directory."""
    identity = _safe_stamp(root)[:2]
    pending, entries, used = [root], [], 0
    while pending:
        for path in pending.pop().iterdir():
            if len(entries) >= 4096:
                raise ValueError("Installer fixture exceeds its file budget")
            token = _safe_stamp(path)
            if path.is_dir():
                pending.append(path)
                entries.append((path.relative_to(root).as_posix(), None))
            elif path.is_file():
                used += token[2]
                if used > 64 * 1024**2:
                    raise ValueError("Installer fixture exceeds its byte budget")
                entries.append((path.relative_to(root).as_posix(), _file_hash(path, 64 * 1024**2)))
            else:
                raise ValueError("Installer fixture contains a special file")
    if identity != _safe_stamp(root)[:2]:
        raise ValueError("Installer fixture directory changed")
    return hashlib.sha256(json.dumps(sorted(entries)).encode("utf-8")).hexdigest()


def _legacy_source_check(source):
    """Validate the pinned closure before reading or executing any source content."""
    source = Path(source).absolute()
    _safe_stamp(source)
    tree = subprocess.run(
        ['git', 'ls-tree', '-rz', LEGACY_BASELINE, '--', 'src', 'scripts/demo_workspace.py'],
        cwd=ROOT, capture_output=True, timeout=15, check=True,
    ).stdout
    expected, directories = {}, set()
    for entry in tree.split(bytes([0])):
        if not entry:
            continue
        meta, name = entry.split(bytes([9]), 1)
        mode, kind, digest = meta.split()
        relative = Path(name.decode('utf-8'))
        if (mode not in {b'100644', b'100755'} or kind != b'blob'
                or relative.is_absolute() or '..' in relative.parts):
            raise ValueError('Unsupported legacy source entry')
        expected[relative.as_posix()] = digest.decode('ascii')
        directories.update(p.as_posix() for p in relative.parents if p != Path('.'))
    pending, found = [source], set()
    while pending:
        for path in pending.pop().iterdir():
            _safe_stamp(path)
            relative = path.relative_to(source).as_posix()
            if path.is_dir() and relative in directories:
                pending.append(path)
            elif path.is_file() and relative in expected:
                found.add(relative)
            else:
                raise ValueError('Legacy source closure differs from the pinned commit')
    if not expected or found != set(expected):
        raise ValueError('Legacy source closure differs from the pinned commit')
    for relative, digest in expected.items():
        path = source / relative
        if _safe_stamp(path)[2] > 4 * 1024**2:
            raise ValueError('Legacy source file exceeds its byte budget')
        raw = path.read_bytes()
        actual = hashlib.sha1(b'blob ' + str(len(raw)).encode() + bytes([0]) + raw,
                              usedforsecurity=False).hexdigest()
        if actual != digest:
            raise ValueError('Legacy source differs from the pinned commit')
    return _data_hash(source)


def _legacy_snapshot(root, prior=None):
    """Retain old research columns and exact PDF/deck files, not just row counts."""
    from contextlib import closing

    database = root / 'papers.db'
    _safe_stamp(database)
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        tables = {}
        for table in ('papers', 'lists', 'list_papers', 'notes', 'dives', 'chat', 'pdf_highlights'):
            columns = (prior['tables'][table][0] if prior else
                       [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')])
            if not columns or any(not re.fullmatch('[a-z_][a-z0-9_]*', c) for c in columns):
                raise ValueError('Legacy research schema is unavailable')
            selected = ','.join('"' + c + '"' for c in columns)
            rows = conn.execute(
                f'SELECT {selected} FROM "{table}" ORDER BY {selected}').fetchmany(101)
            if len(rows) > 100:
                raise ValueError('Legacy fixture exceeds its row budget')
            tables[table] = columns, rows
    files = {}
    for name in ('pdf', 'presentations'):
        folder = root / name
        _data_hash(folder)
        for path in folder.rglob('*'):
            if path.is_file():
                files[path.relative_to(root).as_posix()] = _file_hash(path, 16 * 1024**2)
    if not files or not tables['notes'][1] or not tables['pdf_highlights'][1]:
        raise ValueError('Legacy fixture did not include required research')
    return dict(tables=tables, files=files)


def _legacy_upgrade(command, source, out, run, check=lambda _label, action: action()):
    """Old source creates data; the new CLI upgrades it without a source override."""
    source = Path(source).absolute()
    stamp = check('legacy-source-preflight', lambda: _legacy_source_check(source))
    folder = out / 'legacy-upgrade'
    folder.mkdir(exist_ok=False)
    env = isolated_env(folder)
    old_env = {**env, 'PYTHONPATH': str(source / 'src')}
    seed = r"""
import json, sys
from pathlib import Path
source = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(source / 'scripts'))
import paper_daily
assert paper_daily.__version__ == '0.4.3'
assert Path(paper_daily.__file__).resolve().parents[2] == source
import demo_workspace as demo
from paper_daily import pdf_highlights, presentations, store
demo.seed()
quote = demo.PDF_TEXT[0]
anchor = dict(p0=0, o0=0, p1=0, o1=len(quote))
now = store.now()
with store.connect() as conn:
    conn.execute('UPDATE lists SET name=?,note=? WHERE id=?',
                 ('Renamed upgrade list', 'Retained research purpose', demo.LIST_ID))
    conn.execute('UPDATE list_papers SET state=?,read_at=? WHERE list_id=?',
                 ('read', now, demo.LIST_ID))
    body = 'Saved note caf' + chr(233) + ' ' + chr(30740) + chr(31350)
    conn.execute('INSERT INTO notes(paper_id,body,created_at,kind,page,anchor) VALUES(?,?,?,?,?,?)',
                 (demo.PAPER_ID, body, now, 'note', 1, json.dumps(anchor, sort_keys=True)))
    for role in ('user', 'assistant'):
        conn.execute('INSERT INTO chat(paper_id,role,body,created_at,page,anchor) '
                     'VALUES(?,?,?,?,?,?)',
                     (demo.PAPER_ID, role, 'Retained synthetic ' + role, now, 1,
                      json.dumps(anchor, sort_keys=True)))
from paper_daily.config import PDF_DIR
pdf_highlights.add(demo.PAPER_ID, pdf_highlights.document_hash(PDF_DIR / 'demo_paperfact.pdf'),
                   anchor, quote)
slide = presentations.Slide('Edited slide', 'Background', 'Retain the argument',
    ['Retained bullet'], 'Retained speaker notes', ['note:1'], elements=[dict(
        kind='text', x=120.0, y=100.0, w=900.0, h=320.0,
        text='Hand edited canvas', size=31.0, bold=True)])
deck = presentations.Deck(demo.PAPER_ID, demo.PDF_TEXT[0], 'Edited deck', 'notes',
    'Researchers', 10, [slide], [dict(id='note:1', label='Saved note', kind='notes',
    text='Retained source text')], [], ['notes', 'dive'], now, edited=True)
presentations.save_deck(deck)
print('Seeded pinned 0.4.3 synthetic research; no provider calls.')
"""
    run('legacy-source-seed', [sys.executable, '-B', '-c', seed, source], old_env)
    run('legacy-source-export', [sys.executable, '-B', '-m', 'paper_daily', 'list-export',
                                 'demo', '--out', folder / 'baseline.zip'], old_env)
    workspace = Path(env['PAPERFACT_DATA'])
    before = check('legacy-upgrade-snapshot', lambda: _legacy_snapshot(workspace))
    run('legacy-upgrade-compatibility', [*command, 'list-export', 'demo', '--out',
                                        folder / 'compatible.zip'], env)
    run('legacy-upgrade-init', [*command, 'init'], env)
    run('legacy-upgrade-export', [*command, 'list-export', 'demo', '--out',
                                 folder / 'returned.zip'], env)

    def preserved():
        if _legacy_snapshot(workspace, before) != before or _data_hash(source) != stamp:
            raise ValueError('Legacy research or source changed during upgrade')
        from contextlib import closing

        with closing(sqlite3.connect((workspace / 'papers.db').resolve().as_uri()
                                     + '?mode=ro', uri=True)) as conn:
            for table in ('list_reading_goals', 'paper_annotation_known'):
                row = conn.execute('SELECT type FROM sqlite_master WHERE name=?',
                                   (table,)).fetchone()
                if row is None or row[0] != 'table':
                    raise ValueError('Candidate schema initialization did not complete')
        for returned in ('compatible.zip', 'returned.zip'):
            files = compare_files(folder / 'baseline.zip', folder / returned)
            with zipfile.ZipFile(folder / 'baseline.zip') as old, zipfile.ZipFile(
                    folder / returned) as new:
                previous, current = [json.loads(z.read('manifest.json')) for z in (old, new)]
                if any(previous[key] != current[key] for key in ('list', 'members')):
                    raise ValueError('Exported legacy list or order changed during upgrade')
                old_tables, new_tables = [json.loads(z.read('tables.json')) for z in (old, new)]
                for name, rows in old_tables.items():
                    received = new_tables.get(name, [])
                    if len(rows) != len(received) or any(
                            any(key not in other or other[key] != value
                                for key, value in row.items())
                            for row, other in zip(rows, received, strict=True)):
                        raise ValueError('Exported legacy research changed during upgrade')
        return dict(baseline_version=LEGACY_VERSION, baseline_commit=LEGACY_BASELINE,
                    source_format_only=True, research_preserved=True, schema_initialized=True,
                    tables={name: len(value[1]) for name, value in before['tables'].items()},
                    files=files, editable_deck_preserved=True, exported_research_preserved=True,
                    older_binary_install_checked=False, gui_upgrade_checked=False)

    return check('legacy-upgrade-preservation', preserved)


def _installer_input(built, out, installer):
    """Only this repository's fresh CI build, never a maintainer's daily install."""
    from paper_daily import __version__

    root = ROOT.resolve()
    info = packaged_identity(built)
    if (sys.platform != "win32" or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REPOSITORY", "").casefold() != "puddings-world/paperfact"
            or Path(os.environ.get("GITHUB_WORKSPACE", "")).resolve() != root
            or info["dirty"] is not False or not info["commit"]
            or info["commit"] != os.environ.get("GITHUB_SHA")):
        raise ValueError("Installer acceptance requires a matching clean Windows CI build")
    installer = Path(installer).absolute()
    if (built != root / "dist/Paperfact" or out.parent != root / "build"
            or installer != root / "dist" / f"Paperfact-{__version__}-windows-x64-setup.exe"):
        raise ValueError("Installer acceptance requires the expected CI artifact paths")
    identity = _safe_stamp(out)[:2]
    token = _safe_stamp(installer)
    if not token[2]:
        raise ValueError("Installer acceptance requires a nonempty executable")
    digest = _file_hash(installer, 512 * 1024**2)
    installed = out / "installed-app"
    installed.mkdir(exist_ok=False)
    return dict(installer=installer, token=token, sha256=digest, installed=installed,
                install_identity=_safe_stamp(installed)[:2], output_identity=identity,
                source_identity=info, version=__version__)


def _mac_bundle_hash(root):
    """Bounded content/permission/link closure; bundle links must remain internal."""
    root = Path(root).absolute()
    identity = _safe_stamp(root)
    pending, entries, tokens, total = [root], [], {}, 0
    while pending:
        directory = pending.pop()
        tokens[directory] = _safe_stamp(directory)
        for path in directory.iterdir():
            if len(entries) >= 20000:
                raise ValueError("Mac bundle exceeds its file budget")
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                target = os.readlink(path)
                if not path.resolve(strict=True).is_relative_to(root):
                    raise ValueError("Mac bundle link escapes its app")
                entries.append((relative, "link", target))
            elif path.is_dir():
                pending.append(path)
                entries.append((relative, "directory", None))
            elif path.is_file():
                token = _safe_stamp(path)
                total += token[2]
                if total > 2 * 1024**3:
                    raise ValueError("Mac bundle exceeds its byte budget")
                tokens[path] = token
                entries.append((relative, path.stat().st_mode & 0o111,
                                _file_hash(path, 2 * 1024**3)))
            else:
                raise ValueError("Mac bundle contains a special file")
    if identity != _safe_stamp(root) or any(_safe_stamp(p) != t for p, t in tokens.items()):
        raise ValueError("Mac bundle changed while checking")
    return hashlib.sha256(json.dumps(sorted(entries)).encode("utf-8")).hexdigest()


def _mac_dmg_input(built, out, image):
    """Only the exact generated repository CI image and fresh owned output."""
    from paper_daily import __version__

    root = ROOT.resolve()
    info = packaged_identity(built)
    image = Path(image).absolute()
    if (sys.platform != "darwin" or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REPOSITORY", "").casefold() != "puddings-world/paperfact"
            or Path(os.environ.get("GITHUB_WORKSPACE", "")).resolve() != root
            or info["dirty"] is not False or not info["commit"]
            or info["commit"] != os.environ.get("GITHUB_SHA")):
        raise ValueError("DMG acceptance requires a matching clean Mac CI build")
    if (built != root / "dist/Paperfact.app" or out.parent != root / "build"
            or image != root / "dist" / f"Paperfact-{__version__}-macos-arm64.dmg"):
        raise ValueError("DMG acceptance requires the expected CI artifact paths")
    token = _safe_stamp(image)
    if not token[2]:
        raise ValueError("DMG acceptance requires a nonempty image")
    return dict(image=image, token=token, sha256=_file_hash(image, 1024**3),
                bundle_sha256=_mac_bundle_hash(built), source_identity=info,
                output_identity=_safe_stamp(out)[:2], mount=out / "mac-volume",
                copied=out / "mac-installed" / "Paperfact.app")


def _mac_dmg_copy(plan, out, env, run, acceptance):
    mount, copied, image = plan["mount"], plan["copied"], plan["image"]
    if mount != out / "mac-volume" or copied != out / "mac-installed/Paperfact.app":
        raise ValueError("DMG acceptance paths changed")

    def owned(*, source=True):
        if (_safe_stamp(out)[:2] != plan["output_identity"]
                or source and _safe_stamp(image) != plan["token"]):
            raise ValueError("DMG acceptance ownership changed")

    owned()
    mount.mkdir(exist_ok=False)
    copied.parent.mkdir(exist_ok=False)
    copy_parent = _safe_stamp(copied.parent)[:2]
    mount_identity = None

    def mounted(raw):
        nonlocal mount_identity
        if len(raw) > 1024**2:
            raise ValueError("DMG mount reply exceeds its bound")
        value = plistlib.loads(raw)
        if (not isinstance(value, dict) or not isinstance(value.get("system-entities"), list)
                or any(not isinstance(row, dict) for row in value["system-entities"])):
            raise ValueError("Invalid DMG mount reply")
        points = [row["mount-point"] for row in value.get("system-entities", [])
                  if "mount-point" in row]
        if points != [str(mount)] or not mount.is_mount():
            raise ValueError("DMG did not mount only at the owned destination")
        mount_identity = _safe_stamp(mount)[:2]
        _safe_stamp(mount / "Paperfact.app")

    def copy_owned():
        owned()
        if (_safe_stamp(copied.parent)[:2] != copy_parent or copied.exists()
                or _safe_stamp(mount)[:2] != mount_identity):
            raise ValueError("DMG copy destination or mounted volume changed")

    def checked():
        owned()
        if (packaged_identity(copied) != plan["source_identity"]
                or _mac_bundle_hash(copied) != plan["bundle_sha256"]
                or _file_hash(image, 1024**3) != plan["sha256"]):
            raise ValueError("Copied DMG contents differ from the verified build")

    def detach_owned():
        owned(source=False)
        if mount_identity is not None and _safe_stamp(mount)[:2] != mount_identity:
            raise ValueError("DMG mounted volume changed before detach")

    def detached(_raw):
        if mount.is_mount():
            raise ValueError("DMG remains mounted")

    failure = None
    try:
        run("mac-dmg-mount", ["/usr/bin/hdiutil", "attach", "-readonly", "-nobrowse",
                              "-mountpoint", mount, "-plist", image], env,
            before=owned, after=mounted)
        run("mac-dmg-copy", ["/usr/bin/ditto", mount / "Paperfact.app", copied], env,
            before=copy_owned)
        acceptance.call("mac-dmg-verify", checked)
    except BaseException as error:
        failure = error
        raise
    finally:
        if mount.is_mount():
            active = acceptance.report["active_check"]
            try:
                run("mac-dmg-detach", ["/usr/bin/hdiutil", "detach", mount], env,
                    before=detach_owned, after=detached)
            except BaseException as error:
                if failure is None:
                    raise
                acceptance.report["cleanup_failure"] = dict(
                    stage="mac-dmg-detach", **failure_category(error),
                )
            finally:
                if failure is not None:
                    acceptance.report["active_check"] = active
                    acceptance.write()
    return copied, dict(image_sha256=plan["sha256"], bundle_sha256=plan["bundle_sha256"],
                        copied=True, detached=True)


def _wait_for_idle(data, *, seconds=30, now=time.monotonic, pause=time.sleep):
    """Drain known fixture producers; unknown files/errors must still fail."""
    from paper_daily.enrollment_history import ActiveResearchWork, idle_lock_files

    deadline = now() + seconds
    while True:
        try:
            return idle_lock_files(data / "papers.db")
        except ActiveResearchWork as error:
            remaining = deadline - now()
            if remaining <= 0:
                raise ValueError(
                    "Fixture research work did not finish within its budget"
                ) from error
            pause(min(.25, remaining))


def _windows_install(plan, out, recipient, empty, run, acceptance, integration_check):
    installed, installer = plan["installed"], plan["installer"]
    data = Path(recipient["PAPERFACT_DATA"])
    if acceptance.report["build"]["version"] != plan["version"]:
        raise ValueError("Frozen version differs from the CI source version")
    if data != out / "recipient/workspace" or Path(recipient["HOME"]) != out / "recipient/home":
        raise ValueError("Installer data must be the exact generated recipient")

    def owned(*, may_be_removed=False):
        if _safe_stamp(out)[:2] != plan["output_identity"]:
            raise ValueError("Installer output directory changed")
        if (not may_be_removed or installed.exists()) and (
            _safe_stamp(installed)[:2] != plan["install_identity"]
        ):
            raise ValueError("Installer destination directory changed")
        if _safe_stamp(installer) != plan["token"]:
            raise ValueError("Installer bytes changed since preflight")

    def mutate(label, command, *, uninstall=False):
        snapshot = []

        def ready():
            owned()
            _wait_for_idle(data)
            owned()  # Recheck the destination after waiting, before native mutation.
            if uninstall:
                _safe_stamp(command[0])
            snapshot.append(_data_hash(data))

        def retained(stdout):
            owned(may_be_removed=uninstall)
            if snapshot[0] != _data_hash(data):
                raise ValueError("Installer changed the research fixture")
            if uninstall and any(
                (installed / name).exists() for name in ("Paperfact.exe", "paperfact-cli.exe")
            ):
                raise ValueError("Uninstall left executable payloads behind")
            if not uninstall and packaged_identity(installed) != plan["source_identity"]:
                raise ValueError("Installed source identity differs from the frozen bundle")

        run(label, [*command, "/LOG=" + str(out / (label + "-inno.log"))],
            recipient, before=ready, after=retained)

    flags = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
    setup = [installer, *flags, "/SP-", "/LANG=en", "/NOCLOSEAPPLICATIONS",
             "/NORESTARTAPPLICATIONS", "/ACCEPTANCETEST=1", "/DIR=" + str(installed)]
    mutate("windows-install", setup)
    def version_matches(stdout):
        if stdout.strip() != ("paperfact " + plan["version"]).encode("ascii"):
            raise ValueError("Installed executable reports a different version")

    run("windows-installed-version", [installed / "paperfact-cli.exe", "--version"],
        recipient, after=version_matches)
    run("windows-installed-reader", [installed / "Paperfact.exe", "--paper", "demo:paperfact"],
        recipient)
    integration = acceptance.call(
        "windows-installed-integration",
        lambda: integration_check([installed / "paperfact-cli.exe"],
                                  out / "installed-integration", empty),
    )
    mutate("windows-reinstall", setup)
    uninstaller = installed / "unins000.exe"
    mutate("windows-uninstall", [uninstaller, *flags], uninstall=True)
    return dict(installed=True, reinstalled=True, uninstalled=True, research_preserved=True,
                installer_sha256=plan["sha256"], integration=integration,
                acceptance_mode=True, older_release_upgrade_checked=False,
                registry_shortcuts_checked=False)


def compare_files(first, second):
    with zipfile.ZipFile(first) as a, zipfile.ZipFile(second) as b:
        files = {name: a.read(name) for name in a.namelist() if name.startswith('files/')}
        other = {name: b.read(name) for name in b.namelist() if name.startswith('files/')}
        if not files or files != other:
            raise ValueError('Research files changed during frozen-app round trip')
        return len(files)


def check_process(result, label):
    if result.returncode or b"Traceback (most recent call last):" in result.stdout + result.stderr:
        raise CheckFailure(
            label,
            "process_failed" if result.returncode else "background_traceback",
            result.returncode,
        )



def _instance_probe():
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtNetwork import QLocalSocket

    from paper_daily.workspace_open import instance_key

    app = QCoreApplication.instance() or QCoreApplication([])

    def ready(root):
        app.processEvents()
        socket = QLocalSocket()
        socket.connectToServer(instance_key(root))
        connected = socket.waitForConnected(100)
        socket.abort()
        return connected

    return ready


def _instance_handoff(command, env, out):
    """Two real launches in one synthetic workspace; reap only the owned child."""
    label = "instance-handoff"
    ready = _instance_probe()
    log = out / "instance-primary.log"
    with log.open("wb") as stream:
        primary = subprocess.Popen(
            list(map(str, command)), cwd=ROOT,
            env={**env, "PAPERFACT_SMOKE_SECONDS": "20"},
            stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 30
            while not ready(Path(env["PAPERFACT_DATA"])):
                if primary.poll() is not None:
                    raise CheckFailure(label, "instance_not_ready", primary.returncode)
                if time.monotonic() >= deadline:
                    raise CheckFailure(label, "instance_not_ready")
                time.sleep(0.1)
            try:
                secondary = subprocess.run(
                    list(map(str, command)), cwd=ROOT,
                    env={**env, "PAPERFACT_SMOKE_SECONDS": "60"},
                    stdin=subprocess.DEVNULL, capture_output=True, timeout=15,
                )
            except subprocess.TimeoutExpired as error:
                (out / "instance-secondary.log").write_bytes(
                    (error.stdout or b"") + (error.stderr or b""),
                )
                raise
            (out / "instance-secondary.log").write_bytes(secondary.stdout + secondary.stderr)
            check_process(secondary, label)
            if primary.poll() is not None:
                raise CheckFailure(label, "primary_closed_during_handoff", primary.returncode)
            code = primary.wait(timeout=35)
        finally:
            if primary.poll() is None:
                primary.terminate()
                try:
                    primary.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    primary.kill()
                    primary.wait(timeout=5)
    if log.stat().st_size > 4 * 1024**2:
        raise CheckFailure(label, "output_too_large")
    check_process(subprocess.CompletedProcess(command, code, log.read_bytes(), b""), label)
    return dict(primary_ready=True, second_launch_handoff=True, primary_normal_exit=True)

def _verify(built, out, acceptance, *, installer=None, legacy_source=None, dmg=None):
    installation = acceptance.call(
        "windows-installer-preflight", lambda: _installer_input(built, out, installer),
    ) if installer is not None else None
    image = acceptance.call(
        "mac-dmg-preflight", lambda: _mac_dmg_input(built, out, dmg),
    ) if dmg is not None else None

    def run(label, command, env, *, before=None, after=None):
        def execute():
            if before is not None:
                before()
            try:
                result = subprocess.run(
                    list(map(str, command)), cwd=ROOT, env=env, capture_output=True, timeout=90
                )
            except subprocess.TimeoutExpired as error:
                (out / (label + ".log")).write_bytes((error.stdout or b"") + (error.stderr or b""))
                raise
            (out / (label + ".log")).write_bytes(result.stdout + result.stderr)
            check_process(result, label)
            if label == "version" and len(result.stdout) <= 96:
                text = result.stdout.decode("ascii", errors="replace").strip()
                match = re.fullmatch(
                    r"paperfact (\d+\.\d+\.\d+(?:(?:\.dev|[ab]|rc)\d*|-(?:alpha|beta|rc)\d*)?)",
                    text,
                )
                if match:
                    acceptance.report["build"]["version"] = match[1]
            log = Path(env["PAPERFACT_DATA"]) / "app.log"
            if log.exists() and "Traceback" in log.read_text(encoding="utf-8", errors="replace"):
                raise CheckFailure(label, "app_traceback")
            if after is not None:
                after(result.stdout)
            return result.stdout

        return acceptance.call(label, execute)

    def require(condition):
        if not condition:
            raise AssertionError("Packaged acceptance condition failed")

    empty, recipient, sender = acceptance.call(
        "isolation",
        lambda: tuple(isolated_env(out / name) for name in ("empty", "recipient", "sender")),
    )
    image_result = None
    if image is not None:
        built, image_result = _mac_dmg_copy(image, out, empty, run, acceptance)
    folder = built / "Contents/MacOS" if sys.platform == "darwin" else built
    ext = ".exe" if os.name == "nt" else ""
    cli, gui = folder / ("paperfact-cli" + ext), folder / ("Paperfact" + ext)
    run("version", [cli, "--version"], empty)
    run("doctor", [cli, "doctor"], empty)
    run("first-use", [gui], empty)
    acceptance.call(
        "first-use-privacy",
        lambda: require(not (Path(empty["PAPERFACT_DATA"]) / "llm.json").exists()),
    )
    original, returned = out / "original.zip", out / "returned.zip"
    seed = (
        "import sys; sys.path.insert(0, 'scripts'); import demo_workspace; "
        "from pathlib import Path; demo_workspace.acceptance_package(Path(sys.argv[1]))"
    )
    run("seed", [sys.executable, "-c", seed, original], sender)
    run(
        "share-link",
        [cli, "list-share-link", original, "https://files.example.org/research.zip"],
        sender,
    )

    def checksum():
        expected = "https://files.example.org/research.zip#paperfact-sha256=" + (
            hashlib.sha256(original.read_bytes()).hexdigest()
        )
        require(expected in (out / "share-link.log").read_text(encoding="utf-8"))

    acceptance.call("share-link-checksum", checksum)
    run("import", [cli, "list-import", original], recipient)
    run("import-again", [cli, "list-import", original], recipient)
    # This acknowledges only the generated test recipient's local fixture.
    run(
        "fixture-ack",
        [
            sys.executable,
            "-c",
            "from paper_daily import onboarding; onboarding.accept(analytics=False)",
        ],
        recipient,
    )
    # Two native Mac candidates crashed here while a later one passed. Require
    # three consecutive launches of the same bundle/workspace; never retry a failure.
    reader_launches = 3 if sys.platform == "darwin" else 1
    for _ in range(reader_launches):
        run("reader", [gui, "--paper", "demo:paperfact"], recipient)
    handoff = acceptance.call(
        "instance-handoff", lambda: _instance_handoff(
            [gui, "--paper", "demo:paperfact"], recipient, out,
        ),
    )
    run("export", [cli, "list-export", "demo", "-o", returned], recipient)
    files = acceptance.call("file-fidelity", lambda: compare_files(original, returned))
    workspace = Path(recipient["PAPERFACT_DATA"])

    def content():
        from contextlib import closing

        with closing(sqlite3.connect(workspace / "papers.db")) as db:
            require(db.execute("SELECT count(*) FROM list_papers").fetchone()[0] == 1)
            require(bool(db.execute("SELECT body FROM dives").fetchone()[0]))
            rows = db.execute("SELECT paper_id,corpus_key FROM paper_lineage_sets").fetchall()
            require(len(rows) == 1 and rows[0][0] == "demo:paperfact")
            return dict(paper_id=rows[0][0], corpus_key=rows[0][1])

    audit_args = acceptance.call("research-content", content)
    arguments = out / "lineage-input.json"
    arguments.write_text(json.dumps(audit_args), encoding="utf-8")
    audit_output = run(
        "lineage-audit",
        [cli, "integration", "analysis.audit", "--workspace", workspace, "--file", arguments],
        recipient,
    )

    def checked_lineage():
        require(len(audit_output) <= 2 * 1024**2)
        response = json.loads(audit_output.decode("utf-8"))
        require(response.get("ok") is True)
        report = response["result"]
        require(report["format"] == "paperfact.lineage-audit.v1")
        require(report["originals_checked"] == report["originals_total"] == 3)
        require(len(report["sources"]) == 3 and report["semantics"] == "not_checked")
        require(all(source["state"] == "available" for source in report["sources"]))
        checks = [check for source in report["sources"] for check in source["report"]["checks"]
                  if check["rule"] == "quote_location"]
        require(len(checks) == 5 and all(check["state"] == "located" for check in checks))

    acceptance.call("lineage-audit-result", checked_lineage)
    acceptance.call("credential-isolation", lambda: require(not (workspace / "llm.json").exists()))

    def integration_check(command, folder, env):
        from verify_local_integration import verify as verify_integration

        return verify_integration(command, folder, env)

    integration = acceptance.call(
        "local-integration", lambda: integration_check([cli], out / "integration-workspace", empty)
    )
    from verify_source_report import verify as verify_report

    source_report = acceptance.call(
        "source-aware-report", lambda: verify_report([cli], out / "source-report", empty, original),
    )
    from verify_sync_protocol import verify as verify_sync

    sync_protocol = acceptance.call(
        "sync-protocol", lambda: verify_sync([cli], out / "sync-protocol", empty),
    )
    legacy_upgrade = (_legacy_upgrade([cli], legacy_source, out, run, acceptance.call)
                      if legacy_source is not None else None)
    if sys.platform.startswith("linux"):
        from paper_daily import __version__

        appimage = ROOT / "dist" / f"Paperfact-{__version__}-linux-x86_64.AppImage"
        if appimage.exists():
            integration["appimage"] = acceptance.call(
                "appimage-integration",
                lambda: integration_check(
                    [appimage, "--cli"],
                    out / "appimage-workspace",
                    {**empty, "APPIMAGE_EXTRACT_AND_RUN": "1"},
                ),
            )
    if sys.platform == "darwin":
        # Launch Services foreground activation, separate from direct reader startup.
        run(
            "mac-foreground",
            ["/usr/bin/swift", ROOT / "scripts/verify_mac_app.swift", built],
            {**recipient, "QT_QPA_PLATFORM": "cocoa", "PAPERFACT_SMOKE_SECONDS": "45"},
        )
    result = {
        "passed": True,
        "research_files_preserved": files,
        "reader_launches_verified": reader_launches,
        "instance_handoff": handoff,
        "sync_protocol": sync_protocol,
        "source_report": source_report,
        "legacy_upgrade": legacy_upgrade,
        "integration": integration,
        "checks": [
            "version",
            "doctor",
            "first-use",
            "import",
            "duplicate-import",
            "reader",
            "same-workspace-instance-handoff",
            "export",
            "file-fidelity",
            "lineage-corpus",
            "share-link-checksum",
            "packaged-sync-execution-restart",
            "source-aware-report",
            "json-cli",
            "mcp-stdio",
            "mcp-retry",
        ],
        "limitations": (
            "Synthetic model completion only; no real provider login, paid call, Google Slides "
            "export, hosted multi-device sync, Safari or physical-phone acceptance."
        ),
    }
    if sys.platform == "darwin":
        result["checks"].append("mac-launch-services-foreground")
    if image_result is not None:
        result["mac_dmg"] = dict(
            **image_result, workflow_from_copy=True, quarantine_checked=False,
            notarization_checked=False, older_installed_upgrade_checked=False,
        )
        result["checks"].append("mac-dmg-copy-and-detach")
    if installation is not None:
        result["windows_installer"] = _windows_install(
            installation, out, recipient, empty, run, acceptance, integration_check,
        )
        result["checks"].append("windows-install-reinstall-uninstall")
        result["limitations"] += (
            " Isolated CI install and same-version reinstall only; no older-release upgrade "
            "or registry/shortcut audit."
        )
    return result


def verify(built, out, *, installer=None, legacy_source=None, dmg=None):
    # A reused output directory must never overwrite an earlier acceptance run.
    try:
        out.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise OutputExists("Choose a new acceptance output directory") from None
    acceptance = Acceptance(built, out)
    try:
        result = _verify(built, out, acceptance, installer=installer,
                         **({'legacy_source': legacy_source} if legacy_source is not None else {}),
                         **({'dmg': dmg} if dmg is not None else {}))
    except BaseException as error:
        acceptance.failed(error)
        # Private diagnostics stay separate from the categorical shareable report.
        try:
            detail = "".join(traceback.format_exception(error, limit=12))
            (out / "failure-detail.log").write_text(detail[:16384], encoding="utf-8")
        except (OSError, UnicodeError):
            pass  # Diagnostics must not hide the original failure.
        raise
    result = acceptance.finish(result)
    print(json.dumps(result))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("built", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--installer", type=Path,
                        help="Windows CI only: verify isolated install/reinstall/uninstall")
    parser.add_argument('--dmg', type=Path,
                        help='Mac CI only: run acceptance from a verified DMG copy after detaching')
    parser.add_argument('--legacy-source', type=Path,
                        help='Verify preservation from the pinned 0.4.3 source archive')
    args = parser.parse_args(argv)
    try:
        verify(args.built.resolve(), args.out.resolve(),
               installer=args.installer.absolute() if args.installer else None,
               **({'legacy_source': args.legacy_source.absolute()} if args.legacy_source else {}),
               **({'dmg': args.dmg.absolute()} if args.dmg else {}))
    except KeyboardInterrupt:
        print(
            "Acceptance interrupted; inspect the chosen output folder/report.json.", file=sys.stderr
        )
        return 130
    except OutputExists:
        print(
            "Choose a new output directory; an existing report belongs to an earlier run.",
            file=sys.stderr,
        )
        return 1
    except (Exception, SystemExit):
        print(
            "Acceptance failed; inspect the chosen output folder/report.json if available. "
            "Raw logs stay local and need review before sharing.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
