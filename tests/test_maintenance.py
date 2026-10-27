import hashlib
import json
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication
from test_update_notices import offer
from test_update_notices import pending as _pending
from test_update_notices import workspace as _workspace

from paper_daily import build_identity, diagnostics, updates

pending = _pending
workspace = _workspace


def test_source_identity_reads_commit_without_account_or_command_access(tmp_path):
    git = tmp_path / ".git"
    (git / "refs/heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    (git / "refs/heads/main").write_text("a" * 40)
    info = build_identity.identity(root=tmp_path, frozen=False)
    assert info["commit"] == "a" * 40 and info["dirty"] is None
    assert "開發版" in build_identity.label(info)
    assert "aaaaaaa" in build_identity.label(info)
    assert str(tmp_path) not in build_identity.describe(info)


@pytest.mark.parametrize("data", [None, [], {"commit": "private-email", "dirty": "yes"}])
def test_invalid_build_metadata_never_enters_copyable_identity(tmp_path, data):
    (tmp_path / "build-info.json").write_text(json.dumps(data))
    info = build_identity.identity(root=tmp_path, frozen=True)
    assert info["commit"] is None and info["dirty"] is None
    assert "private" not in build_identity.describe(info)
    assert "安裝版" in build_identity.label(info)


def test_packaged_dirty_build_is_distinguishable(tmp_path):
    (tmp_path / "build-info.json").write_text(json.dumps({"commit": "b" * 40, "dirty": True}))
    info = build_identity.identity(root=tmp_path, frozen=True)
    assert "bbbbbbb" in build_identity.describe(info)
    assert "含未提交修改" in build_identity.describe(info)


def test_diagnostic_stalls_and_build_identity_are_allowlisted(tmp_path):
    (tmp_path / "ui-stalls.log").write_text(
        "private-name stall 600 ms (stack in 3/4 samples)\n"
        "  paper_daily.desktop.main:private-note:234\n"
        "  account.secret:private-path:1\n",
        encoding="utf-8",
    )
    report = diagnostics.collect(tmp_path)
    assert report["ui_stalls"] == [
        {
            "duration_ms": 600,
            "frames": [
                {"module": "paper_daily.desktop.main", "line": 234},
            ],
        }
    ]
    assert "private" not in diagnostics.render(report)
    assert "commit" in report["build"]


def test_cache_expires_within_day_and_manual_check_bypasses_it(workspace):
    from paper_daily import store

    calls = []

    def fetch():
        calls.append(1)
        return []

    with store.connect() as conn:
        updates.check(conn, fetch=fetch, now=10000)
        updates.check(conn, fetch=fetch, now=10001)
        assert len(calls) == 1
        updates.check(conn, fetch=fetch, now=10002, force=True)
        assert len(calls) == 2
        updates.check(conn, fetch=fetch, now=11000)
        assert len(calls) == 3
        with pytest.raises(OSError):
            updates.check(conn, fetch=lambda: None, now=11001, force=True)


def test_wrong_cpu_never_receives_the_arm_mac_installer():
    found = offer()
    assert updates.asset_for(found, "darwin", machine="arm64")[0].endswith("arm64.dmg")
    assert updates.asset_for(found, "darwin", machine="x86_64") is None
    assert updates.asset_for(found, "linux", machine="aarch64") is None


@pytest.mark.parametrize("digest", ["", "sha256:bad", "sha256:" + "0" * 64])
def test_unverified_or_corrupt_download_is_rejected(tmp_path, digest):
    path = tmp_path / "app.exe"
    path.write_bytes(b"fixture")
    with pytest.raises(ValueError):
        updates.verify_download(path, digest)
    updates.verify_download(path, "sha256:" + hashlib.sha256(b"fixture").hexdigest())


def prepared(workspace, tmp_path, monkeypatch):
    found = offer()
    name = updates.asset_for(found)[0]
    path = tmp_path / name
    path.write_bytes(b"fixture")
    found = replace(found, digests={name: "sha256:" + hashlib.sha256(b"fixture").hexdigest()})
    monkeypatch.setattr(updates, "can_install", lambda: True)
    monkeypatch.setattr(updates, "download_dir", lambda: tmp_path)
    monkeypatch.setattr(updates, "download", lambda *a: path)
    workspace.offer(found)
    return path


def test_busy_editor_defers_install_and_retry_launches_once(
    workspace, pending, tmp_path, monkeypatch
):
    path = prepared(workspace, tmp_path, monkeypatch)
    launched, closed = [], []
    workspace._prepare_install = lambda: False
    monkeypatch.setattr(updates, "launch_installer", launched.append)
    workspace.quit_for_update.connect(lambda: closed.append(True))
    workspace.start_install()
    pending.pop()()
    QApplication.processEvents()
    assert not launched and not closed
    assert workspace.install.isEnabled() and "背景工作" in workspace.label.text()
    workspace._prepare_install = lambda: True
    workspace.start_install()
    workspace.start_install()
    assert len(pending) == 1
    pending.pop()()
    QApplication.processEvents()
    assert launched == [path] and closed == [True]


def test_changed_download_after_defer_cannot_be_installed(
    workspace, pending, tmp_path, monkeypatch
):
    path = prepared(workspace, tmp_path, monkeypatch)
    workspace._prepare_install = lambda: False
    launched = []
    monkeypatch.setattr(updates, "launch_installer", launched.append)
    workspace.start_install()
    pending.pop()()
    QApplication.processEvents()
    path.write_bytes(b"tampered")
    workspace._prepare_install = lambda: True
    workspace.start_install()
    pending.pop()()
    QApplication.processEvents()
    assert not launched and workspace.install.isEnabled()
    assert "驗證失敗" in workspace.label.text()


def test_manual_check_retries_and_ignores_snooze(workspace, pending, monkeypatch):
    seen = []
    monkeypatch.setattr(updates, "check", lambda conn, **kw: seen.append(kw) or offer())
    workspace.offer(offer())
    workspace.later.click()
    workspace.check_in_background(force=True)
    workspace.check_in_background(force=True)
    assert len(pending) == 1
    pending.pop()()
    QApplication.processEvents()
    assert seen == [{"channel": "beta", "force": True}]
    assert not workspace.isHidden()


def test_version_dialog_copies_identity_without_opening_browser(workspace):
    from paper_daily.desktop.version_dialog import VersionDialog

    info = build_identity.identity()
    dialog = VersionDialog(None, workspace, info, lambda: None)
    dialog.copy_button.click()
    assert QApplication.clipboard().text() == build_identity.describe(info)
    assert "已複製" in dialog.status.text()
    dialog.close()
    dialog.deleteLater()


def test_footer_exposes_version_and_reuses_one_dialog(workspace):
    from paper_daily import __version__
    from paper_daily.desktop.main import MainWindow

    window = MainWindow()
    window.show()
    assert __version__ in window.version_btn.toolTip()
    assert "開發" in window.version_btn.text()
    assert "不代表已發布版本" in window.version_btn.toolTip()
    window.version_btn.click()
    first = window._version_dialog
    window.version_btn.click()
    assert window._version_dialog is first
    first.close()
    window.close()
    window.deleteLater()


def test_pending_install_cannot_be_replaced_by_a_new_release(
    workspace, pending, tmp_path, monkeypatch
):
    path = prepared(workspace, tmp_path, monkeypatch)
    workspace._prepare_install = lambda: False
    workspace.start_install()
    pending.pop()()
    QApplication.processEvents()
    original = workspace.release
    newer = replace(original, version="9.9.9", digests={})
    workspace.offer(newer)
    workspace._found(newer)
    workspace.check_in_background(force=True)
    assert workspace.release == original and workspace._ready == path
    assert not pending and not workspace.isHidden()


def test_close_during_reverification_never_launches_installer(
    workspace, pending, tmp_path, monkeypatch
):
    path = prepared(workspace, tmp_path, monkeypatch)
    workspace._prepare_install = lambda: False
    launched = []
    monkeypatch.setattr(updates, "launch_installer", launched.append)
    workspace.start_install()
    pending.pop()()
    QApplication.processEvents()
    workspace._prepare_install = lambda: True
    workspace.start_install()
    workspace.close()
    pending.pop()()
    QApplication.processEvents()
    assert not launched and path.read_bytes() == b"fixture"


def test_installer_failure_keeps_app_open_and_can_retry(workspace, pending, tmp_path, monkeypatch):
    path = prepared(workspace, tmp_path, monkeypatch)
    closed, launched = [], []
    workspace.quit_for_update.connect(lambda: closed.append(True))

    def fail(_path):
        raise OSError("fixture failure")

    monkeypatch.setattr(updates, "launch_installer", fail)
    workspace.start_install()
    pending.pop()()
    QApplication.processEvents()
    assert not closed and workspace.install.isEnabled()
    monkeypatch.setattr(updates, "launch_installer", launched.append)
    workspace.start_install()
    pending.pop()()
    QApplication.processEvents()
    assert launched == [path] and closed == [True]


def test_missing_digest_never_downloads_or_launches(workspace, pending, tmp_path, monkeypatch):
    prepared(workspace, tmp_path, monkeypatch)
    workspace.release = replace(workspace.release, digests={})
    called = []
    monkeypatch.setattr(updates, "download", lambda *a: called.append("download"))
    monkeypatch.setattr(updates, "launch_installer", lambda *a: called.append("install"))
    workspace.start_install()
    pending.pop()()
    QApplication.processEvents()
    assert not called and workspace.install.isEnabled()
    assert "發布頁" in workspace.label.text()


@pytest.mark.parametrize("fail_midway", [False, True])
def test_failed_download_preserves_existing_file_and_cleans_partial(
    tmp_path, monkeypatch, fail_midway
):
    class Response:
        headers = {"content-length": "9"}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            pass

        def iter_bytes(self, size):
            yield b"abc"
            if fail_midway:
                raise OSError("fixture disconnect")

    monkeypatch.setattr(updates.httpx, "stream", lambda *a, **k: Response())
    path = tmp_path / "app.exe"
    path.write_bytes(b"previous")
    with pytest.raises(OSError):
        updates.download("https://fixture", path)
    assert path.read_bytes() == b"previous"
    assert not path.with_suffix(".exe.part").exists()


def test_version_dialog_reports_offline_and_allows_retry(workspace, pending, monkeypatch):
    from paper_daily.desktop.version_dialog import VersionDialog

    def fail(*a, **k):
        raise OSError("fixture")

    monkeypatch.setattr(updates, "check", fail)
    dialog = VersionDialog(None, workspace, build_identity.identity(), lambda: None)
    dialog.check_button.click()
    assert not dialog.check_button.isEnabled()
    pending.pop()()
    QApplication.processEvents()
    assert "無法檢查" in dialog.status.text() and dialog.check_button.isEnabled()
    monkeypatch.setattr(updates, "check", lambda *a, **k: None)
    dialog.check_button.click()
    pending.pop()()
    QApplication.processEvents()
    assert "沒有" in dialog.status.text() and dialog.check_button.isEnabled()
    dialog.close()
    dialog.deleteLater()


def test_support_copies_the_reviewed_identity_not_a_later_checkout(tmp_path, monkeypatch):
    from paper_daily.desktop.support_dialog import SupportDialog

    QApplication.instance() or QApplication([])
    dialog = SupportDialog(directory=tmp_path)
    expected = build_identity.describe(dialog.report["build"])
    monkeypatch.setattr(build_identity, "identity", lambda: {})
    dialog.copy_button.click()
    assert QApplication.clipboard().text() == expected
    dialog.close()
    dialog.deleteLater()


def test_update_preflight_defers_busy_work_and_persists_question_draft(workspace, monkeypatch):
    from paper_daily import store
    from paper_daily.desktop.main import MainWindow

    window = MainWindow()
    busy = type(window.reader_page.runner).busy
    monkeypatch.setattr(type(window.reader_page.runner), "busy", property(lambda self: True))
    assert not window._prepare_update()
    monkeypatch.setattr(type(window.reader_page.runner), "busy", busy)
    window.reader_page.ask_box.setText("fixture unsent question")
    assert window._prepare_update()
    with store.connect() as conn:
        state = json.loads(store.get_kv(conn, "ui.restart"))
    assert state["question"] == "fixture unsent question"
    window.close()
    window.deleteLater()


def test_update_preflight_keeps_window_when_storage_fails(workspace, monkeypatch):
    import sqlite3

    from paper_daily.desktop.main import MainWindow

    window = MainWindow()

    def fail():
        raise sqlite3.OperationalError("fixture database locked")

    monkeypatch.setattr(window, "_prepare_restart", fail)
    assert not window._prepare_update()
    window.close()
    window.deleteLater()


def test_worktree_identity_uses_common_packed_refs(tmp_path):
    git = tmp_path / "git"
    work = git / "worktrees" / "candidate"
    work.mkdir(parents=True)
    (tmp_path / ".git").write_text("gitdir: git/worktrees/candidate")
    (work / "HEAD").write_text("ref: refs/heads/candidate")
    (work / "commondir").write_text("../..")
    (git / "packed-refs").write_text("c" * 40 + " refs/heads/candidate\n")
    assert build_identity.identity(root=tmp_path, frozen=False)["commit"] == "c" * 40


def test_unflushed_draft_blocks_update_and_restart(workspace, monkeypatch):
    from paper_daily.desktop import ui_state
    from paper_daily.desktop.main import MainWindow

    window = MainWindow()
    window.reader_page.ask_box.setText("fixture unsaved question")
    real_flush = ui_state.flush
    monkeypatch.setattr(ui_state, "flush", lambda: False)
    assert not window._prepare_update()
    assert window.reader_page.ask_box.text() == "fixture unsaved question"
    monkeypatch.setattr(ui_state, "flush", real_flush)
    assert window._prepare_update()
    window.close()
    window.deleteLater()


@pytest.mark.parametrize("failure", ["move", "copy", "old-exists", "none"])
def test_mac_swap_preserves_original_on_failures(failure):
    import os
    import shutil
    import subprocess
    from pathlib import Path, PurePosixPath

    # Every filesystem/process command is replaced by a shell function. No Mac,
    # actual app bundle, mount, deletion or process termination is involved.
    bash = shutil.which("bash")
    if os.name == "nt":
        git = Path(shutil.which("git"))
        bash = next(
            str(p)
            for p in (
                git.parent / "bash.exe",
                git.parent.parent / "bin/bash.exe",
                git.parent.parent / "usr/bin/bash.exe",
            )
            if p.is_file()
        )
    functions = r"""
kill() { return 1; }
mktemp() { printf '/fixture'; }
hdiutil() { return 0; }
rmdir() { return 0; }
test() {
  if [ "$1" = "!" ] && [ "$FAILURE" = "old-exists" ]; then return 1; fi
  return 0
}
mv() {
  printf 'move:%s\n' "$1"
  if [ "$FAILURE" = "move" ]; then return 1; fi
  return 0
}
ditto() {
  printf 'copy\n'
  if [ "$FAILURE" = "copy" ]; then return 1; fi
  return 0
}
rm() { printf 'remove:%s\n' "$2"; }
open() { printf 'open:%s\n' "$1"; }
"""
    app = PurePosixPath("/Applications/Paper fact.app")
    script = functions + updates.mac_script(PurePosixPath("/fixture/new.dmg"), app, 7)
    result = subprocess.run(
        [bash, "--noprofile", "--norc"],
        input=script,
        text=True,
        capture_output=True,
        timeout=10,
        env={**os.environ, "FAILURE": failure},
    )
    lines = result.stdout.splitlines()
    if failure == "old-exists":
        assert result.returncode == 1 and lines == []
    elif failure == "move":
        assert result.returncode == 1 and lines == [f"move:{app}"]
    elif failure == "copy":
        assert result.returncode == 0
        assert lines == [f"move:{app}", "copy", f"remove:{app}", f"move:{app}.old", f"open:{app}"]
    else:
        assert result.returncode == 0
        assert lines == [f"move:{app}", "copy", f"remove:{app}.old", f"open:{app}"]


def test_late_check_does_not_leave_version_action_disabled(workspace):
    from paper_daily.desktop.version_dialog import VersionDialog

    workspace._checking = True
    dialog = VersionDialog(None, workspace, build_identity.identity(), lambda: None)
    assert not dialog.check_button.isEnabled()
    workspace._downloading = True
    workspace._found(offer())
    assert dialog.check_button.isEnabled() and "等待安裝" in dialog.status.text()
    dialog.close()
    dialog.deleteLater()


@pytest.mark.parametrize("enabled", [True, False])
def test_background_analysis_respects_queued_opt_in_and_out(workspace, monkeypatch, enabled):
    import sqlite3

    from paper_daily import analyze, store
    from paper_daily.desktop import ui_state
    from paper_daily.desktop.main import MainWindow

    window = MainWindow()
    assert ui_state.flush()
    with store.connect() as conn:
        store.set_kv(conn, "ui.background_analysis", "0" if enabled else "1")
    jobs = []
    monkeypatch.setattr(window, "_spawn_job", lambda *a: jobs.append(a))
    monkeypatch.setattr(analyze, "upcoming", lambda *a: ["fixture"])
    holder = sqlite3.connect(store.DB_PATH)
    holder.execute("BEGIN IMMEDIATE")
    try:
        window.remember("background_analysis", "1" if enabled else "0")
        window.top_up_dives()
        assert len(jobs) == int(enabled)
    finally:
        holder.rollback()
        holder.close()
        ui_state.flush()
        window.close()
        window.deleteLater()


def test_update_fixture_does_not_capture_unrelated_workers(pending):
    import threading

    finished = []
    worker = threading.Thread(target=lambda: finished.append(True))
    worker.start()
    worker.join(timeout=5)
    assert finished == [True] and not pending


def test_version_footer_identity_never_spawns_a_process(tmp_path, monkeypatch):
    import subprocess

    def blocked(*a, **k):
        raise AssertionError("Version display must not spawn a process")

    monkeypatch.setattr(subprocess, "Popen", blocked)
    info = build_identity.identity(root=tmp_path, frozen=True)
    assert info["architecture"] in {"amd64", "x86_64", "arm64", "aarch64", "x86", "i686", "other"}



@pytest.mark.parametrize("branch, track", [
    ("feature/0.5-sync-foundation", "0.5"),
    ("candidate/0.4.4-maintenance", "0.4.4"),
    ("feature/private-name", None),
])
def test_development_line_is_distinct_from_release_marker(tmp_path, branch, track):
    git = tmp_path / ".git"
    ref = git / "refs/heads" / branch
    ref.parent.mkdir(parents=True)
    ref.write_text("d" * 40)
    (git / "HEAD").write_text("ref: refs/heads/" + branch)
    info = build_identity.identity(root=tmp_path, frozen=False)
    assert info["development_line"] == track
    assert not build_identity.label(info).startswith("v")
    assert "開發" in build_identity.label(info)
    assert "不代表已發布版本" in build_identity.describe(info)
    assert "private-name" not in json.dumps(info)
