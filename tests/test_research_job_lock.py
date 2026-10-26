"""Actual OS locks prevent queued duplicate model work, including separate CLIs."""

import subprocess
import sys

import pytest

from paper_daily.research_job_lock import claim


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "papers.db"
    path.touch()
    return path


def test_duplicate_is_nonblocking_and_other_owner_can_run(database):
    with (
        claim(database, "survey", "same-list") as first,
        claim(database, "survey", "same-list") as repeated,
        claim(database, "survey", "other-list") as independent,
    ):
        assert first and not repeated and independent
    with claim(database, "survey", "same-list") as retry:
        assert retry


def test_other_database_and_feature_are_independent(database, tmp_path):
    other = tmp_path / "other.db"
    other.touch()
    with (
        claim(database, "survey", "same") as first,
        claim(other, "survey", "same") as second,
        claim(database, "dive", "same") as third,
    ):
        assert first and second and third


def test_exception_releases_job_without_deleting_lockfile(database):
    with pytest.raises(RuntimeError), claim(database, "survey", "same"):
        raise RuntimeError("provider failed")
    with claim(database, "survey", "same") as retry:
        assert retry
    files = list((database.parent / ".research-jobs").glob("*.lock"))
    assert len(files) == 1 and files[0].read_bytes() == b"0"


def test_separate_process_observes_lock_then_can_retry(database):
    script = (
        "from paper_daily.research_job_lock import claim; import sys\n"
        "with claim(sys.argv[1], 'survey', 'same') as acquired:\n"
        " print('acquired' if acquired else 'busy')\n"
    )

    def run():
        return subprocess.run(
            [sys.executable, "-c", script, str(database)],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        ).stdout.strip()

    with claim(database, "survey", "same"):
        assert run() == "busy"
    assert run() == "acquired"


def test_process_exit_releases_ownership(database):
    script = (
        "from paper_daily.research_job_lock import claim; import sys, os\n"
        "with claim(sys.argv[1], 'survey', 'same') as acquired:\n"
        " assert acquired\n"
        " os._exit(7)\n"
    )
    result = subprocess.run([sys.executable, "-c", script, str(database)], timeout=20)
    assert result.returncode == 7
    with claim(database, "survey", "same") as retry:
        assert retry


@pytest.mark.parametrize(
    "feature,owner", [("../path", "a"), ("survey", ""), ("survey", "a" * 1025)]
)
def test_invalid_scope_does_not_create_files(database, feature, owner):
    with pytest.raises(ValueError), claim(database, feature, owner):
        pytest.fail("Invalid scope accepted")
    assert not (database.parent / ".research-jobs").exists()


def test_alias_resolves_same_database(database):
    alias = database.parent / "unused" / ".." / database.name
    (database.parent / "unused").mkdir()
    with claim(database, "survey", "same"), claim(alias, "survey", "same") as repeated:
        assert not repeated
