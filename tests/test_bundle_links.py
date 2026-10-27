import io
import json
import socket
import threading
import zipfile
from types import SimpleNamespace

import httpx
import pytest
from test_bundle import _workspace
from test_bundle import sharer as _sharer

from paper_daily import bundle, research_service
from paper_daily import bundle_links as links

sharer = _sharer
CLIENT = httpx.Client


def package():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("manifest.json", "{}")
        archive.writestr("tables.json", "{}")
    return stream.getvalue()


@pytest.fixture
def network(monkeypatch):
    requests = []

    def install(handler):
        def serve(request):
            requests.append(request)
            return handler(request)

        monkeypatch.setattr(
            links.httpx, "Client", lambda **kw: CLIENT(transport=httpx.MockTransport(serve), **kw)
        )
        monkeypatch.setattr(
            links.socket,
            "getaddrinfo",
            lambda host, *a, **k: [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    ("127.0.0.1" if host == "127.0.0.1" else "8.8.8.8", 443),
                ),
            ],
        )
        return requests

    return install


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://example.org/a.zip",
        "file:///tmp/a.zip",
        "https://u:password@example.org/a.zip",
        "https://example.org:8443/a.zip",
        "https://example.org/a.zip#broken",
        "https://example.org/\nsecret",
    ],
)
def test_invalid_links_fail_before_download(url, tmp_path, monkeypatch):
    monkeypatch.setattr(links.httpx, "Client", lambda **kw: pytest.fail("unexpected network"))
    with pytest.raises(ValueError):
        links.download(url, tmp_path / "p.zip")
    assert not list(tmp_path.iterdir())


def test_share_link_keeps_signed_query_and_does_not_upload(tmp_path, monkeypatch):
    source = tmp_path / "p.zip"
    source.write_bytes(package())
    monkeypatch.setattr(links.httpx, "Client", lambda **kw: pytest.fail("upload is not authorized"))
    url = "https://files.example.org/p.zip?signature=fixture%2Bvalue"
    link = research_service.make_share_link(url, source)
    cleaned, digest = links.parse_link(link)
    assert cleaned == url and digest == links.file_digest(source)


def test_streamed_checksum_download_preserves_old_target_on_failure(tmp_path, network):
    data = package()
    seen = network(lambda r: httpx.Response(200, content=data))
    target = tmp_path / "p.zip"
    target.write_bytes(data)
    link = links.make_link("https://files.example.org/p.zip?secret=fixture", target)
    progress = []
    assert (
        research_service.download_bundle(link, target, progress=lambda *v: progress.append(v))
        == target
    )
    assert target.read_bytes() == data and progress[-1][0] == len(data)
    assert seen[0].method == "GET" and "#" not in str(seen[0].url)
    assert not any(k in seen[0].headers for k in ("authorization", "cookie", "referer"))
    with pytest.raises(ValueError, match="校驗碼"):
        links.download(link.rsplit("=", 1)[0] + "=" + "0" * 64, target)
    assert target.read_bytes() == data and not target.with_suffix(".zip.part").exists()


def test_redirects_keep_checksum_and_strip_cookies(tmp_path, network):
    data = package()
    source = tmp_path / "original.zip"
    source.write_bytes(data)

    def handler(r):
        if r.url.host == "files.example.org":
            return httpx.Response(
                302,
                headers={
                    "Location": "https://cdn.example.org/p.zip",
                    "Set-Cookie": "session=fixture; Domain=.example.org",
                },
            )
        assert not r.headers.get("cookie")
        return httpx.Response(200, content=data)

    seen = network(handler)
    links.download(links.make_link("https://files.example.org/start", source), tmp_path / "p.zip")
    assert len(seen) == 2


@pytest.mark.parametrize(
    "destination",
    ["https://127.0.0.1/private", "http://files.example.org/plain", "https://localhost/private"],
)
def test_redirect_cannot_downgrade_or_target_local_services(tmp_path, network, destination):
    seen = network(lambda r: httpx.Response(302, headers={"Location": destination}))
    with pytest.raises(ValueError):
        links.download("https://files.example.org/p.zip", tmp_path / "p.zip")
    assert len(seen) == 1 and not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "response, message",
    [
        (
            httpx.Response(200, text="<html>Sign in</html>", headers={"Content-Type": "text/html"}),
            "預覽",
        ),
        (httpx.Response(403, text="private"), "403"),
        (httpx.Response(200, content=b"not a zip"), "ZIP"),
    ],
)
def test_bad_links_show_actionable_errors_without_importing(tmp_path, network, response, message):
    network(lambda r: response)
    with pytest.raises(ValueError, match=message):
        links.download("https://files.example.org/p.zip", tmp_path / "p.zip")
    assert not list(tmp_path.iterdir())


def test_unknown_length_limit_and_cancel_remove_partial_files(tmp_path, network):
    data = package()

    def handler(r):
        response = httpx.Response(200, content=data)
        response.headers.pop("content-length", None)
        return response

    network(handler)
    target = tmp_path / "p.zip"
    with pytest.raises(ValueError, match="超過"):
        links.download("https://files.example.org/p.zip", target, max_bytes=10)
    assert not list(tmp_path.iterdir())
    cancelled = threading.Event()
    with pytest.raises(links.Cancelled):
        links.download(
            "https://files.example.org/p.zip",
            target,
            progress=lambda *a: cancelled.set(),
            cancelled=cancelled.is_set,
        )
    assert not list(tmp_path.iterdir())


def test_network_failure_does_not_echo_signed_url_and_retry_works(tmp_path, network):
    def broken(r):
        raise httpx.ReadTimeout("https://files.example.org/?signature=private-value")

    network(broken)
    with pytest.raises(ValueError) as error:
        links.download("https://files.example.org/?signature=private-value", tmp_path / "p.zip")
    assert "private-value" not in str(error.value)
    network(lambda r: httpx.Response(200, content=package()))
    assert links.download("https://files.example.org/p.zip", tmp_path / "p.zip").exists()


def test_archive_expansion_is_bounded(tmp_path, network, monkeypatch):
    network(lambda r: httpx.Response(200, content=package()))
    monkeypatch.setattr(links, "MAX_UNPACKED", 1)
    with pytest.raises(ValueError, match="解壓限制"):
        links.download("https://files.example.org/p.zip", tmp_path / "p.zip")
    assert not list(tmp_path.iterdir())


def test_shared_url_import_preserves_recipient_accounts_and_is_repeatable(
    sharer, monkeypatch, network
):
    made, tmp = sharer
    blob = made["out"].read_bytes()
    link = research_service.make_share_link("https://files.example.org/p.zip", made["out"])
    network(lambda r: httpx.Response(200, content=blob))
    recipient = tmp / "recipient"
    recipient.mkdir()
    db = _workspace(recipient, monkeypatch)
    settings = recipient / "llm.json"
    settings.write_text('{"account":"recipient-owned"}')
    monkeypatch.setattr(bundle, "fetch", lambda *a, **kw: pytest.fail("unexpected PDF network"))
    source = research_service.download_bundle(link, tmp / "received.zip")
    assert research_service.inspect_bundle(source)["papers"] == 2
    assert db.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 0
    research_service.import_bundle(source, pdfs=False)
    assert research_service.import_bundle(source, pdfs=False)["joined_list"] == 0
    assert db.execute("SELECT body FROM dives").fetchone()[0] == "sharer dive"
    assert settings.read_text() == '{"account":"recipient-owned"}'


def test_cli_preview_then_import_use_same_service(sharer, monkeypatch, capsys):
    from paper_daily import cli

    made, tmp = sharer
    recipient = tmp / "recipient"
    recipient.mkdir()
    db = _workspace(recipient, monkeypatch)
    monkeypatch.setattr(research_service, "download_bundle", lambda *a, **k: made["out"])
    args = SimpleNamespace(url="https://files.example.org/p.zip", preview=True, replace=False)
    assert cli.cmd_list_import_url(args) == 0
    assert json.loads(capsys.readouterr().out)["papers"] == 2
    assert db.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 0
    args.preview = False
    assert cli.cmd_list_import_url(args) == 0
    assert json.loads(capsys.readouterr().out)["joined_list"] == 2
    assert db.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 1


def test_cli_share_link_is_offline_and_reports_missing_export(tmp_path, monkeypatch, capsys):
    from paper_daily import cli

    monkeypatch.setattr(links.httpx, "Client", lambda **kw: pytest.fail("share uploaded"))
    source = tmp_path / "export.zip"
    args = SimpleNamespace(path=str(source), url="https://files.example.org/p.zip")
    assert cli.cmd_list_share_link(args) == 2
    assert not capsys.readouterr().out
    source.write_bytes(package())
    assert cli.cmd_list_share_link(args) == 0
    assert capsys.readouterr().out.strip() == links.make_link(args.url, source)


def test_drive_page_link_downloads_the_file_itself(tmp_path, network):
    requests = network(lambda r: httpx.Response(200, content=package()))
    links.download("https://drive.google.com/file/d/F1/view?usp=sharing", tmp_path / "p.zip")
    assert requests[0].url.host == "drive.usercontent.google.com"
    assert requests[0].url.params["id"] == "F1"


def test_restricted_drive_file_explains_how_to_import(tmp_path, network):
    network(
        lambda r: httpx.Response(
            200, text="<html>Sign in</html>", headers={"Content-Type": "text/html"}
        )
    )
    with pytest.raises(ValueError, match="特定帳號"):
        links.download("https://drive.google.com/file/d/F1/view", tmp_path / "p.zip")
    assert not list(tmp_path.iterdir())
