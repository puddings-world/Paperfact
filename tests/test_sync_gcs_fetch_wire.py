"""Real SDK ranged retrieval over in-memory HTTP, with native recovery."""

import hashlib
import io
from urllib.parse import parse_qs, unquote, urlsplit

import google.auth
import pytest
from google.auth.credentials import AnonymousCredentials
from google.cloud.storage.client import Client
from test_sync_authority_backup import state as state
from test_sync_gcs_sdk_wire import Wire
from urllib3.response import HTTPResponse

from paper_daily import sync_admin
from paper_daily import sync_authority_backup as backup
from paper_daily import sync_authority_restore as recovery
from paper_daily import sync_gcs_backup as publication
from paper_daily import sync_gcs_fetch as retrieval
from paper_daily.sync_blob_service import BLOB_CHUNK_BYTES


class DownloadWire(Wire):
    def __init__(self):
        super().__init__()
        self.ranges = []

    def request(self, method, url, data=None, headers=None, **options):
        parsed, query = urlsplit(url), parse_qs(urlsplit(url).query)
        if method == "GET" and (query.get("alt") == ["media"] or "/download/" in parsed.path):
            assert url.startswith("https://storage.googleapis.com/")
            assert not any(key.lower() == "authorization" for key in (headers or {}))
            name = unquote(parsed.path).split("/o/", 1)[1]
            metadata, body = self.objects[name]
            assert query["ifGenerationMatch"] == [metadata["generation"]]
            interval = next(value for key, value in headers.items() if key.lower() == "range")
            start, end = map(int, interval.removeprefix("bytes=").split("-"))
            selected = body[start : end + 1]
            self.ranges.append((name, start, end))
            response = self.response(
                method,
                url,
                206,
                {},
                {
                    "Content-Range": f"bytes {start}-{end}/{len(body)}",
                    "Content-Length": str(len(selected)),
                    "Content-Type": "application/octet-stream",
                    "x-goog-generation": metadata["generation"],
                },
            )
            response._content = selected
            response.raw = HTTPResponse(
                body=io.BytesIO(selected), headers=response.headers, preload_content=False
            )
            return response
        return super().request(method, url, data=data, headers=headers, **options)


@pytest.mark.parametrize("large", [False, True])
def test_real_sdk_publish_download_verify_and_restore_use_no_credentials_or_socket(
    state, tmp_path, monkeypatch, large
):
    monkeypatch.setattr(google.auth, "default", lambda *_a, **_k: pytest.fail("No ADC"))
    monkeypatch.delenv("STORAGE_EMULATOR_HOST", raising=False)
    wire = DownloadWire()
    client = Client(
        project="fixture-project",
        credentials=AnonymousCredentials(),
        _http=wire,
        client_options={"api_endpoint": "https://storage.googleapis.com"},
    )
    snapshot, output = tmp_path / "snapshot", tmp_path / "retrieved"
    if large:
        body = b"verified multi-range object\n" * 100_000
        declared = {"sha256": hashlib.sha256(body).hexdigest(), "size": len(body)}
        upload = state[1].blob_begin(state[2], declared)
        for start in range(0, len(body), BLOB_CHUNK_BYTES):
            state[1].blob_append(
                state[2], upload["upload_id"], start, body[start : start + BLOB_CHUNK_BYTES]
            )
        state[1].blob_commit(state[2], upload["upload_id"])
    backup.export(state[0], snapshot)
    try:
        receipt = publication.publish(snapshot, "fixture-private-backups", client=client)
        result = retrieval.fetch(
            "fixture-private-backups", receipt["snapshot_sha256"], output, client=client
        )
        assert result["state"] == "downloaded_verified"
        assert wire.ranges and all(end - start + 1 <= backup.CHUNK for _, start, end in wire.ranges)
        assert backup.verify(output)["files"] == (3 if large else 2)
        restored = tmp_path / "fresh-authority"
        restored_receipt = recovery.restore(output, restored, "workspace-a", "fresh-workspace")
        assert restored_receipt["state"] == "restored"
        fresh = sync_admin.authority(restored)
        assert fresh.path != state[1].path
        with pytest.raises(PermissionError):
            fresh.session_info(state[2])
        token = fresh.enroll("fresh-workspace", "new-mac")
        assert len(fresh.pull(token)) == 3
        assert fresh.pull(token)[2]["outcome"] == "conflict"
        assert fresh.blob_read(token, state[3]["sha256"], state[3]["size"], 0) == state[4]
        if large:
            selected = [
                (start, end)
                for name, start, end in wire.ranges
                if name.endswith(declared["sha256"])
            ]
            assert len(selected) > 1 and selected[0][0] == 0
            assert selected[-1][1] == len(body) - 1
            assert (
                fresh.blob_read(token, declared["sha256"], declared["size"], 0)
                == body[:BLOB_CHUNK_BYTES]
            )
        assert (output / backup.MANIFEST).read_bytes() == (snapshot / backup.MANIFEST).read_bytes()
    finally:
        client.close()
    assert wire.closed
