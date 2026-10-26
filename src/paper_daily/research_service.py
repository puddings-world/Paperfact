"""Shared local research operations for UI/CLI and a future external-tool adapter.

These functions use the process's selected workspace. They do not expose a server,
authenticate an external caller, switch workspaces or execute bundle instructions.
An external adapter must authorize workspace and file access before calling them.
"""

from pathlib import Path

from paper_daily import bundle, bundle_links
from paper_daily.store import connect


def list_collections() -> list[dict]:
    """Return stable list IDs and names without account or research content."""
    with connect() as conn:
        return [
            dict(row)
            for row in conn.execute("SELECT id, name FROM lists ORDER BY created_at, id")
        ]


def inspect_bundle(source: Path) -> dict:
    """Validate and preview a research snapshot without invoking AI."""
    return bundle.inspect(Path(source))


def export_bundle(
    list_id: str, out: Path, *, notes: bool = True, with_pdfs: bool = True, log=lambda _m: None
) -> dict:
    """Export saved research; the default includes available PDF bytes offline."""
    return bundle.export(list_id, Path(out), notes=notes, with_pdfs=with_pdfs, log=log)


def import_bundle(
    source: Path, *, replace: bool = False, pdfs: bool = True, log=lambda _m: None
) -> dict:
    """Merge validated research, preserving local work unless replacement is explicit."""
    return bundle.import_(Path(source), replace=replace, pdfs=pdfs, log=log)


def download_bundle(url: str, target: Path, **kwargs) -> Path:
    """Download a bounded package; preview/import remain explicit separate steps."""
    return bundle_links.download(url, target, **kwargs)


def make_share_link(url: str, source: Path) -> str:
    """Attach an integrity checksum to a file host URL; never upload research."""
    return bundle_links.make_link(url, source)
