"""Source-native catalog collection and pure complete scientific archive reads."""

import copy
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pymupdf
import pytest
from test_enrolled_deck_proposals import actual as actual
from test_enrolled_deck_proposals import case as case
from test_enrolled_deck_proposals import codec as codec
from test_enrolled_deck_proposals import native, prepare, save
from test_enrolled_deck_proposals import no_external as no_external
from test_enrolled_deck_proposals import original as original
from test_enrolled_deck_proposals import package as package
from test_enrolled_deck_proposals import scientific as scientific
from test_local_deck_proposals import local as local

from paper_daily import enrolled_deck_proposals as enrolled
from paper_daily import local_deck_proposals as local_catalog
from paper_daily import portable_deck_proposal as content
from paper_daily import proposal_recovery as recovery


@pytest.fixture(params=["local", "enrolled"])
def source(request, tmp_path):
    if request.param == "enrolled":
        actual = request.getfixturevalue("actual")
        identity = save(actual, prepare(actual))
        database = actual["client"].journal.path

        def read():
            return enrolled.read(
                actual["client"], actual["store"], identity, expected_native=native(database)
            )

        def add():
            return save(actual, prepare(actual, request_id="second-proposal"))

        module = enrolled
        primary = actual["package"].primary
        assert primary["sha256"] != actual["package"].original_a
    else:
        fixture = request.getfixturevalue("local")
        database = fixture[0]
        deck, evidence, images, originals, sha, primary = request.getfixturevalue("scientific")
        fourth = pymupdf.Pixmap(pymupdf.csRGB, 2, 2, b"\x13\x57\x9b" * 4, False).tobytes("png")
        evidence["figures"].append(
            dict(
                id="evidence:four",
                label="Evidence-only original A",
                caption="Complete scientific caption",
                page=1,
                document_hash=sha,
            )
        )
        images["evidence:four"] = fourth
        manifest, blobs = content.encode(
            deck, evidence, images, originals, source_document_hash=sha
        )

        def retain(request_id):
            prepared = local_catalog.prepare(
                database,
                "local-paper",
                manifest,
                lambda row: blobs[row["sha256"]],
                request_id=request_id,
                expected_native=native(database),
            )
            return local_catalog.retain(prepared)

        identity = retain("first-proposal")

        def read():
            return local_catalog.read(database, identity, expected_native=native(database))

        def add():
            return retain("second-proposal")

        module = local_catalog
        assert hashlib.sha256(primary).hexdigest() != sha
    proposal = read()
    assert len(proposal.content["image_bytes"]) == 4
    snapshot = tmp_path / "snapshot.sqlite"
    with closing(sqlite3.connect(database)) as before, closing(sqlite3.connect(snapshot)) as after:
        before.backup(after)
    assert native(snapshot) != native(database)
    stage = tmp_path / "collection"
    stage.mkdir()
    (stage / "prior-sentinel").write_bytes(b"Preserve prior destination bytes")
    return dict(
        kind=request.param,
        database=database,
        snapshot=snapshot,
        stage=stage,
        module=module,
        read=read,
        add=add,
        proposal=proposal,
        identity=identity,
    )


def collect(source, **kwargs):
    with closing(sqlite3.connect(source["snapshot"])) as conn:
        return recovery.collect(
            source["database"],
            conn,
            source["stage"],
            expected_native=native(source["database"]),
            **kwargs,
        )


def stage_names(source):
    return sorted(path.name for path in source["stage"].iterdir())


def test_real_native_source_and_independent_snapshot_preserve_full_four_image_science(source):
    database = source["database"]
    before = database.read_bytes()
    proposal = source["proposal"]
    result = collect(source)
    assert len(result.rows) == 1 and len(result.objects) == 6
    row = result.rows[0]
    decoded = recovery.read(row, lambda item: result.objects[item["sha256"]].read_bytes())
    for key, value in proposal.content.items():
        assert decoded[key] == value
    assert decoded["archive_only"] and decoded["requires_explicit_review"]
    assert decoded["publish"] is False and decoded["sync"] is False
    assert decoded["provenance"]["record"] == proposal.record
    assert decoded["provenance"]["current_parent"] is True
    assert len(decoded["deck"]["figures"]) == 3 and len(decoded["evidence"]["figures"]) == 4
    assert set(decoded["original_bytes"]) == {decoded["source_document_hash"]}
    assert result.check() and all(path.is_file() for path, _stamp in result.witnesses)
    assert database.read_bytes() == before and source["read"]().content == proposal.content
    row["paper_id"] = "caller mutation"
    decoded["provenance"]["record"].clear()
    assert result.rows[0]["paper_id"] != "caller mutation"
    assert (
        recovery.read(result.rows[0], lambda item: result.objects[item["sha256"]].read_bytes())[
            "provenance"
        ]["record"]
        == proposal.record
    )
    assert (source["stage"] / "prior-sentinel").read_bytes() == b"Preserve prior destination bytes"


@pytest.mark.parametrize("change", ["addition", "snapshot-removal"])
def test_snapshot_and_original_roster_mismatch_refuses_without_staging(source, change):
    if change == "addition":
        source["add"]()
    else:
        with closing(sqlite3.connect(source["snapshot"])) as conn, conn:
            conn.execute("DELETE FROM " + source["module"].TABLE)
    before = source["database"].read_bytes()
    with pytest.raises(ValueError, match="roster"):
        collect(source)
    assert stage_names(source) == ["prior-sentinel"]
    assert source["database"].read_bytes() == before


def test_snapshot_native_inode_or_copied_rows_never_become_original_ownership(source):
    with closing(sqlite3.connect(source["snapshot"])) as conn:
        with pytest.raises(ValueError, match="native"):
            recovery.collect(
                source["snapshot"],
                conn,
                source["stage"],
                expected_native=native(source["database"]),
            )
        with pytest.raises(ValueError):
            recovery.collect(
                source["snapshot"],
                conn,
                source["stage"],
                expected_native=native(source["snapshot"]),
            )
    assert stage_names(source) == ["prior-sentinel"]


@pytest.mark.parametrize("change", ["cancel", "remove", "addition", "same-bytes-cas-write"])
def test_during_staging_change_cleans_only_own_objects_and_preserves_destination(
    source, monkeypatch, change
):
    original = recovery._read_object
    happened = False
    current = True
    before = source["database"].read_bytes()

    def interfere(path, item):
        nonlocal happened, current, before
        value = original(path, item)
        if not happened:
            happened = True
            if change == "cancel":
                current = False
            elif change == "addition":
                with closing(sqlite3.connect(source["database"])) as conn:
                    count = conn.execute(
                        "SELECT COUNT(*) FROM " + source["module"].TABLE
                    ).fetchone()[0]
                source["add"]()
                with closing(sqlite3.connect(source["database"])) as conn:
                    assert (
                        conn.execute("SELECT COUNT(*) FROM " + source["module"].TABLE).fetchone()[0]
                        == count + 1
                    )
                before = source[
                    "database"
                ].read_bytes()  # Actor committed; collector must add nothing.
            elif change == "remove":
                with closing(sqlite3.connect(source["database"])) as conn, conn:
                    conn.execute(
                        "DELETE FROM " + source["module"].TABLE + " WHERE proposal_id=?",
                        (source["identity"],),
                    )
            else:
                # Actual native file version changes; exact bytes remain scientifically identical.
                source_path = source["proposal"].witnesses[0][0]
                source_path.write_bytes(source_path.read_bytes())
        return value

    monkeypatch.setattr(recovery, "_read_object", interfere)
    with pytest.raises(ValueError):
        collect(source, current=lambda: current)
    assert happened and stage_names(source) == ["prior-sentinel"]
    assert (source["stage"] / "prior-sentinel").read_bytes() == b"Preserve prior destination bytes"
    if change != "remove":
        assert source["database"].read_bytes() == before


@pytest.mark.parametrize(
    "limit", ["MAX_ROWS", "MAX_OBJECTS", "MAX_TOTAL_BYTES", "MAX_METADATA_BYTES"]
)
def test_explicit_collection_budgets_refuse_without_truncation_or_prior_destination_changes(
    source, monkeypatch, limit
):
    monkeypatch.setattr(recovery, limit, 0)
    with pytest.raises(ValueError, match="bound|budget"):
        collect(source)
    assert stage_names(source) == ["prior-sentinel"]
    assert source["read"]().content == source["proposal"].content


def test_pure_read_never_opens_provenance_paths_and_rejects_closed_or_byte_tampering(
    source, monkeypatch
):
    collected = collect(source)
    row = collected.rows[0]
    blobs = {key: path.read_bytes() for key, path in collected.objects.items()}
    expected = source["proposal"].content

    def deny(*_args, **_kwargs):
        raise AssertionError("Archived provenance must not perform path/SQL/owner activation")

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", deny)
        patch.setattr(local_catalog, "_path", deny)
        patch.setattr(enrolled, "_runtime", deny)
        decoded = recovery.read(row, lambda item: blobs[item["sha256"]])
        assert decoded["image_bytes"] == expected["image_bytes"]
        assert decoded["original_bytes"] == expected["original_bytes"]
        assert decoded["provenance"]["record"] == source["proposal"].record
        for change in ("unknown", "paper", "id", "version", "kind"):
            bad = copy.deepcopy(row)
            if change == "unknown":
                bad["unexpected"] = True
            elif change == "paper":
                bad["paper_id"] = "foreign"
            elif change == "id":
                bad["record_id"] = "0" * 64
            else:
                provenance = json.loads(bad["provenance_json"])
                provenance["version" if change == "version" else "source_kind"] = (
                    2 if change == "version" else []
                )
                bad["provenance_json"] = content.canonical_json(provenance).decode()
            with pytest.raises(ValueError):
                recovery.read(bad, lambda item: blobs[item["sha256"]])
        damaged = dict(blobs)
        item = json.loads(row["manifest_json"])["images"][0]
        data = damaged[item["sha256"]]
        damaged[item["sha256"]] = data[:-1] + bytes([data[-1] ^ 1])
        with pytest.raises(ValueError, match="bytes"):
            recovery.read(row, lambda item: damaged[item["sha256"]])


def test_records_scope_checks_refuse_foreign_paper_mapping_or_workspace(source):
    row = collect(source).rows[0]
    with pytest.raises(ValueError, match="paper"):
        recovery.validate_row(row, papers=set())
    if source["kind"] == "enrolled":
        with pytest.raises(ValueError, match="mapping"):
            recovery.validate_row(row, paper_map={})
        with pytest.raises(ValueError, match="workspace"):
            recovery.validate_row(row, workspace="foreign")
    else:
        with pytest.raises(ValueError, match="enrolled"):
            recovery.validate_row(row, workspace="foreign")


def test_check_detects_later_roster_or_staged_byte_changes(source):
    collected = collect(source)
    path = next(iter(collected.objects.values()))
    before = path.read_bytes()
    path.write_bytes(before[:-1] + bytes([before[-1] ^ 1]))
    with pytest.raises(ValueError):
        collected.check()
    assert source["read"]().content == source["proposal"].content


def test_actual_stage_write_failure_keeps_source_and_prior_destination(source, monkeypatch):
    original = Path.open
    before = source["database"].read_bytes()
    attempted = []

    def fail(path, mode="r", *args, **kwargs):
        if mode == "xb" and path.parent.parent == source["stage"]:
            attempted.append(path)
            raise OSError("Synthetic temporary disk write denial")
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail)
    with pytest.raises(OSError, match="disk"):
        collect(source)
    assert len(attempted) == 1 and stage_names(source) == ["prior-sentinel"]
    assert source["database"].read_bytes() == before
    assert source["read"]().content == source["proposal"].content
