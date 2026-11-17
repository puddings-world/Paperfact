"""Bundle the developer Desktop OAuth client; never user grants or service accounts."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path


def prepare(raw, target):
    try:
        data = json.loads(raw)
        client = data["installed"]
        identity = client["client_id"]
        secret = client.get("client_secret", "")
        if (not isinstance(identity, str) or len(identity) > 300
                or not identity.endswith(".apps.googleusercontent.com")
                or not isinstance(secret, str) or len(secret) > 300
                or any(ord(c) < 33 or ord(c) > 126 for c in identity + secret)):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise ValueError(
            "Provide a Google Desktop app OAuth client JSON, never user tokens"
        ) from None
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=".google-client-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({"installed": {"client_id": identity, "client_secret": secret}}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parents[1]
                        / "src/paper_daily/google-client.json")
    args = parser.parse_args()
    raw = os.environ.get("PAPERFACT_GOOGLE_DESKTOP_CLIENT")
    if not raw:
        parser.error(
            "Configure the PAPERFACT_GOOGLE_DESKTOP_CLIENT repository secret before packaging"
        )
    prepare(raw, args.output)
    print("Bundled Google Desktop OAuth application configuration; no user grant included")


if __name__ == "__main__":
    main()
