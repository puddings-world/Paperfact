"""Normal local preferences never become recovered research or credential exports."""

import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

import pytest
from test_recovery_adoption import prepared
from test_recovery_adoption import research as research_fixture
from test_recovery_adoption import restored as restored_fixture

from paper_daily.recovery_adoption import RecoveryAdoptionService

research = research_fixture
restored = restored_fixture


def test_normal_private_preferences_before_inspect_are_excluded_without_reading_files(
    restored, tmp_path, monkeypatch
):
    folder, _, _ = restored
    database = folder / "papers.db"
    secret = "FIXTURE-LOCAL-CREDENTIAL-NEVER-EXPORT-7041"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("INSERT INTO kv VALUES('ui.theme','private-dark')")
        conn.execute("INSERT INTO kv VALUES('auth.fixture',?)", (secret,))
    private = folder / "settings.json"
    private.write_text(json.dumps({"account": secret}), encoding="utf-8")
    before_db = database.read_bytes()
    original_open = Path.open

    class MetadataOnly:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            if name in {"read", "readinto", "readline", "readlines"}:
                pytest.fail("Credential file contents were read")
            return getattr(self.stream, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

    def opened(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return MetadataOnly(stream) if path == private else stream

    monkeypatch.setattr(Path, "open", opened)
    service = RecoveryAdoptionService(database)
    inspection = service.inspect()
    assert inspection.report["supported"]
    assert inspection.report["excluded_private_kv"] == 2
    assert inspection.report["excluded_private_files"] == 1
    assert secret.encode() not in inspection._snapshot
    assert secret not in json.dumps(inspection.report)
    result = prepared(service, inspection, tmp_path, "-private")
    assert database.read_bytes() == before_db
    assert not (Path(result["destination"]) / private.name).exists()
    with closing(sqlite3.connect(result["database"])) as conn:
        assert (
            conn.execute("SELECT key FROM kv WHERE key IN ('ui.theme','auth.fixture')").fetchall()
            == []
        )
    with zipfile.ZipFile(result["backup"]) as archive:
        assert secret.encode() not in b"".join(archive.read(name) for name in archive.namelist())
        assert b"private-dark" not in b"".join(archive.read(name) for name in archive.namelist())


@pytest.mark.parametrize("scope", ["unknown-kv", "settings-suffix-file"])
def test_private_exclusion_is_closed_not_a_blanket_ignore(restored, scope):
    folder, _, _ = restored
    secret = "UNKNOWN-SCOPE-DO-NOT-SILENTLY-DROP"
    if scope == "unknown-kv":
        with closing(sqlite3.connect(folder / "papers.db")) as conn, conn:
            conn.execute("INSERT INTO kv VALUES('settings.custom',?)", (secret,))
    else:
        (folder / "settings.extra.json").write_text(secret)
    with pytest.raises(ValueError) as failure:
        RecoveryAdoptionService(folder / "papers.db").inspect()
    assert secret not in str(failure.value)


@pytest.mark.parametrize("scope", ["private-kv", "private-file", "new-research-file"])
def test_late_private_or_inventory_change_requires_fresh_inspection(restored, tmp_path, scope):
    folder, _, _ = restored
    with closing(sqlite3.connect(folder / "papers.db")) as conn, conn:
        conn.execute("INSERT INTO kv VALUES('ui.theme','light')")
    private = folder / "settings.json"
    private.write_text("{}")
    service = RecoveryAdoptionService(folder / "papers.db")
    inspection = service.inspect()

    def mutate(text):
        if text != "Verified candidate ready for explicit review and adoption":
            return
        if scope == "private-kv":
            with closing(sqlite3.connect(folder / "papers.db")) as conn, conn:
                conn.execute("UPDATE kv SET value='dark' WHERE key='ui.theme'")
        elif scope == "private-file":
            private.write_text('{"local":true}')
        else:
            (folder / "new-research.pdf").write_bytes(b"unrepresented new research")

    with pytest.raises(ValueError, match="changed"):
        prepared(service, inspection, tmp_path, "-late", progress=mutate)
    assert not (tmp_path / "editable-late").exists()
    assert not (tmp_path / "editable-late.zip").exists()
