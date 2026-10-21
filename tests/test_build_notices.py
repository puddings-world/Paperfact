import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_notices', ROOT / 'scripts/build_notices.py')
notices = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notices)


def test_notices_include_nested_licenses_but_never_runtime_credentials(tmp_path, monkeypatch):
    files = [Path('example.dist-info/licenses/MIT.txt'), Path('example/token.json')]
    for file in files:
        target = tmp_path / file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('fixture', encoding='utf-8')
    dist = SimpleNamespace(metadata={'Name': 'example'}, version='1.2.3', files=files,
                           locate_file=lambda path: tmp_path / path)
    monkeypatch.setattr(notices.subprocess, 'check_output',
                        lambda args, **kw: 'abc123\n' if 'rev-parse' in args else b'')
    out = tmp_path / 'built' / 'dependency-licenses'
    manifest = notices.collect(tmp_path, out, distributions=[dist])
    assert (out / 'example/licenses/MIT.txt').read_text() == 'fixture'
    assert not list(out.rglob('token.json'))
    assert manifest['commit'] == 'abc123' and not manifest['dirty']
    assert manifest['dependencies'][0]['version'] == '1.2.3'
    assert json.loads((out.parent / 'build-info.json').read_text()) == manifest


def test_notice_path_cannot_escape_distribution(tmp_path):
    file = Path('example.dist-info/../NOTICE')
    (tmp_path / 'example.dist-info').mkdir()
    (tmp_path / 'NOTICE').write_text('fixture')
    dist = SimpleNamespace(metadata={'Name': 'example'}, version='1', files=[file],
                           locate_file=lambda path: tmp_path / path)
    with pytest.raises(ValueError, match='Unsafe'):
        notices.collect(tmp_path, tmp_path / 'out', distributions=[dist])


def test_project_license_and_binary_notices_are_present():
    assert 'GNU AFFERO GENERAL PUBLIC LICENSE' in (ROOT / 'LICENSE').read_text()
    assert 'AGPL-3.0-or-later' in (ROOT / 'pyproject.toml').read_text()
    packaging = (ROOT / 'packaging/paperfact.spec').read_text()
    for name in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md', 'dependency-licenses',
                 'build-info.json'):
        assert name in packaging
