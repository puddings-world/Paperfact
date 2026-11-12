# Saved deep-reading preparation

This local candidate extends the existing `ReaderPreparation` lane. Opening a
paper, receiving saved analysis, or finishing explicit figure preparation queues
saved deep-reading preparation rather than reading SQLite and typesetting the
explanation on the GUI thread. No AI login, model call, PDF extraction, research
write, cache adoption, or configuration write is performed by this rendering lane.

The reader keeps one running worker and one latest pending request. Chat and deep
reading share it; repeated activations coalesce. Busy includes native completion
and queued GUI install/discard, using the existing close/restart/update barriers.
Unsent questions, notes, and slide drafts are not edited by saved rendering.

## Source and delivery

The request captures the existing paper owner, database native identity, actual
loaded document and completed native-load witness, reader/paper intent, palette,
view format, and explicit figure cache root/options. The worker uses the maintained
read-only saved snapshot and source verification. It never resolves a new desired
PDF or calls global legacy cached helpers during delayed work. A retained loaded
original A can remain readable while the synchronized desired original is B.
Annotations/reading links retain the existing exact source and observed-output
checks. The installed highlight navigation projection carries the captured PDF
hash; stored annotation bodies and reading-link keys are unchanged.

The physical DB/WAL fence remains an interference check: existing bounded semantic
revalidation handles changed saved inputs before installation. Native replacement,
changed paper/view/source intent, cancellation, and accepted close reject late
results. No fresh writer/sync authority is created by rendering.

## Cached figures before the figures tab

Saved close reading can display a cache preview without first opening the figures
tab. The worker reads the captured cache root, its bounded manifest and PNG bytes;
it validates declared source/cache bindings, native before/after revisions,
digests when declared, PNG header/dimension bounds, and complete closure stability.
The index and assets must resolve inside the captured cache; each actual opened
stream must match its captured native identity/size before any bounded content
read, and must remain stable after that read.
Known other-original/cache bindings are rejected. These checks establish byte
consistency, not origin: persisted previews are explicitly labeled **Unverified
cached figure — original-source provenance not verified**, omit original-page
claims, and contain no original-source action.

An existing completed owned figure frame is a separate fast path. Its actual
original source proof and captured generated digests must verify; rendering never
extracts or decodes a PDF to manufacture such proof. The unchanged `_figures_ready`
callback queues a fresh saved-render request, allowing its images to upgrade the
preview. The figure pipeline's own extraction, source rechecks, image decode,
ready count, and lifecycle remain unchanged.

PNG bytes are embedded in the returned HTML. A later file swap cannot alter those
rendered bytes through a mutable file URL. There is still a bounded native-only
GUI delivery scan over the exact captured closure: at most 128 assets plus one
manifest. On Windows this opens native read handles for revision metadata; this is
not a claim of zero GUI I/O. Hashes, byte reads, JSON/Markdown parsing and SQL stay
on the worker. A queued manifest/asset mutation rejects the new result, retaining
prior accepted content until explicit retry.

Budgets are 1 MiB for the manifest, 128 preview assets, 24 MiB total PNG bytes, the
existing 32-million-pixel image bound, and the existing rendered-content bound.
Missing/malformed/mismatched/over-budget cache content produces a visible coverage
notice while keeping saved research text readable. Unknown previews never become
extraction, publication, source-navigation, or sync authority.

## Evidence and limits

New actual Qt/SQLite/PDF fixtures cover the original GUI-typesetting failure,
readable cached images before visiting figures, owned-frame upgrade, source A/B,
queued PNG/manifest changes, cache budgets, GUI heartbeat, repeated activation,
account changes without acquiring a route, view/workspace/native replacement,
cancellation, retry, closing and draft preservation. Existing tests and their
assertions are unchanged. The Windows test token cannot create physical file symlinks (WinError 1314); the
closed-root escape test uses only a controlled path-resolution seam there, with
real disposable reads/native revisions. Where permitted it uses an actual file
symlink. Same-path replacement tests use real filesystem replacement and native
versions, recording zero content reads before stream admission. No real account,
model, network, owner research data,
native owner app, runtime assets or fonts are used.

Focused results and source hashes are recorded in the ignored handoff receipt.
The parent still owns the full check before a commit or completion claim. This is
not an end-to-end guarantee that all reader actions avoid GUI SQL; note editing,
source-link actions and other existing UI paths retain their own maintained seams.
No cached-reopen speed or whole-app performance claim is made.
