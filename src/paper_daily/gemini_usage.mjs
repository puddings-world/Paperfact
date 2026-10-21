// Use the installed official CLI's credential handling. Never print credentials,
// initialize tools, onboard an account, open a browser or request generation.
import { pathToFileURL } from "node:url";

export async function readQuota(core) {
  const config = {
    getProxy: () => undefined,
    isBrowserLaunchSuppressed: () => true,
    isInteractive: () => false,
  };
  const client = await core.getOauthClient("oauth-personal", config);
  const version = await core.getVersion();
  const server = new core.CodeAssistServer(client, undefined, { headers: {
    "User-Agent": `GeminiCLI/${version}/quota (${process.platform}; ${process.arch}) Paperfact`,
  } }, "");
  const account = await server.loadCodeAssist({
    metadata: { ideType: "IDE_UNSPECIFIED", platform: "PLATFORM_UNSPECIFIED", pluginType: "GEMINI" },
  });
  const tier = account.paidTier || account.currentTier;
  const plan = typeof tier?.name === "string" ? tier.name : tier?.id;
  const project = account.cloudaicompanionProject;
  if (typeof project !== "string" || !project) {
    return { plan, buckets: [], needs_setup: true,
      unsupported_client: account.ineligibleTiers?.some(t => t.reasonCode === "UNSUPPORTED_CLIENT"),
    };
  }
  const quota = await server.retrieveUserQuota({ project });
  return {
    plan: typeof plan === "string" ? plan : null,
    buckets: Array.isArray(quota.buckets) ? quota.buckets.map(b => ({
      modelId: b.modelId, remainingFraction: b.remainingFraction,
      resetTime: b.resetTime, tokenType: b.tokenType,
    })) : [],
  };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const core = await import(pathToFileURL(process.argv[2]).href);
    const result = await readQuota(core);
    process.stdout.write("PAPERFACT_QUOTA=" + JSON.stringify(result) + "\n");
    process.exit(0);
  } catch {
    // Upstream exceptions can contain account information or HTTP headers.
    process.stderr.write("Gemini quota unavailable\n");
    process.exit(1);
  }
}
