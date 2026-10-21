"""Machine translation for a passage selected in the reader.

Translating through the selected AI profile can preserve technical terms, but its
latency and cost depend on the provider. Quick machine translation is available
for a first glance, with the AI translation offered beside it.

This is the endpoint browser translation extensions use, which needs no key. It is
not a published API: Google may throttle or close it, and when it fails the caller
falls back to the model rather than showing an error. It is not a language model in
the sense of `llm`, so it does not go through `llm.complete`.
"""

from __future__ import annotations

import httpx

URL = "https://translate.googleapis.com/translate_a/single"


def machine(text: str, target: str = "zh-TW", timeout: float = 10) -> tuple[str | None, str]:
    """Translate `text`, or say why not. Same (text, reason) shape as `llm.complete`."""
    try:
        r = httpx.post(
            URL,
            params={"client": "gtx", "sl": "auto", "tl": target, "dt": "t"},
            # In the body, not the query string: a long passage overruns a URL.
            data={"q": text},
            timeout=timeout,
        )
    except httpx.HTTPError as e:
        return None, f"Google 翻譯連不上:{type(e).__name__}"
    if r.status_code != 200:
        return None, f"Google 翻譯回應 {r.status_code}"
    try:
        pieces = r.json()[0]
        out = "".join(p[0] for p in pieces if p and p[0])
    except (ValueError, TypeError, IndexError):
        return None, "Google 翻譯的回應看不懂"
    return (out.strip() or None), "ok"
