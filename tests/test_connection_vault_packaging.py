"""Bundle-selection contracts without opening native vaults or building an app."""

import sys
import tomllib
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("platform,backend", [
    ("win32", "Windows"), ("darwin", "macOS"), ("linux", "SecretService"),
])
def test_bundled_dependency_and_native_discovery_metadata(monkeypatch, platform, backend):
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert any(
        dep.startswith("keyring>=")
        for dep in config["project"]["optional-dependencies"]["app"]
    )
    hooks = ModuleType("PyInstaller.utils.hooks")
    hooks.collect_data_files = lambda name: []
    hooks.collect_submodules = lambda name: [name]
    hooks.copy_metadata = lambda name: [("metadata/" + name, name + ".dist-info")]
    monkeypatch.setitem(sys.modules, "PyInstaller", ModuleType("PyInstaller"))
    monkeypatch.setitem(sys.modules, "PyInstaller.utils", ModuleType("PyInstaller.utils"))
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks)
    monkeypatch.setattr(sys, "platform", platform)
    seen = {}

    def analysis(*args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(binaries=[], datas=[], scripts=[], pure=[])

    env = {"SPECPATH": str(ROOT / "packaging"), "Analysis": analysis}
    env.update({name: lambda *a, **k: SimpleNamespace() for name in (
        "PYZ", "EXE", "COLLECT", "BUNDLE"
    )})
    exec(compile((ROOT / "packaging/paperfact.spec").read_text(encoding="utf-8"),
                 "<packaging fixture>", "exec"), env)
    assert ("metadata/keyring", "keyring.dist-info") in seen["datas"]
    assert "keyring.backends." + backend in seen["hiddenimports"]
    assert not any("keyrings.alt" in name for name in seen["hiddenimports"])
