"""Put a research package in the sharer's own Google Drive and copy its link.

Uses the same `drive.file` sign-in as Google Slides: Paperfact can only see and
share the files it created, never the rest of the Drive.
"""

from __future__ import annotations

import re
from contextlib import suppress
from pathlib import Path

import httpx

from paper_daily import google_slides
from paper_daily.bundle_links import drive_download_url, file_digest
from paper_daily.store import connect, get_kv, set_kv

UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
FILES = "https://www.googleapis.com/drive/v3/files"
# Drive accepts resumable chunks only in multiples of 256 KiB (the last excepted).
CHUNK = 32 * 256 * 1024
RETRIES = 3
EMAIL = re.compile(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+")
ANYONE = "anyoneWithLink"

_session: google_slides.GoogleSession | None = None


class Cancelled(ValueError):
    pass


def session(authorize=google_slides.authorize) -> google_slides.GoogleSession:
    """One browser sign-in per app run; the token is never written to disk."""
    global _session
    if _session is None:
        _session = authorize()
    return _session


def forget_session() -> None:
    global _session
    _session = None


def parse_emails(text: str) -> list[str]:
    parts = [p for p in re.split(r"[\s,;]+", text.strip()) if p]
    for part in parts:
        if not EMAIL.fullmatch(part):
            raise ValueError(f"無法辨識的 email：{part}")
    return list(dict.fromkeys(p.lower() for p in parts))


def view_url(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view"


def previous(list_id: str) -> dict | None:
    with connect() as conn:
        record = get_kv(conn, f"drive.share.{list_id}")
    return record if isinstance(record, dict) and record.get("file_id") else None


def _client() -> httpx.Client:
    return httpx.Client(timeout=120.0)


def _valid_id(value) -> str:
    if not isinstance(value, str) or not value or not all(c.isalnum() or c in "_-" for c in value):
        raise ValueError("Google Drive 未回傳有效的檔案 ID")
    return value


def _begin(client, token: str, path: Path, name: str, file_id: str | None) -> tuple[str, bool]:
    """Open a resumable upload: replace `file_id` in place, or create a new file
    when there is none or the sharer has since deleted it."""
    headers = {
        "Authorization": "Bearer " + token,
        "X-Upload-Content-Type": "application/zip",
        "X-Upload-Content-Length": str(path.stat().st_size),
    }
    params = {"uploadType": "resumable", "fields": "id"}
    if file_id:
        response = client.patch(
            f"{UPLOAD}/{file_id}", params=params, json={"name": name}, headers=headers
        )
        if response.status_code == 200:
            return response.headers["location"], True
        if response.status_code != 404:
            raise ValueError(f"無法更新 Google Drive 上的資料包（HTTP {response.status_code}）")
    response = client.post(
        UPLOAD, params=params, json={"name": name, "mimeType": "application/zip"}, headers=headers
    )
    if response.status_code != 200:
        raise ValueError(
            f"無法在 Google Drive 建立檔案（HTTP {response.status_code}）。"
            "請確認 Drive API 已啟用。"
        )
    return response.headers["location"], False


def _committed(response) -> int:
    """Bytes Drive has kept, from a 308's `Range: bytes=0-N` (absent means none)."""
    match = re.fullmatch(r"bytes=0-(\d+)", response.headers.get("range", ""))
    return int(match[1]) + 1 if match else 0


def upload(
    path: Path,
    token: str,
    *,
    name: str,
    file_id: str | None = None,
    progress=lambda _done, _total: None,
    cancelled=lambda: False,
) -> tuple[str, bool]:
    """Upload in chunks so a large package shows progress and survives a dropped
    connection. Returns (file id, whether an existing file was replaced)."""
    path = Path(path)
    size = path.stat().st_size
    auth = {"Authorization": "Bearer " + token}
    with _client() as client, path.open("rb") as file:
        location, replaced = _begin(client, token, path, name, file_id)
        offset, failures = 0, 0
        while True:
            if cancelled():
                # Ending the session discards the partial upload; a replaced file
                # keeps its previous contents.
                with suppress(httpx.TransportError):
                    client.delete(location, headers=auth)
                raise Cancelled("已取消上傳。")
            file.seek(offset)
            chunk = file.read(CHUNK)
            span = (
                f"bytes {offset}-{offset + len(chunk) - 1}/{size}" if chunk else f"bytes */{size}"
            )
            try:
                response = client.put(
                    location, content=chunk, headers=auth | {"Content-Range": span}
                )
            except httpx.TransportError:
                response = None
            if response is not None and response.status_code in (200, 201):
                progress(size, size)
                return _valid_id(response.json().get("id")), replaced
            if response is not None and response.status_code == 308:
                offset, failures = _committed(response), 0
                progress(offset, size)
                continue
            if response is not None and response.status_code < 500:
                raise ValueError(f"上傳到 Google Drive 失敗（HTTP {response.status_code}）")
            failures += 1
            if failures > RETRIES:
                raise ValueError("上傳到 Google Drive 時連線中斷，請稍後重試。")
            # Ask Drive how much arrived before resending from there.
            try:
                status = client.put(location, headers=auth | {"Content-Range": f"bytes */{size}"})
            except httpx.TransportError:
                continue
            if status.status_code in (200, 201):
                progress(size, size)
                return _valid_id(status.json().get("id")), replaced
            if status.status_code == 308:
                offset = _committed(status)


def grant(token: str, file_id: str, *, emails: list[str], anyone: bool, before: dict | None):
    """Readers only. Turning "anyone with the link" off removes it, so narrowing a
    share takes effect on the existing link too."""
    auth = {"Authorization": "Bearer " + token}
    url = f"{FILES}/{file_id}/permissions"
    with _client() as client:
        if anyone:
            response = client.post(url, json={"role": "reader", "type": "anyone"}, headers=auth)
            if response.status_code != 200:
                raise ValueError(f"無法開放連結檢視（HTTP {response.status_code}）")
        elif before and before.get("anyone"):
            response = client.delete(f"{url}/{ANYONE}", headers=auth)
            if response.status_code not in (204, 404):
                raise ValueError(f"無法關閉公開連結（HTTP {response.status_code}）")
        for email in emails:
            response = client.post(
                url,
                params={"sendNotificationEmail": "true"},
                json={"role": "reader", "type": "user", "emailAddress": email},
                headers=auth,
            )
            if response.status_code != 200:
                raise ValueError(
                    f"無法分享給 {email}（HTTP {response.status_code}）；請確認這是 Google 帳號。"
                )


def publish(
    list_id: str,
    path: Path,
    google: google_slides.GoogleSession,
    *,
    name: str,
    emails: list[str],
    anyone: bool,
    progress=lambda _done, _total: None,
    cancelled=lambda: False,
) -> dict:
    """Upload (replacing this list's earlier share, so its link keeps working),
    grant access, and return the link to hand out."""
    if not emails and not anyone:
        raise ValueError("請輸入對方的 Google 帳號 email，或開放「知道連結的人」下載。")
    before = previous(list_id)
    file_id, replaced = upload(
        path,
        google.access_token(),
        name=name,
        file_id=before and before["file_id"],
        progress=progress,
        cancelled=cancelled,
    )
    grant(google.access_token(), file_id, emails=emails, anyone=anyone, before=replaced and before)
    shared = sorted(set(emails) | set(before.get("emails", []) if replaced else []))
    with connect() as conn:
        set_kv(
            conn,
            f"drive.share.{list_id}",
            {"file_id": file_id, "anyone": anyone, "emails": shared},
        )
        conn.commit()
    # Only a public file can be fetched without a browser sign-in; the checksum
    # lets the receiver's import confirm it got exactly this package.
    link = (
        drive_download_url(file_id) + "#paperfact-sha256=" + file_digest(path)
        if anyone
        else view_url(file_id)
    )
    return {"link": link, "file_id": file_id, "replaced": replaced, "emails": shared}
