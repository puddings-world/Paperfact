"""Real SDK multipart/resumable code over a local in-memory HTTP session only."""

import base64
import hashlib
import json
from email import policy
from email.parser import BytesParser
from urllib.parse import parse_qs, unquote, urlsplit

import google.auth
import google_crc32c
import pytest
import requests
from google.auth.credentials import AnonymousCredentials
from google.cloud.storage.client import Client
from test_sync_authority_backup import state as state

from paper_daily import sync_authority_backup as backup
from paper_daily import sync_gcs_backup as gcs
from paper_daily.sync_blob_service import BLOB_CHUNK_BYTES


def crc(data):
    return base64.b64encode(google_crc32c.Checksum(data).digest()).decode("ascii")


class Wire:
    def __init__(self):
        self.objects, self.sessions, self.calls = {}, {}, []
        self.resumable_chunks = 0
        self.closed = False

    @staticmethod
    def response(method, url, code, value, headers=None):
        response = requests.Response()
        response.status_code = code
        response._content = json.dumps(value).encode("utf-8")
        response.headers.update({"Content-Type": "application/json", **(headers or {})})
        response.url = url
        response.request = requests.Request(method, url).prepare()
        return response

    def stored(self, method, url, metadata, body):
        name = metadata["name"]
        assert name not in self.objects
        expected = metadata.get("crc32c")
        if expected is not None:
            assert expected == crc(body)
        value = {
            "name": name,
            "bucket": "fixture-private-backups",
            "generation": "1",
            "metageneration": "1",
            "size": str(len(body)),
            "crc32c": crc(body),
            "metadata": metadata["metadata"],
            "contentType": metadata["contentType"],
        }
        self.objects[name] = value, body
        return self.response(method, url, 200, value)

    def request(self, method, url, data=None, headers=None, **_options):
        assert url.startswith("https://storage.googleapis.com/")
        assert not any(name.lower() == "authorization" for name in (headers or {}))
        self.calls.append((method, url))
        parsed, query = urlsplit(url), parse_qs(urlsplit(url).query)
        path = unquote(parsed.path)
        if method == "GET" and path == "/storage/v1/b/fixture-private-backups":
            return self.response(
                method,
                url,
                200,
                {
                    "name": "fixture-private-backups",
                    "projectNumber": "123456",
                    "iamConfiguration": {
                        "publicAccessPrevention": "enforced",
                        "uniformBucketLevelAccess": {"enabled": True},
                    },
                },
            )
        if method == "GET" and "/o/" in path:
            name = path.split("/o/", 1)[1]
            if name not in self.objects:
                return self.response(
                    method, url, 404, {"error": {"code": 404, "message": "Absent"}}
                )
            value = self.objects[name][0]
            if "ifGenerationMatch" in query:
                assert query["ifGenerationMatch"] == [value["generation"]]
            return self.response(method, url, 200, value)
        if method == "POST" and query.get("uploadType") == ["multipart"]:
            assert query["ifGenerationMatch"] == ["0"]
            content_type = next(
                value for key, value in headers.items() if key.lower() == "content-type"
            )
            if isinstance(content_type, str):
                content_type = content_type.encode("ascii")
            message = BytesParser(policy=policy.default).parsebytes(
                b"Content-Type: " + content_type + b"\r\n\r\n" + data
            )
            parts = list(message.iter_parts())
            metadata = json.loads(parts[0].get_payload(decode=True))
            metadata["contentType"] = parts[1].get_content_type()
            return self.stored(method, url, metadata, parts[1].get_payload(decode=True))
        if method == "POST" and query.get("uploadType") == ["resumable"]:
            assert query["ifGenerationMatch"] == ["0"]
            key = str(len(self.sessions))
            metadata = json.loads(data)
            metadata["contentType"] = next(
                value for name, value in headers.items() if name.lower() == "x-upload-content-type"
            )
            self.sessions[key] = metadata, bytearray()
            location = f"https://storage.googleapis.com/fake-resumable/{key}"
            return self.response(method, url, 200, {}, {"Location": location})
        if method == "PUT" and path.startswith("/fake-resumable/"):
            key = path.rsplit("/", 1)[-1]
            metadata, body = self.sessions[key]
            ranges = next(
                value for name, value in headers.items() if name.lower() == "content-range"
            )
            if isinstance(ranges, bytes):
                ranges = ranges.decode("ascii")
            offsets, total = ranges.removeprefix("bytes ").split("/")
            start, end = map(int, offsets.split("-"))
            assert len(body) == start and len(data) == end - start + 1
            body.extend(data)
            self.resumable_chunks += 1
            if end + 1 == int(total):
                return self.stored(method, url, metadata, bytes(body))
            return self.response(method, url, 308, {}, {"Range": f"bytes=0-{end}"})
        raise AssertionError(f"Unexpected SDK request shape: {method} {path}")

    def close(self):
        self.closed = True


@pytest.mark.parametrize("large", [False, True])
def test_real_sdk_transmits_exact_snapshot_through_multipart_and_resumable(
    state, tmp_path, monkeypatch, large
):
    root, authority, token, _manifest, _data = state
    monkeypatch.setattr(google.auth, "default", lambda *_a, **_k: pytest.fail("No ADC"))
    monkeypatch.delenv("STORAGE_EMULATOR_HOST", raising=False)
    if large:
        data = b"large verified fixture object\n" * 330_000
        declared = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        upload = authority.blob_begin(token, declared)
        for start in range(0, len(data), BLOB_CHUNK_BYTES):
            authority.blob_append(
                token, upload["upload_id"], start, data[start : start + BLOB_CHUNK_BYTES]
            )
        authority.blob_commit(token, upload["upload_id"])
    snapshot = tmp_path / "sdk-wire-snapshot"
    backup.export(root, snapshot)
    wire = Wire()
    client = Client(
        project="fixture-project",
        credentials=AnonymousCredentials(),
        _http=wire,
        client_options={"api_endpoint": "https://storage.googleapis.com"},
    )
    try:
        result = gcs.publish(snapshot, "fixture-private-backups", client=client)
        assert result["state"] == "published"
        remote = result["remote_prefix"].split("fixture-private-backups/", 1)[1]
        manifest = wire.objects[remote + "/manifest.json"][1]
        assert manifest == (snapshot / backup.MANIFEST).read_bytes()
        expected = json.loads(manifest)
        for entry in expected["files"]:
            key = gcs.PREFIX + "/objects/" + entry["sha256"]
            assert wire.objects[key][1] == (snapshot / entry["path"]).read_bytes()
        assert wire.resumable_chunks > 1 if large else wire.resumable_chunks == 0
    finally:
        client.close()
    assert wire.closed
