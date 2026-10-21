"""Polite HTTP with an on-disk cache.

Crawling 40k papers means re-running the pipeline many times while developing. The
cache makes re-runs free and keeps us from hammering proceedings sites that are run
by volunteers. Rate limits are per-host because Semantic Scholar is far stricter
than GitHub raw.
"""

from __future__ import annotations

import functools
import hashlib
import os
import random
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from paper_daily.config import HTTP_CACHE, S2_API_KEY, USER_AGENT, ensure_dirs

# Minimum seconds between requests to the same host.
HOST_DELAY = {
    "api.semanticscholar.org": 1.1,
    "papers.nips.cc": 0.35,
    "proceedings.neurips.cc": 0.35,
    "proceedings.mlr.press": 0.35,
    "raw.githubusercontent.com": 0.1,
    "arxiv.org": 3.0,
    # arXiv asks for one request every three seconds; the API host is separate.
    "export.arxiv.org": 3.2,
}
DEFAULT_DELAY = 0.5

_last_hit: dict[str, float] = {}
_lock = threading.Lock()


class FetchError(RuntimeError):
    pass


def _throttle(host: str) -> None:
    delay = HOST_DELAY.get(host, DEFAULT_DELAY)
    with _lock:
        prev = _last_hit.get(host, 0.0)
        wait = delay - (time.monotonic() - prev)
        if wait > 0:
            time.sleep(wait)
        _last_hit[host] = time.monotonic()


def _cache_path(url: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()
    return HTTP_CACHE / h[:2] / f"{h}.bin"


def fetch(
    url: str,
    *,
    cache: bool = True,
    max_age: float | None = None,
    retries: int = 8,
    timeout: float = 60.0,
) -> bytes:
    """GET with disk cache, per-host throttle, and backoff on 429/5xx.

    max_age caps how old a cached entry may be, in seconds; None means never expire.
    """
    ensure_dirs()
    cp = _cache_path(url)
    if cache and cp.exists() and (max_age is None or (time.time() - cp.stat().st_mtime) < max_age):
        return cp.read_bytes()

    host = urlparse(url).netloc
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    if S2_API_KEY and host == "api.semanticscholar.org":
        headers["x-api-key"] = S2_API_KEY
    if host == "api.github.com" and github_token():
        headers["Authorization"] = f"Bearer {github_token()}"

    last: Exception | None = None
    for attempt in range(retries):
        _throttle(host)
        try:
            r = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        except httpx.HTTPError as e:  # network flake -- worth retrying
            last = e
            time.sleep(min(2**attempt, 30) + random.random())
            continue

        if r.status_code == 200:
            body = r.content
            if cache:
                cp.parent.mkdir(parents=True, exist_ok=True)
                cp.write_bytes(body)
            return body
        if r.status_code == 404:
            raise FetchError(f"404 {url}")
        # 406 is how arXiv says "too many requests": it refuses to produce the Atom
        # response rather than returning 429. Treated as fatal, a throttled minute
        # looked exactly like a paper that is not on arXiv at all.
        if r.status_code in (406, 429, 500, 502, 503, 504):
            # Semantic Scholar throttles hard without an API key, and a bulk crawl
            # walks straight into it. Being impatient here is expensive: giving up
            # loses a whole venue-year of enrichment, while waiting a few minutes
            # costs nothing, so 429 gets a longer ceiling than a server error.
            ceiling = 300 if r.status_code == 429 else 60
            sleep = min(2**attempt * 2, ceiling) + random.random() * 2
            last = FetchError(f"{r.status_code} {url}")
            time.sleep(sleep)
            continue
        raise FetchError(f"{r.status_code} {url}: {r.text[:200]}")

    raise FetchError(f"gave up after {retries} attempts: {url} ({last})")


@functools.cache
def github_token() -> str:
    """GitHub allows 60 anonymous API calls an hour, which one look over a reading
    list's repositories uses up. A token raises that to 5,000; the gh CLI's login is
    the one most machines already have."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token.strip()
    try:
        out = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def fetch_text(url: str, **kw) -> str:
    return fetch(url, **kw).decode("utf-8", "replace")


def post_json(url: str, payload: dict, *, retries: int = 8, timeout: float = 90.0):
    """POST for the Semantic Scholar batch endpoints. Never cached -- batch bodies
    are built from whatever ids we still need, so a cache key would never hit."""
    host = urlparse(url).netloc
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    if S2_API_KEY and host == "api.semanticscholar.org":
        headers["x-api-key"] = S2_API_KEY

    for attempt in range(retries):
        _throttle(host)
        try:
            r = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        except httpx.HTTPError as e:
            if attempt == retries - 1:
                raise FetchError(f"POST {url}: {e}") from e
            time.sleep(min(2**attempt, 30) + random.random())
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            ceiling = 300 if r.status_code == 429 else 60
            time.sleep(min(2**attempt * 2, ceiling) + random.random() * 2)
            continue
        raise FetchError(f"POST {r.status_code} {url}: {r.text[:200]}")
    raise FetchError(f"POST gave up: {url}")
