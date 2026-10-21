# Optional product-data consent lifecycle

Use this when an app introduces optional usage recording or background submission.
Public distribution alone is not a reason to add tracking. Determine the concrete
improvement question and the data actually needed first.

## Separate three decisions

1. Whether the app records optional product events locally.
2. Whether the app sends specified events to a specified recipient.
3. Whether and when to show the notice again.

Represent them separately. "Do not ask again" only changes reminders. Local
recording, a file export, or opening/importing a shared workspace cannot authorize
background submission. An unavailable receiver must not appear operational.

If a product separately requires a first-use usage acknowledgement, give it its
own policy and state. Do not infer optional analytics consent from that acceptance.
When saving both choices together, make persistence atomic and test independent
withdrawal/policy renewal. A mandatory usage explanation does not itself establish
legal terms or justify requiring unrelated data collection.

## Notice and stored choice

- Explain the purpose, categories, excluded content, recipient/location, retention,
  withdrawal and effect of declining in ordinary product language.
- Start optional agreement controls unchecked. Checking without saving, closing,
  Escape and declining are not acceptance. Keep the app usable after declining.
- For a first-use invitation, prefer lifecycle initialization after the main UI is
  visible. Deduplicate prompts per launch; do not open them from reusable widgets
  or background model calls.
- Store accepted purpose/version and time. Scope reminder suppression to a notice
  version and define a non-nagging cooldown for "later"; a specific day count is a
  product choice, not a universal rule.
- Treat changed-purpose consent as inactive until renewed. Do not leave an old
  record in place with INSERT OR IGNORE while displaying a new checkbox as enabled.
- Save choice and reminder state consistently. Repeated acceptance of the same
  version is idempotent; withdrawal clears the local recording identity and data
  covered by the notice. Renewed collection must not silently carry forward data
  gathered for an incompatible purpose.
- Keep a permanent settings entry accessible without signing in to an AI provider.
  Read/storage errors fail closed for optional collection without blocking core use.

## Export and cloud boundaries

Preview the exact export and recheck consent after long-lived native dialogs,
not only before opening a file chooser. A future uploader also checks consent
immediately before sending queued work and defines withdrawal/deletion behavior
for server, derived and backup copies. A local delete cannot revoke files someone
has already shared manually.

Transport configuration, public notice text and consent version belong to each
product. The common mechanism is reusable; legal adequacy depends on the actual
data practice and audience. Do not certify compliance from the presence of a
checkbox or a copied template.

## Behavioral acceptance cases

First launch with no choice; accept only after explicit action; unchecked decline;
checked-but-closed; do-not-ask without consent; cooldown across launches; duplicate
prompt callbacks; repeated acceptance; policy change; withdrawal/reacceptance;
storage failure; withdrawal while the export chooser is open; and verifying that
research imports, exports and account switching do not transfer consent.

For cloud submission, additionally test revocation while queued/in flight,
deduplicated retries and deletion propagation. Local fixture tests cannot certify
those integrations.
