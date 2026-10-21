"""Canvas geometry, editable exports and Google authorization boundaries."""

import base64
import hashlib
import io
import json
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

from paper_daily import google_slides, presentation_export, presentation_odp, presentations
from paper_daily.slide_layout import elements_for, validate_elements


@pytest.fixture
def deck(tmp_path, monkeypatch):
    monkeypatch.setattr(presentations, "DECK_DIR", tmp_path)
    slide = presentations.Slide(
        "Title", "Method", "Finding", ["Evidence"], "Speaker notes", ["page:1"]
    )
    slide.elements = elements_for(slide)
    return presentations.Deck(
        "paper",
        "Paper",
        "Deck",
        "guide",
        "Researcher",
        15,
        [slide],
        [{"id": "page:1", "kind": "original", "label": "Page 1"}],
        [],
        [],
        "2026-10-13",
    )


def test_canvas_export_keeps_editable_text_position_and_no_secret(deck, tmp_path):
    obj = deck.slides[0].elements[1]
    obj.update(text="Edited <content>", x=70, size=32, color="#234567")
    html = presentation_export.render_html(deck)
    assert "Edited &lt;content&gt;" in html and "#234567" in html
    assert "left:5.833" in html
    data = presentation_odp.render_odp(deck, include_notes=False)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.namelist()[0] == "mimetype"
        assert z.read("mimetype").decode() == presentation_odp.MIME
        content = ET.fromstring(z.read("content.xml"))
        assert "Edited <content>" in "".join(content.itertext())
        assert "Speaker notes" not in "".join(content.itertext())
        assert len(content.findall(".//draw:text-box", presentation_odp.NS)) == 5
        ET.fromstring(z.read("styles.xml"))
        ET.fromstring(z.read("META-INF/manifest.xml"))


@pytest.mark.parametrize(
    "change",
    [{"x": float("nan")}, {"w": -1}, {"size": 200}, {"color": "red;url(evil)"}, {"x": 1190}],
)
def test_invalid_canvas_geometry_is_rejected(deck, change):
    obj = deck.slides[0].elements[0]
    obj.update(change)
    with pytest.raises(ValueError):
        presentations.save_deck(deck)


def test_canvas_unknown_image_is_rejected():
    with pytest.raises(ValueError):
        validate_elements([dict(kind="figure", x=0, y=0, w=100, h=100, figure="unknown")], set())


def test_google_upload_is_editable_private_copy_and_persists_link(deck, monkeypatch):
    captured = {}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(200, json={"id": "slides_123"})

    monkeypatch.setattr(google_slides.httpx, "post", post)
    session = google_slides.GoogleSession({}, {"access_token": "private-token"}, time.time() + 600)
    url = google_slides.export_copy(deck, session, include_notes=False)
    assert url == "https://docs.google.com/presentation/d/slides_123/edit"
    assert google_slides.last_link(deck.paper_id, "guide") == url
    assert captured["url"].endswith("/upload/drive/v3/files")
    assert b"application/vnd.google-apps.presentation" in captured["content"]
    assert b"private-token" not in captured["content"]
    assert b"permissions" not in captured["content"]
    assert "private-token" not in repr(session)


def test_google_desktop_authorization_uses_state_pkce_and_narrow_scope(tmp_path, monkeypatch):
    client = tmp_path / "client.json"
    client.write_text(json.dumps({"installed": {"client_id": "test.apps.googleusercontent.com"}}))
    monkeypatch.setattr(google_slides, "CLIENT_FILE", client)
    seen = {}
    threads = []

    def opener(url):
        args = parse_qs(urlsplit(url).query)
        seen.update(args)
        callback = (
            args["redirect_uri"][0]
            + "?"
            + urlencode({"state": args["state"][0], "code": "test-code"})
        )
        thread = threading.Thread(target=lambda: urllib.request.urlopen(callback).read())
        thread.start()
        threads.append(thread)
        return True

    def post(url, **kwargs):
        data = kwargs["data"]
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(data["code_verifier"].encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        assert seen["code_challenge"] == [expected]
        assert seen["scope"] == [google_slides.SCOPE]
        assert url == google_slides.TOKEN_URL
        return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})

    monkeypatch.setattr(google_slides.httpx, "post", post)
    session = google_slides.authorize(opener=opener, timeout=3)
    for thread in threads:
        thread.join(timeout=2)
    assert session.access_token() == "token"
    assert list(tmp_path.iterdir()) == [client]


def test_table_objects_render_in_every_export(deck):
    from paper_daily.slide_layout import table_box

    rows = [["Dataset", "Dice"], ["A", "0.754"], ["B", "0.625"]]
    deck.slides[0].elements.append(table_box(rows, 56, 300, 600, 120))
    presentations.deck_from_dict(deck.to_dict())
    html = presentation_export.render_html(deck)
    assert '<table class="canvas-object canvas-table"' in html
    assert "<th>Dataset</th>" in html and "<td>0.754</td>" in html
    data = presentation_odp.render_odp(deck, include_notes=False)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        content = ET.fromstring(z.read("content.xml"))
        cells = content.findall(".//table:table-cell", presentation_odp.NS)
        assert len(cells) == 6 and "0.625" in "".join(content.itertext())
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as folder:
        dest = Path(folder) / "deck.md"
        presentation_export.export_markdown(deck, dest)
        text = dest.read_text(encoding="utf-8")
        assert "| Dataset | Dice |" in text and "| B | 0.625 |" in text


@pytest.mark.parametrize(
    "rows",
    [[], [["a"], ["b", "c"]], [["x" * 201]], [[1, 2]], [["a"] * 13]],
)
def test_invalid_table_rows_are_rejected(rows):
    with pytest.raises(ValueError):
        validate_elements([dict(kind="table", rows=rows, x=0, y=0, w=100, h=100)], set())


def test_notes_include_speaker_text_page_and_safe_source_links(deck):
    deck.sources[0].update(page=3, url="https://example.org/paper")
    notes = presentation_export.speaker_notes_text(deck, deck.slides[0])
    assert "Speaker notes" in notes and "原文 p.3" in notes
    assert "引用來源" in notes and "https://example.org/paper" in notes
    with zipfile.ZipFile(io.BytesIO(presentation_odp.render_odp(deck))) as archive:
        xml = ET.fromstring(archive.read("content.xml"))
        exported = xml.find(".//presentation:notes", presentation_odp.NS)
        assert all(part in "".join(exported.itertext()) for part in notes.splitlines())
    deck.sources[0]["url"] = "file:///private/secret"
    assert "file:" not in presentation_export.speaker_notes_text(deck, deck.slides[0])


def test_google_notes_write_uses_actual_notes_object_and_keeps_source_links(deck, monkeypatch):
    seen = []
    deck.sources[0].update(page=1, url="https://example.org/paper")
    monkeypatch.setattr(
        google_slides.httpx,
        "get",
        lambda *args, **kw: httpx.Response(
            200,
            json={
                "slides": [
                    {
                        "slideProperties": {
                            "notesPage": {
                                "notesProperties": {"speakerNotesObjectId": "notes1"},
                                "pageElements": [{"objectId": "notes1"}],
                            }
                        }
                    }
                ]
            },
        ),
    )

    def post(url, **kwargs):
        seen.append((url, kwargs))
        return httpx.Response(200, json={"id": "slides_with_notes"})

    monkeypatch.setattr(google_slides.httpx, "post", post)
    session = google_slides.GoogleSession({}, {"access_token": "token"}, time.time() + 600)
    url = google_slides.export_copy(deck, session)
    assert url.endswith("/slides_with_notes/edit")
    assert len(seen) == 2 and seen[1][0].endswith("slides_with_notes:batchUpdate")
    requests = seen[1][1]["json"]["requests"]
    assert requests[0]["deleteText"]["objectId"] == "notes1"
    assert requests[1]["insertText"]["objectId"] == "notes1"
    assert "Speaker notes" in requests[1]["insertText"]["text"]
    assert "https://example.org/paper" in requests[1]["insertText"]["text"]


def test_google_notes_failure_preserves_created_cloud_link(deck, monkeypatch):
    monkeypatch.setattr(
        google_slides.httpx,
        "post",
        lambda *args, **kwargs: httpx.Response(200, json={"id": "partial_copy"}),
    )
    monkeypatch.setattr(
        google_slides.httpx,
        "get",
        lambda *args, **kwargs: httpx.Response(403, json={"error": "API disabled"}),
    )
    session = google_slides.GoogleSession({}, {"access_token": "token"}, time.time() + 600)
    with pytest.raises(google_slides.GoogleNotesError) as error:
        google_slides.export_copy(deck, session)
    assert error.value.url.endswith("/partial_copy/edit")
    assert google_slides.last_link(deck.paper_id, deck.mode) == error.value.url


def test_deployment_oauth_config_does_not_require_user_json(tmp_path, monkeypatch):
    monkeypatch.setattr(google_slides, "CLIENT_FILE", tmp_path / "missing.json")
    monkeypatch.delenv("PAPERFACT_GOOGLE_CLIENT_ID", raising=False)
    with pytest.raises(ValueError, match="尚未啟用"):
        google_slides.read_client()
    monkeypatch.setenv("PAPERFACT_GOOGLE_CLIENT_ID", "paperfact.apps.googleusercontent.com")
    monkeypatch.setenv("PAPERFACT_GOOGLE_CLIENT_SECRET", "deployment-secret")
    assert google_slides.read_client()["client_id"] == "paperfact.apps.googleusercontent.com"
    assert not list(tmp_path.iterdir())
