"""Markdown to a web page for the reading views: typeset formulas, highlighted code,
algorithm boxes and drawn diagrams.

The deep dives and answers are technical writing, and Qt's rich text shows a
formula as a line of monospace, a diagram as box-drawing characters that drift
apart wherever Chinese appears, and pseudocode as plain text. This renders the same
Markdown for a web view instead:

- `$...$` and `$$...$$` become KaTeX formulas (a lone `$5` stays a price);
- a ```mermaid block is drawn as a diagram;
- a ```pseudocode (or ```algorithm) block becomes a numbered algorithm box, its
  title taken from the rest of the fence line (```pseudocode Algorithm 1 · MPC);
- other fenced code is highlighted by language;
- an unlabelled block -- the older dives' box diagrams -- keeps every wide character
  exactly two columns, so its lines meet again.

Only the HTML is made here, with no Qt, so it can be tested on its own; the page
loads KaTeX, highlight.js and Mermaid from `vendor/web` (see web_assets).
"""

from __future__ import annotations

import html
import re
import unicodedata

from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin

from paper_daily import fonts as font_files

PSEUDO = ("pseudocode", "algorithm", "algo")
PLAIN = ("", "text", "txt", "plain", "diagram", "ascii")
_KEYWORDS = re.compile(
    r"\b(for|for each|foreach|while|do|if|then|else|elif|else if|end|endfor|endwhile|"
    r"endif|return|function|procedure|def|input|output|require|ensure|repeat|until|"
    r"in|to|and|or|not|break|continue|let|parallel|yield)\b",
    re.IGNORECASE,
)
_COMMENT = re.compile(r"(//|#|▷|⊳).*$")


def _parser() -> MarkdownIt:
    # Raw HTML stays escaped: the text comes from a model, and the page runs scripts.
    md = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
    md.enable(["table", "strikethrough"])
    # No space inside the dollars and none of `$5 and $10` read as a formula.
    md.use(dollarmath_plugin, allow_space=False, allow_digits=False, double_inline=True)
    md.add_render_rule("fence", _fence)
    md.add_render_rule("code_block", _fence)
    return md


def _columns(text: str) -> str:
    """Escape, and pin each non-ASCII character to its terminal width in columns."""
    out = []
    for char in text:
        if ord(char) < 128:
            out.append(html.escape(char))
            continue
        wide = unicodedata.east_asian_width(char) in ("W", "F")
        out.append(f'<span class="{"c2" if wide else "c1"}">{html.escape(char)}</span>')
    return "".join(out)


def _pseudo_line(line: str) -> str:
    comment = _COMMENT.search(line)
    code, note = (line[: comment.start()], comment.group(0)) if comment else (line, "")
    code = _KEYWORDS.sub(lambda m: f'<b class="kw">{m.group(0)}</b>', html.escape(code))
    if note:
        code += f'<span class="cm">{html.escape(note)}</span>'
    return f'<span class="ln">{code or " "}</span>'


def _fence(self, tokens, idx, options, env) -> str:
    token = tokens[idx]
    info = (token.info or "").strip()
    lang, _, rest = info.partition(" ")
    lang = lang.lower()
    body = token.content.rstrip("\n")
    if lang == "mermaid":
        return f'<pre class="mermaid">{html.escape(body)}</pre>\n'
    if lang in PSEUDO:
        title = rest.strip() or "Algorithm"
        lines = "".join(_pseudo_line(line) for line in body.split("\n"))
        return (
            f'<figure class="algo"><figcaption>{html.escape(title)}</figcaption>'
            f"<pre><code>{lines}</code></pre></figure>\n"
        )
    if lang in PLAIN:
        return f'<pre class="plain"><code>{_columns(body)}</code></pre>\n'
    return (
        f'<pre class="code"><span class="lang">{html.escape(lang)}</span>'
        f'<code class="language-{html.escape(lang)}">{html.escape(body)}</code></pre>\n'
    )


_MD = _parser()


def _isolate_display(src: str) -> str:
    """Give a `$$` block blank lines around it. Written straight under a sentence,
    as models do, it would otherwise be read as part of that paragraph and set
    inline."""
    out: list[str] = []
    fence = in_math = False
    for line in src.split("\n"):
        bare = line.strip()
        if bare.startswith("```"):
            fence = not fence
        elif not fence and bare.startswith("$$"):
            whole = len(bare) > 4 and bare.endswith("$$")
            opening = not in_math
            if opening and out and out[-1].strip():
                out.append("")
            out.append(line)
            if whole or not opening:
                out.append("")
            if not whole:
                in_math = not in_math
            continue
        out.append(line)
    return "\n".join(out)


def markdown(src: str) -> str:
    return _MD.render(_isolate_display(src or ""))


def _dark(palette: dict[str, str]) -> bool:
    ground = palette["ground"].lstrip("#")
    r, g, b = (int(ground[i : i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) < 128


def _font_faces() -> str:
    faces = []
    for spec in font_files.FONTS:
        path = font_files.FONT_DIR / spec["file"]
        if path.exists():
            faces.append(
                f'@font-face{{font-family:"{spec["family"]}";'
                f'src:url("{path.as_uri()}");font-weight:100 900;}}'
            )
    return "".join(faces)


def css(palette: dict[str, str]) -> str:
    p = palette
    return (
        _font_faces()
        + f"""
:root {{ color-scheme: {"dark" if _dark(p) else "light"}; }}
html {{ background:{p["ground"]}; }}
body {{ margin:0; padding:20px 26px 48px; color:{p["ink"]}; background:{p["ground"]};
  font: 15px/1.75 "Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif;
  -webkit-font-smoothing:antialiased; }}
main {{ max-width: 860px; margin: 0 auto; }}
h1,h2,h3,h4 {{ line-height:1.35; margin:1.6em 0 .55em; font-weight:650; }}
h1 {{ font-size:22px; }} h2 {{ font-size:18px; padding-bottom:6px;
  border-bottom:1px solid {p["border"]}; }}
h3 {{ font-size:16px; }} h4 {{ font-size:15px; color:{p["muted"]}; }}
main > :first-child {{ margin-top:0; }}
p {{ margin:0 0 .9em; }} ul,ol {{ margin:0 0 1em; padding-left:1.5em; }}
li {{ margin:.2em 0; }} strong {{ font-weight:650; }}
a {{ color:{p["accent"]}; text-decoration:none; }} a:hover {{ text-decoration:underline; }}
hr {{ border:0; border-top:1px solid {p["border"]}; margin:2em 0; }}
blockquote {{ margin:0 0 1em; padding:.4em 1em; color:{p["muted"]};
  border-left:3px solid {p["firm"]}; background:{p["surface"]}; }}
code {{ font: .9em "JetBrains Mono",Consolas,Menlo,monospace;
  background:{p["sunk"]}; padding:.1em .35em; border-radius:4px; }}
pre {{ margin:0 0 1.1em; padding:12px 14px; overflow-x:auto; border-radius:6px;
  background:{p["sunk"]}; border:1px solid {p["border"]};
  font: 13px/1.55 "JetBrains Mono",Consolas,Menlo,monospace; }}
pre code, pre code.hljs {{ background:none; padding:0; font:inherit; }}
pre.code {{ position:relative; }}
pre.code .lang {{ position:absolute; top:4px; right:8px; font-size:11px; color:{p["faint"]};
  font-family:"Noto Sans TC",sans-serif; }}
pre.plain .c1,pre.plain .c2 {{ display:inline-block; text-align:center; overflow:visible; }}
pre.plain .c1 {{ width:1ch; }} pre.plain .c2 {{ width:2ch; }}
pre.plain {{ line-height:1.25; }}
figure.algo {{ margin:0 0 1.2em; border:1px solid {p["firm"]}; border-radius:6px;
  background:{p["surface"]}; overflow:hidden; }}
figure.algo figcaption {{ padding:6px 14px; font-weight:650; font-size:14px;
  border-bottom:1px solid {p["firm"]}; background:{p["sunk"]}; }}
figure.algo pre {{ margin:0; border:0; border-radius:0; background:none;
  counter-reset:line; }}
figure.algo .ln {{ display:block; padding-left:3.2em; text-indent:-3.2em; }}
figure.algo .ln::before {{ counter-increment:line; content:counter(line);
  display:inline-block; width:2.4em; margin-right:.8em; text-align:right;
  color:{p["faint"]}; text-indent:0; }}
figure.algo .kw {{ color:{p["accent"]}; font-weight:700; }}
figure.algo .cm {{ color:{p["done"]}; font-style:italic; }}
pre.mermaid {{ background:{p["surface"]}; text-align:center; font-family:inherit; }}
pre.mermaid.drawn {{ overflow-x:auto; }}
table {{ border-collapse:collapse; margin:0 0 1.2em; font-size:14px; display:block;
  overflow-x:auto; max-width:100%; }}
th,td {{ border:1px solid {p["border"]}; padding:6px 10px; text-align:left;
  vertical-align:top; }}
th {{ background:{p["sunk"]}; font-weight:650; }}
tbody tr:nth-child(even) td {{ background:{p["surface"]}; }}
.math.block {{ margin:.2em 0 1.1em; overflow-x:auto; overflow-y:hidden; padding:4px 0; }}
.katex {{ font-size:1.08em; }}
figure.paper {{ margin:1em 0 1.4em; text-align:center; }}
figure.paper img {{ max-width:100%; height:auto; border:1px solid {p["border"]};
  border-radius:4px; background:#fff; }}
figure.paper figcaption {{ margin-top:6px; color:{p["muted"]}; font-size:12.5px;
  line-height:1.5; }}
aside.evidence {{ margin:.4em 0 1.4em; padding:10px 14px; font-size:14px;
  background:{p["surface"]}; border:1px solid {p["border"]};
  border-left:3px solid {p["accent"]}; border-radius:4px; }}
aside.evidence .head {{ font-weight:650; margin-bottom:4px; }}
aside.evidence .head a {{ font-weight:400; margin-left:10px; font-size:13px; }}
aside.evidence .label {{ font-weight:650; color:{p["muted"]}; font-size:13px; }}
aside.evidence p {{ margin:.1em 0 .6em; }}
.note {{ color:{p["muted"]}; }}
article.qa {{ margin:0 0 14px; border:1px solid {p["border"]}; border-radius:6px;
  overflow:hidden; background:{p["surface"]}; }}
article.qa header {{ padding:9px 14px; background:{p["accentSoft"]}; }}
article.qa header .where {{ color:{p["accent"]}; font-size:11px; }}
article.qa header .ask {{ font-weight:650; font-size:14px; }}
article.qa header .passage {{ color:{p["muted"]}; font-size:12px; margin-top:3px; }}
article.qa .answer {{ padding:10px 14px 2px; font-size:14px; }}
article.qa footer {{ padding:0 14px 8px; text-align:right; font-size:12px; }}
article.qa footer a {{ margin-left:14px; }}
article.qa footer a.quiet {{ color:{p["faint"]}; }}
.thinking {{ color:{p["faint"]}; }}
.empty {{ color:{p["faint"]}; font-size:13px; }}
::selection {{ background:{p["accentSoft"]}; }}
"""
    )


_SCRIPT = """
function renderAll() {
  if (window.katex) {
    document.querySelectorAll('.math').forEach(function (el) {
      try {
        katex.render(el.textContent, el, {
          displayMode: el.classList.contains('block') || el.tagName === 'DIV',
          throwOnError: false,
          strict: 'ignore', output: 'html' });
      } catch (e) { el.classList.add('math-error'); }
    });
  }
  if (window.hljs) {
    document.querySelectorAll('pre.code code').forEach(function (el) {
      var lang = (el.className.match(/language-(\\S+)/) || [])[1];
      if (lang && hljs.getLanguage(lang)) hljs.highlightElement(el);
    });
  }
  if (window.mermaid) {
    mermaid.initialize({ startOnLoad: false, theme: MERMAID_THEME, securityLevel: 'strict',
      fontFamily: '"Noto Sans TC", sans-serif',
      // At its own size and scrolled sideways, not shrunk until the labels are dots.
      flowchart: { useMaxWidth: false }, sequence: { useMaxWidth: false } });
    // A diagram the model got wrong shows its source, not an error banner.
    document.querySelectorAll('pre.mermaid').forEach(function (el, i) {
      var source = el.textContent;
      mermaid.render('diagram' + i, source).then(function (out) {
        el.innerHTML = out.svg;
        el.classList.add('drawn');
      }).catch(function () {
        el.className = 'plain failed';
        el.textContent = source;
        var gone = document.getElementById('ddiagram' + i);
        if (gone) gone.remove();
      });
    });
  }
}
function findHeading(text) {
  var all = document.querySelectorAll('h1,h2,h3,h4');
  for (var i = 0; i < all.length; i++) {
    if (all[i].textContent.indexOf(text) >= 0) {
      all[i].scrollIntoView({ block: 'start' });
      return true;
    }
  }
  return false;
}
document.addEventListener('DOMContentLoaded', function () {
  renderAll();
  if (window.START_AT_END) window.scrollTo(0, document.body.scrollHeight);
  else if (window.START_AT) window.scrollTo(0, window.START_AT);
});
"""


def page(body: str, palette: dict[str, str], *, at_end: bool = False, at: int = 0) -> str:
    """A whole document around `body`, with its assets referenced relative to
    `vendor/web` (the view's base URL)."""
    dark = _dark(palette)
    theme = "hljs-dark.css" if dark else "hljs-light.css"
    start = "window.START_AT_END = true;" if at_end else f"window.START_AT = {int(at)};"
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<link rel="stylesheet" href="katex/katex.min.css">'
        f'<link rel="stylesheet" href="{theme}">'
        f"<style>{css(palette)}</style>"
        '<script src="katex/katex.min.js"></script>'
        '<script src="highlight.min.js"></script>'
        '<script src="mermaid.min.js"></script>'
        f"<script>var MERMAID_THEME = '{'dark' if dark else 'neutral'}';{start}"
        f"{_SCRIPT}</script>"
        f"</head><body><main>{body}</main></body></html>"
    )
