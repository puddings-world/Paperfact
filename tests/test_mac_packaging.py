"""Guard the emitted GUI bundle, including PyInstaller's CLI-derived defaults."""
import ast
import importlib.util
import plistlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_app', ROOT / 'scripts/build_app.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def gui_manifest():
    # Evaluate the actual BUNDLE overrides without invoking a platform build.
    tree = ast.parse((ROOT / 'packaging/paperfact.spec').read_text(encoding='utf-8'))
    bundle = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id == 'BUNDLE')
    overrides = next(kw.value for kw in bundle.keywords if kw.arg == 'info_plist')
    values = eval(compile(ast.Expression(overrides), '<bundle overrides>', 'eval'),
                  {'__version__': '0.4.5'})
    # PyInstaller defaults to background-only when COLLECT ends with console=True.
    return {'LSBackgroundOnly': True, 'CFBundlePackageType': 'APPL', **values}


def write_bundle(tmp_path, manifest):
    bundle = tmp_path / 'Paperfact.app'
    executables = bundle / 'Contents/MacOS'
    executables.mkdir(parents=True)
    for name in ('Paperfact', 'paperfact-cli'):
        (executables / name).write_bytes(b'fixture executable')
    with (bundle / 'Contents/Info.plist').open('wb') as output:
        plistlib.dump(manifest, output)
    return bundle


def test_gui_overrides_cli_background_default_and_keeps_both_executables(tmp_path):
    info = gui_manifest()
    assert info['LSBackgroundOnly'] is False
    assert info['LSUIElement'] is False
    assert info['CFBundleExecutable'] == 'Paperfact'
    build.verify_mac_bundle(write_bundle(tmp_path, info))


@pytest.mark.parametrize('key', ['LSBackgroundOnly', 'LSUIElement'])
@pytest.mark.parametrize('value', [True, 'false', 0, None])
def test_bad_or_missing_foreground_flags_block_packaging(tmp_path, key, value):
    info = gui_manifest()
    if value is None:
        info.pop(key)
    else:
        info[key] = value
    with pytest.raises(ValueError, match=key):
        build.verify_mac_bundle(write_bundle(tmp_path, info))


@pytest.mark.parametrize(
    'change', ['helper-entrypoint', 'not-an-app', 'missing-gui', 'missing-cli'])
def test_invalid_bundle_is_rejected(tmp_path, change):
    info = gui_manifest()
    if change == 'helper-entrypoint':
        info['CFBundleExecutable'] = 'paperfact-cli'
    if change == 'not-an-app':
        info['CFBundlePackageType'] = 'BNDL'
    bundle = write_bundle(tmp_path, info)
    if change.startswith('missing-'):
        name = 'Paperfact' if change == 'missing-gui' else 'paperfact-cli'
        (bundle / 'Contents/MacOS' / name).unlink()
    with pytest.raises(ValueError):
        build.verify_mac_bundle(bundle)


def test_broken_bundle_never_launches_or_replaces_existing_dmg(tmp_path, monkeypatch):
    monkeypatch.setattr(build, 'PLATFORM', 'darwin')
    monkeypatch.setattr(build, 'WORK', tmp_path / 'work')
    monkeypatch.setattr(build, 'DIST', tmp_path)
    old_dmg = tmp_path / build.artifact_name()
    old_dmg.write_bytes(b'previous candidate')
    info = gui_manifest()
    info['LSBackgroundOnly'] = True
    bundle = write_bundle(tmp_path, info)
    calls = []
    monkeypatch.setattr(build.subprocess, 'run', lambda *a, **kw: calls.append(a))
    with pytest.raises(ValueError, match='LSBackgroundOnly'):
        build.smoke(bundle)
    with pytest.raises(ValueError, match='LSBackgroundOnly'):
        build.mac_dmg(bundle)
    assert not calls
    assert old_dmg.read_bytes() == b'previous candidate'


def test_staging_cannot_reintroduce_background_only_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(build, 'WORK', tmp_path / 'work')
    monkeypatch.setattr(build, 'DIST', tmp_path)
    bundle = write_bundle(tmp_path, gui_manifest())
    calls = []

    def copy_with_bad_metadata(*command, **kwargs):
        calls.append(command[0])
        if command[0] == 'ditto':
            import shutil
            shutil.copytree(command[1], command[2])
            path = command[2] / 'Contents/Info.plist'
            info = plistlib.loads(path.read_bytes())
            info['LSBackgroundOnly'] = True
            path.write_bytes(plistlib.dumps(info))

    monkeypatch.setattr(build, 'run', copy_with_bad_metadata)
    with pytest.raises(ValueError, match='LSBackgroundOnly'):
        build.mac_dmg(bundle)
    assert calls == ['ditto']  # Never create a DMG with the invalid staged app.
