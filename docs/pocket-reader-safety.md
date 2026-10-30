# Legacy pocket reader

New pocket exports disable PDF.js evaluation for both PDF display and full-text
extraction, using the legacy-compatible [Mozilla advisory workaround](https://github.com/mozilla/pdf.js/security/advisories/GHSA-wgrm-67xf-hhpq).
Existing exported HTML snapshots are unchanged; re-export a pocket page to receive
this template fix. Paperfact does not scan or modify previously shared bundles.

Regression tests exercise the actual exported parser calls with simulated PDF.js;
they validate configuration and normal outcomes, not browser exploitation resistance.
