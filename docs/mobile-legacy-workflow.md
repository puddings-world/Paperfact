# Mobile legacy reading workflow

The mobile reader accepts the closed `queue_entry`, `reading_event`, and
`legacy_brief` contracts maintained by `legacy_workflow.py` and `legacy_briefs.py`.
They are read-only observations. They do not create lists, memberships, schedules,
assistant answers, historical jobs, or mobile editing authority.

Queue metadata belongs to one paper, with an optional distinct parent paper as
the second ordered graph parent. The owner must be first. Existing generic
parent rules remain unchanged. Same-incarnation updates and known deletes retain
the observed ordered parent closure; restoring an inactive record requires a
fresh incarnation and the same parent identities. The narrow queue-only context
transition may change the optional secondary paper while the old queue and both
old/new parent closures remain active. It requires an unchanged owner reference,
an accepted queue origin, a fresh incarnation equal to the new operation ID,
and exact data-head and structural compare-and-swap revisions (or their accepted
same-device predecessor receipts). It cannot change a queue owner or relax
generic graph reparenting. A reading event has one owner paper and a stable UUID;
`delivered_at` cannot change within its incarnation. Only explicit prior records
give these new features known-delete semantics. The existing four singleton
annotation tombstone identities are unchanged.

Queue ranks remain finite numbers, including Python JSON spellings such as
`1.0`, `-2.75`, `1e21`, and `-1e-7`. Original nullable prose and timestamps are
retained. The wire rejects booleans, unknown fields, sender paths, invalid UTF-8
strings, unbounded content, and unknown feature formats.

A brief manifest has exactly one owned Markdown asset, bounded to 8 MiB, and a
canonical JSON body bounded to 4096 bytes. Its graph parent is the paper; the
event is bound through the body's exact event UUID and incarnation. Metadata may
arrive before that event, but it cannot activate until the current event's owner,
parent incarnation, and declared Markdown hash/size/media type all match.
Activation checks that binding again inside the final store transaction.

The reader verifies both descriptors and byte hashes before use, preserves UTF-8
bytes including BOM and CRLF, and displays Markdown as literal text nodes. It
does not execute HTML, follow sender paths, or infer dates from filenames. An
event deletion, brief clear, descriptor change, or replacement incarnation hides
previously verified bytes immediately, including after offline restart. A file
retirement also disables cached access. Existing download cancellation, session
binding, retry, deduplication, and cache quota controls apply.

The overview shows saved queue state, reason, event timestamp/note, and a
“Save brief offline” action when a manifest exists. It guards duplicate clicks
and ignores asynchronous results after navigation, connection switch, or close.
English and Traditional Chinese labels are provided. No native vault, model, or
account operation is involved.

## Verification

`mobile/tests/legacy-workflow.test.mjs` uses the stable Python golden fixture at
`tests/fixtures/legacy-workflow.json` (SHA-256
`a74e1ff5513d504efe5544bb3347bc310d8f50c0d28b2b3d76a807107bdef265`).
The independent Python queue-context verdict matrix is
`tests/fixtures/legacy-queue-context.json` (SHA-256
`64ea18553bc3d71f1a94e0dc652cd0bac367c0e1d7d5cbaf45922577d976a93c`).
It pins direct/dependency transitions, data versus structural CAS failures,
origin/owner/parent failures, and existing generic same-ID epoch refresh.
The view tests use text-only DOM fixtures and delayed promises.

`node mobile/check.mjs --python <python> --core-root <core-root>` also runs
`mobile/legacy-workflow-service-check.mjs`. The core root must include the
separately maintained `mobile/legacy-workflow-service-fixture.py` and typed
Python legacy producers. The fixture uses temporary databases, actual
`record_pack`, file transfers and the loopback HTTP reference service. It checks
exact Markdown bytes, offline reopen, interrupted retry, duplicate downloads,
note/rank edits, the actual `queue.add_companions` fresh context transition,
clear/delete suppression, empty mobile outbox, and no upload.

The isolated mobile candidate intentionally does not copy evolving Python
producer modules. The parent integration must combine the reviewed producer and
mobile changes before the full project gate. Service worker `sw.mjs` remains at
v8 in this candidate; integrate the two new shell module paths contextually with
the separately reviewed lineage v9 shell update. Do not replace either shell
inventory wholesale.
