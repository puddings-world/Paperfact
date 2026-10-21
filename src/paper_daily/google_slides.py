"""User-authorized Google Slides copies; credentials never enter a deck."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import webbrowser
from contextlib import suppress
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from paper_daily.config import DATA_DIR
from paper_daily.presentation_export import speaker_notes_text
from paper_daily.presentation_odp import MIME, render_odp
from paper_daily.presentations import _atomic_json, _folder

CLIENT_FILE = DATA_DIR / "google-slides-client.json"
BUNDLED_CLIENT_FILE = Path(__file__).with_name("google-client.json")
SCOPE = "https://www.googleapis.com/auth/drive.file"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def read_client(path=None):
    if (
        path is None
        and not CLIENT_FILE.exists()
        and not os.environ.get("PAPERFACT_GOOGLE_CLIENT_ID")
        and BUNDLED_CLIENT_FILE.exists()
    ):
        path = BUNDLED_CLIENT_FILE
    if path is None and not CLIENT_FILE.exists():
        client_id = os.environ.get("PAPERFACT_GOOGLE_CLIENT_ID", "")
        if not client_id:
            raise ValueError(
                "此安裝尚未啟用 Google 登入。需由 Paperfact 開發者設定應用程式 OAuth；"
                "一般使用者只需登入帳號。"
            )
        raw = {
            "installed": {
                "client_id": client_id,
                "client_secret": os.environ.get("PAPERFACT_GOOGLE_CLIENT_SECRET", ""),
            }
        }
    else:
        raw = json.loads((path or CLIENT_FILE).read_text(encoding="utf-8"))
    cfg = raw.get("installed") if isinstance(raw, dict) else None
    if not isinstance(cfg, dict) or not isinstance(cfg.get("client_id"), str):
        raise ValueError("請選擇 Google Cloud 的 Desktop app OAuth client JSON")
    if not cfg["client_id"].endswith(".apps.googleusercontent.com"):
        raise ValueError("Google OAuth client ID 無效")
    return {k: cfg[k] for k in ("client_id", "client_secret") if isinstance(cfg.get(k), str)}


def configure(path):
    cfg = read_client(path)
    _atomic_json(CLIENT_FILE, {"installed": cfg})


@dataclass
class GoogleSession:
    client: dict = field(repr=False)
    token: dict = field(repr=False)
    expires: float = 0

    def access_token(self):
        if time.time() >= self.expires:
            response = httpx.post(
                TOKEN_URL,
                data={
                    **self.client,
                    "grant_type": "refresh_token",
                    "refresh_token": self.token.get("refresh_token", ""),
                },
                timeout=30,
            )
            if response.status_code != 200:
                raise ValueError("Google 登入已失效，請重新連接")
            refreshed = response.json()
            self.token.update(refreshed)
            self.expires = time.time() + int(refreshed.get("expires_in", 3600)) - 60
        token = self.token.get("access_token")
        if not isinstance(token, str) or not token:
            raise ValueError("Google 未回傳有效的登入憑證")
        return token


def authorize(*, opener=webbrowser.open, timeout=180):
    cfg = read_client()
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    state = secrets.token_urlsafe(32)
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlsplit(self.path)
            args = parse_qs(parsed.query)
            if parsed.path != "/callback" or args.get("state") != [state]:
                self.send_error(400, "Invalid OAuth callback")
                return
            result.update(code=args.get("code", [None])[0], error=args.get("error", [None])[0])
            body = b"Google authorization received. You may return to Paperfact."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    with HTTPServer(("127.0.0.1", 0), Callback) as server:
        redirect = f"http://127.0.0.1:{server.server_port}/callback"
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
            {
                "client_id": cfg["client_id"],
                "redirect_uri": redirect,
                "response_type": "code",
                "scope": SCOPE,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "access_type": "offline",
                "prompt": "select_account consent",
            }
        )
        if not opener(url):
            raise ValueError("無法開啟系統瀏覽器，請檢查預設瀏覽器設定")
        server.timeout = 1
        deadline = time.monotonic() + timeout
        while not result and time.monotonic() < deadline:
            server.handle_request()
    if not result.get("code"):
        raise ValueError("Google 登入已取消或逾時，請重新連接")
    response = httpx.post(
        TOKEN_URL,
        data={
            **cfg,
            "code": result["code"],
            "code_verifier": verifier,
            "redirect_uri": redirect,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise ValueError("Google 授權交換失敗，請確認 Desktop OAuth client 設定")
    token = response.json()
    session = GoogleSession(cfg, token, time.time() + int(token.get("expires_in", 3600)) - 60)
    session.access_token()
    return session


def export_copy(deck, session: GoogleSession, *, include_notes=True):
    data = render_odp(deck, include_notes=include_notes)
    boundary = "paperfact_" + secrets.token_hex(16)
    metadata = json.dumps(
        {"name": deck.title, "mimeType": "application/vnd.google-apps.presentation"},
        ensure_ascii=False,
    )
    body = (
        (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{metadata}\r\n"
            f"--{boundary}\r\nContent-Type: {MIME}\r\n\r\n"
        ).encode()
        + data
        + f"\r\n--{boundary}--\r\n".encode()
    )
    response = httpx.post(
        "https://www.googleapis.com/upload/drive/v3/files",
        params={"uploadType": "multipart", "fields": "id"},
        content=body,
        headers={
            "Authorization": "Bearer " + session.access_token(),
            "Content-Type": "multipart/related; boundary=" + boundary,
        },
        timeout=120,
    )
    if response.status_code not in (200, 201):
        raise ValueError(
            f"Google Slides 匯出失敗（HTTP {response.status_code}）。"
            "請確認 Drive API 已啟用及帳號權限。"
        )
    file_id = response.json().get("id")
    if (
        not isinstance(file_id, str)
        or not file_id
        or not all(c.isalnum() or c in "_-" for c in file_id)
    ):
        raise ValueError("Google 未回傳有效的簡報 ID")
    url = f"https://docs.google.com/presentation/d/{file_id}/edit"
    # Each export creates a copy, so subsequent local exports cannot erase cloud edits.
    link = {"url": url, "created_at": time.time(), "deck_id": deck.deck_id}
    # Return the cloud link even if the local link cache cannot be written.
    with suppress(OSError):
        _atomic_json(_folder(deck.paper_id) / f"{deck.mode}-google.json", link)
    if include_notes:
        try:
            write_speaker_notes(deck, session, file_id)
        except (ValueError, httpx.HTTPError, KeyError, TypeError) as exc:
            raise GoogleNotesError(url) from exc
    return url


class GoogleNotesError(ValueError):
    def __init__(self, url):
        self.url = url
        super().__init__(
            "簡報已建立，但講稿同步未完成；已保留連結。"
            "請在雲端檢查講稿，或啟用 Slides API 後重新建立副本。"
        )


def write_speaker_notes(deck, session, file_id):
    endpoint = f"https://slides.googleapis.com/v1/presentations/{file_id}"
    headers = {"Authorization": "Bearer " + session.access_token()}
    response = httpx.get(
        endpoint,
        headers=headers,
        params={
            "fields": (
                "slides(slideProperties(notesPage(notesProperties(speakerNotesObjectId),"
                "pageElements(objectId))))"
            )
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise ValueError(f"無法讀取 Google 講稿區（HTTP {response.status_code}）")
    pages = response.json().get("slides", [])
    if len(pages) != len(deck.slides):
        raise ValueError("Google 匯入後的投影片頁數不同，未覆寫講稿。")
    requests = []
    for page, slide in zip(pages, deck.slides, strict=True):
        notes = page["slideProperties"]["notesPage"]
        object_id = notes["notesProperties"]["speakerNotesObjectId"]
        if not isinstance(object_id, str) or not object_id:
            raise ValueError("Google 未回傳有效的講稿區 ID")
        if any(e.get("objectId") == object_id for e in notes.get("pageElements", [])):
            requests.append({"deleteText": {"objectId": object_id, "textRange": {"type": "ALL"}}})
        requests.append(
            {
                "insertText": {
                    "objectId": object_id,
                    "insertionIndex": 0,
                    "text": speaker_notes_text(deck, slide),
                }
            }
        )
    response = httpx.post(
        endpoint + ":batchUpdate", headers=headers, json={"requests": requests}, timeout=60
    )
    if response.status_code != 200:
        raise ValueError(f"Google 講稿寫入失敗（HTTP {response.status_code}）")


def last_link(paper_id, mode):
    path = _folder(paper_id) / f"{mode}-google.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        url = data.get("url", "") if isinstance(data, dict) else ""
    except (ValueError, OSError):
        return None
    return (
        url
        if isinstance(url, str) and url.startswith("https://docs.google.com/presentation/d/")
        else None
    )
