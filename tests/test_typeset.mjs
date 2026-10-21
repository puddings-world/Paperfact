import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync("src/paper_daily/typeset.js", "utf8");
const context = vm.createContext({ window: {} });
vm.runInContext(source + "\nthis.Typeset = Typeset;", context);
const { protect, restore } = context.Typeset;

test("formulas are lifted out before Markdown sees their underscores", () => {
  const { text, math } = protect("Loss $L_t = a_t^2$ and\n\n$$\n\\sum_t x_t\n$$\n");
  assert.equal(text, "Loss @@MATH0@@ and\n\n@@MATH1@@\n");
  assert.equal(JSON.stringify(math.map((m) => [m.tex, m.display])), JSON.stringify([["L_t = a_t^2", false], ["\n\\sum_t x_t\n", true]]));
});

test("prices, code and fenced blocks keep their dollars", () => {
  const src = "costs $5 and $10\n\n`echo $HOME`\n\n```\nx = $y$\n```";
  assert.equal(protect(src).text, src);
});

test("without KaTeX the source is shown, escaped", () => {
  const { text, math } = protect("see $a<b$");
  assert.equal(restore(text, math), "see a&lt;b");
});
