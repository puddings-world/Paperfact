"""Bounded PDF prefetch, atomic files and paper-keyed observable job states."""

import os
import tempfile
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pymupdf

from paper_daily import pdf_sources
from paper_daily.config import PDF_DIR, USER_AGENT
from paper_daily.fetch import _safe_name
from paper_daily.http import FetchError, _throttle
from paper_daily.store import connect

MAX_BYTES = 150 * 1024 * 1024


class Cancelled(Exception):
    pass


def check_cancel(cancel):
    if cancel.is_set():
        raise Cancelled()


@contextmanager
def paper_lock(dest, cancel):
    """A process-shared lock, released by the OS even after a crash."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.with_suffix(".download.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        while True:
            check_cancel(cancel)
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                cancel.wait(0.1)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def stream_pdf(url, dest, progress, cancel):
    """Publish only a complete, readable PDF; partial bytes never have a .pdf name."""
    check_cancel(cancel)
    _throttle(urlsplit(url).hostname or "")
    check_cancel(cancel)
    temporary = None
    started = time.monotonic()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(15, connect=10), follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        ) as client, client.stream("GET", url) as response:
            if response.status_code != 200:
                raise FetchError(f"下載來源回應 HTTP {response.status_code}")
            length = response.headers.get("content-length", "")
            total = int(length) if length.isdigit() and not response.headers.get(
                "content-encoding") else None
            total = total or None
            if total and total > MAX_BYTES:
                raise FetchError("PDF 超過 150 MB 下載上限，可手動加入檔案。")
            with tempfile.NamedTemporaryFile(dir=dest.parent, prefix=dest.stem + ".",
                                             suffix=".part", delete=False) as output:
                temporary = Path(output.name)
                received, prefix, trailer = 0, b"", b""
                progress("downloading", 0, total, "")
                for chunk in response.iter_bytes(64 * 1024):
                    check_cancel(cancel)
                    if time.monotonic() - started > 180:
                        raise FetchError("下載逾時，請重試。")
                    received += len(chunk)
                    if received > MAX_BYTES:
                        raise FetchError("PDF 超過 150 MB 下載上限，可手動加入檔案。")
                    prefix = (prefix + chunk)[:5]
                    trailer = (trailer + chunk)[-4096:]
                    if len(prefix) == 5 and prefix != b"%PDF-":
                        raise FetchError("來源回傳網頁或驗證頁，並非 PDF。")
                    output.write(chunk)
                    progress("downloading", received, total, "")
            check_cancel(cancel)
            if not received or (total and received != total):
                raise FetchError("PDF 傳輸不完整，請重試。")
            if b"%%EOF" not in trailer:
                raise FetchError("PDF 結尾不完整，請重試。")
        progress("verifying", received, total, "")
        try:
            # Opening invalid PDFs by path can retain a native Windows handle in
            # an exception traceback. A bounded byte stream lets cleanup always unlink.
            with pymupdf.open(stream=temporary.read_bytes(), filetype="pdf") as document:
                if document.needs_pass or document.page_count < 1:
                    raise ValueError("unreadable")
                document.load_page(0)
        except Exception as exc:
            raise FetchError("PDF 無法讀取或需要密碼，未存入原文。") from exc
        check_cancel(cancel)
        # The lock also coordinates the reader/analysis fetch path. Preserve an
        # independently supplied file if it appeared while this request ran.
        if not dest.exists():
            os.link(temporary, dest)
        return dest
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def download(paper_id, progress, cancel):
    with connect() as conn:
        record = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
    if record is None:
        raise FetchError("論文已不在資料庫中。")
    row = dict(record)
    dest = PDF_DIR / (_safe_name(paper_id) + ".pdf")
    progress("waiting", 0, None, "等待同篇下載工作")
    with paper_lock(dest, cancel):
        if dest.exists():
            return dest
        attempted, reasons = set(), []

        def attempt(url):
            check_cancel(cancel)
            if url in attempted:
                return None
            attempted.add(url)
            try:
                result = stream_pdf(url, dest, progress, cancel)
            except (FetchError, httpx.HTTPError) as exc:
                reasons.append(str(exc) if isinstance(exc, FetchError) else "下載連線中斷或逾時。")
                return None
            with connect() as conn:
                conn.execute("UPDATE papers SET pdf_url=? WHERE id=?", (url, paper_id))
                conn.execute("DELETE FROM kv WHERE key=?", (f"analyze.failed.pdf.{paper_id}",))
            return result

        for url in pdf_sources.known_links(row):
            if result := attempt(url):
                return result
        progress("resolving", 0, None, "正在查找開放原文來源")
        try:
            for url in pdf_sources.discover(row, lambda: check_cancel(cancel)):
                if result := attempt(url):
                    return result
                progress("resolving", 0, None, "嘗試其他原文來源")
        except FetchError as exc:
            reasons.append(str(exc))
        check_cancel(cancel)
        raise FetchError(reasons[-1] if reasons else "尚未找到可下載的開放 PDF；可重試或右鍵補入。")


@dataclass(frozen=True)
class State:
    phase: str = "queued"
    received: int = 0
    total: int | None = None
    message: str = ""

    @property
    def percent(self):
        if self.phase == "done":
            return 100
        if self.phase == "downloading" and self.total:
            return min(99, int(self.received * 100 / self.total))
        return None

    @property
    def label(self):
        labels = dict(queued="等待下載", waiting="等待同篇下載", resolving="尋找原文來源",
                      verifying="檢查 PDF", done="PDF 已下載", cancelled="已暫停",
                      error="下載未完成")
        if self.phase == "downloading":
            size = f"{self.received / 1048576:.1f} MB"
            return f"下載 PDF · {self.percent}% · {size}" if self.percent is not None else (
                f"下載 PDF · {size}（總大小未知）")
        return labels.get(self.phase, self.phase) + (" · " + self.message if self.message else "")


class DownloadQueue:
    """Shared across lists; UI polls immutable snapshots without worker Qt calls."""

    def __init__(self, worker=download, limit=3):
        self.worker, self.limit = worker, max(1, min(3, limit))
        self._lock = threading.RLock()
        self._states, self._active = {}, {}
        self._pending = deque()
        self._closed = False

    def snapshot(self):
        with self._lock:
            return dict(self._states)

    @property
    def busy(self):
        with self._lock:
            return bool(self._active or self._pending)

    def submit(self, paper_ids, *, retry=False):
        with self._lock:
            if self._closed:
                return
            for pid in dict.fromkeys(paper_ids):
                old = self._states.get(pid)
                if pid in self._active or (old and not (
                    retry and old.phase in ("error", "cancelled")
                )):
                    continue
                self._states[pid] = State()
                self._pending.append(pid)
            self._pump()

    def _pump(self):
        while not self._closed and self._pending and len(self._active) < self.limit:
            pid = self._pending.popleft()
            cancel = threading.Event()
            self._active[pid] = cancel
            threading.Thread(target=self._run, args=(pid, cancel), daemon=True).start()

    def _run(self, pid, cancel):
        def progress(phase, received, total, message):
            with self._lock:
                self._states[pid] = State(phase, received, total, message)

        try:
            result = self.worker(pid, progress, cancel)
            if result is None:
                raise FetchError("未取得 PDF，請重試。")
            with self._lock:
                self._states[pid] = replace(self._states[pid], phase="done", message="")
        except Cancelled:
            progress("cancelled", 0, None, "")
        except Exception as exc:
            message = (str(exc) if isinstance(exc, FetchError)
                       else "下載失敗，請重試或檢查磁碟空間。")
            progress("error", 0, None, message)
        finally:
            with self._lock:
                self._active.pop(pid, None)
                self._pump()

    def cancel(self, paper_ids=None):
        with self._lock:
            chosen = set(self._states if paper_ids is None else paper_ids)
            self._pending = deque(pid for pid in self._pending if pid not in chosen)
            for pid in chosen:
                if pid in self._active:
                    self._active[pid].set()
                elif pid in self._states and self._states[pid].phase == "queued":
                    self._states[pid] = State("cancelled")

    def close(self):
        with self._lock:
            self._closed = True
            self.cancel()
