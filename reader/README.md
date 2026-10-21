# Reader

`paper-reader.html` is the source of the published Artifact reader.

It is a queue browser and a two-pane reading desk: the paper's extracted text on the
left, and the deep dive, your notes, and a question box using the embedding host's AI capability on the right.

It holds no data of its own. Everything it renders comes from the artifact's store:

| Document | Written by | Contents |
|---|---|---|
| `queue/upcoming` | `paperfact sync-queue` | the next N papers in reading order |
| `papers/<paper id>` | `paperfact prefetch` / the nightly run | `fullText`, `deepDive` |
| `state/progress` | the page itself | which papers are marked read |
| `notes/<paper id>/entries` | the page itself | your notes, newest first |

To publish an updated version, edit this file and re-publish it to the same artifact
URL. Publishing to a different path would create a second, separate artifact and
leave your notes behind on the old one.

Custom hosts can supply window.paperfact.use(name) for sample, db and user.
The Claude Artifact bridge remains the fallback when no custom host exists.
See [the capability and provider contracts](../docs/architecture.md).
