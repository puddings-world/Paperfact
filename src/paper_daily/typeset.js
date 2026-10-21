/* Typesetting shared by the pages built outside the desktop app (the pocket page
   and share pages): KaTeX formulas, Mermaid diagrams and numbered algorithm boxes,
   matching what the reader shows. Inlined into each page by its builder.

   Formulas are lifted out before the Markdown is parsed, so `_` and `*` inside
   them are never read as emphasis, and put back afterwards as KaTeX's HTML. A page
   without KaTeX or Mermaid loaded still shows the source text. */
const Typeset = (() => {
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  // No space just inside the dollars and no digit after the closing one, so
  // "$5 and $10" stays prose.
  const INLINE = /\$(?!\s)((?:\\\$|[^$\n])+?)(?<!\s)\$(?!\d)/g;

  function protect(src) {
    const math = [];
    const out = [];
    let fence = false;
    let block = null;
    for (const line of String(src || "").split("\n")) {
      if (/^\s*```/.test(line)) { fence = !fence; out.push(line); continue; }
      if (fence) { out.push(line); continue; }
      const trimmed = line.trim();
      if (block !== null) {
        if (trimmed.endsWith("$$")) {
          block.push(trimmed.slice(0, -2));
          math.push({ tex: block.join("\n"), display: true });
          out.push(`@@MATH${math.length - 1}@@`);
          block = null;
        } else block.push(line);
        continue;
      }
      if (trimmed.startsWith("$$")) {
        const rest = trimmed.slice(2);
        if (rest.endsWith("$$") && rest.length > 2) {
          math.push({ tex: rest.slice(0, -2), display: true });
          out.push(`@@MATH${math.length - 1}@@`);
        } else block = [rest];
        continue;
      }
      // Inline code keeps its dollars.
      out.push(line.split(/(`[^`]*`)/).map((part) => part.startsWith("`") ? part
        : part.replace(INLINE, (_m, tex) => { math.push({ tex, display: false }); return `@@MATH${math.length - 1}@@`; })).join(""));
    }
    if (block !== null) out.push("$$" + block.join("\n"));
    return { text: out.join("\n"), math };
  }

  function restore(html, math) {
    return html.replace(/(<p>)?@@MATH(\d+)@@(<\/p>)?/g, (whole, open, n, close) => {
      const m = math[Number(n)];
      if (!m) return whole;
      let out = esc(m.tex);
      if (window.katex) {
        try {
          out = katex.renderToString(m.tex, { displayMode: m.display, throwOnError: false, strict: "ignore" });
        } catch (e) { /* the source stays */ }
      }
      if (m.display) return `<div class="math-block">${out}</div>`;
      return (open || "") + out + (close || "");
    });
  }

  const KEYWORDS = /\b(for each|for|while|do|if|then|else|end|return|function|procedure|input|output|require|ensure|repeat|until|in|to|and|or|not|break|continue)\b/gi;

  function algorithm(pre, title) {
    const lines = pre.textContent.replace(/\n$/, "").split("\n").map((line) => {
      const cut = line.search(/(\/\/|▷)/);
      const code = cut >= 0 ? line.slice(0, cut) : line;
      const note = cut >= 0 ? `<span class="cm">${esc(line.slice(cut))}</span>` : "";
      return `<span class="ln">${esc(code).replace(KEYWORDS, '<b class="kw">$1</b>')}${note || (code ? "" : " ")}</span>`;
    });
    const fig = document.createElement("figure");
    fig.className = "algo";
    fig.innerHTML = `<figcaption>${esc(title || "Algorithm")}</figcaption><pre><code>${lines.join("")}</code></pre>`;
    pre.replaceWith(fig);
  }

  let drawn = 0;
  function blocks(root) {
    for (const pre of root.querySelectorAll("pre")) {
      const code = pre.querySelector("code");
      const lang = (pre.dataset.lang || (code && (code.className.match(/language-(\S+)/) || [])[1]) || "").toLowerCase();
      if (["pseudocode", "algorithm", "algo"].includes(lang)) algorithm(pre, pre.dataset.title);
      else if (lang === "mermaid" && window.mermaid) {
        const source = pre.textContent;
        const id = `typeset-diagram-${drawn++}`;
        if (drawn === 1) mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "neutral",
          flowchart: { useMaxWidth: false } });
        mermaid.render(id, source).then((out) => {
          const div = document.createElement("div");
          div.className = "diagram";
          div.innerHTML = out.svg;
          pre.replaceWith(div);
        }).catch(() => { const stray = document.getElementById("d" + id); if (stray) stray.remove(); });
      }
    }
  }

  return { protect, restore, blocks };
})();
