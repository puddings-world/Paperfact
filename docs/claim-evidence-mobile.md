# Claim evidence on mobile

The mobile overview displays saved claim sets and quoted passages as read-only research.
The account, model and source-bound claim extraction still runs through the desktop producer;
receiving, rendering, restarting or deleting the mobile projection never starts an AI call.

Every card labels caller judgments as **proposed**. A supported/inferred/unresolved proposal is
separate from semantic validation, which remains **not performed**. Quote location refers only
to the producer's original PDF snapshot. A located quote is not proof that a claim is supported,
nor a guarantee that the original/current PDF is available on this device.

The closed mirror validates bounded fields, deterministic claim/passage/report IDs, duplicate
identities/locations, ambiguity candidates, anchors and semantic flags. It checks the non-null
envelope source, row document hash and original report hash are identical. The report's source
paper alias is retained provenance; it does not authorize navigation or moving content between
papers. Outer portable content identity and parent scope remain separately validated.

Cards use plain text and expose no automatic source URL, PDF activation, model action or edit.
Unlocated, ambiguous and invalid proposals remain clearly labeled. Proposed citation identities
stay unresolved without a trusted mapping. Saved generation/input metadata is not presented as
a semantic verdict. English and Traditional Chinese carry the same scope explanations.

Canonical updates/deletions suppress stale imported snapshots. Offline restart preserves accepted
claim bodies and tombstones. An invalid source or newer unsupported contract stops receive without
advancing the accepted cursor or replacing the prior projection; retry is explicit. Session tokens
remain in the existing in-memory transport boundary, outside saved research and exports.

The service worker adds only the static `claims.mjs` module to the shell. It does not cache private
research/authentication requests. This module's synchronous bounded SHA256 matches the Python
closed hash contract; the shared golden fixture is unchanged. Tests also compare Python-generated
location/Unicode vectors and exercise an actual ClaimJob with simulated completion through an
authenticated loopback HTTP service, then offline restart, retry and canonical deletion.

Run the normal mobile check with `--python <project-python> --core-root <checkout>` to include
that fixture. Production endpoints, live accounts, native phones and semantic research appraisal
remain separate acceptance checks.
