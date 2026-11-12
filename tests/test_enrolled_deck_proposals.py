"""Actual enrolled union content, before-insert grants and transaction ownership."""

import copy
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from uuid import uuid4

import pymupdf
import pytest
from test_deck_proposal_packages import package as package
from test_portable_deck_proposal import scientific as scientific
from test_rescue_deck_import import RECEIVER
from test_rescue_deck_import import case as case
from test_rescue_deck_import import codec as codec
from test_rescue_deck_import import no_external as no_external
from test_rescue_deck_import import original as original
from test_sync_files import paper_payload

from paper_daily import enrolled_deck_proposals as catalog
from paper_daily import portable_deck_proposal as content_codec
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.sync_artifacts import desired_file
from paper_daily.sync_capture import suppress_capture
from paper_daily.sync_files import file_id
from paper_daily.sync_research import _local_paper as local_paper_id


def native(path):
    value = path.stat()
    return value.st_dev, value.st_ino


@pytest.fixture
def actual(package, scientific):
    client = package.case["a"]
    store = package.case["transfer"].store
    with client.journal.transaction() as conn:
        local_id = local_paper_id(conn, RECEIVER)
    deck, evidence, images, _originals, _sha, _b = scientific
    source = package.case["root"] / "source-a.pdf"
    original_a = source.read_bytes()
    sha = hashlib.sha256(original_a).hexdigest()
    for row in deck.sources + deck.figures + evidence["sources"] + evidence["figures"]:
        row["document_hash"] = sha
    fourth = pymupdf.Pixmap(pymupdf.csRGB, 2, 2, b"\x13\x57\x9b" * 4, False).tobytes("png")
    images["evidence:four"] = fourth
    evidence["figures"].append(
        dict(
            id="evidence:four",
            label="Evidence-only plate",
            caption="Full scientific metadata",
            page=1,
            document_hash=sha,
        )
    )
    manifest, blobs = content_codec.encode(
        deck, evidence, images, {sha: original_a}, source_document_hash=sha
    )
    expected = content_codec.decode(manifest, lambda row: blobs[row["sha256"]])
    return dict(
        client=client,
        store=store,
        local=local_id,
        portable=RECEIVER,
        manifest=manifest,
        blobs=blobs,
        expected=expected,
        package=package,
    )


def prepare(actual, **kwargs):
    return catalog.prepare(
        actual["client"],
        actual["store"],
        actual["local"],
        actual["portable"],
        actual["manifest"],
        lambda row: actual["blobs"][row["sha256"]],
        request_id=kwargs.pop("request_id", "union-four"),
        expected_native=native(actual["client"].journal.path),
        **kwargs,
    )


def count(actual):
    with closing(sqlite3.connect(actual["client"].journal.path)) as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (catalog.TABLE,)
        ).fetchone():
            return 0
        return conn.execute("SELECT COUNT(*) FROM " + catalog.TABLE).fetchone()[0]


def save(actual, prepared):
    with actual["client"].journal.transaction() as conn:
        return catalog.adopt_in(conn, prepared)


def test_full_union_retained_without_mutating_science_or_saved_deck_and_exact_retry(actual):
    client, blobs = actual["client"], actual["store"]
    before = client.journal.path.read_bytes()
    pending = client.journal.pending()
    scientific = copy.deepcopy((actual["manifest"], actual["expected"]))
    prepared = prepare(actual)
    assert client.journal.path.read_bytes() == before and count(actual) == 0
    with client.journal.transaction() as conn:
        active = desired_file(conn, file_id(RECEIVER, "deck", "guide"))
    identity = save(actual, prepared)
    assert save(actual, prepared) == identity and count(actual) == 1
    assert save(actual, prepare(actual)) == identity
    view = catalog.read(client, blobs, identity, expected_native=native(client.journal.path))
    assert view.current_parent and view.content == actual["expected"]
    assert len(view.content["deck"]["figures"]) == 3
    assert len(view.content["evidence"]["figures"]) == 4
    assert len(view.content["image_bytes"]) == 4
    assert all(path.is_file() for path, _version in view.witnesses)
    assert view.content["source_document_hash"] == actual["package"].original_a
    assert client.journal.pending() == pending
    with client.journal.transaction() as conn:
        assert desired_file(conn, file_id(RECEIVER, "deck", "guide")) == active
        assert catalog.assert_current_in(conn, view)
    assert (actual["manifest"], actual["expected"]) == scientific
    changed = view.content
    changed["deck"]["title"] = "external mutation"
    changed["image_bytes"].clear()
    assert view.content == actual["expected"]


def test_caller_rollback_after_adoption_leaves_no_catalog_or_outbox_then_exact_retry(actual):
    prepared = prepare(actual)
    pending = actual["client"].journal.pending()
    with (
        pytest.raises(RuntimeError, match="Synthetic"),
        actual["client"].journal.transaction() as conn,
    ):
        identity = catalog.adopt_in(conn, prepared)
        assert catalog.record(conn, identity)
        raise RuntimeError("Synthetic after insertion")
    assert count(actual) == 0 and actual["client"].journal.pending() == pending
    assert save(actual, prepared) == prepared.proposal_id and count(actual) == 1


def test_absent_target_requires_before_insert_grant_and_real_mapping(actual):
    client = actual["client"]
    actual["portable"] = str(uuid4())
    actual["local"] = "sync:" + actual["portable"]
    # Unknown scientific sources are legitimate content, with no invented originals.
    source = copy.deepcopy(actual["expected"])
    for row in [
        *source["deck"]["sources"],
        *source["deck"]["figures"],
        *source["evidence"]["sources"],
        *source["evidence"]["figures"],
    ]:
        row["document_hash"] = None
    actual["manifest"], actual["blobs"] = content_codec.encode(
        source["deck"], source["evidence"], source["image_bytes"], {}
    )
    prepared = prepare(actual, allow_absent=True)
    assert prepared.expected_absent
    with pytest.raises(ValueError, match="grant|absent"):
        save(actual, prepared)
    with client.journal.transaction() as conn, catalog.import_targets_in(conn, [prepared]) as grant:
        operation = client.new_graph_operation_in(
            conn, "paper", actual["portable"], paper_payload()
        )
        client.journal.apply_in(conn, operation, client.writer)
        assert local_paper_id(conn, actual["portable"]) == actual["local"]
        ids = grant.adopt()
        assert grant.adopt() == ids
    assert count(actual) == 1
    with pytest.raises(ValueError, match="no longer"):
        grant.adopt()
    view = catalog.read(
        client, actual["store"], ids[0], expected_native=native(client.journal.path)
    )
    assert view.current_parent and view.content["original_bytes"] == {}
    with (
        client.journal.transaction() as conn,
        catalog.import_targets_in(conn, [prepared]) as replay,
    ):
        assert replay.adopt() == ids


@pytest.mark.parametrize("allow_updates", [False, True])
def test_import_metadata_update_is_explicit_same_lifetime_only(actual, allow_updates):
    prepared = prepare(actual)
    client = actual["client"]
    pending = client.journal.pending()
    with client.journal.transaction() as conn:
        before = conn.execute("SELECT title FROM papers WHERE id=?", (actual["local"],)).fetchone()[
            0
        ]
    if not allow_updates:
        with (
            pytest.raises(ValueError, match="parent"),
            client.journal.transaction() as conn,
            catalog.import_targets_in(conn, [prepared]) as grant,
        ):
            with suppress_capture(conn):
                conn.execute(
                    "UPDATE papers SET title='Imported metadata' WHERE id=?",
                    (actual["local"],),
                )
            grant.adopt()
        assert count(actual) == 0
        with client.journal.transaction() as conn:
            assert (
                conn.execute("SELECT title FROM papers WHERE id=?", (actual["local"],)).fetchone()[
                    0
                ]
                == before
            )
    else:
        with (
            client.journal.transaction() as conn,
            catalog.import_targets_in(conn, [prepared], allow_updates=True) as grant,
        ):
            with suppress_capture(conn):
                conn.execute(
                    "UPDATE papers SET title='Imported metadata' WHERE id=?", (actual["local"],)
                )
            identity = grant.adopt()[0]
        view = catalog.read(
            client, actual["store"], identity, expected_native=native(client.journal.path)
        )
        assert view.current_parent and view.content == actual["expected"]
        assert json.loads(view.record["captured_json"])["paper"]["title"] == before
        assert (
            json.loads(view.record["owner_json"])["target"]["paper"]["title"] == "Imported metadata"
        )
    assert client.journal.pending() == pending


@pytest.mark.parametrize("phase", ["before", "inside"])
def test_delete_recreate_refuses_original_epoch_even_when_metadata_updates_allowed(actual, phase):
    client = actual["client"]
    prepared = prepare(actual)
    pending = client.journal.pending()

    def repair(conn):
        columns = [r[1] for r in conn.execute("PRAGMA table_info(papers)")]
        row = conn.execute("SELECT * FROM papers WHERE id=?", (actual["local"],)).fetchone()
        token = parent_lifecycle(conn, "paper", actual["local"])
        with suppress_capture(conn):  # Controlled external repair, not supported protocol deletion.
            conn.execute("DELETE FROM papers WHERE id=?", (actual["local"],))
            conn.execute(
                "INSERT INTO papers("
                + ",".join(columns)
                + ") VALUES("
                + ",".join("?" for _ in columns)
                + ")",
                tuple(row),
            )
        assert parent_lifecycle(conn, "paper", actual["local"]) != token

    if phase == "before":
        with client.journal.transaction() as conn:
            repair(conn)
        with pytest.raises(ValueError, match="parent"):
            save(actual, prepared)
    else:
        with (
            pytest.raises(ValueError, match="parent"),
            client.journal.transaction() as conn,
            catalog.import_targets_in(conn, [prepared], allow_updates=True) as grant,
        ):
            repair(conn)
            grant.adopt()
    assert count(actual) == 0 and client.journal.pending() == pending


@pytest.mark.parametrize("fault", ["foreign-source", "missing-source", "cancel", "request-reuse"])
def test_invalid_source_cancel_and_reused_request_never_gain_ownership(actual, fault, monkeypatch):
    pending = actual["client"].journal.pending()
    prepared = prepare(actual)
    if fault == "cancel":
        with (
            actual["client"].journal.transaction() as conn,
            pytest.raises(ValueError, match="cancelled"),
        ):
            catalog.adopt_in(conn, prepared, current=lambda: False)
    elif fault == "request-reuse":
        save(actual, prepared)
        changed = copy.deepcopy(actual["expected"])
        changed["deck"]["title"] = "Different scientific result"
        actual["manifest"], actual["blobs"] = content_codec.encode(
            changed["deck"],
            changed["evidence"],
            changed["image_bytes"],
            changed["original_bytes"],
            source_document_hash=changed["source_document_hash"],
        )
        with pytest.raises(ValueError, match="reused"):
            save(actual, prepare(actual))
    else:
        if fault == "foreign-source":
            actual["portable"] = str(uuid4())
            actual["client"].save(
                actual["client"].new_graph_operation("paper", actual["portable"], paper_payload())
            )
            with actual["client"].journal.transaction() as conn:
                actual["local"] = local_paper_id(conn, actual["portable"])
            pending = actual["client"].journal.pending()
            prepared = prepare(actual)
        else:
            monkeypatch.setattr(catalog, "inspectable", lambda *_: None)
        with pytest.raises(ValueError, match="exact receiver"):
            save(actual, prepared)
    assert count(actual) == int(fault == "request-reuse")
    assert actual["client"].journal.pending() == pending


@pytest.mark.parametrize("fault", ["binding", "index", "database", "partial-schema"])
def test_native_binding_index_and_schema_change_refuse_without_publication(actual, fault):
    prepared = prepare(actual)
    client, store = actual["client"], actual["store"]
    pending = client.journal.pending()
    if fault == "binding":
        with closing(sqlite3.connect(store.root / "index.sqlite")) as conn, conn:
            conn.execute("UPDATE transfer_binding SET device='foreign'")
    elif fault == "partial-schema":
        with client.journal.transaction() as conn:
            conn.execute("CREATE TABLE " + catalog.TABLE + "(proposal_id TEXT)")
    else:
        path = client.journal.path if fault == "database" else store.root / "index.sqlite"
        replacement = path.with_suffix(".replacement")
        with (
            closing(sqlite3.connect(path)) as source,
            closing(sqlite3.connect(replacement)) as target,
        ):
            source.backup(target)
        assert native(path) != native(replacement)
        os.replace(replacement, path)
    with pytest.raises(ValueError):
        save(actual, prepared)
    assert client.journal.pending() == pending


def test_read_is_readonly_defensive_and_same_parent_rename_is_reviewable(actual):
    identity = save(actual, prepare(actual))
    client = actual["client"]
    with client.journal.transaction() as conn, suppress_capture(conn):
        conn.execute(
            "UPDATE papers SET title='Renamed same lifetime' WHERE id=?", (actual["local"],)
        )
    before = client.journal.path.read_bytes()
    view = catalog.read(
        client, actual["store"], identity, expected_native=native(client.journal.path)
    )
    with client.journal.transaction() as conn:
        assert catalog.assert_current_in(conn, view)
    assert client.journal.path.read_bytes() == before
    assert view.content == actual["expected"] and view.current_parent


def test_stage_failure_preserves_prior_rows_and_exact_retry(actual, monkeypatch):
    actual_stage = catalog.stage_bytes
    pending = actual["client"].journal.pending()

    def deny(*_args):
        raise OSError("Synthetic CAS failure")

    monkeypatch.setattr(catalog, "stage_bytes", deny)
    with pytest.raises(OSError, match="CAS"):
        prepare(actual)
    assert count(actual) == 0 and actual["client"].journal.pending() == pending
    monkeypatch.setattr(catalog, "stage_bytes", actual_stage)
    assert save(actual, prepare(actual)) and count(actual) == 1


def test_absent_target_appearing_before_grant_refuses_without_reobserving_authority(actual):
    actual["portable"] = str(uuid4())
    actual["local"] = "sync:" + actual["portable"]
    prepared = prepare(actual, allow_absent=True)
    client = actual["client"]
    client.save(client.new_graph_operation("paper", actual["portable"], paper_payload()))
    with (
        client.journal.transaction() as conn,
        pytest.raises(ValueError, match="mapping|absence|parent"),
        catalog.import_targets_in(conn, [prepared]) as grant,
    ):
        grant.adopt()
    assert count(actual) == 0


def test_changed_blob_after_prepare_refuses_retention_and_keeps_existing_content(actual):
    prepared = prepare(actual)
    item = actual["manifest"]["images"][0]
    path = actual["store"].root / "objects" / item["sha256"]
    before = path.read_bytes()
    path.write_bytes(before[:-1] + bytes([before[-1] ^ 1]))
    with pytest.raises(ValueError, match="changed"):
        save(actual, prepared)
    assert count(actual) == 0


def test_historical_preview_after_external_parent_deletion_is_readonly_not_apply_authority(actual):
    identity = save(actual, prepare(actual))
    client = actual["client"]
    with client.journal.transaction() as conn, suppress_capture(conn):
        conn.execute("DELETE FROM papers WHERE id=?", (actual["local"],))
    # Controlled unsupported external repair; no shared deletion is claimed.
    pending = client.journal.pending()
    before = client.journal.path.read_bytes()
    view = catalog.read(
        client, actual["store"], identity, expected_native=native(client.journal.path)
    )
    assert view.content == actual["expected"] and not view.current_parent
    with client.journal.transaction() as conn, pytest.raises(ValueError):
        catalog.assert_current_in(conn, view)
    assert client.journal.path.read_bytes() == before and client.journal.pending() == pending


def test_closed_catalog_refuses_unknown_observation_fields(actual):
    identity = save(actual, prepare(actual))
    with actual["client"].journal.transaction() as conn:
        row = catalog.record(conn, identity)
    owner = json.loads(row["owner_json"])
    owner["observation"]["unknown_authority"] = "must refuse"
    row["owner_json"] = content_codec.canonical_json(owner).decode()
    with pytest.raises(ValueError):
        catalog.validate_record(row)


def test_absent_target_source_and_catalog_adopt_atomically_with_rollback_and_exact_retry(actual):
    from paper_daily.sync_source_files import prepare_source, publish_source_in

    client = actual["client"]
    actual["portable"] = str(uuid4())
    actual["local"] = "sync:" + actual["portable"]
    prepared = prepare(actual, allow_absent=True)
    operation = client.new_graph_operation("paper", actual["portable"], paper_payload())
    source = prepare_source(
        client,
        actual["portable"],
        actual["package"].case["root"] / "source-a.pdf",
        document_hash=actual["package"].original_a,
        parent_incarnation=operation["incarnation"],
        store=actual["store"],
        version_root=actual["package"].case["transfer"].root,
        request_id="absent-original-a",
    )
    pending = client.journal.pending()
    with (
        pytest.raises(RuntimeError, match="after both"),
        client.journal.transaction() as conn,
        catalog.import_targets_in(conn, [prepared]) as grant,
    ):
        client.journal.apply_in(conn, operation, client.writer)
        publish_source_in(conn, client, source)
        identity = grant.adopt()[0]
        assert catalog.record(conn, identity)
        raise RuntimeError("after both source and proposal")
    assert count(actual) == 0 and client.journal.pending() == pending
    with client.journal.transaction() as conn:
        assert (
            conn.execute("SELECT 1 FROM papers WHERE id=?", (actual["local"],)).fetchone() is None
        )
    with client.journal.transaction() as conn, catalog.import_targets_in(conn, [prepared]) as grant:
        client.journal.apply_in(conn, operation, client.writer)
        publish_source_in(conn, client, source)
        identity = grant.adopt()[0]
    view = catalog.read(
        client, actual["store"], identity, expected_native=native(client.journal.path)
    )
    assert view.current_parent and view.content == actual["expected"]
    assert len(client.journal.pending()) == len(pending) + 2 and count(actual) == 1
