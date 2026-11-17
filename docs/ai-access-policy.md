# How Paperfact may use a reader's AI subscription

Status: policy for 0.5 onward, checked against vendor sources on 2026-11-17.
Implementation gaps are listed at the end. This is not legal advice; vendors
change these terms, so re-check the sources before each public release.

## Goal

A reader pays for AI once, through a subscription they already hold. Paperfact
must not create API charges by default, must not hold or route anyone's
subscription credentials, and must say plainly, before the first AI call, which
account each feature uses.

## The rule: who starts the conversation

| Direction | Example | Subscription allowed? |
| --- | --- | --- |
| An official agent host calls Paperfact's MCP tools | The reader asks `agy`, Claude Code or Codex to "rerun the research context of the paper I am reading" | Yes, for every vendor below. This is what MCP is for. |
| Paperfact starts the vendor's own unmodified CLI, signed in through the vendor's flow | The 深入分析 button runs `claude -p` | Depends on the vendor (table below) |
| Paperfact holds or forwards a login token, or calls the model endpoint with it | none; never built | No, for every vendor |

Paperfact never reads, copies or forwards a vendor login. Sign-in always
completes in the vendor's own program.

## Per vendor

| Vendor | App starts the official CLI with the reader's subscription | Scheduled or background runs | Sources |
| --- | --- | --- | --- |
| Anthropic (Claude) | Allowed: an end user may sign in to the unmodified Claude Code binary, including inside another product. `claude -p` with a plan sign-in draws from the subscription's usage limits. | Allowed within "ordinary, individual usage"; keep runs bounded and user-chosen. | [Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance), [Agent SDK with your plan](https://support.claude.com/en/articles/15036540), [Consumer Terms §3(7)](https://www.anthropic.com/legal/consumer-terms) |
| OpenAI (Codex) | Allowed for trusted local use: ChatGPT sign-in access tokens are "intended for trusted scripts, schedulers, and private CI runners"; usage follows the ChatGPT plan. | Same; OpenAI still recommends API keys for automation. | [Codex authentication](https://learn.chatgpt.com/docs/auth) |
| Google (Antigravity `agy`) | **Not allowed.** "Wrapping `agy` inside third-party coding agents or applications" is not supported under consumer plans; third-party access can suspend the account. | Only through agy's own scheduler (its `schedule` tool), with agy calling Paperfact's MCP tools. | [Antigravity FAQ](https://antigravity.google/docs/faq/), [ACP](https://antigravity.google/docs/cli/acp/) |
| Gemini CLI (`gemini`) | Workspace accounts only; personal Google accounts lost Gemini CLI access on 2026-06-18. | — | see `ai_choices.py` |
| Any vendor, API key | Allowed; billed per token to the key owner. | Allowed. | as above |

Anthropic's statement that `claude -p` uses subscription limits replaced an
announced separate "Agent SDK credit"; the support article shows that change as
paused. If it returns, Claude moves to the host-driven row for background work.

## What this means for each feature

- **Interactive features** (深入分析, 問 AI, 整理研究脈絡, translation): may run the
  reader's own Claude Code or Codex sign-in. Gemini through a subscription is
  reached only from agy, through MCP.
- **Nightly or ahead-of-time analysis**: off by default. When on, it may use
  Claude Code or Codex within a per-night budget the reader sets, or an API key the
  reader chose. Gemini nightly analysis is set up in agy's scheduler, not in
  Paperfact's nightly task.
- **Distribution**: Paperfact ships no model credentials and never resells usage.
  Each reader authenticates with their own account, which is the condition
  Anthropic sets for products that run Claude Code.

## Consent screen (before the first AI call, and in 設定)

State, in this order, with the first two lines emphasised:

1. Which account each AI feature uses, by name ("Claude Code, signed in as …").
2. That subscription usage counts against that plan's limits, and that an API
   key, if chosen, is billed per use by its provider.
3. What is sent: the paper's text and the reader's question, to that vendor only.
4. What runs without a click (nothing, unless scheduled analysis is turned on),
   and its nightly budget.
5. That Gemini subscriptions are used only from agy, through Paperfact's tools.
6. Links to each vendor's terms (sources above).

## Gaps (not implemented)

- MCP tools for the deep dive, as a task to read and an answer to save. The
  research context has them (`research.citations.task` / `.save`, see
  [Local integration](local-integration.md)); notes, claims and highlights already
  had their review tools.
- The consent screen above and a per-night budget.
- No `agy` backend is to be added to `llm.py`.
