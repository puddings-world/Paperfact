"""Transfer explicit HTTPS research-package links without using AI credentials."""

import hashlib
import ipaddress
import re
import socket
import time
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from paper_daily import __version__

MAX_DOWNLOAD = 1024**3
MAX_UNPACKED = 4 * 1024**3
MAX_ENTRY = 256 * 1024**2
MAX_FILES = 50000
CHECKSUM = re.compile(r"paperfact-sha256=([a-fA-F0-9]{64})")


class Cancelled(ValueError):
    pass


def parse_link(value: str) -> tuple[str, str | None]:
    """Keep signed query strings intact; fragments never reach the file host."""
    value = value.strip()
    if not value or len(value) > 8192 or any(ord(c) < 32 for c in value):
        raise ValueError("請貼上研究資料包的 HTTPS 下載網址。")
    try:
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.port not in (None, 443)
            or "\\" in value
        ):
            raise ValueError
    except ValueError as exc:
        raise ValueError("請使用 HTTPS 下載網址，不要包含帳號密碼或自訂連接埠。") from exc
    digest = None
    if url.fragment:
        match = CHECKSUM.fullmatch(url.fragment)
        if not match:
            raise ValueError("分享網址的校驗碼格式不正確；請向分享者取得完整連結。")
        digest = match[1].lower()
    return urlunsplit((url.scheme, url.netloc, url.path, url.query, "")), digest


def public_destination(url: str) -> None:
    """Reject local/private destinations before each network hop."""
    host = urlsplit(url).hostname
    if host.lower().rstrip(".").endswith((".local", ".localhost")) or host.lower() == "localhost":
        raise ValueError("分享網址須指向可公開連線的檔案主機。")
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError("分享網址不能指向本機或私人網路位址。")
    except OSError as exc:
        raise ValueError("無法連線到分享主機，請檢查網址與網路。") from exc


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for block in iter(lambda: file.read(1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def make_link(url: str, source: Path) -> str:
    """Create a local integrity link; no upload or permissions change occurs."""
    clean, _ = parse_link(url)
    return clean + "#paperfact-sha256=" + file_digest(source)


def check_archive(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if (
                len(entries) > MAX_FILES
                or sum(e.file_size for e in entries) > MAX_UNPACKED
                or any(e.file_size > MAX_ENTRY or e.flag_bits & 1 for e in entries)
            ):
                raise ValueError("研究包超過解壓限制或需要密碼；請拆分清單後分享。")
            if not {"manifest.json", "tables.json"} <= set(archive.namelist()):
                raise ValueError("這不是 Paperfact 匯出的研究資料包，請不要使用軟體原始碼 ZIP。")
    except zipfile.BadZipFile as exc:
        raise ValueError(
            "連結沒有傳回完整 ZIP；若是雲端預覽或登入頁，請先在瀏覽器下載再匯入。"
        ) from exc


def download(
    url: str,
    target: Path,
    *,
    progress=lambda _done, _total: None,
    cancelled=lambda: False,
    max_bytes=MAX_DOWNLOAD,
) -> Path:
    """Bounded, cancellable download; errors do not disclose signed query strings."""
    current, expected = parse_link(url)
    target = Path(target)
    partial = target.with_name(target.name + ".part")
    started = time.monotonic()

    def check_cancel():
        if cancelled():
            raise Cancelled("已取消下載。")
        if time.monotonic() - started > 600:
            raise ValueError("下載時間過長；可重試，或先使用瀏覽器下載 ZIP。")

    try:
        check_cancel()
        target.parent.mkdir(parents=True, exist_ok=True)
        # Dedicated client: no provider tokens, browser login, cookies or netrc.
        with httpx.Client(timeout=15.0, follow_redirects=False, trust_env=False) as client:
            for _hop in range(6):
                check_cancel()
                public_destination(current)
                client.cookies.clear()
                with client.stream(
                    "GET",
                    current,
                    headers={
                        "User-Agent": f"Paperfact/{__version__}",
                        "Accept-Encoding": "identity",
                    },
                ) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        next_url = urljoin(current, response.headers.get("location", ""))
                        if next_url == current:
                            raise ValueError("分享連結重新導向失敗，請取得直接下載網址。")
                        current, _ignored = parse_link(next_url)
                        continue
                    if response.status_code != 200:
                        raise ValueError(
                            f"下載失敗（HTTP {response.status_code}）；請確認連結有效且可下載。"
                        )
                    if "text/html" in response.headers.get("content-type", "").lower():
                        raise ValueError(
                            "這是網頁預覽或登入頁；請先在瀏覽器下載 ZIP，再匯入研究資料包。"
                        )
                    try:
                        total = max(0, int(response.headers.get("content-length") or 0))
                    except ValueError:
                        total = 0
                    if total > max_bytes:
                        raise ValueError("研究包超過 1 GB 下載限制；請拆分清單或先在瀏覽器下載。")
                    count = 0
                    with partial.open("wb") as file:
                        for chunk in response.iter_bytes(chunk_size=64 * 1024):
                            check_cancel()
                            count += len(chunk)
                            if count > max_bytes:
                                raise ValueError("研究包超過下載限制；請拆分清單或先在瀏覽器下載。")
                            file.write(chunk)
                            progress(count, total)
                    check_cancel()
                    if expected and file_digest(partial) != expected:
                        raise ValueError("研究包校驗碼不符；檔案可能已更換，請向分享者取得新連結。")
                    check_archive(partial)
                    partial.replace(target)
                    return target
            raise ValueError("分享連結重新導向過多；請取得直接下載網址。")
    except httpx.HTTPError as exc:
        raise ValueError("下載中斷或連線逾時，請重試；需要登入的連結可先在瀏覽器下載。") from exc
    finally:
        partial.unlink(missing_ok=True)
