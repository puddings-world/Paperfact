# Workspace watcher binding and lifetime

A WorkspaceChanges instance observes the exact database path and file identity
captured at construction. A process-global path change does not move that
observer to another workspace. A missing initial file grants no authority to a
later file; deleting or replacing the database at the same path requires a new
watcher. Ordinary committed revisions in the same file remain observable.

The revision read keeps its no-argument seam and uses a short read-only SQLite
connection. Returned metadata is labelled with the bound path, never a second
read of the mutable global path. GUI delivery rechecks the current process path
and captured device/inode before emitting changed. These are metadata guards:
there are no database writes or PDF hashes.

The maintenance branch's bounded persistent ThreadPoolExecutor is preserved.
One admitted read remains active through queued GUI delivery. Explicit close or
dispose stops the timer, cancels queued work and shuts down the pool with
cancel_futures=True and wait=False. A running read drains off the GUI thread;
its late result cannot notify a closed or destroyed QObject. An accepted parent
window close calls close only after the existing busy/draft guards accept exit.

The standalone maintenance patch contains the observer and its behavior tests.
The one-line accepted-close hook and its native window tests are separate
patches with exact beforeimages. A feature projection uses the same observer
implementation, preserving the maintenance pool rather than restoring
per-poll thread creation.

## Evidence and limits

The unchanged master observer deterministically failed a new actual SQLite
A-to-B ownership test by opening B. The accepted-window-close test separately
failed before its one-line hook. Focused evidence covers normal revisions,
rapid repeated polling, worker reuse, missing/replaced files, queued stale
delivery, actual native replacement of B while A is being read, failure/retry,
queued cancellation, close/drain and QObject destruction. Exact final counts,
source hashes and separate patch ownership are recorded in the ignored build
handoff.

This is a common maintenance fix, intended to land on master before projection
to the feature branch. No existing source worktree was edited and no version,
commit, push or release action was performed by this candidate.

The earlier warm feature-suite WinError 5 remains separate evidence. A green
focused watcher test is not proof that this change explains its closed SQLite
cache/Statement remnants. The full maintenance check and later controlled
feature validation are still required. No cache disabling, GC collection,
replacement retry or test weakening was used.

The existing local-integration skill already requires fixed workspace ownership,
short final delivery guards and explicit resource lifetime. This fix adds local
project evidence; it does not establish a new global rule from an unverified
native-cache explanation.
