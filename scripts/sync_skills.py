"""Synchronize reviewed repo skills; refuse to overwrite local destination edits."""

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path

TARGETS = (".agents/skills", ".claude/skills")
MANIFEST = ".paperfact-skills.json"


def digest(content):
    # Git may check Markdown out with CRLF on Windows.
    return hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()


def checked(root, relative):
    path = root / relative
    current = path
    while current != root:
        if current.is_symlink() or (
            current.exists()
            and getattr(current.lstat(), "st_file_attributes", 0)
            & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError(f"Linked skill path is not supported: {relative}")
        current = current.parent
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"Skill path escapes repository: {relative}")
    return path


def source_files(root):
    base = checked(root, "skills")
    result = {}
    for folder in sorted(base.iterdir()):
        checked(root, folder.relative_to(root))
        if not folder.is_dir() or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", folder.name):
            raise ValueError(f"Invalid skill directory: {folder.name}")
        skill = checked(root, folder.relative_to(root) / "SKILL.md")
        content = skill.read_text(encoding="utf-8")
        if not content.startswith(f"---\nname: {folder.name}\ndescription: "):
            raise ValueError(f"Missing portable skill metadata: {folder.name}")
        if "\n---\n" not in content[4:]:
            raise ValueError(f"Unclosed skill metadata: {folder.name}")
        for file in sorted(folder.rglob("*")):
            checked(root, file.relative_to(root))
            if file.is_dir():
                continue
            if file.suffix != ".md":
                raise ValueError(f"Only reviewed Markdown is synchronized: {file.name}")
            result[file.relative_to(base).as_posix()] = file.read_bytes()
    if not result:
        raise ValueError("No source skills found")
    return result


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".skill-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sync(root, *, write=False):
    root = Path(root).resolve()
    sources = source_files(root)
    expected = {name: digest(content) for name, content in sources.items()}
    manifest_data = (json.dumps(expected, indent=2, sort_keys=True) + "\n").encode()
    changes = []
    for target in TARGETS:
        manifest = checked(root, Path(target) / MANIFEST)
        previous = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
        if not isinstance(previous, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in previous.items()
        ):
            raise ValueError(f"Invalid synchronization manifest: {target}")
        # Renames/removals require explicit review; never silently delete installed skills.
        if previous.keys() - expected.keys():
            raise ValueError(f"Removed source files need manual reconciliation: {target}")
        for name, content in sources.items():
            dest = checked(root, Path(target) / name)
            actual = digest(dest.read_bytes()) if dest.exists() else None
            if actual == expected[name]:
                continue
            if actual is not None and actual != previous.get(name):
                raise ValueError(f"Local skill edit conflicts with source: {target}/{name}")
            changes.append((dest, content))
        if previous != expected or not manifest.exists():
            changes.append((manifest, manifest_data))
    # All destinations are checked before writing anything. Each file replacement
    # is atomic; interruption between files is recoverable by running sync again.
    if write:
        for path, content in changes:
            atomic_write(path, content)
    return [path.relative_to(root).as_posix() for path, _ in changes]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="apply updates (default: check only)")
    args = parser.parse_args(argv)
    try:
        changed = sync(Path(__file__).resolve().parents[1], write=args.write)
    except (OSError, ValueError) as exc:
        print(f"Skills not synchronized: {exc}")
        return 2
    for name in changed:
        print(("Updated: " if args.write else "Out of sync: ") + name)
    if not changed:
        print("Skills are synchronized.")
    return 0 if args.write or not changed else 1


if __name__ == "__main__":
    raise SystemExit(main())
