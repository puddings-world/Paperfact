# Google Slides for colleagues

The developer registers one Desktop OAuth client. Each researcher authorizes their
own Google account, and each export creates a private editable copy in that account.
Users do not need a Cloud project when the distribution includes the application
identity. This does not provide AI login, AI credits, or bidirectional Slides sync.

## Small team trial

Keep the Google Auth Platform audience External and publishing status Testing.
Add each colleague's Google account under Audience → Test users. Removing the test
users does not open access. Testing permits up to 100 test users; authorizations
using Drive access expire after seven days. Organizational administrators can also
block an app. See [Google's audience rules](https://support.google.com/cloud/answer/15549945).

Enable Drive API and Slides API and request only `drive.file`. Verify a fresh account
can authorize, create a deck, and read the speaker notes and source links. Automated
tests mock Google; they do not prove Cloud publication, verification or user consent.

## Optional developer distribution of the application identity

Normal Paperfact installation is **Git clone → setup → app**. Research bundles are
imported separately inside the app and include local PDFs. The source zip below is
only an optional way to deliver the Google Desktop app identity during testing;
it is not needed to create lists, sign in to AI services, or import research bundles.

From the developer checkout with `data/google-slides-client.json` configured:

```powershell
.\.venv\Scripts\python.exe scripts/package-colleagues.py
```

This creates `dist/Paperfact-colleagues.zip`. It contains the source, setup scripts
and an application-only `src/paper_daily/google-client.json`. It excludes the local
database, PDFs, AI settings and CLI login directories. The JSON contains the Desktop
client ID and its client secret, not any user's access/refresh tokens. A desktop
application cannot keep a distributed client secret confidential; do not substitute
a web-server OAuth client or service-account key. See
[Google's native-app OAuth guide](https://developers.google.com/identity/protocols/oauth2/native-app).

Recipients extract the zip, run `scripts/setup.ps1` (or `setup.sh`), start the app,
and configure their own AI connections. Share a reading-list bundle separately if
desired. A plain Git clone does not include this generated application identity;
use the prepared distribution or configure a developer client locally. Runtime
precedence is local client file, deployment environment variables, then bundled client.

## Public release

Before opening to people outside the test list, use Audience → Publish app to change
to In production. Publishing and verification are separate: complete the branding,
privacy-policy/homepage/domain and any verification Google requires. `drive.file`
is non-sensitive, but that does not automatically complete the app's branding checks.
Keep development/testing and production Cloud projects separate when moving beyond
the trial. Do not delete test users as a substitute for publishing.

[Google scope guidance](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)
and [production readiness](https://developers.google.com/identity/protocols/oauth2/production-readiness/overview).
