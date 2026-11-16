"""Mac distribution verification uses owned copied bytes, not a mounted/developer app."""

import json
import plistlib
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_built_app_verification import verify

from paper_daily import __version__


@pytest.fixture
def scene(tmp_path, monkeypatch):
    built = tmp_path / "dist/Paperfact.app"
    resources = built / "Contents/Resources"
    resources.mkdir(parents=True)
    (resources / "build-info.json").write_text(json.dumps(dict(commit="a" * 40, dirty=False)))
    binaries = built / "Contents/MacOS"
    binaries.mkdir()
    (binaries / "Paperfact").write_bytes(b"synthetic GUI")
    (binaries / "paperfact-cli").write_bytes(b"synthetic CLI")
    image = tmp_path / "dist" / f"Paperfact-{__version__}-macos-arm64.dmg"
    image.write_bytes(b"synthetic compressed image")
    out = tmp_path / "build/acceptance"
    out.mkdir(parents=True)
    monkeypatch.setattr(verify, "ROOT", tmp_path)
    monkeypatch.setattr(verify.sys, "platform", "darwin")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "puddings-world/Paperfact")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    acceptance = verify.Acceptance(built, out)
    plan = verify._mac_dmg_input(built, out, image)
    state = dict(mounted=False, fault=None, calls=[])
    path_type = type(plan["mount"])
    is_mount = path_type.is_mount
    monkeypatch.setattr(
        path_type, "is_mount", lambda p: state["mounted"] if p == plan["mount"] else is_mount(p)
    )
    env = verify.isolated_env(out / "isolated")

    def run(label, command, supplied, *, before=None, after=None):
        def execute():
            assert supplied == env and "CODEX_HOME" not in supplied
            assert Path(supplied["PAPERFACT_DATA"]).is_relative_to(out)
            if before:
                before()
            state["calls"].append((label, list(map(str, command))))
            raw = b""
            if label == "mac-dmg-mount":
                assert {"-readonly", "-nobrowse", "-mountpoint", "-plist"} <= set(command)
                assert command[-1] == image
                state["mounted"] = True
                shutil.copytree(built, plan["mount"] / "Paperfact.app")
                point = str(plan["mount"] if state["fault"] != "reply" else tmp_path / "foreign")
                raw = plistlib.dumps({"system-entities": [{"mount-point": point}]})
                if state["fault"] == "image":
                    image.write_bytes(b"changed image while attached")
            elif label == "mac-dmg-copy":
                if state["fault"] == "interrupt":
                    raise KeyboardInterrupt()
                if state["fault"] in {"copy", "both"}:
                    raise verify.CheckFailure(label, "subprocess_failed", 7)
                assert command[1:] == [plan["mount"] / "Paperfact.app", plan["copied"]]
                shutil.copytree(command[1], command[2])
                if state["fault"] == "bytes":
                    (plan["copied"] / "Contents/MacOS/Paperfact").write_bytes(b"wrong GUI")
            elif label == "mac-dmg-detach":
                assert command[-1] == plan["mount"]
                if state["fault"] in {"detach", "both"}:
                    raise verify.CheckFailure(label, "subprocess_failed", 9)
                state["mounted"] = False
            else:
                raise AssertionError(label)
            if after:
                after(raw)
            return raw

        return acceptance.call(label, execute)

    return SimpleNamespace(
        built=built,
        out=out,
        image=image,
        plan=plan,
        state=state,
        acceptance=acceptance,
        env=env,
        run=run,
    )


def test_exact_distribution_copy_is_detached_and_preserves_source(scene):
    original = verify._mac_bundle_hash(scene.built)
    copied, result = verify._mac_dmg_copy(
        scene.plan, scene.out, scene.env, scene.run, scene.acceptance
    )
    assert copied == scene.out / "mac-installed/Paperfact.app"
    assert verify._mac_bundle_hash(copied) == verify._mac_bundle_hash(scene.built) == original
    assert result == dict(
        image_sha256=scene.plan["sha256"], bundle_sha256=original, copied=True, detached=True
    )
    assert not scene.state["mounted"]
    assert [label for label, _ in scene.state["calls"]] == [
        "mac-dmg-mount",
        "mac-dmg-copy",
        "mac-dmg-detach",
    ]
    assert "mac-dmg-verify" in scene.acceptance.report["completed_checks"]


@pytest.mark.parametrize(
    "fault", ["reply", "bytes", "image", "copy", "detach", "both", "interrupt"]
)
def test_failure_refuses_acceptance_and_detaches_only_owned_volume(scene, fault):
    scene.state["fault"] = fault
    original = verify._mac_bundle_hash(scene.built)
    with pytest.raises((ValueError, verify.CheckFailure, KeyboardInterrupt)):
        verify._mac_dmg_copy(scene.plan, scene.out, scene.env, scene.run, scene.acceptance)
    assert verify._mac_bundle_hash(scene.built) == original
    assert scene.acceptance.report["passed"] is False
    assert scene.state["mounted"] is (fault in {"detach", "both"})
    labels = [label for label, _ in scene.state["calls"]]
    assert labels[-1] == "mac-dmg-detach"
    if fault == "both":
        assert scene.acceptance.report["active_check"] == "mac-dmg-copy"
        assert scene.acceptance.report["cleanup_failure"] == dict(
            stage="mac-dmg-detach", code="subprocess_failed", returncode=9
        )
    elif fault == "detach":
        assert scene.acceptance.report["active_check"] == "mac-dmg-detach"


@pytest.mark.parametrize("fault", ["not-ci", "wrong-path", "existing-copy"])
def test_preflight_and_existing_destination_never_touch_other_locations(scene, monkeypatch, fault):
    if fault == "not-ci":
        monkeypatch.delenv("GITHUB_ACTIONS")
        with pytest.raises(ValueError):
            verify._mac_dmg_input(scene.built, scene.out, scene.image)
    elif fault == "wrong-path":
        with pytest.raises(ValueError):
            verify._mac_dmg_input(scene.built, scene.out, scene.image.with_name("other.dmg"))
    else:
        scene.plan["copied"].mkdir(parents=True)
        keep = scene.plan["copied"] / "keep.txt"
        keep.write_bytes(b"existing content")
        with pytest.raises(FileExistsError):
            verify._mac_dmg_copy(scene.plan, scene.out, scene.env, scene.run, scene.acceptance)
        assert keep.read_bytes() == b"existing content"
    assert scene.state["calls"] == [] and scene.state["mounted"] is False


def test_public_verifier_flag_is_forwarded_without_a_real_mount(tmp_path, monkeypatch):
    selected = []

    def fake(built, out, *, installer=None, dmg=None):
        selected.append((built, out, installer, dmg))

    monkeypatch.setattr(verify, "verify", fake)
    image = tmp_path / "candidate.dmg"
    assert verify.main([str(tmp_path / "app"), str(tmp_path / "out"), "--dmg", str(image)]) == 0
    assert selected == [(tmp_path / "app", tmp_path / "out", None, image)]
