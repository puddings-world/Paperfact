import copy
import json
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_sync_transfers import setup as transfer_setup_fixture
from test_workspace_open import destination
from test_workspace_sync import connect
from test_workspace_sync import enrolled as enrolled_fixture
from test_workspace_sync import research as research_fixture
from test_workspace_sync import service as service_fixture
from test_workspace_sync_edges import new_device

from paper_daily import sync_bootstrap
from paper_daily.workspace_service import Ticket

transfer_setup = transfer_setup_fixture
research = research_fixture
enrolled = enrolled_fixture
service = service_fixture
__all__ = ["destination"]


def test_join_rejects_reused_remote_device_identity(service, tmp_path):
    token = new_device(service)
    authority = service[1]
    original = authority.pull(token)[0]["operation"]
    operation = copy.deepcopy(original)
    identifier = str(uuid4())
    operation.update(
        operation_id=identifier,
        incarnation=identifier,
        entity_id=str(uuid4()),
        device_id="new-device",
        depends_on=None,
        base_revision=0,
        structure_revision=0,
    )
    assert authority.push(token, operation)["outcome"] == "accepted"
    with pytest.raises(ValueError, match="unused device"):
        sync_bootstrap.join(service[0], tmp_path / "joined", Ticket())
    assert not (tmp_path / "joined").exists()
    staged = next(tmp_path.glob(".paperfact-join-*/workspace/papers.db"))
    with sqlite3.connect(staged) as conn:
        assert conn.execute("SELECT sequence FROM paperfact_sync_cursor").fetchone() == (0,)


@pytest.mark.parametrize("target", ["", "  ", None])
def test_empty_join_never_creates_stage_or_contacts_private_research(service, tmp_path, target):
    connect(service)
    before = list(service[3])
    with pytest.raises(ValueError):
        sync_bootstrap.join(service[0], target, Ticket())
    assert service[3] == before and not list(tmp_path.glob(".paperfact-join-*"))


def test_malformed_oversized_stage_is_not_adopted(service, tmp_path):
    new_device(service)
    destination = tmp_path / "joined"
    first = sync_bootstrap.join(service[0], destination, Ticket(), max_pages=1)
    stage = next(tmp_path.glob(".paperfact-join-*/request.json"))
    original = stage.read_text(encoding="utf-8")
    stage.write_text("x" * 16385, encoding="utf-8")
    with pytest.raises(ValueError, match="receipt"):
        sync_bootstrap.join(service[0], destination, Ticket())
    assert not destination.exists() and first["state"] == "catching_up"
    malformed = json.loads(original)
    malformed["device_id"] = "different"
    stage.write_text(json.dumps(malformed), encoding="utf-8")
    with pytest.raises(ValueError, match="another request"):
        sync_bootstrap.join(service[0], destination, Ticket())
    stage.write_text(original, encoding="utf-8")
    assert sync_bootstrap.join(service[0], destination, Ticket())["state"] == "metadata_ready"


def test_editable_copy_delivery_retries_failure_and_deduplicates_success(destination):
    from paper_daily.desktop.main import ReaderPage

    messages, calls = [], []
    reader = SimpleNamespace(
        presentation_pane=SimpleNamespace(status=SimpleNamespace(setText=messages.append))
    )

    def launch(value):
        calls.append(value)
        if len(calls) == 1:
            raise OSError("fixture launch error")

    reader._workspace_opener = launch
    assert not ReaderPage._open_created_workspace(reader, destination.payload())
    assert ReaderPage._open_created_workspace(reader, destination.payload())
    assert not ReaderPage._open_created_workspace(reader, destination.payload())
    assert len(calls) == 2 and len(messages) == 2


def test_wrong_workspace_credential_cannot_upload_pdf_bytes(transfer_setup, tmp_path):
    from test_sync_transfers import attach
    from test_workspace_sync import Native
    from test_workspace_sync_files import enable

    from paper_daily.workspace_sync import EnrollmentRequired, SyncSession

    a, _, authority, _, _, _, _, _, _ = transfer_setup
    attach(transfer_setup, tmp_path)
    enable(a)
    other_token = authority.enroll("other-workspace", "a")
    calls = []
    controller = SyncSession(
        a.journal.path, transport_factory=lambda endpoint: Native(endpoint, authority, calls)
    )
    controller.connect("https://fixture.invalid", "other-workspace", "a", other_token, Ticket())
    with pytest.raises(EnrollmentRequired):
        controller.sync(Ticket())
    assert calls == ["session_info", "session_info"]
