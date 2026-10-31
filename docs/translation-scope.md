# Source-bound translation delivery

Translation is transient reading UI. It does not publish research, create an
identity, change the current PDF or edit note/Q&A drafts.

An explicit click captures the loaded paper owner, database, original PDF/hash,
reader/document/selection epochs, actual selected words and anchor, and the
translation route with resolved account/model settings and the existing 300-second
model timeout. Provider-default model=None remains unchanged. Clearing and selecting
identical words again is a new intent. Google translation remains usable without
an AI account; its existing AI fallback retains the original captured route.
Repeated clicks while either translation stage runs do not enqueue another job.

The existing AskRunner runs byte hashing and read-only ownership/source checks
before and after the call. An intact loaded original A remains eligible while a
new primary B is available; translation never activates B. Closing a verifier
uses read-only connections, not a writable connection that could checkpoint WAL.
Empty WAL creation has no committed frame and does not invalidate a proof. Real
DB/nonempty-WAL/native-source revision changes invalidate delivery.

GUI delivery performs no SQL, JSON/profile reads, PDF parsing or byte hashing.
The only config file actually read during capture is llm.SETTINGS_PATH; capture
seals its native path/revision before and after resolution, plus the environment.
The existing opt-in translate flow events remain inside the background call. It checks the original
in-memory intent and native DB/WAL/source revisions. Selection changes, reader
hide/close, workspace/account/model changes and cancellation discard stale
responses and suppress fallback. A late callback cannot clear a newer result.
Unsent note/question drafts remain untouched. A current failure is retryable;
exceptions show a bounded generic message rather than raw credentials/paths.

Scope and limits:

- No attempt is made to interrupt an already-running provider subprocess/network
  request. Cancellation prevents later display/fallback and further stages.
- Native revisions are fail-closed observations, not protection against a hostile
  kernel/filesystem forging metadata. Unrelated DB writes during the final
  delivery gap can conservatively discard an otherwise valid transient result.
- Account/model configuration is captured; external login/logout inside a provider
  CLI's private storage is not represented as a portable research identity.
- Fixture tests use synthetic PDFs, real Qt workers and simulated responses. Real
  Google/provider integration and physical Windows/macOS acceptance remain manual.
