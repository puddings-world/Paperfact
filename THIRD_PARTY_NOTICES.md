# Third-party software and materials

Paperfact uses unmodified upstream packages. Their licenses are independent of
Paperfact's AGPL-3.0-or-later license. A binary build includes `licensing/` and a
generated `dependency-licenses/` directory, plus a version inventory in
`build-info.json`. Python wheels include their upstream notices where supplied.

| Component | License / source |
|---|---|
| PyMuPDF / MuPDF | AGPL-3.0; [licensing](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright), [source](https://github.com/pymupdf/PyMuPDF) |
| PySide6 / Shiboken / Qt | LGPL-3.0 / GPL alternatives per module; [Qt licensing](https://doc.qt.io/qt-6/licensing.html), [source](https://download.qt.io/official_releases/QtForPython/) |
| Qt WebEngine / Chromium | Multiple third-party licenses; [notices](https://doc.qt.io/qt-6/qtwebengine-licensing.html), [source](https://code.qt.io/cgit/qt/qtwebengine.git/) |
| Python | PSF license; [source](https://www.python.org/downloads/source/) |
| HTTPX, HTTPCore, AnyIO, H11, Markdown-it-py, mdit-py-plugins, mdurl | MIT; packaged upstream notices and version inventory |
| MCP Python SDK / mcp-types, Pydantic / pydantic-core | MIT; packaged upstream notices and version inventory |
| certifi | MPL-2.0; [source](https://github.com/certifi/python-certifi) |
| idna | BSD-3-Clause; [source](https://github.com/kjd/idna) |
| typing-extensions | PSF-2.0; [source](https://github.com/python/typing_extensions) |
| KaTeX 0.16.11 / Mermaid 10.9.1 | MIT; [KaTeX](https://github.com/KaTeX/KaTeX), [Mermaid](https://github.com/mermaid-js/mermaid) |
| highlight.js 11.10.0 | BSD-3-Clause; [source](https://github.com/highlightjs/highlight.js) |
| Noto Sans TC / JetBrains Mono | SIL Open Font License 1.1; pinned sources in `src/paper_daily/fonts.py` |
| PyInstaller bootloader | GPL with a distribution exception; [license](https://pyinstaller.org/en/stable/license.html) |

The build inventory lists the installed build environment, including build tools;
not every listed tool is shipped at runtime. Exact dependency versions are locked
in `uv.lock`. Qt DLLs remain separate files in the installed application.

Release maintainers must provide the matching Paperfact source archive and retain
access to corresponding third-party source for the binaries distributed, including
Qt/Chromium subcomponents. Notices and upstream links alone are not a certification
that every binary distribution obligation has been completed. Verify source and
notice coverage before public publication. Do not substitute commercial-only Qt or
MuPDF packages without the appropriate license.

## Research content

Papers and figures are not relicensed by Paperfact. Existing research screenshots
need their original attribution and permitted reuse; the AI settings screenshots
use synthetic accounts and usage. Research bundles are shared at the sender's
discretion under the rights applicable to their content.
