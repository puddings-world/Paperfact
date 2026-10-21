"""Local maintainer notes must stay out of ordinary Git sharing."""

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_root_admin_notes_are_ignored_without_hiding_public_docs(tmp_path):
    git = shutil.which("git")
    assert git, "Git is required to verify private maintainer-note exclusion"
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    subprocess.run([git, "init", "-q", str(tmp_path)], check=True, env=env)
    shutil.copyfile(ROOT / ".gitignore", tmp_path / ".gitignore")
    # Neither this fixture nor the test reads the owner's private admin.md.
    (tmp_path / "admin.md").write_text("Synthetic private plan", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "privacy.md").write_text("Public consent information", encoding="utf-8")
    result = subprocess.run(
        [git, "check-ignore", "--no-index", "--", "admin.md", "docs/privacy.md", "docs/admin.md"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.splitlines() == ["admin.md"]
    visible = subprocess.run(
        [git, "ls-files", "--others", "--exclude-standard"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "admin.md" not in visible.stdout.splitlines()
    assert "docs/privacy.md" in visible.stdout.splitlines()


def test_release_screenshot_workspace_is_not_publishable_source(tmp_path):
    git = shutil.which("git")
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    subprocess.run([git, "init", "-q", str(tmp_path)], check=True, env=env)
    shutil.copyfile(ROOT / ".gitignore", tmp_path / ".gitignore")
    result = subprocess.run(
        [git, "check-ignore", "--no-index", "--", "shots/reader.png",
         "shots/workspace/papers.db", "docs/images/reader.jpg"],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=True,
    )
    assert result.stdout.splitlines() == ["shots/reader.png", "shots/workspace/papers.db"]
