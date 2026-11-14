"""Read and re-export real imported scientific/original closure; no AI or new grants."""

import json
import shutil
import sqlite3
import zipfile
from contextlib import closing
from dataclasses import replace
from uuid import uuid4

import pytest
from lineage_package_fixture import lineage_archive as lineage_archive
from test_lineage_jobs import work
from test_lineage_package_publish import apply
from test_lineage_package_publish import incoming as incoming
from test_lineage_package_transaction import seed_in
from test_lineage_packages import package
from test_research_evidence import pdf

from paper_daily import lineage_import_originals as originals
from paper_daily import lineage_package_publish as publisher
from paper_daily import lineage_package_targets as targets
from paper_daily import (
    lineage_packages,
    lineage_sets,
    llm,
    research_generation,
    store,
)
from paper_daily.manual_highlight_ops import observe_owner
from paper_daily.research_lifecycle import ensure_lifecycle


@pytest.fixture
def loaded(incoming, monkeypatch):
    work(apply, incoming)
    owner = observe_owner(incoming[0], "receiver-focal", expected_native=incoming[1])
    row = lineage_sets.saved(incoming[0], "receiver-focal")[0]
    monkeypatch.setattr(
        llm, "complete_result", lambda *_a, **_k: pytest.fail("Saved-only read/export")
    )
    return incoming, owner, row


def source(row, index=1):
    return lineage_sets.decode(row["body_json"])["report"]["sources"][index]


@pytest.mark.parametrize("index", [0, 1, 2])
def test_actual_focal_and_peer_originals_read_without_database_write_or_ai(loaded, index):
    incoming, owner, row = loaded
    selected = source(row, index)
    before = incoming[0].read_bytes()
    snapshot = work(originals.prepare, owner, row, selected["id"])
    assert snapshot.paper_id == ["receiver-focal", "receiver-prior", "receiver-later"][index]
    assert snapshot.document_hash == selected["document_hash"]
    assert originals.metadata_current(snapshot)
    expected = next(
        data
        for path, data in incoming[4].files
        if path.endswith(selected["document_hash"] + ".pdf")
    )
    assert originals.for_delivery(snapshot, owner, row, selected["id"]) == expected
    assert incoming[0].read_bytes() == before
    if index == 0:
        from paper_daily import audit_lineage

        audit = work(audit_lineage.prepare, owner, row)
        report = audit.for_delivery(owner, row)
        assert report["originals_checked"] == report["originals_total"] == 3
        assert all(source["state"] == "available" for source in report["sources"])
        assert incoming[0].read_bytes() == before



def test_current_primary_pdf_is_never_substituted_for_saved_imported_original(loaded):
    incoming, owner, row = loaded
    selected = source(row, 0)
    current = incoming[0].parent / "pdf" / "receiver-focal.pdf"
    pdf(current, [["A different current primary document."]])
    newer = current.read_bytes()
    snapshot = work(originals.prepare, owner, row, selected["id"])
    assert originals.for_delivery(snapshot, owner, row, selected["id"]) != newer
    assert snapshot.document_hash == selected["document_hash"]
    assert current.read_bytes() == newer


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_id", "0" * 64),
        ("paper_id", "foreign"),
        ("document_hash", "0" * 64),
        ("_data", b"different immutable bytes"),
    ],
)
def test_forged_public_identity_or_bytes_cannot_deliver(loaded, field, value):
    _incoming, owner, row = loaded
    selected = source(row)
    snapshot = work(originals.prepare, owner, row, selected["id"])
    changed = replace(snapshot, **{field: value})
    assert not originals.metadata_current(changed)
    with pytest.raises(ValueError, match="native verified snapshot"):
        originals.for_delivery(changed, owner, row, selected["id"])


@pytest.mark.parametrize(
    "change",
    [
        "science-row",
        "import-receipt",
        "source-association",
        "peer-lifetime",
        "focal-lifetime",
        "database",
        "binding",
        "file",
        "file-restored",
    ],
)
def test_pending_original_cannot_deliver_after_source_or_native_ownership_changes(loaded, change):
    incoming, owner, row = loaded
    selected = source(row)
    snapshot = work(originals.prepare, owner, row, selected["id"])
    if change == "database":
        replacement = incoming[0].with_name("replacement.sqlite")
        shutil.copyfile(incoming[0], replacement)
        replacement.replace(incoming[0])
    elif change in ("file", "file-restored"):
        data = snapshot._source.read_bytes()
        snapshot._source.write_bytes(b"different original bytes")
        if change == "file-restored":
            snapshot._source.write_bytes(data)
    else:
        with closing(sqlite3.connect(incoming[0])) as conn, conn:
            if change == "science-row":
                conn.execute("UPDATE paper_lineage_sets SET written_at='2026-10-01T00:00:00+00:00'")
            elif change == "import-receipt":
                conn.execute("UPDATE research_lineage_imports SET body_json='{}'")
            elif change == "source-association":
                conn.execute("DELETE FROM research_local_source_owners")
            elif change in ("peer-lifetime", "focal-lifetime"):
                identity = "receiver-prior" if change == "peer-lifetime" else "receiver-focal"
                saved = conn.execute("SELECT * FROM papers WHERE id=?", (identity,)).fetchone()
                conn.execute("DELETE FROM papers WHERE id=?", (identity,))
                conn.execute(
                    "INSERT INTO papers VALUES(" + ",".join("?" for _ in saved) + ")", saved
                )
            else:
                conn.execute("CREATE TABLE paperfact_sync_identity(workspace TEXT,device TEXT)")
                conn.execute("INSERT INTO paperfact_sync_identity VALUES('bound','fixture')")
    assert not originals.metadata_current(snapshot)
    with pytest.raises(ValueError, match="view changed"):
        originals.for_delivery(snapshot, owner, row, selected["id"])
    if change in ("peer-lifetime", "focal-lifetime", "database"):
        fresh = observe_owner(
            incoming[0],
            "receiver-focal",
            expected_native=research_generation._identity(incoming[0]),
        )
        with pytest.raises(ValueError):
            work(originals.prepare, fresh, row, selected["id"])


def test_missing_declared_pdf_refuses_and_does_not_fall_back_to_current_primary(loaded):
    _incoming, owner, row = loaded
    selected = source(row, 0)
    snapshot = work(originals.prepare, owner, row, selected["id"])
    snapshot._source.unlink()
    pdf(
        owner.database.parent / "pdf" / "receiver-focal.pdf",
        [["A different primary is available."]],
    )
    with pytest.raises(ValueError, match="missing or changed"):
        work(originals.prepare, owner, row, selected["id"])


def test_wrong_or_equivalent_reloaded_view_does_not_receive_old_snapshot(loaded):
    _incoming, owner, row = loaded
    selected = source(row)
    snapshot = work(originals.prepare, owner, row, selected["id"])
    equivalent = observe_owner(
        owner.database,
        owner.paper_id,
        expected_native=research_generation._identity(owner.database),
    )
    assert equivalent == owner and equivalent is not owner
    with pytest.raises(ValueError, match="view changed"):
        originals.for_delivery(snapshot, equivalent, row, selected["id"])
    with pytest.raises(ValueError, match="outside the displayed corpus"):
        work(originals.prepare, owner, row, "0" * 64)
    with pytest.raises(ValueError, match="actual loaded paper owner"):
        work(originals.prepare, None, row, selected["id"])


def test_cancel_before_and_after_byte_verification_creates_no_receipt(loaded, monkeypatch):
    incoming, owner, row = loaded
    before = incoming[0].read_bytes()
    assert work(originals.prepare, owner, row, source(row)["id"], cancelled=lambda: True) is None
    read = originals.owners._read_pdf
    done = False

    def after_read(*args, **kwargs):
        nonlocal done
        result = read(*args, **kwargs)
        done = True
        return result

    monkeypatch.setattr(originals.owners, "_read_pdf", after_read)
    assert work(originals.prepare, owner, row, source(row)["id"], cancelled=lambda: done) is None
    assert incoming[0].read_bytes() == before


@pytest.mark.parametrize("change", ["view", "history-budget", "malformed", "wrong-records"])
def test_import_receipt_lookup_refuses_invalid_history_without_source_fallback(
    loaded, change, monkeypatch
):
    incoming, owner, row = loaded
    if change == "history-budget":
        monkeypatch.setattr(publisher, "MAX_HISTORY", 1)
    else:
        with closing(sqlite3.connect(incoming[0])) as conn, conn:
            if change == "view":
                conn.execute("ALTER TABLE research_lineage_imports RENAME TO archived_imports")
                conn.execute(
                    "CREATE VIEW research_lineage_imports AS SELECT * FROM archived_imports"
                )
            elif change == "wrong-records":
                body = json.loads(
                    conn.execute("SELECT body_json FROM research_lineage_imports").fetchone()[0]
                )
                body["records"] = ["not an encoded report object"]
                conn.execute("UPDATE research_lineage_imports SET body_json=?", (json.dumps(body),))
            else:
                conn.execute("UPDATE research_lineage_imports SET body_json='not JSON'")
    before = incoming[0].read_bytes()
    with pytest.raises(ValueError):
        originals.has_record(owner.database, row)
    with pytest.raises(ValueError):
        work(lineage_packages.collect, owner.database, [owner.paper_id])
    assert incoming[0].read_bytes() == before


def test_actual_import_reexports_all_exact_sources_and_third_receiver_can_read(loaded, tmp_path):
    incoming, owner, row = loaded
    before = incoming[0].read_bytes()
    prepared = work(lineage_packages.collect, owner.database, [owner.paper_id])
    assert prepared.rows == [row]
    assert {kind for kind, _snapshot in prepared._proofs} == {"import"}
    output = tmp_path / "reexport.zip"
    manifest, tables = package(prepared, output, focal_ids=(owner.paper_id,))
    with zipfile.ZipFile(output) as archive:
        assert lineage_packages.validate_package(archive, manifest, tables) == [row]
        validated = work(targets.validate, archive, manifest, tables)
        raw = archive.read("tables.json") + archive.read("manifest.json")
    assert b"parent_lifecycle" not in raw and b"database_identity" not in raw
    assert b"request_id" not in raw and b"owner_json" not in raw
    assert incoming[0].read_bytes() == before
    work(lineage_packages.check_export, prepared)
    receiver = tmp_path / "third" / "papers.db"
    receiver.parent.mkdir()
    with closing(sqlite3.connect(receiver)) as conn:
        conn.executescript(store.SCHEMA)
        conn.execute("BEGIN IMMEDIATE")
        ensure_lifecycle(conn)
        conn.commit()
    native = research_generation._identity(receiver)
    papers = tables["papers"] + tables["cited_papers"]
    mapping = {p["id"]: p["id"].replace("receiver-", "third-") for p in papers}
    staged = work(
        publisher.stage,
        receiver,
        validated,
        mapping,
        request_id=str(uuid4()),
        expected_native=native,
    )

    def import_third():
        with closing(sqlite3.connect(receiver)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            seed_in(conn, papers, mapping)
            observed = targets.observe_in(conn, validated, mapping, expected_native=native)
            publisher.publish_in(conn, staged, observed)
            conn.commit()

    work(import_third)
    third_owner = observe_owner(receiver, "third-focal", expected_native=native)
    third_row = lineage_sets.saved(receiver, third_owner.paper_id)[0]
    assert (
        lineage_sets.decode(third_row["body_json"])["report"]
        == lineage_sets.decode(row["body_json"])["report"]
    )
    for index in range(3):
        selected = source(third_row, index)
        read = work(originals.prepare, third_owner, third_row, selected["id"])
        assert originals.for_delivery(read, third_owner, third_row, selected["id"]) == next(
            data
            for path, data in validated.files
            if path.endswith(selected["document_hash"] + ".pdf")
        )


def test_source_metadata_change_after_collect_refuses_final_export(loaded):
    incoming, owner, row = loaded
    prepared = work(lineage_packages.collect, owner.database, [owner.paper_id])
    with closing(sqlite3.connect(incoming[0])) as conn, conn:
        conn.execute("DELETE FROM research_local_source_owners")
    with pytest.raises(ValueError, match="original ownership changed"):
        work(lineage_packages.check_export, prepared)


def empty_receiver(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(store.SCHEMA)
        conn.execute("BEGIN IMMEDIATE")
        ensure_lifecycle(conn)
        conn.commit()
    return research_generation._identity(path)


def import_archive(path, receiver, *, prefix):
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        tables = json.loads(archive.read("tables.json"))
        validated = work(targets.validate, archive, manifest, tables)
    native = empty_receiver(receiver)
    papers = tables["papers"] + tables["cited_papers"]
    mapping = {p["id"]: prefix + p["id"] for p in papers}
    staged = work(
        publisher.stage,
        receiver,
        validated,
        mapping,
        request_id=str(uuid4()),
        expected_native=native,
    )

    def publish():
        with closing(sqlite3.connect(receiver)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            seed_in(conn, papers, mapping)
            observed = targets.observe_in(conn, validated, mapping, expected_native=native)
            publisher.publish_in(conn, staged, observed)
            conn.commit()

    work(publish)
    return native, validated


def test_unrelated_coimported_report_lifetime_does_not_invalidate_the_selected_corpus(
    lineage_archive, tmp_path
):
    with zipfile.ZipFile(lineage_archive) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        tables = json.loads(archive.read("tables.json"))
        files = {
            name.removeprefix("files/"): archive.read(name)
            for name in archive.namelist()
            if name.startswith("files/")
        }
    original_row = tables["paper_lineage_sets"][0]
    second_body = lineage_sets.decode(original_row["body_json"])
    second_body["corpus_id"] = str(uuid4())
    for binding in second_body["bindings"]:
        binding["paper_id"] = "other-" + binding["paper_id"]
    second_row = dict(
        original_row,
        paper_id="other-focal",
        corpus_key=second_body["corpus_id"],
        body_json=lineage_sets.canonical(second_body),
        source_hash=lineage_sets.source_hash(second_body),
    )
    tables["paper_lineage_sets"].append(second_row)
    for key in ("papers", "cited_papers"):
        tables[key].extend(
            [
                dict(p, id="other-" + p["id"], title_key="other-" + p["title_key"])
                for p in tables[key]
            ]
        )
    for original in list(manifest["lineage_sources"]):
        item = dict(
            original,
            focal_paper_id="other-" + original["focal_paper_id"],
            paper_id="other-" + original["paper_id"],
            corpus_key=second_body["corpus_id"],
        )
        item["path"] = lineage_packages.relative(
            item["focal_paper_id"], item["paper_id"], item["sha256"]
        ).as_posix()
        files[item["path"]] = files[original["path"]]
        manifest["file_hashes"][item["path"]] = item["sha256"]
        manifest["lineage_sources"].append(item)
    path = tmp_path / "two-corpora.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("tables.json", json.dumps(tables))
        for name, data in files.items():
            archive.writestr("files/" + name, data)
    receiver = tmp_path / "batch" / "papers.db"
    native, _validated = import_archive(path, receiver, prefix="rx-")
    owner = observe_owner(receiver, "rx-focal", expected_native=native)
    row = lineage_sets.saved(receiver, owner.paper_id)[0]
    selected = source(row)
    snapshot = work(originals.prepare, owner, row, selected["id"])
    with closing(sqlite3.connect(receiver)) as conn, conn:
        conn.execute("DELETE FROM papers WHERE id='rx-other-prior'")
    assert originals.metadata_current(snapshot)
    assert originals.for_delivery(snapshot, owner, row, selected["id"]) == snapshot._data
    other_owner = observe_owner(receiver, "rx-other-focal", expected_native=native)
    other_row = lineage_sets.saved(receiver, other_owner.paper_id)[0]
    with pytest.raises(ValueError, match="selected paper lifetime changed"):
        work(originals.prepare, other_owner, other_row, source(other_row)["id"])


def test_saved_unavailable_peer_remains_unavailable_after_import_and_reexport(
    tmp_path, monkeypatch
):
    from test_lineage_publication import publish
    from test_lineage_target_jobs import job_for, observed
    from test_research_lineage import corpus

    from paper_daily import lineage_publication, research_lineage
    from paper_daily.ai_types import Completion

    sender = tmp_path / "sender"
    sender.mkdir()
    captured = corpus.__wrapped__(sender)
    with closing(sqlite3.connect(captured[0])) as conn, conn:
        store._migrate(conn)
    all_sources = research_lineage.capture(
        captured[0], "focal", ["prior", "later", "missing"], legacy_root=captured[1]
    )
    chosen = (captured[0], captured[1], all_sources)
    target = observed(chosen)
    response = json.dumps(
        dict(format=research_lineage.PROPOSALS, focal=all_sources.focal, statements=[])
    )
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: Completion(response))
    job = job_for(chosen, target)
    work(job.run)
    work(publish, captured[0], work(lineage_publication.prepare, job._state.candidate))
    monkeypatch.setattr(
        llm, "complete_result", lambda *_a, **_k: pytest.fail("Saved-only originals")
    )
    export = work(lineage_packages.collect, captured[0], ["focal"])
    path = tmp_path / "missing.zip"
    package(export, path)
    receiver = tmp_path / "receiver" / "papers.db"
    native, _validated = import_archive(path, receiver, prefix="rx-")
    owner = observe_owner(receiver, "rx-focal", expected_native=native)
    row = lineage_sets.saved(receiver, owner.paper_id)[0]
    missing = source(row, 3)
    assert missing["availability"] == "unavailable"
    before = receiver.read_bytes()
    assert work(originals.prepare, owner, row, missing["id"]) is None
    exported = work(lineage_packages.collect, receiver, [owner.paper_id])
    assert len(exported.records) == len(exported.files) == 3
    assert {p["id"] for p in exported.papers} == {"rx-focal", "rx-prior", "rx-later", "rx-missing"}
    assert receiver.read_bytes() == before


def test_mixed_imported_and_locally_generated_corpora_choose_their_own_source_reader(
    loaded, monkeypatch
):
    from uuid import UUID

    import test_lineage_target_jobs
    from test_lineage_recovery import published

    from paper_daily import research_lineage

    incoming, owner, row = loaded
    root = owner.database.parent / "pdf"
    body = lineage_sets.decode(row["body_json"])
    source_bytes = {
        sha: data
        for path, data in incoming[4].files
        for sha in [path.rsplit("/", 1)[1].removesuffix(".pdf")]
    }
    for binding, descriptor in zip(body["bindings"], body["report"]["sources"], strict=True):
        (root / (binding["paper_id"] + ".pdf")).write_bytes(
            source_bytes[descriptor["document_hash"]]
        )
    captured = research_lineage.capture(
        owner.database, owner.paper_id, ["receiver-prior", "receiver-later"], legacy_root=root
    )
    # Force the local corpus after the imported corpus to catch a sticky import dispatch.
    monkeypatch.setattr(
        test_lineage_target_jobs, "uuid4", lambda: UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    )
    published((owner.database, root, captured), monkeypatch)
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("Saved-only export"))
    exported = work(lineage_packages.collect, owner.database, [owner.paper_id])
    assert len(exported.rows) == 2
    assert {kind for kind, _proof in exported._proofs} == {"local", "import"}
    assert len(exported.files) == 3
    work(lineage_packages.check_export, exported)
