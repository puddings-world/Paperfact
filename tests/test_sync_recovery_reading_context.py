"""Retained explanation links resolve exact source context without mutation or AI."""

from copy import deepcopy

import pytest
from test_sync_device_recovery import dump
from test_sync_recovery_highlight_group import group as _highlights
from test_sync_recovery_highlight_group import original_group as original_group
from test_sync_recovery_highlight_group import positioned as positioned
from test_sync_recovery_target import codec as codec
from test_sync_recovery_target import pair as pair
from test_workspace_dialog import app as app
from test_workspace_dialog import wait

from paper_daily import llm, reading_links
from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_reading_context as context
from paper_daily.sync_authority_backup import BackupCancelled
from paper_daily.sync_content import content_id

highlights = _highlights


@pytest.fixture
def group(highlights):
    value = dict(highlights)
    old = value["old"]
    scope = dict(kind="paper", id=value["root"]["payload"]["scope"]["id"])
    inputs = []
    for feature, body in [
        ("dive", "# Research problem\nThe original problem and assumptions."),
        ("close_reading", "# Controlled study\nThe comparison and limitations."),
    ]:
        payload = dict(
            scope=scope,
            feature=feature,
            key="main",
            source_document_hash=value["sha"],
            data=dict(body=body, written_at="2026-11-14T00:00:00+00:00", spec="fixture"),
        )
        operation = old.new_graph_operation(
            "research_content", content_id(scope, feature, "main"), payload
        )
        old.save(operation)
        inputs.append(operation)
    value["inputs"] = inputs + [value["root"]]
    return linked(value)


def linked(group, *, bodies=None, damage=None):
    old, previous = group["old"], group["source"]
    inputs = group["inputs"]
    bodies = bodies or [o["payload"]["data"]["body"] for o in inputs[:2]]
    parts = reading_links.sections(*bodies)
    analysis = inputs[2]["payload"]["data"]
    sha = reading_links._key(
        parts, dict(analysis["body_json"], source_hash=analysis["source_hash"])
    )
    body = dict(
        links=[
            dict(
                quote=0,
                section=parts[0]["id"],
                explanation="This original quotation explains the stated experimental condition.",
            )
        ],
        analysis_hash=analysis["source_hash"],
    )
    payload = dict(
        scope=inputs[2]["payload"]["scope"],
        feature="reading_links",
        key="main",
        source_document_hash=group["sha"],
        data=dict(
            body_json=body,
            source_hash=sha,
            document_hash=group["sha"],
            written_at="2026-11-14T00:00:00+00:00",
        ),
    )
    if damage:
        damage(payload)
    root = old.new_graph_operation(
        "research_content", content_id(payload["scope"], "reading_links", "main"), payload
    )
    old.save(root)
    source = candidates.prepare(old.journal.path, previous.snapshot, previous.workspace)
    change = next(
        r["change_id"] for r in source.page()["items"] if r["operation_id"] == root["operation_id"]
    )
    return dict(group, source=source, change=change, root=root)


def refreshed(group):
    previous = group["source"]
    source = candidates.prepare(group["old"].journal.path, previous.snapshot, previous.workspace)
    change = next(
        r["change_id"]
        for r in source.page()["items"]
        if r["operation_id"] == group["root"]["operation_id"]
    )
    return dict(group, source=source, change=change)


def resolve(group, **kwargs):
    return context.resolve(group["source"], group["change"], **kwargs)


def test_exact_current_context_and_original_are_read_only_and_never_capture_an_ai_route(
    group,
    monkeypatch,
):
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("Context called AI"))
    monkeypatch.setattr(llm, "capture_connections", lambda: pytest.fail("Context captured AI"))
    before = dump(group["old"].journal.path), dump(group["path"])
    result = resolve(group)
    assert result["state"] == "resolved_read_only" and not result["write_authority"]
    assert result["original_hash"] == group["sha"] and result["link_count"] == 1
    assert [m["operation"] for m in result["members"][:3]] == group["inputs"]
    assert result["members"][-1]["operation"] == group["root"]
    assert (dump(group["old"].journal.path), dump(group["path"])) == before


def test_historical_sections_and_quote_order_survive_newer_edits_and_source_deletion(group):
    old = group["old"]
    for operation in group["inputs"][:2]:
        payload = deepcopy(operation["payload"])
        payload["data"]["body"] += "\nA later interpretation with a different section context."
        old.save(old.new_graph_operation("research_content", operation["entity_id"], payload))
    old.save(
        old.new_graph_operation(
            "research_content", group["inputs"][2]["entity_id"], {}, action="delete"
        )
    )
    group = refreshed(group)
    before = dump(old.journal.path)
    result = resolve(group)
    assert [m["operation"] for m in result["members"][:3]] == group["inputs"]
    assert dump(old.journal.path) == before


def test_a_known_absent_dive_remains_absent_and_close_section_ids_are_not_shifted(group):
    old = group["old"]
    old.save(
        old.new_graph_operation(
            "research_content", group["inputs"][0]["entity_id"], {}, action="delete"
        )
    )
    group = linked(group, bodies=[None, group["inputs"][1]["payload"]["data"]["body"]])
    result = resolve(group)
    assert result["members"][0]["operation"] is None and result["members"][0]["data"] is None
    assert result["members"][-1]["data"]["body_json"]["links"][0]["section"] == "close:0"


@pytest.mark.parametrize("damage", ["digest", "index", "cancel", "budget", "result_budget"])
def test_unproved_or_over_budget_context_returns_no_partial_context(group, monkeypatch, damage):
    if damage in {"digest", "index"}:

        def corrupt(payload):
            if damage == "digest":
                payload["data"]["source_hash"] = "f" * 64
            else:
                payload["data"]["body_json"]["links"][0]["quote"] = 31

        group = linked(group, damage=corrupt)
    elif damage == "budget":
        original = group["inputs"][0]
        payload = deepcopy(original["payload"])
        payload["data"]["body"] = "# New context\nNew words."
        group["old"].save(
            group["old"].new_graph_operation("research_content", original["entity_id"], payload)
        )
        group = refreshed(group)
        monkeypatch.setattr(context, "MAX_COMBINATIONS", 1)
    if damage == "result_budget":
        monkeypatch.setattr(context, "MAX_CONTEXT_BYTES", 1)
    before = dump(group["old"].journal.path), dump(group["path"])
    with pytest.raises(BackupCancelled if damage == "cancel" else ValueError):
        resolve(group, cancelled=lambda: damage == "cancel")
    assert (dump(group["old"].journal.path), dump(group["path"])) == before


@pytest.mark.parametrize("accepted", [True, False])
def test_only_accepted_foreign_history_can_supply_a_missing_link_input(
    group, pair, tmp_path, accepted
):
    from paper_daily import sync_admin

    service = sync_admin.authority(tmp_path / "marked-authority")
    sender = pair[2]
    token = service.enroll("workspace", "b")
    payload = deepcopy(group["inputs"][0]["payload"])
    payload["data"]["body"] = "# Foreign explanation\nA specific retained peer interpretation."
    if not accepted:
        other = deepcopy(payload)
        other["data"]["body"] = "# Accepted other version\nThis is a different interpretation."
        assert (
            service.push(
                token,
                sender.new_graph_operation(
                    "research_content", group["inputs"][0]["entity_id"], other
                ),
            )["outcome"]
            == "accepted"
        )
    operation = sender.new_graph_operation(
        "research_content", group["inputs"][0]["entity_id"], payload
    )
    assert service.push(token, operation)["outcome"] == ("accepted" if accepted else "conflict")
    group["old"].receive(service.pull(token, after=group["old"].status()["cursor"]))
    group = linked(
        group, bodies=[payload["data"]["body"], group["inputs"][1]["payload"]["data"]["body"]]
    )
    before = dump(group["old"].journal.path)
    if accepted:
        result = resolve(group)
        assert result["members"][0]["operation"] == operation
    else:
        with pytest.raises(ValueError, match="No native history matches"):
            resolve(group)
    assert dump(group["old"].journal.path) == before


@pytest.mark.parametrize("language,bad_digest", [("en", False), ("zh-TW", False), ("en", True)])
def test_native_review_shows_verified_link_context_without_enabling_group_publication(
    group,
    app,
    language,
    bad_digest,
):
    from paper_daily.desktop.workspace_dialog import WorkspaceDialog

    if bad_digest:
        group = linked(group, damage=lambda payload: payload["data"].update(source_hash="f" * 64))
    owner = WorkspaceDialog(group["old"].journal.path, language=language)
    owner.show()
    try:
        wait(app, lambda: owner._ready and not owner.busy)
        owner.task_tabs.setCurrentIndex(2)
        owner.device_review.disclosure.setChecked(True)
        ui = owner.device_review.changes
        assert owner.device_review.inspect(group["source"].snapshot)
        wait(app, lambda: not owner.busy)
        assert ui.load(group["path"].parent)
        wait(app, lambda: not owner.busy)
        selected = next(
            row["change_id"]
            for row in ui.page["items"]
            if row["operation_id"] == group["root"]["operation_id"]
        )
        for index in range(ui.rows.count()):
            ui.rows.setCurrentRow(index)
            if ui.selected() == selected:
                break
        before = dump(group["old"].journal.path), dump(group["path"])
        assert ui.compare()
        wait(app, lambda: not owner.busy)
        assert "This original quotation explains" in ui.old.toPlainText()
        if bad_digest:
            assert "No native history matches" in ui.notice.text()
        else:
            assert "The original problem and assumptions." in ui.old.toPlainText()
            assert "The comparison and limitations." in ui.old.toPlainText()
            assert "New post-backup source evidence" in ui.old.toPlainText()
            assert "body_json" not in ui.old.toPlainText()
            if language == "zh-TW":
                assert "\u5df2\u6838\u5c0d" in ui.notice.text()
            else:
                assert "Comparison only" in ui.notice.text()
        assert not ui.copy_button.isEnabled()
        assert (dump(group["old"].journal.path), dump(group["path"])) == before
    finally:
        if owner.busy:
            owner.cancel()
            wait(app, lambda: not owner.busy)
        owner.close()
        app.processEvents()
