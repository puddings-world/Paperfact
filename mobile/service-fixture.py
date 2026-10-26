"""Isolated local reference authority for the JavaScript integration check."""

import json
import sys
import tempfile
import threading
from pathlib import Path

core_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(core_root / "src"))

from paper_daily.sync_http import make_server  # noqa: E402
from paper_daily.sync_service import ReferenceService  # noqa: E402


def main():
    with tempfile.TemporaryDirectory(prefix="paperfact-mobile-service-") as folder:
        root = Path(folder)
        service = ReferenceService(root / "authority.sqlite", blob_root=root / "blobs")
        token = service.enroll("demo-workspace", "demo-phone")
        desktop_token = service.enroll("demo-workspace", "demo-desktop")
        server = make_server(service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}", "token": token,
                          "desktop_token": desktop_token}), flush=True)
        try:
            sys.stdin.readline()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
