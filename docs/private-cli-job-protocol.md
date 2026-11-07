# Private CLI job protocol in the isolated integration candidate

The isolated 0.5 merge candidate uses this protocol for list surveys, adding a
paper, list analysis, MainWindow analysis and citation subprocesses. This work
has not yet been committed into the canonical checkpoint or released.

The desktop admission gate captures configuration/environment at the original
request. Its background preflight resolves the declared routes, checks those
exact resolved values, and admits an immutable route map only on success.
The callback, nested workers and private child frame retain that same map,
including across replacement confirmation or executable-discovery changes.
The final logical command is bound after confirmation without recapturing routes.
A new explicit request reads the current configuration. Ordinary CLI and MCP
stdin remain unchanged.

This is not an all-AI completion claim. Direct feature paths outside this gate
still require separate review; Cites jobs do not yet gain the common ActivityHub
notice. Vendor credential files and the identity currently signed into them
are not frozen or copied. See [Popen ownership](private-popen-jobs.md).

## Values and launch binding

`FrozenRoutes(default, tasks, *, profiles=None, account_directory=None)` accepts
only already-resolved `ai_types.Settings` values. It stores defensive immutable
primitive copies and returns fresh `Settings`/dictionary copies. Its default is
used only for the declared `default` lookup; an unknown task never inherits it.
Explicit profile lookup requires both a declared task and a captured profile.

All twelve current Settings fields are carried exactly, including `model=None`,
API-key absence, task-specific requested aliases, token controls, isolated/account
selection and `cli_home`. There is no model discovery/default-version substitution.
`auto` backend is rejected because resolution belongs at dispatch, outside this
pure core. Backend names are syntactically validated, not checked against a live
adapter registry; the future host must check capabilities before execution.

`account_directory` and home paths are private literal context, not normalized or
resolved filesystem authority. This code never reads, creates or copies vendor
credential files, and cannot establish which person is currently signed into one.

After any user confirmation determines the actual command, call
`routes.bind(request_id, command)` (or `BoundJobIntent(...)`). The command is the
**exact logical CLI argument sequence**, for example `survey`, the list ID, and
`--force`. It excludes the interpreter/executable and private bootstrap prefix.
A new bound value can include `--force` without recapturing or changing routes.
The core does not mint request IDs, track replay, execute argv or authorize writes.

Request IDs are either 32 lowercase hexadecimal UUID digits or canonical lowercase
hyphenated UUID spelling. They are compared exactly, never normalized across those
spellings. The new `FrozenRoutes`/`BoundJobIntent` repr and their error messages redact route
values, private paths and argv. Returned `Settings`, command accessors and raw data
remain private value objects; this does not change the existing Settings repr.
`to_data()` and encoded frames **do contain secrets**: they are explicitly private
transport values, not safe log, diagnostics, clipboard, research, bundle or sync data.

## Binary frame and control lines

`cli_job_protocol.encode_frame(bound)` produces:

- six-byte magic `PFJOB` followed by NUL;
- one-byte protocol version `1`;
- four-byte unsigned big-endian UTF-8 JSON length;
- one closed JSON object with `version`, `request_id`, `command` and `routes`.

The nested routes object has exactly `default`, `tasks`, `profiles` and
`account_directory`; every Settings object has all known fields. Unknown/missing
fields, duplicate JSON keys at any depth, nonstandard JSON constants, invalid types,
unknown versions, oversized/truncated input and binding mismatches fail closed.
No error falls back to live settings. The JSON must describe the expected request
and complete final command supplied separately by the receiving caller.

`read_frame(stream, expected_request_id=..., expected_command=...)` reads exactly
one header and its declared body. It does not consume trailing stdin, seek, close
the stream, require EOF, or access `sys.stdin` implicitly. Normal CLI/MCP stdin is
therefore untouched unless future code explicitly calls this reader. In contrast,
`decode_frame(bytes, ...)` expects an exact standalone frame and rejects trailing
bytes in its private bytes value.

`hello_line(id)` and `ready_line(id)` return nonsecret versioned ASCII lines.
`parse_control_line(..., expected_phase=...)` checks complete LF/CRLF lines, protocol,
request and expected phase. These stateless helpers do not implement a handshake,
ordering, request uniqueness, or trusted process identity by themselves.

Budgets: 1 MiB JSON payload, 64 KiB UTF-8 per settings/context string, 64 task routes,
64 explicit profiles, 128 command arguments, 16 KiB per argument, 64 KiB total argv,
and 128 bytes per control line. Positive integer token limits and exact boolean
types retain their existing meanings. Binary read/write primitives complete partial
operations without an unbounded read; blocking-I/O deadlines remain the caller's job.
`write_frame` flushes but never closes a caller's stream. It is a blocking primitive,
not suitable for direct use on a GUI thread.

## Active bootstrap and QProcess launchers

`integration_entry` recognizes `_desktop-job-v1 <request-id> <logical-command>`
before importing CLI/configuration code. The child emits a nonsecret hello, validates
the complete frame and binding, then installs an immutable process default and emits
ready. Invalid input returns a fixed startup failure before CLI execution. Nested
connection captures and fresh thread pools use the same captured routes. The
process scope is cleared on normal return or exception.

Only this validated bootstrap suppresses checkout dotenv loading, preventing an
absent captured API key from reappearing through a later `.env` read. Normal CLI
startup keeps its existing behavior. One job runs per private child; no credential
payload is written to argv, environment variables or temporary files.

`desktop.cli_job.JobHandoff` owns one QProcess handshake, bounded output parser,
nonblocking Qt write queue and 30-second startup deadline. It sends no private frame
before a matching versioned hello. Partial writes/control lines are supported;
startup failure, malformed output, deadline and early exit clear retained frame
buffers. Normal child output reaches the activity UI only after ready. A zero exit
before ready cannot be presented as successful generation. QProcess owns actual
child termination/reaping; this helper does not create a second worker scheduler.

Adding a paper and list-wide analysis use the same transport. Their signal handlers
bind the exact original QProcess, so a failed process's late output/error/completion
cannot clear a newer retry. Both pass their captured workspace as PAPERFACT_DATA;
a replaced workspace starts no new job. Non-AI PDF replacement remains ordinary
CLI with untouched stdin and no AI route requirement. Rejecting an active add-paper
dialog invalidates its callbacks, stops the owned process without a GUI-thread wait,
and clears its temporary input/private startup frame. Accepted stored research is
not rolled back by this transport.

The survey keeps its window-owned process and existing workspace/target checks,
confirmation, duplicate-job gate and observed research publication. Closing the
survey dialog still permits its window-owned work to finish. Old process callbacks
cannot complete a newer retry.

## Remaining integrations and evidence limits

The other launchers named above must adopt equivalent captured-intent delivery;
Popen needs asynchronous owned feeding/output filtering rather than GUI-thread
blocking writes. Missing login continues to end a request; a deliberate new click
captures the user's new selection. No automatic retry changes a queued account.

Synthetic keys, fake provider responses and an actual local QProcess exercise the
transport, not live subscriptions, provider credential refresh, installed CLI twins
or macOS/Linux packaging. Hostile command execution, credential-file immutability,
scientific accuracy and a universal secret-erasure guarantee are not established.
See [the human regression map](ai-job-test-map.md). Full project acceptance remains
required before committing, publishing or declaring the integration complete.
