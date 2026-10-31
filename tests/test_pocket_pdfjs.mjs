import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

// Exercise the shipped calls, not a copied parser wrapper. The workaround is
// documented at https://github.com/mozilla/pdf.js/security/advisories/GHSA-wgrm-67xf-hhpq.
const exported = process.env.PAPERFACT_POCKET_TEST_HTML;
const html = readFileSync(exported || "src/paper_daily/pocket_reader.html", "utf8");
const declaration = (name) => {
  const match = html.match(new RegExp(`^const ${name} = .+;$`, "m"));
  assert.ok(match, `actual ${name} declaration exists`);
  return match[0];
};
const functionBody = (name, next) => {
  const begin = html.indexOf(`async function ${name}(`);
  const end = html.indexOf(`async function ${next}(`, begin);
  assert.ok(begin >= 0 && end > begin, `actual ${name} parser boundary exists`);
  return html.slice(begin, end);
};
const code = [
  declaration("PAPERS"), declaration("pdf"), declaration("fullText"),
  functionBody("openPdf", "showPage"), functionBody("paperText", "askWhole"),
  "globalThis.reader = { openPdf, paperText, pdf, papers: PAPERS };",
].join("\n");

function documentFixture() {
  return {
    numPages: 2,
    destroyed: 0,
    async getPage(page) {
      return { async getTextContent() {
        return { items: [{ str: `Text ${page}`, hasEOL: true }, { str: "end" }] };
      } };
    },
    destroy() { this.destroyed += 1; },
  };
}

function readerFixture(load = () => documentFixture()) {
  const calls = [], shown = [];
  const elements = { pages: { innerHTML: "" }, pagejump: { innerHTML: "" } };
  const pdfjsLib = {
    GlobalWorkerOptions: {},
    getDocument(options) {
      calls.push({ ...options });
      return { promise: Promise.resolve().then(() => load(options)) };
    },
  };
  const context = vm.createContext({
    pdfjsLib,
    document: { getElementById: (id) => {
      assert.ok(Object.hasOwn(elements, id));
      return elements[id];
    } },
    savedPage: () => 2,
    esc: (value) => String(value).replaceAll("<", "&lt;"),
    showPage: (token) => shown.push(token),
  });
  vm.runInContext(code, context);
  const reader = context.reader;
  if (exported) {
    assert.equal(reader.papers.length, 1);
    assert.equal(reader.papers[0].id, "ref:a");
    assert.ok(reader.papers[0].pdf, "the exported original has a real served PDF");
  }
  const paper = (reader.papers || []).find((item) => item.pdf)
    || { id: "fixture-paper", pdf: "pdf/original.pdf" };
  return { ...reader, context, pdfjsLib, paper, calls, shown, elements };
}

function assertSafeCall(options, paper) {
  assert.deepEqual(options, { url: paper.pdf, isEvalSupported: false });
}

test("pocket display disables eval on its actual PDF.js document load", async () => {
  const doc = documentFixture();
  const reader = readerFixture(() => doc);
  await reader.openPdf(reader.paper, reader.pdf.token);
  assert.equal(reader.calls.length, 1);
  assertSafeCall(reader.calls[0], reader.paper);
  assert.equal(reader.pdfjsLib.GlobalWorkerOptions.workerSrc, "lib/pdf.worker.min.js");
  assert.equal(reader.pdf.doc, doc);
  assert.equal(reader.pdf.id, reader.paper.id);
  assert.equal(reader.pdf.page, 2);
  assert.equal(reader.pdf.count, 2);
  assert.deepEqual(reader.shown, [reader.pdf.token]);
  assert.match(reader.elements.pagejump.innerHTML, /data-page="2"/);
});

test("pocket full-paper extraction disables eval and caches the extracted text", async () => {
  const doc = documentFixture();
  const reader = readerFixture(() => doc);
  const text = await reader.paperText(reader.paper);
  assert.equal(reader.calls.length, 1);
  assertSafeCall(reader.calls[0], reader.paper);
  assert.equal(text, "[第 1 頁]\nText 1\nend\n\n[第 2 頁]\nText 2\nend");
  assert.equal(doc.destroyed, 1);
  assert.equal(await reader.paperText(reader.paper), text);
  assert.equal(reader.calls.length, 1);
});

test("text extraction reuses the safely loaded display document without destroying it", async () => {
  const doc = documentFixture();
  const reader = readerFixture(() => doc);
  await reader.openPdf(reader.paper, reader.pdf.token);
  assert.match(await reader.paperText(reader.paper), /Text 2/);
  assert.equal(reader.calls.length, 1);
  assertSafeCall(reader.calls[0], reader.paper);
  assert.equal(doc.destroyed, 0);
});

test("failed display load remains retryable and every retry disables eval", async () => {
  let fail = true;
  const reader = readerFixture(() => {
    if (fail) throw new Error("fixture PDF unavailable");
    return documentFixture();
  });
  await reader.openPdf(reader.paper, reader.pdf.token);
  assert.equal(reader.pdf.doc, null);
  assert.match(reader.elements.pages.innerHTML, /PDF 開不起來:fixture PDF unavailable/);
  assert.deepEqual(reader.shown, []);
  fail = false;
  await reader.openPdf(reader.paper, reader.pdf.token);
  assert.equal(reader.calls.length, 2);
  reader.calls.forEach((options) => assertSafeCall(options, reader.paper));
  assert.deepEqual(reader.shown, [reader.pdf.token]);
});

test("failed extraction does not cache failure and retries with eval disabled", async () => {
  let fail = true;
  const reader = readerFixture(() => {
    if (fail) throw new Error("fixture extraction unavailable");
    return documentFixture();
  });
  await assert.rejects(reader.paperText(reader.paper), /fixture extraction unavailable/);
  fail = false;
  assert.match(await reader.paperText(reader.paper), /Text 1/);
  assert.equal(reader.calls.length, 2);
  reader.calls.forEach((options) => assertSafeCall(options, reader.paper));
});

test("unavailable PDF.js and papers without PDFs do not invoke the parser", async () => {
  const reader = readerFixture();
  assert.equal(await reader.paperText({ id: "empty", pdf: null }), "");
  reader.context.pdfjsLib = undefined;
  await reader.openPdf(reader.paper, reader.pdf.token);
  assert.match(reader.elements.pages.innerHTML, /PDF 元件沒有載入/);
  assert.equal(await reader.paperText(reader.paper), "");
  assert.deepEqual(reader.calls, []);
});
