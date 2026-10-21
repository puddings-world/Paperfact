import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

function element() {
  const names = new Set();
  return {
    classList: {
      contains: x => names.has(x),
      add: x => names.add(x),
      remove: x => names.delete(x),
      toggle(x, force) {
        const next = force ?? !names.has(x);
        next ? names.add(x) : names.delete(x);
        return next;
      },
    },
    disabled: false, textContent: "", onclick: null, scrolled: false,
    setAttribute(key, value) { this[key] = value; },
    scrollIntoView() { this.scrolled = true; },
    getBoundingClientRect() { return { width: 1200 }; },
    clientHeight: 675, scrollHeight: 675,
  };
}

function boot() {
  const controls = Object.fromEntries(
    ["previous", "next", "position", "notes", "present", "print"].map(x => [x, element()])
  );
  const slides = [element(), element(), element()];
  const body = element();
  const listeners = {};
  let prints = 0;
  const document = {
    body,
    querySelectorAll: () => slides,
    getElementById: id => controls[id],
    addEventListener: (type, callback) => { listeners[type] = callback; },
  };
  const window = {
    addEventListener() {},
    print() { prints++; },
  };
  const template = fs.readFileSync("src/paper_daily/presentation.html", "utf8");
  const script = template.match(/<script>([\s\S]*?)<\/script>/)[1];
  vm.runInNewContext(script, { document, window });
  return { controls, slides, body, listeners, prints: () => prints };
}

test("offline deck navigation stays within its slide boundaries", () => {
  const { controls, slides } = boot();
  assert.equal(controls.position.textContent, "1 / 3");
  assert.equal(controls.previous.disabled, true);
  controls.next.onclick();
  assert.equal(controls.position.textContent, "2 / 3");
  assert.equal(slides[1].classList.contains("active"), true);
  controls.next.onclick();
  controls.next.onclick();
  assert.equal(controls.position.textContent, "3 / 3");
  assert.equal(controls.next.disabled, true);
});

test("playback and speaker notes are independent controls", () => {
  const { controls, body } = boot();
  controls.present.onclick();
  assert.equal(body.classList.contains("present"), true);
  controls.notes.onclick();
  assert.equal(body.classList.contains("notes"), true);
  assert.equal(controls.notes["aria-pressed"], "true");
  controls.present.onclick();
  assert.equal(body.classList.contains("present"), false);
  assert.equal(body.classList.contains("notes"), true);
});

test("keyboard shortcuts and PDF printing work without a remote service", () => {
  const { controls, listeners, prints } = boot();
  let prevented = false;
  listeners.keydown({
    target: { closest: () => null }, key: "ArrowRight",
    preventDefault: () => { prevented = true; },
  });
  assert.equal(controls.position.textContent, "2 / 3");
  assert.equal(prevented, true);
  controls.print.onclick();
  assert.equal(prints(), 1);
});


test("arrow shortcuts still work after a playback button has focus", () => {
  const { controls, listeners } = boot();
  controls.present.onclick();
  listeners.keydown({
    target: { closest: selector => selector.includes("button") ? {} : null },
    key: "ArrowRight", preventDefault() {},
  });
  assert.equal(controls.position.textContent, "2 / 3");
});
