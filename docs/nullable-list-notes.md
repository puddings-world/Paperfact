# Nullable list notes in the version-2 sync domain

The persisted list schema permits SQL NULL for `lists.note`, including ordinary
unbound package imports. The version-2 list payload now accepts exactly a bounded
string or explicit JSON null. Capture preserves the original value; projection,
peers, package export and complete recovery preserve it again. NULL, empty text
and whitespace text remain distinct. This supersedes the nullable-list refusal
noted in the initial imported-source enrollment slice.

No version-1 behavior changes: v1 still requires text. No new fields or implicit
missing-value defaults are introduced. Booleans, numbers, objects, arrays,
oversized strings and unexpected fields remain invalid. The existing version-2
list writer already binds the explicit value into SQL without normalization.
The PWA validates the same closed domain and preserves null during retry,
projection and an offline restart. Its static shell cache advances to v8.

This is an additive v2 domain extension. An older v2 implementation that accepts
only text will reject a null-bearing operation; it must update before joining a
workspace using nullable list notes. Compatibility does not coerce null or strip
that operation. Existing version numbers alone do not imply an old build knows
every later bounded content-domain extension.

The owner approved changing the previous initial-enrollment test from expecting
a non-lossless nullable-list refusal to requiring a successful exact-null copy.
That assertion now checks the saved SQL NULL, while the new real two-device
fixtures check NULL/empty/whitespace/text separately through initial enrollment,
a captured rename, peer sync, package export and detached recovery. A separate
actual authenticated HTTP/PWA fixture exercises retry/offline persistence with
no model calls or mobile writes. Unsupported original sources, decks, history
formats and unknown files retain their existing refusal gates.
