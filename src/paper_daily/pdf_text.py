"""The text of each page of a PDF, read once per version of the file.

Highlights, slide materials and their checks all need a paper's page text, and
cutting a PDF into text costs about 30 ms a page. Each caller used to do it again,
on the reader's thread, every time its tab was shown. The file's identity (path,
size and both timestamps) is the key, so a replaced or edited PDF is read afresh.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


def pages(path: Path) -> tuple[str, ...]:
    stat = Path(path).stat()
    return _read(str(Path(path).resolve()), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)


@lru_cache(maxsize=8)
def _read(filename: str, _modified: int, _changed: int, _size: int) -> tuple[str, ...]:
    import pymupdf

    with pymupdf.open(filename) as doc:
        return tuple(page.get_text() for page in doc)
