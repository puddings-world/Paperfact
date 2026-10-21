import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

for (const file of ["reader/paper-reader.html", "src/paper_daily/pocket_reader.html"]) {
  const html = readFileSync(file, "utf8");
  const begin = html.indexOf("// Paperfact capability bridge:");
  const end = html.indexOf("// End Paperfact capability bridge.", begin);
  assert.ok(begin >= 0 && end > begin, file + " supplies a capability bridge");
  const bridge = html.slice(begin, end);
  const use = (window, name) => {
    const context = vm.createContext({ window });
    vm.runInContext(bridge, context);
    return context.useCapability(name);
  };

  test(file + ": custom hosts take precedence", async () => {
    const seen = [];
    const capability = { custom: true };
    const result = await use({
      paperfact: { use: async (name) => { seen.push(name); return capability; } },
      claude: { use: () => assert.fail("must not switch to another account") },
    }, "sample");
    assert.equal(result, capability);
    assert.deepEqual(seen, ["sample"]);
  });

  test(file + ": legacy host remains supported", async () => {
    const capability = { legacy: true };
    const result = await use({ claude: { use: async (name) => {
      assert.equal(name, "db"); return capability;
    } } }, "db");
    assert.equal(result, capability);
  });

  test(file + ": failed custom capability never changes account", async () => {
    const result = await use({
      paperfact: { use: async () => { throw new Error("not granted"); } },
      claude: { use: () => assert.fail("must not fall back") },
    }, "sample");
    assert.equal(result, null);
    assert.equal(await use({}, "sample"), null);
  });

  test(file + ": inline JavaScript is syntactically valid", () => {
    let scripts = 0;
    for (const match of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) {
      new vm.Script(match[1], { filename: file });
      scripts += 1;
    }
    assert.ok(scripts > 0);
  });
}
