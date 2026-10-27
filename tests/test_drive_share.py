import json

import httpx
import pytest

from paper_daily import bundle_links, drive_share, store

CLIENT = httpx.Client
SESSION_URL = "https://www.googleapis.com/upload/drive/v3/files?upload_id=s1"


class Drive:
    """A fake Drive that keeps what a resumable session received."""

    def __init__(self):
        self.requests = []
        self.received = b""
        self.files = {"OLD": b"previous"}
        self.permissions = []
        self.accept_at_most = None
        self.drop_next_put = False

    def __call__(self, request):
        self.requests.append(request)
        url = str(request.url)
        if request.method == "POST" and "uploadType=resumable" in url:
            return httpx.Response(200, headers={"location": SESSION_URL})
        if request.method == "PATCH":
            file_id = request.url.path.rsplit("/", 1)[1]
            if file_id not in self.files:
                return httpx.Response(404)
            return httpx.Response(200, headers={"location": SESSION_URL + "&f=" + file_id})
        if request.method == "PUT":
            span = request.headers["content-range"]
            if self.drop_next_put and request.content:
                self.drop_next_put = False
                return httpx.Response(503)
            total = int(span.rsplit("/", 1)[1])
            if span.startswith("bytes */"):
                pass
            else:
                start = int(span.split()[1].split("-")[0])
                chunk = request.content
                if self.accept_at_most is not None:
                    chunk = chunk[: self.accept_at_most]
                self.received = self.received[:start] + chunk
            if len(self.received) < total:
                headers = {"range": f"bytes=0-{len(self.received) - 1}"} if self.received else {}
                return httpx.Response(308, headers=headers)
            file_id = url.split("&f=")[1] if "&f=" in url else "NEW"
            self.files[file_id] = self.received
            return httpx.Response(200, json={"id": file_id})
        if request.method == "DELETE" and "upload_id" in url:
            return httpx.Response(499)
        if "/permissions" in url:
            if request.method == "DELETE":
                self.permissions.append(("remove", request.url.path.rsplit("/", 1)[1]))
                return httpx.Response(204)
            body = json.loads(request.content)
            self.permissions.append((body["type"], body.get("emailAddress")))
            return httpx.Response(200, json={"id": "p"})
        return httpx.Response(500)


class Google:
    def access_token(self):
        return "token"


@pytest.fixture
def drive(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    fake = Drive()
    monkeypatch.setattr(drive_share, "_client", lambda: CLIENT(transport=httpx.MockTransport(fake)))
    monkeypatch.setattr(drive_share, "CHUNK", 4)
    package = tmp_path / "package.zip"
    package.write_bytes(b"0123456789")
    return fake, package


def test_new_share_uploads_every_byte_and_invites_each_reader(drive):
    fake, package = drive
    seen = []
    result = drive_share.publish(
        "cat",
        package,
        Google(),
        name="Cataract.paperfact.zip",
        emails=["a@x.org", "b@y.org"],
        anyone=False,
        progress=lambda done, total: seen.append((done, total)),
    )
    assert fake.files["NEW"] == package.read_bytes()
    assert result["file_id"] == "NEW" and not result["replaced"]
    assert fake.permissions == [("user", "a@x.org"), ("user", "b@y.org")]
    # Invited readers open the Drive page; only a public file can be fetched directly.
    assert result["link"] == drive_share.view_url("NEW")
    assert seen[-1] == (10, 10) and [d for d, _ in seen] == sorted(d for d, _ in seen)
    assert drive_share.previous("cat") == {
        "file_id": "NEW",
        "anyone": False,
        "emails": ["a@x.org", "b@y.org"],
    }


def test_sharing_again_replaces_the_same_file_so_the_link_keeps_working(drive):
    fake, package = drive
    drive_share.publish("cat", package, Google(), name="n", emails=["a@x.org"], anyone=False)
    package.write_bytes(b"new contents")
    result = drive_share.publish("cat", package, Google(), name="n", emails=[], anyone=True)
    assert result["replaced"] and result["file_id"] == "NEW"
    assert fake.files["NEW"] == b"new contents"
    assert any(r.method == "PATCH" for r in fake.requests)
    assert ("anyone", None) in fake.permissions
    assert result["link"] == (
        bundle_links.drive_download_url("NEW")
        + "#paperfact-sha256="
        + bundle_links.file_digest(package)
    )
    # Earlier readers keep their access, so the record still names them.
    assert result["emails"] == ["a@x.org"]


def test_narrowing_a_public_share_removes_the_public_link(drive):
    fake, package = drive
    drive_share.publish("cat", package, Google(), name="n", emails=[], anyone=True)
    drive_share.publish("cat", package, Google(), name="n", emails=["a@x.org"], anyone=False)
    assert ("remove", drive_share.ANYONE) in fake.permissions


def test_a_share_deleted_in_drive_is_uploaded_again_as_a_new_file(drive):
    fake, package = drive
    with store.connect() as conn:
        store.set_kv(conn, "drive.share.cat", {"file_id": "GONE", "anyone": True, "emails": []})
        conn.commit()
    result = drive_share.publish("cat", package, Google(), name="n", emails=[], anyone=True)
    assert result["file_id"] == "NEW" and not result["replaced"]
    # The old public grant belonged to the deleted file; nothing to revoke.
    assert ("remove", drive_share.ANYONE) not in fake.permissions


def test_upload_resumes_from_what_drive_kept(drive):
    fake, package = drive
    fake.accept_at_most = 3
    drive_share.publish("cat", package, Google(), name="n", emails=["a@x.org"], anyone=False)
    assert fake.files["NEW"] == package.read_bytes()


def test_upload_survives_a_dropped_chunk(drive):
    fake, package = drive
    fake.drop_next_put = True
    drive_share.publish("cat", package, Google(), name="n", emails=["a@x.org"], anyone=False)
    assert fake.files["NEW"] == package.read_bytes()


def test_cancel_ends_the_upload_and_records_nothing(drive):
    fake, package = drive
    with pytest.raises(drive_share.Cancelled):
        drive_share.publish(
            "cat",
            package,
            Google(),
            name="n",
            emails=["a@x.org"],
            anyone=False,
            cancelled=lambda: len(fake.requests) > 2,
        )
    assert any(r.method == "DELETE" for r in fake.requests)
    assert "NEW" not in fake.files and drive_share.previous("cat") is None


def test_a_share_needs_a_reader(drive):
    _fake, package = drive
    with pytest.raises(ValueError, match="email"):
        drive_share.publish("cat", package, Google(), name="n", emails=[], anyone=False)


def test_parse_emails_accepts_lists_and_rejects_typos():
    assert drive_share.parse_emails(" A@x.org, b@y.org;a@x.org\n") == ["a@x.org", "b@y.org"]
    assert drive_share.parse_emails("") == []
    with pytest.raises(ValueError, match="bob"):
        drive_share.parse_emails("a@x.org, bob")


def test_session_signs_in_once_per_run(monkeypatch):
    drive_share.forget_session()
    calls = []
    first = drive_share.session(lambda: calls.append(1) or Google())
    assert drive_share.session(lambda: calls.append(1) or Google()) is first
    assert calls == [1]
    drive_share.forget_session()


@pytest.mark.parametrize(
    "link",
    [
        "https://drive.google.com/file/d/AbC_1-2/view?usp=sharing",
        "https://drive.google.com/open?id=AbC_1-2",
    ],
)
def test_drive_page_links_import_as_the_file_itself(link):
    assert bundle_links.drive_direct(link) == bundle_links.drive_download_url("AbC_1-2")


def test_other_links_are_left_alone():
    url = "https://files.example.org/file/d/x/view"
    assert bundle_links.drive_direct(url) == url
