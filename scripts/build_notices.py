"""Collect installed upstream notices and an exact source revision for binaries."""

import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def notice_file(path):
    parts = path.as_posix().lower().split('/')
    return (any(p.endswith('.dist-info') for p in parts)
            and ("licenses" in parts or parts[-1].startswith(("license", "copying", "notice"))))


def collect(root, out, *, distributions=None):
    out.mkdir(parents=True, exist_ok=True)
    inventory = []
    for dist in distributions if distributions is not None else importlib.metadata.distributions():
        name = dist.metadata['Name']
        safe = re.sub(r'[^a-zA-Z0-9_.-]', '_', name)
        copied = []
        for file in dist.files or []:
            if not notice_file(file):
                continue
            source = Path(dist.locate_file(file))
            if not source.is_file():
                continue
            # Preserve paths below the metadata folder, including nested notices.
            parts = file.parts
            index = next(i for i, part in enumerate(parts) if part.endswith('.dist-info'))
            relative = Path(*parts[index + 1:])
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Unsafe license path')
            target = out / safe / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied.append(target.relative_to(out).as_posix())
        inventory.append({'name': name, 'version': dist.version, 'notices': copied})
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.exists():
        shutil.copyfile(python_license, out / 'Python-LICENSE.txt')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root))
    manifest = {'commit': revision, 'dirty': dirty, 'channel': 'beta-candidate',
                'python': sys.version.split()[0],
                'dependencies': sorted(inventory, key=lambda row: row['name'].lower())}
    (out.parent / 'build-info.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    collect(root, root / 'build' / 'dependency-licenses')
