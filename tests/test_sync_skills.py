import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sync_skills", ROOT / "scripts/sync_skills.py")
skills = importlib.util.module_from_spec(spec)
spec.loader.exec_module(skills)


@pytest.fixture
def repo(tmp_path):
    folder = tmp_path / "skills/example-pattern"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: example-pattern\ndescription: Use for a fixture workflow.\n---\n\nSteps.\n",
        encoding="utf-8",
        newline="\n",
    )
    refs = folder / "references"
    refs.mkdir()
    (refs / "evidence.md").write_text("Synthetic evidence.\n", encoding="utf-8")
    return tmp_path


def test_check_is_read_only_and_install_is_repeatable(repo):
    assert skills.sync(repo)
    assert not (repo / ".agents").exists()
    assert not (repo / ".claude").exists()
    assert skills.sync(repo, write=True)
    assert skills.sync(repo) == []
    assert skills.sync(repo, write=True) == []
    for target in skills.TARGETS:
        assert (repo / target / "example-pattern/references/evidence.md").read_text() == (
            "Synthetic evidence.\n"
        )


def test_source_update_reaches_both_agents_and_preserves_unrelated_skill(repo):
    skills.sync(repo, write=True)
    unrelated = repo / ".claude/skills/unrelated/SKILL.md"
    unrelated.parent.mkdir()
    unrelated.write_text("User skill", encoding="utf-8")
    source = repo / "skills/example-pattern/references/evidence.md"
    source.write_text("Revised evidence.\n", encoding="utf-8")
    assert skills.sync(repo)
    skills.sync(repo, write=True)
    assert skills.sync(repo) == []
    assert unrelated.read_text() == "User skill"
    for target in skills.TARGETS:
        assert (repo / target / "example-pattern/references/evidence.md").read_bytes() == (
            source.read_bytes()
        )


def test_local_conflict_prevents_all_writes(repo):
    skills.sync(repo, write=True)
    original = (repo / ".agents/skills/example-pattern/SKILL.md").read_bytes()
    source = repo / "skills/example-pattern/SKILL.md"
    source.write_bytes(original + b"\nNew source step.\n")
    dest = repo / ".claude/skills/example-pattern/SKILL.md"
    dest.write_bytes(original + b"\nUser local edit.\n")
    with pytest.raises(ValueError, match="Local skill edit"):
        skills.sync(repo, write=True)
    assert (repo / ".agents/skills/example-pattern/SKILL.md").read_bytes() == original
    assert b"User local edit." in dest.read_bytes()


def test_unmanaged_existing_file_is_not_overwritten(repo):
    dest = repo / ".agents/skills/example-pattern/SKILL.md"
    dest.parent.mkdir(parents=True)
    dest.write_text("An unrelated existing skill", encoding="utf-8")
    with pytest.raises(ValueError, match="Local skill edit"):
        skills.sync(repo, write=True)
    assert dest.read_text() == "An unrelated existing skill"
    assert not (repo / ".claude").exists()


def test_interrupted_write_can_retry_without_destroying_installed_content(repo, monkeypatch):
    original = skills.atomic_write
    calls = []

    def interrupted(path, content):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("simulated disk failure")
        original(path, content)

    monkeypatch.setattr(skills, "atomic_write", interrupted)
    with pytest.raises(OSError, match="simulated disk failure"):
        skills.sync(repo, write=True)
    assert calls[0].is_file()
    monkeypatch.setattr(skills, "atomic_write", original)
    skills.sync(repo, write=True)
    assert skills.sync(repo) == []


def test_removed_source_requires_review_without_deleting_installed_evidence(repo):
    skills.sync(repo, write=True)
    (repo / "skills/example-pattern/references/evidence.md").unlink()
    with pytest.raises(ValueError, match="manual reconciliation"):
        skills.sync(repo, write=True)
    assert (repo / ".agents/skills/example-pattern/references/evidence.md").is_file()


def test_invalid_manifest_and_metadata_do_not_write(repo):
    manifest = repo / ".agents/skills" / skills.MANIFEST
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps(["bad"]), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid synchronization manifest"):
        skills.sync(repo, write=True)
    assert not (repo / ".claude").exists()
    manifest.unlink()
    (repo / "skills/example-pattern/SKILL.md").write_text("No metadata", encoding="utf-8")
    with pytest.raises(ValueError, match="metadata"):
        skills.sync(repo, write=True)
    assert not (repo / ".claude").exists()


@pytest.mark.parametrize("relative", ["skills/example-pattern", ".agents", ".claude/skills"])
def test_linked_paths_are_rejected_before_writing(repo, monkeypatch, relative):
    # Simulate symlinks without requiring Windows developer mode or admin rights.
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == repo / relative or original(path))
    with pytest.raises(ValueError, match="Linked skill path"):
        skills.sync(repo, write=True)
    assert not (repo / ".agents").exists()
    assert not (repo / ".claude").exists()


def test_crlf_checkout_does_not_create_false_conflicts(repo):
    skills.sync(repo, write=True)
    dest = repo / ".agents/skills/example-pattern/SKILL.md"
    dest.write_bytes(dest.read_bytes().replace(b"\n", b"\r\n"))
    assert skills.sync(repo) == []
    source = repo / "skills/example-pattern/SKILL.md"
    source.write_bytes(source.read_bytes() + b"\nNew step.\n")
    skills.sync(repo, write=True)
    assert skills.sync(repo) == []


def test_executable_source_is_not_distributed_implicitly(repo):
    (repo / "skills/example-pattern/run.py").write_text("print('no')", encoding="utf-8")
    with pytest.raises(ValueError, match="Only reviewed Markdown"):
        skills.sync(repo, write=True)
    assert not (repo / ".agents").exists()


def test_checked_in_skill_copies_are_synchronized():
    assert skills.sync(ROOT) == [], "Run python scripts/sync_skills.py --write"


def test_skill_references_and_paperfact_evidence_paths_exist():
    import re

    for file in (ROOT / "skills").rglob("*.md"):
        text = file.read_text(encoding="utf-8")
        for relative in re.findall(r"\]\((references/[^)]+)\)", text):
            assert (file.parent / relative).is_file(), (file, relative)
        if file.name == "evidence.md":
            for relative in re.findall(r"`((?:src/|tests/|docs/)[^`]+)`", text):
                assert (ROOT / relative).is_file(), (file, relative)
