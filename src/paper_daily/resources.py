"""The code, data and models a paper comes with, and the ones it points to.

Whether a method can be run is half of whether it is worth building on: a paper you
mean to compare against at MICCAI with no released code is a reimplementation, and a
dataset you want to evaluate on has to be downloadable. Finding that out by hand
means reading to the end of the abstract or a footnote on page nine.

Three places say where the code is, in order of trust:

- the paper itself. Authors put "Code is available at github.com/..." in the
  abstract or a footnote, and name the repositories and datasets they used.
- Hugging Face's paper pages, which link a paper to its repository, models and
  datasets (from READMEs that cite the arXiv id).
- a GitHub search for the paper's short name ("CataractSAM-2"), for papers whose
  text says nothing. Kept only when the repository's own description names it too,
  and shown as a guess.

PDF text breaks URLs across lines ("https://github.com/MJAHMADEE/C" / "ataract-LMM").
A break is joined when the URL cannot end there; when it could, both readings are
tried against GitHub and the one that exists wins.
"""

from __future__ import annotations

import json
import re
import urllib.parse

from paper_daily.config import PDF_DIR, TEXT_DIR
from paper_daily.fetch import _safe_name
from paper_daily.http import FetchError, fetch_text
from paper_daily.store import get_kv, now, set_kv

KINDS = {"code": "程式碼", "data": "資料集", "model": "模型", "demo": "Demo", "page": "專案頁"}

_HOSTS = (
    r"github\.com|gitlab\.com|bitbucket\.org|[\w-]+\.github\.io|huggingface\.co|"
    r"zenodo\.org|doi\.org/10\.5281/zenodo\.\d+|figshare\.com|synapse\.org|kaggle\.com|"
    r"osf\.io|physionet\.org|data\.mendeley\.com|ieee-dataport\.org|[\w-]+\.grand-challenge\.org"
)
_URL = re.compile(rf"(?:https?://)?(?:www\.)?(?:{_HOSTS})[^\s)\]>,;\"'<]*", re.I)
_URL_AT_END = re.compile(r"(?:https?://|www\.)\S*$")
_TRAIL = ".,;:)]}'\"’”"
# The start of the next section or footnote, which a URL ending in "/" runs into.
_HEADING = re.compile(r"(?:\d+(?:\.\d+)*\.?|[IVX]+\.)$")

# Words that say the link is this paper's own release rather than something it used.
_OWN = re.compile(
    r"\b(our|code|codes|implementation|project page|website|released?|repository|"
    r"weights|this dataset|the dataset is|data (?:are|is) (?:publicly )?available)\b",
    re.I,
)

# Not repositories: GitHub's own pages, and a user's profile with no repository.
_NOT_REPO = {"features", "about", "pricing", "orgs", "sponsors", "topics", "collections"}


def _unbreak(text: str) -> str:
    """Join line breaks that fall where a URL cannot end: inside the host, or
    straight after "/", "-" or "_"."""
    lines = text.split("\n")
    out = [lines[0]]
    for line in lines[1:]:
        head = _URL_AT_END.search(out[-1])
        token = line.lstrip()
        joins = head and token and _must_continue(head.group(0))
        if joins and not _HEADING.match(token.split()[0]):
            out[-1] += token
        else:
            out.append(line)
    return "\n".join(out)


def _must_continue(url: str) -> bool:
    rest = re.sub(r"^(?:https?://)?(?:www\.)?", "", url)
    host = rest.split("/", 1)[0]
    return "/" not in rest and not re.search(r"\.[a-z]{2,}$", host) or url[-1] in "/-_"


def links_in(text: str) -> list[dict]:
    """Every code or data link printed in the paper: {url, alt, own, context}.

    `alt` is the reading with the next line joined on, for a URL that ends at a line
    break where it might also have been cut.
    """
    text = _unbreak(text)
    found, seen, last = [], set(), 0
    for m in _URL.finditer(text):
        url = m.group(0).rstrip(_TRAIL)
        after = text[m.end() :]
        alt = None
        if after.startswith("\n") and m.group(0)[-1] not in _TRAIL[1:]:
            nxt = after[1:].split(None, 1)
            if nxt:
                alt = (m.group(0) + nxt[0]).rstrip(_TRAIL)
        if url.lower() in seen:
            continue
        seen.add(url.lower())
        # Only the words since the previous link: "Code is available at <ours>. We use
        # <theirs>" must not lend the first sentence to the second link.
        context = " ".join(text[max(last, m.start() - 160) : m.start()].split())
        last = m.end()
        found.append(
            {
                "url": url,
                "alt": alt,
                "own": bool(_OWN.search(context[-110:])),
                "context": context[-110:],
            }
        )
    return found


def classify(url: str) -> tuple[str, str] | None:
    """(kind, canonical URL), or None for a link that is not a release."""
    bare = re.sub(r"^(?:https?://)?(?:www\.)?", "", url).rstrip("/")
    host, _, path = bare.partition("/")
    host = host.lower()
    parts = [p for p in path.split("/") if p]
    if host in ("github.com", "gitlab.com", "bitbucket.org"):
        if len(parts) < 2 or parts[0].lower() in _NOT_REPO:
            return None
        repo = parts[1].removesuffix(".git")
        return "code", f"https://{host}/{parts[0]}/{repo}"
    if host.endswith(".github.io"):
        return "page", f"https://{bare}"
    if host == "huggingface.co":
        if not parts or parts[0] in ("papers", "docs", "blog"):
            return None
        if parts[0] in ("datasets", "spaces"):
            if len(parts) < 3:
                return None
            kind = "data" if parts[0] == "datasets" else "demo"
            return kind, f"https://huggingface.co/{'/'.join(parts[:3])}"
        if len(parts) < 2:
            return None
        return "model", f"https://huggingface.co/{parts[0]}/{parts[1]}"
    return "data", f"https://{bare}"


def _repo(url: str) -> dict | None:
    """GitHub's record of a repository: alive=False when there is no such repository,
    None when GitHub could not be asked."""
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)$", url)
    if not m:
        return None
    try:
        raw = fetch_text(
            f"https://api.github.com/repos/{m[1]}/{m[2]}", max_age=7 * 86400, retries=2
        )
    except FetchError as e:
        return {"url": url, "alive": False} if str(e).startswith("404") else None
    data = json.loads(raw)
    return {
        "url": data["html_url"],
        "alive": True,
        "stars": data.get("stargazers_count"),
        "license": (data.get("license") or {}).get("spdx_id"),
        "pushed_at": (data.get("pushed_at") or "")[:10] or None,
        "note": data.get("description"),
    }


def by_an_author(owner: str, authors: list[str]) -> bool:
    """Whether an account name looks like one of the authors': "SsharvienKumar" for
    Ssharvien Kumar Sivakumar, "mjahmadi" for Mohammad Javad Ahmadi."""
    owner = _norm(owner)
    for name in authors:
        words = [_norm(w) for w in name.split() if _norm(w)]
        if any(len(w) >= 4 and w in owner for w in words):
            return True
    return False


def _hugging_face(arxiv_id: str, authors: list[str]) -> list[dict]:
    """The repository Hugging Face ties to the paper, and its models, datasets and
    demos. Anyone can tie a model to a paper by citing it, so only those under an
    author's account count as the paper's own."""
    try:
        page = json.loads(
            fetch_text(
                f"https://huggingface.co/api/papers/{arxiv_id}", max_age=7 * 86400, retries=2
            )
        )
    except Exception:
        return []
    out = []
    if page.get("githubRepo"):
        out.append({"url": page["githubRepo"], "own": True})
    for key, kind in (
        ("linkedModels", ""),
        ("linkedDatasets", "datasets/"),
        ("linkedSpaces", "spaces/"),
    ):
        for item in (page.get(key) or [])[:5]:
            owner = item["id"].split("/", 1)[0]
            out.append(
                {
                    "url": f"https://huggingface.co/{kind}{item['id']}",
                    "own": by_an_author(owner, authors),
                }
            )
    return out


def short_name(title: str) -> str | None:
    """ "CataractSAM-2" from "CataractSAM-2: A Domain-Adapted Model ...", when the
    paper has a one-word name; a descriptive title gives nothing to search for."""
    m = re.match(r"\s*([^:–—]+?)\s*(?::| -{1,2} | – | — )", title or "")
    name = m.group(1).strip() if m else ""
    return name if name and " " not in name and len(name) >= 4 else None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _significant(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{6,}", (text or "").lower())}


def _search(title: str, authors: list[str]) -> list[dict]:
    """A repository named after the paper. A name is not evidence on its own --
    "catseg" is also an R package -- so the account must look like an author's, or
    the description must name the paper and share its subject."""
    name = short_name(title)
    if not name:
        return []
    query = urllib.parse.quote(f"{name} in:name")
    try:
        items = (
            json.loads(
                fetch_text(
                    f"https://api.github.com/search/repositories?q={query}&per_page=5",
                    max_age=7 * 86400,
                    retries=2,
                )
            ).get("items")
            or []
        )
    except Exception:
        return []
    words = _significant(title)
    kept = []
    for item in items:
        if _norm(item["name"]) != _norm(name):
            continue
        about = item.get("description") or ""
        named = _norm(name) in _norm(about) and len(words & _significant(about)) >= 2
        if named or by_an_author(item["owner"]["login"], authors):
            kept.append({"url": item["html_url"], "own": True})
    return kept[:2]


def _first_page(paper_id: str) -> set[str]:
    """Links printed on the first page, where a paper names its own code in the
    abstract or a footnote even without saying "our code"."""
    pdf = PDF_DIR / f"{_safe_name(paper_id)}.pdf"
    if not pdf.exists():
        return set()
    import pymupdf

    with pymupdf.open(pdf) as doc:
        if not doc.page_count:
            return set()
        text = doc[0].get_text()
    return {c[1].lower() for link in links_in(text) if (c := classify(link["url"]))}


def _owner(url: str) -> str:
    m = re.match(
        r"https://(?:github\.com|gitlab\.com|huggingface\.co(?:/datasets|/spaces)?)/([^/]+)", url
    )
    return m.group(1) if m else ""


def find(conn, paper_id: str) -> int:
    """Look for the paper's code and data, and store what was found. Returns how many."""
    row = conn.execute(
        "SELECT title, arxiv_id, authors_json FROM papers WHERE id=?", (paper_id,)
    ).fetchone()
    if row is None:
        return 0
    text_path = TEXT_DIR / f"{_safe_name(paper_id)}.txt"
    text = text_path.read_text(encoding="utf-8") if text_path.exists() else ""

    authors = json.loads(row["authors_json"] or "[]")
    candidates = [dict(link, source="pdf") for link in links_in(text)]
    if row["arxiv_id"]:
        candidates += [dict(link, source="hf") for link in _hugging_face(row["arxiv_id"], authors)]
    if not any(c["own"] for c in candidates):
        candidates += [dict(link, source="search") for link in _search(row["title"], authors)]
    first_page = _first_page(paper_id) if candidates else set()

    kept: dict[str, dict] = {}
    for cand in candidates:
        sorted_out = classify(cand["url"])
        alt = classify(cand["alt"]) if cand.get("alt") else None
        if sorted_out is None and alt is None:
            continue
        kind, url = sorted_out or alt
        meta = _repo(url) if kind == "code" and "github.com" in url else None
        if kind == "code" and not (meta or {}).get("alive") and alt and alt[0] == "code":
            alt_meta = _repo(alt[1])
            if (alt_meta or {}).get("alive"):
                kind, url, meta = "code", alt[1], alt_meta
        if meta:
            url = meta["url"]
        own = (
            cand["own"]
            or url.lower() in first_page
            or (kind != "page" and by_an_author(_owner(url), authors))
        )
        key = url.lower()
        prior = kept.get(key)
        if prior:
            # The paper saying "our code" outranks a search; a mention elsewhere in
            # the text does not take that back.
            prior["own"] = prior["own"] or own
            if prior["source"] == "search":
                prior["source"] = cand["source"]
            continue
        kept[key] = {
            "url": url,
            "kind": kind,
            "own": own,
            "source": cand["source"],
            "context": cand.get("context"),
            **{k: (meta or {}).get(k) for k in ("stars", "license", "pushed_at", "note", "alive")},
        }

    conn.execute("DELETE FROM resources WHERE paper_id=?", (paper_id,))
    conn.executemany(
        "INSERT INTO resources(paper_id, url, kind, own, source, context, stars, license, "
        "pushed_at, note, alive, checked_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                paper_id,
                r["url"],
                r["kind"],
                int(r["own"]),
                r["source"],
                r["context"],
                r["stars"],
                r["license"],
                r["pushed_at"],
                r["note"],
                None if r["alive"] is None else int(r["alive"]),
                now(),
            )
            for r in kept.values()
        ],
    )
    # Whether the full text was there to read: a paper checked before its PDF
    # arrived is worth checking again once it has.
    set_kv(conn, f"resources:{paper_id}", "text" if text else "notext")
    conn.commit()
    return len(kept)


def needs_check(conn, paper_id: str) -> bool:
    seen = get_kv(conn, f"resources:{paper_id}")
    if seen is None:
        return True
    return seen == "notext" and (TEXT_DIR / f"{_safe_name(paper_id)}.txt").exists()


def of(conn, paper_id: str) -> list[dict]:
    """The paper's own releases first, code before data, then what it points to."""
    order = list(KINDS)
    rows = [dict(r) for r in conn.execute("SELECT * FROM resources WHERE paper_id=?", (paper_id,))]
    return sorted(
        rows,
        key=lambda r: (
            not r["own"],
            r["source"] == "search",
            order.index(r["kind"]),
            -(r["stars"] or 0),
        ),
    )


def label(resource: dict) -> str:
    """ "程式碼 MECLabTUDA/SASVi ★17", as the reader's header shows it."""
    path = re.sub(r"^https?://(?:www\.)?[^/]+/", "", resource["url"]).rstrip("/")
    if resource["kind"] == "page":
        path = re.sub(r"^https?://", "", resource["url"]).rstrip("/")
    if resource["kind"] in ("data", "demo") and path.startswith(("datasets/", "spaces/")):
        path = path.split("/", 1)[1]
    text = f"{KINDS[resource['kind']]} {path}"
    if resource.get("stars") is not None:
        text += f" ★{resource['stars']}"
    if resource.get("alive") == 0:
        text += "(repo 尚未公開)"
    if resource["source"] == "search":
        text += "(搜尋到,未經論文確認)"
    return text


def refresh(conn, paper_ids: list[str], log=print, force: bool = False) -> int:
    found = 0
    for pid in paper_ids:
        if not force and not needs_check(conn, pid):
            continue
        n = find(conn, pid)
        title = conn.execute("SELECT title FROM papers WHERE id=?", (pid,)).fetchone()[0]
        own = [r for r in of(conn, pid) if r["own"]]
        log(f"  {n:2d} links  {title[:60]}")
        for r in own:
            log(f"      {label(r)}")
        found += n
    return found
