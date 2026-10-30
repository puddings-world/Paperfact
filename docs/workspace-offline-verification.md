# Resumable selected-attachment verification

This local-only verification session fixes the stateless 64 MiB pass limit.
Use the offline dialog's **Verify selected files** action. When the selected
closure exceeds one pass, **Continue verification** resumes with valid sealed
in-process proofs. Counts are actual distinct verified objects, not a time
estimate. Downloading, pinning, verification and metadata sync remain separate.

`OfflineService.verification(local_ids)` creates an
`OfflineVerification`. `advance(ticket, progress=...)` checks the same captured
selection and current PDF/deck manifests. Before reusing a proof, and again
before returning a report, it checks the actual file identity and exact target.
Source, parent, workspace or applied-manifest changes require a new verification;
mutated or missing files invalidate proof reuse. Returned dictionaries cannot
change internal proof authority. Repeated concurrent activation is rejected.

A pass defaults to 256 MiB, 256 assets and a soft 10-second expensive-verification
budget. The entire selected closure is bounded to 8 GiB / 4,096 distinct assets
and the existing 100-paper selection limit. Native PDF/closure verification is
not interrupted mid-call; cancellation is observed at safe boundaries. A single
object/closure must fit one pass; native document limits still apply. No ready
flag is persisted or trusted from another process.

Unfinished passes may keep valid proofs for explicit retry. A completed dialog
check discards its session, so a later Verify starts a fresh byte check. Closing
also discards proofs and waits safely for an active native stage. Download and
pin/refresh actions start a new verification context. The dated ready snapshot
covers only selected current managed PDFs and canonical notes/guide assets.
Unknown source provenance, corrupt bytes and unregistered files never become
verified because a previous pass succeeded. No entire-workspace claim is made.

This service does not implement cache eviction, pin retention enforcement,
historical claim-source transfer, enrollment or a native-device acceptance run.


## Windows cached-proof invalidation

The initial proof still hashes actual PDF/artifact bytes. Windows reuse observes
both FILE_BASIC_INFO.ChangeTime and the per-file USN revision through the same
handle: creation time is insufficient, and change timestamps can still alias
same-clock-tick writes. Unavailable/unknown revision observations fail closed.
These are local cache invalidation observations, not replacement hashes or a
defense against a hostile filesystem/kernel. See Microsoft's
[ChangeTime reference](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_basic_info)
and [per-file USN query](https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-fsctl_read_file_usn_data).

The original regression failed before the fix. A timestamp-only candidate passed
132 cases but failed the unchanged rapid-write assertion in a combined run.
The revision repair passed 44 cases in 65.79 seconds, including 32 immediate
restored-mtime writes. The combined source/claims/offline/controller selection
then passed 144 Python cases, 198 mobile cases and four actual HTTP runners.
Selections overlap. Native Mac/Linux and removable-filesystem acceptance remain
separate gates; a complete frozen project gate is required before commit.
