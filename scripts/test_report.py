"""Build a local, catalog-backed test explanation map without executing tests."""

from __future__ import annotations

import argparse
import ast
import hashlib
import html
import json
import os
import re
import tempfile
from collections import defaultdict
from pathlib import Path

MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_NODES = 100_000
LANGUAGES = {
    "zh-TW": {
        "title": "Paperfact 測試說明地圖",
        "notice": "這是測試情境與收集清單，不是執行結果；產生本頁不會執行測試或呼叫 AI。",
        "search": "搜尋功能、操作或預期結果",
        "only": "只看已整理的說明",
        "reviewed": "已整理的說明",
        "unknown": "尚未撰寫逐項說明",
        "stale": "待重新審閱：來源或收集條件已改變",
        "cases": "展開案例",
        "functions": "測試函式",
        "files": "測試檔",
        "entries": "已整理函式",
        "scenario": "測試情境",
        "actions": "操作步驟",
        "outcomes": "預期結果",
        "risk": "防止的問題",
        "limits": "未驗證範圍",
        "source": "程式與參數",
        "inventory": "收集清單已變更；以下逐項核對來源與參數。",
        "missing": "沒有符合的項目。",
        "revision": "說明審閱的版本",
        "not_quality": "案例數包含參數變體，不能換算成功能完成率或學術品質。",
    },
    "en": {
        "title": "Paperfact test explanation map",
        "notice": "A scenario and collection map, not execution results. Building it runs no "
        "tests or AI.",
        "search": "Search features, actions or expected outcomes",
        "only": "Reviewed explanations only",
        "reviewed": "Reviewed explanation",
        "unknown": "No reviewed explanation yet",
        "stale": "Needs review: source or collected cases changed",
        "cases": "Collected cases",
        "functions": "Test functions",
        "files": "Test files",
        "entries": "Documented functions",
        "scenario": "Scenario",
        "actions": "Actions",
        "outcomes": "Expected outcomes",
        "risk": "Risk protected",
        "limits": "Not proven",
        "source": "Source and parameters",
        "inventory": "Collection inventory changed; source and parameters are checked per entry.",
        "missing": "No matching items.",
        "revision": "Explanations reviewed against",
        "not_quality": "Case counts include parameter variants, not feature completion or "
        "scientific quality.",
    },
}


class ReportError(ValueError):
    """Invalid catalog/inventory, never an instruction to relax a regression."""


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReportError("Duplicate JSON field")
        result[key] = value
    return result


def _read(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise ReportError("Report input exceeds its byte bound")
    try:
        value = json.loads(
            data.decode("utf-8-sig"),
            object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ReportError("Nonfinite JSON value")),
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ReportError("Invalid report JSON") from exc
    return value, hashlib.sha256(data).hexdigest()


def _function(node):
    if not isinstance(node, str) or len(node) > 16_384:
        raise ReportError("Invalid collected node")
    base = node.split("[", 1)[0]
    parts = base.split("::")
    file = Path(parts[0])
    if (
        len(parts) < 2
        or file.is_absolute()
        or ".." in file.parts
        or not parts[0].startswith("tests/")
        or file.suffix != ".py"
        or not all(part.isidentifier() for part in parts[1:])
        or not parts[-1].startswith("test_")
    ):
        raise ReportError("Invalid collected test identity")
    return base


def _source(root, entry, catalog):
    source = entry.get("source", {})
    if not isinstance(source, dict):
        raise ReportError("Invalid source descriptor")
    relative, function = source.get("path"), source.get("function")
    if not isinstance(relative, str) or not isinstance(function, str):
        raise ReportError("Catalog source identity is missing")
    if entry["id"] != relative + "::" + function:
        raise ReportError("Catalog/source identity mismatch")
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or not target.is_relative_to((root / "tests").resolve()):
        raise ReportError("Catalog source escapes tests")
    digest = source.get("sha256")
    if digest is None:
        paths = {
            item.get("source", {}).get("path")
            for item in catalog["entries"]
            if isinstance(item, dict) and isinstance(item.get("source"), dict)
        }
        if len(paths) == 1:
            digest = catalog.get("reviewed_source_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        return "missing_source_digest"
    try:
        data = target.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            return "source_changed"
        tree = ast.parse(data)
    except (OSError, SyntaxError):
        return "source_unavailable"
    found = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function
        for node in tree.body
    )
    return None if found else "function_missing"


def build_model(root, catalog_path, inventory_path):
    """Join exact IDs; reviewed prose never substitutes for missing source evidence."""
    root = Path(root).resolve()
    catalog, _ = _read(catalog_path)
    inventory, inventory_digest = _read(inventory_path)
    if (
        not isinstance(catalog, dict)
        or catalog.get("format") != "paperfact.test-catalog.v1"
        or not isinstance(catalog.get("entries"), list)
    ):
        raise ReportError("Unsupported test catalog")
    skipped = inventory.get("collection_skipped", 0) if isinstance(inventory, dict) else 0
    if type(skipped) is not int or skipped < 0:
        raise ReportError("Invalid skipped collection count")
    scope = (
        inventory.get("collection_scope", "unspecified")
        if isinstance(inventory, dict)
        else "unspecified"
    )
    selection = inventory.get("selection", []) if isinstance(inventory, dict) else []
    if (
        not isinstance(scope, str)
        or scope not in {"full", "selected", "unspecified"}
        or not isinstance(selection, list)
        or any(not isinstance(value, str) for value in selection)
        or (scope == "full" and selection != ["tests"])
        or (scope == "selected" and not selection)
    ):
        raise ReportError("Invalid collection scope")
    nodes = inventory.get("nodes") if isinstance(inventory, dict) else None
    if not isinstance(nodes, list) or len(nodes) > MAX_NODES:
        raise ReportError("Invalid collection inventory")
    by_function = defaultdict(list)
    for node in nodes:
        by_function[_function(node)].append(node)
    if len(nodes) != len(set(nodes)):
        raise ReportError("Repeated collected node")
    files = {name.split("::", 1)[0] for name in by_function}
    counts = {
        "node_count": len(nodes),
        "unique_test_functions": len(by_function),
        "test_files": len(files),
        "parameter_expansion_extra_cases": len(nodes) - len(by_function),
    }
    for key, value in counts.items():
        if key in inventory and (type(inventory[key]) is not int or inventory[key] != value):
            raise ReportError("Collection counts disagree with exact nodes")
    entries, seen = [], set()
    for entry in catalog["entries"]:
        if not isinstance(entry, dict) or "id" not in entry:
            raise ReportError("Invalid catalog entry")
        identity = entry["id"]
        if _function(identity) != identity or identity in seen:
            raise ReportError("Duplicate or parameterized catalog function")
        seen.add(identity)
        parameter_matrix = entry.get("parameter_matrix")
        if not isinstance(parameter_matrix, dict):
            raise ReportError("Invalid parameter matrix")
        matrix = parameter_matrix.get("cases")
        if not isinstance(matrix, list):
            raise ReportError("Missing exact parameter matrix")
        expected = [case.get("node_id") for case in matrix if isinstance(case, dict)]
        if (
            len(expected) != len(matrix)
            or any(not isinstance(n, str) for n in expected)
            or len(expected) != len(set(expected))
            or any(_function(n) != identity for n in expected)
            or type(entry.get("case_count")) is not int
            or entry["case_count"] != len(expected)
        ):
            raise ReportError("Invalid exact parameter matrix")
        for language in LANGUAGES:
            prose = entry.get(language)
            if not isinstance(prose, dict):
                raise ReportError("Missing reviewed language")
            for key in ("title", "scenario", "risk_protected"):
                if not isinstance(prose.get(key), str) or not prose[key]:
                    raise ReportError("Missing reviewed text")
            for key in ("actions", "expected_outcomes", "not_proven"):
                if (
                    not isinstance(prose.get(key), list)
                    or not prose[key]
                    or any(not isinstance(text, str) or not text for text in prose[key])
                ):
                    raise ReportError("Missing reviewed steps or limits")
        issues = []
        issue = _source(root, entry, catalog)
        if issue:
            issues.append(issue)
        actual = sorted(by_function.get(identity, []))
        if sorted(expected) != actual:
            issues.append("parameter_matrix_changed")
        entries.append({"entry": entry, "nodes": actual, "issues": issues})
    return {
        "counts": counts,
        "entries": entries,
        "undocumented": {
            key: sorted(value) for key, value in by_function.items() if key not in seen
        },
        "reviewed_against": catalog.get("reviewed_against", "unknown"),
        "inventory_changed": inventory_digest != catalog.get("collection_inventory_sha256"),
        "execution_status": "not_executed",
        "collection_skipped": skipped,
        "collection_scope": scope,
        "selection": selection,
    }


def _escape(value):
    return html.escape(str(value), quote=True)


def _list(values):
    return "<ol>" + "".join("<li>" + _escape(value) + "</li>" for value in values) + "</ol>"


def render(model, language="zh-TW"):
    if language not in LANGUAGES:
        raise ReportError("Unsupported report language")
    labels = LANGUAGES[language]
    e = _escape
    cards = []
    for item in model["entries"]:
        entry, issues = item["entry"], item["issues"]
        prose = entry[language]
        status = labels["stale"] if issues else labels["reviewed"]
        search = " ".join(
            [entry["id"], entry.get("primary_group", ""), *[str(v) for v in prose.values()]]
        )
        body = f'<p class="tag">{e(status)}</p><h2>{e(prose["title"])}</h2>'
        if issues:
            body += '<p class="warning">' + e(", ".join(issues)) + "</p>"
        body += f"<h3>{e(labels['scenario'])}</h3><p>{e(prose['scenario'])}</p>"
        body += f"<h3>{e(labels['actions'])}</h3>" + _list(prose["actions"])
        body += f"<h3>{e(labels['outcomes'])}</h3>" + _list(prose["expected_outcomes"])
        body += f"<h3>{e(labels['risk'])}</h3><p>{e(prose['risk_protected'])}</p>"
        body += f"<h3>{e(labels['limits'])}</h3>" + _list(prose["not_proven"])
        body += f"<details><summary>{e(labels['source'])} · {len(item['nodes'])} "
        body += e(labels["cases"]) + "</summary><code>" + e(entry["id"]) + "</code>"
        body += _list(item["nodes"]) + "</details>"
        cards.append(f'<article data-reviewed="yes" data-search="{e(search)}">{body}</article>')
    by_file = defaultdict(list)
    for identity, nodes in model["undocumented"].items():
        by_file[identity.split("::", 1)[0]].append((identity, nodes))
    for file, entries in sorted(by_file.items()):
        body = "<details><summary>" + e(file) + f" · {len(entries)} " + e(labels["functions"])
        body += "</summary><p>" + e(labels["unknown"]) + "</p>"
        for identity, nodes in entries:
            body += "<details><summary><code>" + e(identity) + f"</code> · {len(nodes)}</summary>"
            body += _list(nodes) + "</details>"
        body += "</details>"
        cards.append(
            f'<article data-reviewed="no" data-search="{e(str(entries))}">{body}</article>'
        )
    metrics = [
        (model["counts"]["test_files"], labels["files"]),
        (model["counts"]["unique_test_functions"], labels["functions"]),
        (model["counts"]["node_count"], labels["cases"]),
        (len(model["entries"]), labels["entries"]),
    ]
    top = "".join(
        f"<div><strong>{number:,}</strong><span>{e(label)}</span></div>"
        for number, label in metrics
    )
    warning = (
        '<p class="warning">' + e(labels["inventory"]) + "</p>"
        if model["inventory_changed"]
        else ""
    )
    if model.get("collection_skipped"):
        skipped_text = (
            "\u6536\u96c6\u6642\u6709\u6a94\u6848\u88ab\u8df3\u904e\uff0c"
            "\u6b64\u6e05\u55ae\u4e26\u4e0d\u5b8c\u6574\u3002"
            if language == "zh-TW"
            else "Collection skipped files; this inventory is incomplete."
        )
        warning += '<p class="warning">' + e(skipped_text) + "</p>"
    if model.get("collection_scope") == "selected":
        scope_text = (
            "\u50c5\u6536\u96c6\u9078\u5b9a\u7bc4\u570d: "
            if language == "zh-TW"
            else "Selected collection only: "
        )
        warning += '<p class="warning">' + e(scope_text) + e(", ".join(model["selection"])) + "</p>"
    elif model.get("collection_scope") == "unspecified":
        scope_text = (
            "\u6536\u96c6\u7bc4\u570d\u672a\u8a18\u9304\uff1b"
            "\u672c\u9801\u4ee5\u63d0\u4f9b\u7684\u6e05\u55ae\u70ba\u6e96\u3002"
            if language == "zh-TW"
            else "Collection scope was not recorded in the supplied inventory."
        )
        warning += '<p class="tag">' + e(scope_text) + "</p>"
    values = {
        "LANG": e(language),
        "TITLE": e(labels["title"]),
        "NOTICE": e(labels["notice"]),
        "METRICS": top,
        "REVISION": e(labels["revision"]) + ": " + e(model["reviewed_against"]),
        "QUALITY": e(labels["not_quality"]),
        "WARNING": warning,
        "SEARCH": e(labels["search"]),
        "ONLY": e(labels["only"]),
        "CARDS": "\n".join(cards),
        "MISSING": e(labels["missing"]),
    }
    return re.sub(r"@@([A-Z]+)@@", lambda match: values[match[1]], TEMPLATE)


TEMPLATE = """<!doctype html>
<html lang="@@LANG@@"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none';
 style-src 'unsafe-inline';
 script-src 'unsafe-inline'">
<title>@@TITLE@@</title><style>
:root{--bg:#f4f6f8;
--surface:#fff;
--fg:#172d42;
--muted:#526477;
--line:#d5dfe7;
--accent:#12624e}

*{box-sizing:border-box}
body{margin:0;
background:var(--bg);
color:var(--fg);
font:16px/1.65 system-ui,sans-serif}

main{max-width:1000px;overflow-wrap:anywhere;
margin:0 auto;
padding:40px 24px}
h1{font-size:32px;
line-height:1.25;
margin:0 0 16px}

h2{font-size:24px;
line-height:1.4;
margin:4px 0 20px}
h3{font-size:16px;
margin:20px 0 4px}
p{margin:8px 0}

.metrics{display:grid;
grid-template-columns:repeat(4,1fr);
gap:16px;
margin:24px 0}
.metrics div,article{background:var(--surface);
border:1px solid var(--line);
border-radius:12px;
padding:24px}

.metrics strong{display:block;
font-size:28px}
.metrics span,.tag{color:var(--muted);
font-size:14px}

article{margin:16px 0}
ol{padding-left:24px;
margin:8px 0}
li{margin:6px 0}
.warning{color:#80430b}

.controls{margin:24px 0}
label{display:block;
margin:12px 0 8px}
input[type=search]{width:100%;
font:inherit;
border:1px solid var(--line);
border-radius:8px;
padding:12px;
background:var(--surface);
color:var(--fg)}

input[type=checkbox]{width:18px;
height:18px;
vertical-align:middle;
margin-right:8px;
accent-color:var(--accent)}

summary{cursor:pointer;
padding:8px 0;
border-radius:4px}
summary:hover{color:var(--accent)}
summary:active{opacity:.75}

:focus-visible{outline:3px solid var(--accent);
outline-offset:4px}
code{font-size:13px;
overflow-wrap:anywhere}
details details{margin-left:12px}
details ol{overflow-wrap:anywhere}

[hidden]{display:none!important}
@media(max-width:600px){main{padding:24px 16px}
h1{font-size:28px}
h2{font-size:20px}
.metrics{grid-template-columns:repeat(2,1fr);
gap:8px}
.metrics div,article{padding:16px}
}

@media(prefers-color-scheme:dark){:root{--bg:#101b25;
--surface:#182834;
--fg:#ecf3f8;
--muted:#b3c4d2;
--line:#40586b;
--accent:#76d2b7}
.warning{color:#f4c593}
}

</style></head><body><main><h1>@@TITLE@@</h1><p>@@NOTICE@@</p>
<div class="metrics">@@METRICS@@</div>
<p>@@QUALITY@@</p><p><small>@@REVISION@@</small></p>
@@WARNING@@
<div class="controls"><label for="search">@@SEARCH@@</label>
<input id="search" type="search" autocomplete="off">
<label><input id="reviewed" type="checkbox" checked>@@ONLY@@</label></div>
<section aria-label="Test explanations">@@CARDS@@</section>
<p id="empty" hidden role="status">@@MISSING@@</p>
</main><script>
const search=document.querySelector('#search'), reviewed=document.querySelector('#reviewed');

const cards=[...document.querySelectorAll('article')];

function filter(){const q=search.value.trim().toLocaleLowerCase();
let count=0;

for(const card of cards){card.hidden=(reviewed.checked&&card.dataset.reviewed!=='yes')||
!card.dataset.search.toLocaleLowerCase().includes(q);
if(!card.hidden)count++;
}

document.querySelector('#empty').hidden=count!==0;
}

search.addEventListener('input',filter);
reviewed.addEventListener('change',filter);

search.value=new URLSearchParams(location.search).get('q')||'';
filter();

</script></body></html>"""


def write_report(root, catalog_path, inventory_path, output, *, language="zh-TW"):
    root, output = Path(root).resolve(), Path(output).resolve()
    build = (root / "build").resolve()
    if (
        not build.is_relative_to(root)
        or not output.is_relative_to(build)
        or output.suffix != ".html"
    ):
        raise ReportError("Generated HTML must stay inside the workspace build directory")
    model = build_model(root, catalog_path, inventory_path)
    rendered = render(model, language)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False, dir=output.parent, suffix=".tmp"
        ) as stream:
            temporary = Path(stream.name)
            stream.write(rendered)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return model


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--catalog", type=Path, default=Path("docs/testing/catalog.json"))
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("build/test-explanations.html"))
    parser.add_argument("--language", choices=tuple(LANGUAGES), default="zh-TW")
    options = parser.parse_args(argv)
    root = options.root.resolve()
    try:
        model = write_report(
            root,
            root / options.catalog,
            root / options.inventory,
            root / options.output,
            language=options.language,
        )
    except (ReportError, OSError) as exc:
        parser.exit(1, f"Test report could not be generated: {type(exc).__name__}.\n")
    print(
        json.dumps(
            {
                "status": "explanation_map_generated",
                "execution_status": "not_executed",
                "counts": model["counts"],
                "documented_functions": len(model["entries"]),
                "needs_review": sum(bool(item["issues"]) for item in model["entries"]),
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
