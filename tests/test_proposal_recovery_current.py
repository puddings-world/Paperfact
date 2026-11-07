"""Actual manually saved slots: byte preservation without invented AI provenance."""

import copy
import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import closing

import pytest
from test_local_deck_proposals import local as local
from test_local_deck_proposals import native
from test_local_deck_proposals import no_external as no_external
from test_local_deck_proposals import scientific as scientific

from paper_daily import local_deck_proposals as catalog
from paper_daily import presentations, recovery_decks
from paper_daily import proposal_recovery_current as observed
from paper_daily.sync_files import canonical_json


@pytest.fixture
def manual(local, scientific, tmp_path, monkeypatch):
    database, manifest, blobs, old, _before = local
    proposal = catalog.prepare(
        database,
        "local-paper",
        manifest,
        lambda item: blobs[item["sha256"]],
        request_id="manual-owner",
        expected_native=native(database),
    )
    identity = catalog.retain(proposal)
    retained = catalog.read(database, identity, expected_native=native(database))
    originals = {
        sha: next(path for path, _ in retained.witnesses if path.name == sha)
        for sha in retained.content["original_bytes"]
    }
    monkeypatch.setattr(presentations, "DECK_DIR", database.parent / "presentations")
    prior = presentations.deck_from_dict(json.loads(old.read_bytes()))
    prior._revision_figures = scientific[2]
    saved = presentations.save_deck(prior)
    snapshot = tmp_path / "manual-snapshot.sqlite"
    with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(snapshot)) as dest:
        source.backup(dest)
    temporary = tmp_path / "manual-stage"
    temporary.mkdir()
    return dict(
        database=database,
        snapshot=snapshot,
        native=native(database),
        saved=saved,
        before=saved.read_bytes(),
        temporary=temporary,
        originals=originals,
    )


def collect(manual, **kwargs):
    with closing(sqlite3.connect(manual["snapshot"])) as conn:
        return observed.collect(
            manual["database"],
            conn,
            manual["temporary"],
            expected_native=manual["native"],
            source_objects=manual["originals"],
            **kwargs,
        )


def content(value):
    return observed.read(value.rows[0], lambda item: value.objects[item["sha256"]].read_bytes())


def test_manual_exact_json_dormant_metadata_and_saved_assets_have_unknown_provenance(manual):
    before = manual["database"].read_bytes()
    value = collect(manual)
    assert value.check() and len(value.rows) == 1
    row = value.rows[0]
    manifest = observed.validate(row)
    assert value.objects[manifest["body"]["sha256"]].read_bytes() == manual["before"]
    result = content(value)
    assert result["raw"] == json.loads(manual["before"])
    assert result["raw"]["figures"][-1]["caption"] == "Full unused caption"
    assert result["raw"]["figures"][-1]["file"] == "C:/private/cache.png"
    assert len(result["raw"]["figures"]) == 3 and len(result["images"]) == 2
    assert result["evidence"] is None and result["input_provenance"] == "unknown"
    assert result["publish"] is False and "request_id" not in row
    assert set(manifest["originals"][0]) == {"sha256", "size"}
    assert manifest["originals"][0]["sha256"] in manual["originals"]
    row["paper_id"] = "caller mutation"
    result["raw"]["title"] = "caller mutation"
    assert value.rows[0]["paper_id"] == "local-paper"
    assert content(value)["raw"]["title"] == "Prior saved deck"
    assert manual["database"].read_bytes() == before
    assert manual["saved"].read_bytes() == manual["before"]


@pytest.mark.parametrize("change", ["json", "asset", "original", "native", "parent", "roster"])
def test_changed_actual_content_or_native_parent_rejects_final_publication(manual, change):
    value = collect(manual)
    if change == "json":
        raw = json.loads(manual["before"])
        raw["title"] = "Actual newer manual edit"
        manual["saved"].write_bytes(canonical_json(raw))
    elif change == "asset":
        next((manual["saved"].parent / "assets").glob("*.png")).write_bytes(b"changed PNG")
    elif change == "original":
        next(iter(manual["originals"].values())).write_bytes(b"changed original PDF")
    elif change == "native":
        replacement = manual["database"].with_name("replacement.sqlite")
        shutil.copyfile(manual["database"], replacement)
        assert native(replacement) != manual["native"]
        os.replace(replacement, manual["database"])
    elif change == "parent":
        with closing(sqlite3.connect(manual["database"])) as conn, conn:
            conn.execute("UPDATE papers SET title='Actual newer title' WHERE id='local-paper'")
    else:
        (manual["saved"].parent / "new-unrepresented.txt").write_bytes(b"New source file")
    with pytest.raises((ValueError, OSError)):
        value.check()
    assert not (manual["temporary"] / "published.zip").exists()


def test_actual_native_replacement_during_read_rejects_not_recaptures(manual, monkeypatch):
    original = observed._read
    done = False

    def read(path, maximum, files):
        nonlocal done
        data = original(path, maximum, files)
        if not done:
            done = True
            replacement = manual["database"].with_name("read-replacement.sqlite")
            shutil.copyfile(manual["database"], replacement)
            os.replace(replacement, manual["database"])
        return data

    monkeypatch.setattr(observed, "_read", read)
    with pytest.raises(ValueError, match="replaced"):
        collect(manual)
    assert done and manual["saved"].read_bytes() == manual["before"]


@pytest.mark.parametrize("phase", ["before", "after-read", "after-collect"])
def test_cancelled_manual_capture_is_not_missing_or_success_and_retry_is_exact(
    manual, monkeypatch, phase
):
    allowed = phase != "before"
    original = observed._read

    def read(path, maximum, files):
        nonlocal allowed
        data = original(path, maximum, files)
        if phase == "after-read":
            allowed = False
        return data

    monkeypatch.setattr(observed, "_read", read)
    before = manual["database"].read_bytes()
    if phase == "after-collect":
        value = collect(manual, current=lambda: allowed)
        allowed = False
        with pytest.raises(ValueError, match="cancelled"):
            value.check(current=lambda: allowed)
    else:
        with pytest.raises(ValueError, match="cancelled"):
            collect(manual, current=lambda: allowed)
    assert manual["database"].read_bytes() == before
    assert manual["saved"].read_bytes() == manual["before"]
    monkeypatch.setattr(observed, "_read", original)
    retry = collect(manual)
    assert retry.check() and content(retry)["raw"] == json.loads(manual["before"])


@pytest.mark.parametrize("missing", ["used-png", "declared-unused-png", "original"])
def test_missing_required_saved_bytes_never_claim_complete_manual_archive(manual, missing):
    if missing == "original":
        next(iter(manual["originals"].values())).unlink()
    elif missing == "used-png":
        next((manual["saved"].parent / "assets").glob("*.png")).unlink()
    else:
        raw = json.loads(manual["before"])
        raw["figures"][-1]["asset"] = "a" * 64 + ".png"
        manual["saved"].write_bytes(canonical_json(raw))
    with pytest.raises((ValueError, OSError)):
        collect(manual)
    assert manual["database"].exists()


def test_snapshot_mismatch_rejects_actual_original_scope(manual):
    with closing(sqlite3.connect(manual["snapshot"])) as conn, conn:
        conn.execute("UPDATE papers SET title='Different snapshot' WHERE id='local-paper'")
    with pytest.raises(ValueError, match="snapshot"):
        collect(manual)
    assert manual["saved"].read_bytes() == manual["before"]


@pytest.mark.parametrize("change", ["unknown", "producer", "version", "extra-image", "original"])
def test_closed_format_and_exact_byte_closure_refuse_unsupported_claims(manual, change):
    value = collect(manual)
    row = value.rows[0]
    manifest = json.loads(row["manifest_json"])
    if change == "unknown":
        manifest["writer"] = "sender-authority"
    elif change == "producer":
        manifest["input_provenance"] = "receiver notes produced it"
    elif change == "version":
        manifest["version"] = True
    elif change == "original":
        manifest["originals"] = []
    else:
        manifest["figures"]["invented"] = next(iter(manifest["figures"].values()))
    row["manifest_json"] = canonical_json(manifest).decode()
    with pytest.raises(ValueError):
        observed.read(row, lambda item: value.objects[item["sha256"]].read_bytes())


def test_detached_read_uses_exact_manual_closure_and_rejects_multiple_owners(manual, tmp_path):
    value = collect(manual)
    row = value.rows[0]
    stage = tmp_path / "detached-direct"
    (stage / "objects").mkdir(parents=True)
    for sha, path in value.objects.items():
        shutil.copyfile(path, stage / "objects" / sha)
    observed.restore(stage, {("local-paper", "guide"): row})
    target = (
        stage / "presentations" / hashlib.sha256(b"local-paper").hexdigest()[:24] / "guide.json"
    )
    assert target.read_bytes() == manual["before"]
    token = row["parent_token"]
    rows = [
        (observed.TABLE, row),
        (
            "research_parent_lifecycle",
            dict(kind="paper", entity_id="local-paper", active=1, token=token),
        ),
    ]
    deck, evidence, figures, originals = recovery_decks._snapshot(
        stage / "papers.db", "local-paper", "guide", rows
    )
    assert deck.to_dict() == json.loads(manual["before"])
    assert evidence is None and len(figures) == 2 and len(originals) == 1
    duplicate = copy.deepcopy(row)
    with pytest.raises(ValueError, match="unique"):
        recovery_decks._snapshot(
            stage / "papers.db", "local-paper", "guide", [*rows, (observed.TABLE, duplicate)]
        )
    next((target.parent / "assets").glob("*.png")).write_bytes(b"changed")
    # Normal detached loader separately verifies the projected asset against this closure.
    assert len(observed.references(row)) == 4
