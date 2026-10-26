"""Exercise a frozen app using generated research and isolated account/data homes."""

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
               QT_QPA_PLATFORM=os.environ.get('QT_QPA_PLATFORM', 'offscreen'),
               PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
               HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9')
    system = Path(os.environ.get('SYSTEMROOT', '/usr'))
    env['PATH'] = os.pathsep.join(map(str, [Path(sys.executable).parent, system / 'System32',
                                          system] if os.name == 'nt' else ['/usr/bin', '/bin']))
    return env


def compare_files(first, second):
    with zipfile.ZipFile(first) as a, zipfile.ZipFile(second) as b:
        files = {name: a.read(name) for name in a.namelist() if name.startswith('files/')}
        other = {name: b.read(name) for name in b.namelist() if name.startswith('files/')}
        if not files or files != other:
            raise ValueError('Research files changed during frozen-app round trip')
        return len(files)


def check_process(result, label):
    if result.returncode or b'Traceback (most recent call last):' in result.stdout + result.stderr:
        raise RuntimeError(f'{label} failed ({result.returncode}); inspect the captured log')


def verify(built, out):
    out.mkdir(parents=True, exist_ok=False)
    folder = built / 'Contents/MacOS' if sys.platform == 'darwin' else built
    ext = '.exe' if os.name == 'nt' else ''
    cli, gui = folder / ('paperfact-cli' + ext), folder / ('Paperfact' + ext)

    def run(label, command, env):
        result = subprocess.run(list(map(str, command)), cwd=ROOT, env=env,
                                capture_output=True, timeout=90)
        (out / (label + '.log')).write_bytes(result.stdout + result.stderr)
        check_process(result, label)
        log = Path(env['PAPERFACT_DATA']) / 'app.log'
        if log.exists() and 'Traceback' in log.read_text(encoding='utf-8', errors='replace'):
            raise RuntimeError(f'{label} logged a traceback')

    empty = isolated_env(out / 'empty')
    run('version', [cli, '--version'], empty)
    run('doctor', [cli, 'doctor'], empty)
    run('first-use', [gui], empty)
    assert not (Path(empty['PAPERFACT_DATA']) / 'llm.json').exists()
    recipient = isolated_env(out / 'recipient')
    sender = isolated_env(out / 'sender')
    original, returned = out / 'original.zip', out / 'returned.zip'
    seed = (
        "import sys; sys.path.insert(0, 'scripts'); import demo_workspace; "
        "demo_workspace.seed(); from paper_daily import bundle; "
        "from pathlib import Path; bundle.export('demo', Path(sys.argv[1]))"
    )
    run('seed', [sys.executable, '-c', seed, original], sender)
    run('share-link', [cli, 'list-share-link', original,
                       'https://files.example.org/research.zip'], sender)
    expected = 'https://files.example.org/research.zip#paperfact-sha256=' + (
        hashlib.sha256(original.read_bytes()).hexdigest())
    assert expected in (out / 'share-link.log').read_text(encoding='utf-8')
    run('import', [cli, 'list-import', original], recipient)
    run('import-again', [cli, 'list-import', original], recipient)
    # This acknowledges only the generated test recipient's local fixture.
    run('fixture-ack', [sys.executable, '-c',
                       'from paper_daily import onboarding; onboarding.accept(analytics=False)'],
        recipient)
    run('reader', [gui, '--paper', 'demo:paperfact'], recipient)
    run('export', [cli, 'list-export', 'demo', '-o', returned], recipient)
    files = compare_files(original, returned)
    workspace = Path(recipient['PAPERFACT_DATA'])
    with sqlite3.connect(workspace / 'papers.db') as db:
        assert db.execute('SELECT count(*) FROM list_papers').fetchone()[0] == 1
        assert db.execute('SELECT body FROM dives').fetchone()[0]
    assert not (workspace / 'llm.json').exists()
    from verify_local_integration import verify as verify_integration

    integration = verify_integration([cli], out / 'integration-workspace', empty)
    if sys.platform.startswith('linux'):
        from paper_daily import __version__

        appimage = ROOT / 'dist' / f'Paperfact-{__version__}-linux-x86_64.AppImage'
        if appimage.exists():
            integration['appimage'] = verify_integration(
                [appimage, '--cli'], out / 'appimage-workspace',
                {**empty, 'APPIMAGE_EXTRACT_AND_RUN': '1'})
    result = {'passed': True, 'research_files_preserved': files, 'integration': integration,
              'checks': ['version', 'doctor', 'first-use', 'import', 'duplicate-import',
                         'reader', 'export', 'file-fidelity', 'share-link-checksum',
                         'json-cli', 'mcp-stdio', 'mcp-retry'],
              'limitations': 'No real provider login, model call or Google Slides export.'}
    (out / 'report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('built', type=Path)
    parser.add_argument('out', type=Path)
    args = parser.parse_args()
    verify(args.built.resolve(), args.out.resolve())
