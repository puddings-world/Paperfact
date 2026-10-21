import test from "node:test";
import assert from "node:assert/strict";
import { readQuota } from "../src/paper_daily/gemini_usage.mjs";

function fixture(account, quota) {
  const calls = [];
  return {
    calls,
    getVersion: async () => "0.38.2",
    getOauthClient: async (auth, cfg) => {
      assert.equal(auth, "oauth-personal");
      assert.equal(cfg.isBrowserLaunchSuppressed(), true);
      assert.equal(cfg.isInteractive(), false);
      calls.push("cached-auth");
      return { secret: "must-not-leak" };
    },
    CodeAssistServer: class {
      constructor(client, project, options) {
        assert.match(options.headers["User-Agent"], /GeminiCLI\/0.38.2\/quota/);
        assert.equal(project, undefined);
      }
      async loadCodeAssist() { calls.push("account"); return account; }
      async retrieveUserQuota(request) {
        calls.push("quota");
        assert.equal(request.project, "fixture-project");
        return quota;
      }
    },
  };
}

test("Gemini quota uses cached login and only account/quota calls, strips other fields", async () => {
  const core = fixture({
    paidTier: { name: "Google AI Pro" }, cloudaicompanionProject: "fixture-project",
  }, { buckets: [{ modelId: "gemini-pro", remainingFraction: 1, secret: "private" }] });
  const result = await readQuota(core);
  assert.deepEqual(core.calls, ["cached-auth", "account", "quota"]);
  assert.equal(result.plan, "Google AI Pro");
  assert.equal(result.buckets[0].remainingFraction, 1);
  assert.equal(JSON.stringify(result).includes("secret"), false);
  assert.equal(JSON.stringify(result).includes("fixture-project"), false);
});

test("unsupported Gemini login does not onboard or query a different project", async () => {
  const core = fixture({ ineligibleTiers: [{ reasonCode: "UNSUPPORTED_CLIENT" }] });
  const result = await readQuota(core);
  assert.deepEqual(core.calls, ["cached-auth", "account"]);
  assert.equal(result.unsupported_client, true);
  assert.equal(result.needs_setup, true);
  assert.deepEqual(result.buckets, []);
});

test("Gemini missing buckets and authentication failure remain unknown", async () => {
  const core = fixture({
    currentTier: { id: "standard-tier" }, cloudaicompanionProject: "fixture-project",
  }, {});
  assert.deepEqual(await readQuota(core), { plan: "standard-tier", buckets: [] });
  core.getOauthClient = async () => { throw new Error("auth unavailable"); };
  await assert.rejects(readQuota(core), /auth unavailable/);
});
