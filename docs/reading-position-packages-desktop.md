# Reading-page records: packages and native desktop

A reading position belongs to one paper lifetime and one exact PDF hash. It is
not a last-opened timestamp or a promise that every viewport gesture was saved.
Ordinary reading state, list order, notes and question drafts keep their existing
meaning.

## Desktop behavior

The reader verifies the loaded PDF's real page count on a worker. A native load
version witness is captured around the existing native open and Ready boundary;
its cached metadata must match the worker's exact original version. A same-path
replacement, including a same-count A→B→A change, cannot bind a new hash to the old
rendered document. An unavailable witness leaves reading available and asks the
user to reopen the PDF before recording a page.

Genuine keyboard, wheel and scrollbar navigation can record a changed page after
a short debounce. Initial loading, rendering, programmatic scrolling and received
suggestions create no reading event. Only one worker and one latest pending
native observation exist per reader. A later input may follow only the exact
proven committed predecessor from this controller; a concurrent position is kept
and the conflicting local intent is retained. Remember page explicitly chooses
the currently visible page after refreshing its base.

Resume page acts only on a matching, already-loaded original. It rechecks the
exact displayed record and paper lifetime on a worker and holds the bounded SQL
reservation through the native jump. The GUI only compares its live view epoch,
source witness, page and unchanged draft state before moving. It does not open a
paper, discard a draft, or schedule a jump after a future load. Resume itself
does not save or echo a new position.

Immediately before the native jump, one bounded file-version comparison checks
the worker's captured source version. This is final known-version validation,
not an atomicity guarantee against an adversarial filesystem.

Source verification, PDF hashing/count parsing, retention and SQL run off Qt.
Only bounded file-version metadata surrounding the existing native load and its
explicit jump belongs to that native boundary. An absent optional schema requires explicit
installation; passive reading never repairs it with DDL.

記住此頁會明確選用目前頁碼；前往記錄頁只作用於已開啟且版本相符的原文。
初次開啟、畫面重繪與收到同步記錄不會自動記錄或跳頁。頁碼衝突會保留，
不會根據時鐘或較大的頁碼自行選擇；未送出的問題與筆記不會被捨棄。

## Portable packages

Default full list packages include each reading position's exact original PDF,
independently from the paper's current primary PDF. Source A therefore remains
available when primary B is current. The closed, sorted `position_sources`
inventory contains only exact paper/hash/size/package-path declarations. The
receiver verifies bytes and actual page bounds, assigns its own paper lifetime
and source ownership, and commits position/source data atomically. Sender device,
database and job observations never become receiver authority.

`with_pdfs=False` refuses a position-bearing export before creating output, with
an Include PDFs message. Metadata-only unavailable-history packages remain a
later capability. A changed original, position, paper lifetime or ownership
during packing preserves the previous output and requires retry. Kept receiver
positions retain differing imported values in closed archive-only history.

## Private preparation and preservation

Passive loaded-source verification creates no files or position records. An
admitted Remember/native intent may retain a private original/provenance pair
before its SQL save. New pairs use `paperfact.position-source-owner.v2`: one
atomic directory containing exactly `original.pdf` and `receipt.json`. This
private publication format changes neither the application version nor the
reading-position wire/request formats. The previous v1 path and receipt remain
readable and verifiable.

A complete prepared pair is private historical provenance, never an active
position, outbox operation, device authority or replayable job. Position, active
source ownership, retry result and original-source publication remain one caller
transaction. Cancellation or rollback can preserve private provenance without
inventing saved progress. A narrowly named, bounded preparation directory is
disposable device cache; unknown entries and incomplete published pairs fail
closed. Enrollment and independent recovery archive exact original provenance
without reactivating old owners. Older unsupported readers/restorers must refuse
the new private format, rather than omit it.

## Coverage limits

This slice enables native desktop recording after package closure. It does not
implement an Inbox or mobile page entry/parser. The mobile native PDF object has
no observable viewport or independently verified count, so no mobile automatic
tracking or guaranteed native jump is claimed. The noncanonical read-only
workspace snapshot still explicitly refuses nonempty reading positions; it does
not silently omit them. Unsupported live receivers continue to refuse the
required capability before advancing their cursor.

Debounced/cancelled input is not a guarantee of the last page before closing.
Only admitted and committed records are displayed as saved. Offscreen fixtures
cover both native Qt PDF and the image fallback; real operating-system gesture
coverage beyond the exercised keyboard/wheel/scrollbar boundary remains a manual
check. A combined full regression gate is required before release or commit.
