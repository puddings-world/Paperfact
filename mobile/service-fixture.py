"""Isolated local reference authority for the JavaScript integration check."""

import base64
import json
import sys
import tempfile
import threading
from pathlib import Path

core_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(core_root / "src"))

from paper_daily.sync_http import make_server  # noqa: E402
from paper_daily.sync_service import ReferenceService  # noqa: E402


def artifact_fixture():
    import pymupdf

    from paper_daily.sync_files import canonical_json, descriptor, validate_closure

    paper = "00000000-0000-4000-8000-000000000001"
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 2, 2), False)
    pixmap.clear_with(200)
    image = pixmap.tobytes("png")
    body = {
        "version": 1,
        "evidence_asset": None,
        "deck": {
            "paper_id": paper,
            "paper_title": "Synthetic research",
            "title": "研究 🧪",
            "mode": "notes",
            "audience": "Researchers",
            "minutes": 5,
            "slides": [
                {
                    "title": "Evidence",
                    "section": "Method",
                    "takeaway": "Traceable evidence",
                    "bullets": ["A result"],
                    "speaker_notes": "原文引用與講稿",
                    "sources": ["figure-1"],
                    "figure": "figure-1",
                    "elements": [
                        {
                            "kind": "text",
                            "text": "研究 🧪",
                            "x": 40.0,
                            "y": 40.0,
                            "w": 1000.0,
                            "h": 100.0,
                            "size": 40.0,
                            "bold": True,
                        },
                        {
                            "kind": "figure",
                            "figure": "figure-1",
                            "x": 200.0,
                            "y": 160.0,
                            "w": 580.0,
                            "h": 300.0,
                        },
                    ],
                }
            ],
            "sources": [{"id": "figure-1", "label": "Figure 1", "kind": "figure", "page": 1}],
            "figures": [{"id": "figure-1", "label": "Figure 1", "asset_id": "image"}],
            "coverage": ["方法"],
            "created_at": "2026-10-26T00:00:00Z",
            "deck_id": "python-fixture",
            "source_hash": "",
            "generation": {},
            "edited": False,
            "version": 1,
        },
    }
    data = canonical_json(body)
    image_info, body_info = descriptor(image, "image/png"), descriptor(data, "application/json")
    payload = {
        "paper_id": paper,
        "feature": "deck",
        "slot": "notes",
        "format_version": 1,
        "source_document_hash": None,
        "input_versions": {
            "schema_version": 1,
            "complete": False,
            "entities": [],
            "documents": [],
            "inputs_sha256": None,
        },
        "body": body_info,
        "assets": [{"id": "image", "role": "figure", **image_info}],
    }
    blobs = {body_info["sha256"]: data, image_info["sha256"]: image}
    validate_closure(payload, lambda row: blobs[row["sha256"]])
    return {
        "payload": payload,
        "blobs": {key: base64.b64encode(value).decode() for key, value in blobs.items()},
    }


def main():
    with tempfile.TemporaryDirectory(prefix="paperfact-mobile-service-") as folder:
        root = Path(folder)
        service = ReferenceService(root / "authority.sqlite", blob_root=root / "blobs")
        token = service.enroll("demo-workspace", "demo-phone")
        desktop_token = service.enroll("demo-workspace", "demo-desktop")
        server = make_server(service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(
            json.dumps(
                {
                    "url": f"http://127.0.0.1:{server.server_port}",
                    "token": token,
                    "desktop_token": desktop_token,
                    "artifact": artifact_fixture(),
                }
            ),
            flush=True,
        )
        try:
            sys.stdin.readline()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
