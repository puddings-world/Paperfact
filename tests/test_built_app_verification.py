import importlib.util
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verify', ROOT / 'scripts/verify_built_app.py')
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def test_verification_does_not_inherit_developer_accounts(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'private')
    monkeypatch.setenv('CODEX_HOME', '/private/codex')
    monkeypatch.setenv('PAPERFACT_DATA', '/private/research')
    env = verify.isolated_env(tmp_path)
    assert 'ANTHROPIC_API_KEY' not in env and 'CODEX_HOME' not in env
    assert Path(env['PAPERFACT_DATA']).is_relative_to(tmp_path)
    assert Path(env['HOME']).is_relative_to(tmp_path)


def test_frozen_roundtrip_checks_pdf_bytes_not_just_counts(tmp_path):
    first, second = tmp_path / 'a.zip', tmp_path / 'b.zip'
    for target in (first, second):
        with zipfile.ZipFile(target, 'w') as archive:
            archive.writestr('files/pdf/demo.pdf', b'original bytes')
    assert verify.compare_files(first, second) == 1
    with zipfile.ZipFile(second, 'w') as archive:
        archive.writestr('files/pdf/demo.pdf', b'changed bytes')
    with pytest.raises(ValueError, match='changed'):
        verify.compare_files(first, second)


def test_zero_exit_does_not_hide_a_background_traceback():
    result = subprocess.CompletedProcess([], 0, b'Checks complete',
                                         b'Traceback (most recent call last):\nworker failed')
    with pytest.raises(RuntimeError, match='doctor failed'):
        verify.check_process(result, 'doctor')
    verify.check_process(subprocess.CompletedProcess([], 0, b'Checks complete', b''), 'doctor')
