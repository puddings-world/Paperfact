# Academic and commercial modes: how Paperfact uses MCP

Status: required architecture, not implemented modes. Current model profiles and
the custom gateway adapter are available; the managed service, account/credits UI,
agent executor, MCP client and managed policy enforcement below remain to be built.
The local stdio MCP server for offline list operations ships in 0.3.0.

For the concrete local-project use case, CLI/MCP examples and
call-flow diagrams, see [Local integration](local-integration.md).

## One product, two execution modes

Both modes use the same library, list operations, workflow modules and job schemas.
"Academic" means bring your own execution connection here; it is not an implemented
license eligibility rule. The product must support both modes without duplicating
the research workspace.

| | Academic / bring your own | Commercial / Paperfact managed |
| --- | --- | --- |
| Model access | Personal API, compatible local model or supported agent host | Paperfact account and service |
| AI cost | User's provider/subscription/local compute | Paperfact credits charged by the service |
| Upstream vendor credentials | User's connection, kept outside research exports | Server-owned credentials, never sent to the app |
| Agent execution | Built-in executor or a supported external host | Official executor with all model calls routed through Paperfact |
| Research tools and modules | Shared core tool contract | Same core tool contract |
| Research storage | Local by default | Local by default; cloud storage is a separate choice |

The connection screen offers "Use my own AI" and "Use Paperfact credits".
Personal API/local endpoint/agent-host choices live under the first. Account,
balance, permitted models, job budgets and usage history live under the second.

Managed mode must route every official AI step through the service, including
parsing, repair attempts, summaries, background preparation and module analysis.
It must not silently substitute a personal profile or an external subscription.
BYO mode must not invoke a chargeable Paperfact endpoint without a chosen managed
connection. Work already running retains its execution/billing snapshot when the
user changes modes.

Mode policy belongs above per-task routing. Current environment/profile overrides
do not implement this constraint. Module code must request execution through the
policy service; it must not open its own model account. Server-side entitlements
and spend limits are authoritative even if a local client is edited.

## MCP is the tool boundary

A model API generates answers and tool requests. A workflow executor manages steps,
state and retries. MCP lets a compatible agent host discover and call tools and
read context. A module/skill describes a research workflow. The credit service
authenticates and accounts for managed execution. These are separate interfaces.

The [official MCP architecture](https://modelcontextprotocol.io/docs/learn/architecture)
defines hosts, clients and servers, and limits MCP's scope to context/tool exchange.
It does not determine a host's model provider or token billing.

Paperfact provides a local MCP server over stdio for structured list operations. A supported external
agent host starts it and uses its tools against the selected local workspace.
The desktop and built-in executor call the same underlying services directly.
They need not serialize every in-process operation through MCP.

If Paperfact later consumes third-party academic MCP servers, its executor also
needs an MCP client. This second direction is optional and independent of exposing
Paperfact's own tools. A tool server does not give Paperfact the ability to drive
conversations inside an arbitrary external agent application.

## Minimum tool surface

The broader execution surface below is a proposal. For the six implemented offline
operations, use the [local integration tool reference](local-integration.md).

| Tool | Result or allowed effect |
| --- | --- |
| lists.list / lists.create | Inspect lists or create one in the selected workspace |
| papers.search / papers.inspect | Search local papers and retrieve bounded context |
| sources.search / papers.resolve | Query supported sources; return identity evidence |
| imports.propose | Stage candidates with input fragments and source provenance |
| imports.commit | Commit an allowed selection with an idempotent operation ID |
| jobs.inspect / jobs.cancel | Inspect progress or cancel a scoped job |
| analysis.start | Start an explicitly budgeted AI job using the selected mode |

Provide input/output schemas, stable IDs and typed errors. Names above describe
application services; concrete MCP tool naming is selected with the supported
SDK/protocol version. The [MCP tools specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
supports structured schemas and results; validate at the core service boundary too.

The same operations must work from the UI, an embedded executor and an external
host. Avoid a universal SQL/shell tool. Scope mutations to workspace/list/job,
preserve user corrections, stage uncertain matches and deduplicate repeated calls.
Tool descriptions and annotations are metadata, not authorization enforcement.

Source searches and identifier matching do not intrinsically consume model tokens.
An AI-backed tool must state that it starts a paid/model job and bind its mode,
connection and budget explicitly. Count actual service generations, including
repair/reasoning steps when reported, rather than charging one inference per MCP
tool call. An external host's own generations are outside Paperfact's usage ledger.

## Academic execution

Two supported paths:

- The desktop executor uses a personal model connection and core tools.
- A supported external agent host uses its own account plus the local Paperfact
  MCP server. The user can ask it to turn rough references into an import job.

The second path is close to the original agent-driven workflow, but needs tested
host setup and capability support. A subscription does not automatically supply a
model API key. Do not promise cancellation, host-session resume or exact token
counts when the adapter cannot report them. Local checkpoints remain independent.

## Commercial execution

Start with an executor inside Paperfact: it sends every model step to the managed
gateway, executes approved local tools and stores local job checkpoints. That
preserves the existing local research DB and reuses the academic executor's tools.
The server authenticates the customer, routes vendor requests and settles credits.

This is sufficient for a desktop managed mode; a cloud-hosted agent is a later
option, not a requirement for the first service. A hosted agent would need job
events and an explicit local-tool bridge. It cannot directly reach the desktop
SQLite database or a stdio process on the user's machine. Do not expose the local
database/server to the internet to make this connection work.

Connecting a third-party agent host to Paperfact MCP does not route that host's
reasoning through Paperfact. The host still selects and pays for its model.
Charging for a remote AI tool can create a hybrid, but cannot make the entire
external agent's token bill belong to Paperfact. The full commercial mode requires
the official executor, or a host explicitly configured and tested to use the
Paperfact model gateway.

The current OpenAI-compatible adapter only handles text completions. A tool-using
executor also needs structured extraction/tool requests, an execution loop,
capability checks, checkpoints and request correlation. Adding MCP alone supplies
none of those orchestration or billing behaviors.

## Authentication and credit records

Keep customer identity, model API credentials and MCP tool authorization separate.
A Paperfact gateway token is not an upstream vendor key. A credential for a remote
MCP service must be scoped to that service; do not reuse or pass it through to an
unrelated model endpoint. A single account can obtain separate service credentials.

For a future remote MCP server, implement the supported protocol's HTTP
authorization flow, resource/audience validation and scoped access. Local stdio
has a different launch/credential boundary. These distinctions are covered in the
[official MCP authorization specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization).
Do not require a remote MCP deployment just to implement a model gateway.

For each managed generation, persist customer, workflow job, request/operation ID,
model, pricing version, provider-reported usage, reservation/settlement state and
the receipt. Deduplicate retries before charging. Check limits on the server.
Show unknown/awaiting-provider usage honestly; local logs are not balances.
A cancelled job can still have already consumed tokens; explain settled usage.
Prices for different models/token categories may differ, so credits need a
documented conversion rather than a promise that all tokens cost the same.

## Recommended build order

1. Validated core tools and staged import jobs shared by UI/executors.
2. Built-in executor with explicit BYO/managed policy and job budget snapshots.
3. Local MCP server plus one tested external academic agent host.
4. Managed gateway, customer accounts, usage ledger and credit UI. Test every
   official task and module against a spy transport: managed mode never bypasses
   the service, and BYO mode never unexpectedly invokes it.
5. A second external host and field-specific module to test portability.
6. Remote MCP integrations or a hosted agent only when their use case needs them.

This is a dual-mode requirement from the outset, even though a live paid service
can ship later. See [the workflow design](agent-workflows.md) for UI and failure
semantics and [the current model architecture](architecture.md) for existing code.
