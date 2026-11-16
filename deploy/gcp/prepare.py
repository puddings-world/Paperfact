"""Render existing pilot templates for offline review; never install or contact GCP."""

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

FORMAT = "paperfact.sync-pilot-review.v1"
FIELDS = {"format", "project_id", "region", "zone", "hostname", "monthly_budget_usd",
          "backup_bucket", "backup_snapshot", "source_commit", "mobile_zip_sha256",
          "browser_enabled"}
ROOT = Path(__file__).resolve().parent


def _unique(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate configuration field")
        result[name] = value
    return result


def load(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(16 * 1024 + 1)
    if len(raw) > 16 * 1024:
        raise ValueError("Pilot review configuration exceeds 16 KiB")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
    if not isinstance(value, dict) or set(value) != FIELDS or value["format"] != FORMAT:
        raise ValueError("Use the closed pilot.example.json configuration")
    patterns = {
        "project_id": r"[a-z][a-z0-9-]{4,28}[a-z0-9]",
        "region": r"[a-z]+(?:-[a-z]+)+[0-9]+",
        "backup_bucket": r"[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]",
        "backup_snapshot": r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}",
        "source_commit": r"(?:[0-9a-f]{40}|[0-9a-f]{64})",
        "mobile_zip_sha256": r"[0-9a-f]{64}",
    }
    for name, pattern in patterns.items():
        if not isinstance(value[name], str) or not re.fullmatch(pattern, value[name]):
            raise ValueError("Invalid pilot review field: " + name)
    host = value["hostname"]
    if (not isinstance(host, str) or len(host) > 253 or "." not in host
            or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
                   for part in host.split(".")) or host.replace(".", "").isdigit()):
        raise ValueError("Use a DNS hostname without URL, port or directive text")
    if value["zone"] not in tuple(value["region"] + "-" + c for c in "abcdefghijklmnopqrstuvwxyz"):
        raise ValueError("Zone must belong to the selected region")
    budget = value["monthly_budget_usd"]
    if (type(budget) not in (int, float) or budget <= 0
            or (type(budget) is float and not math.isfinite(budget))
            or type(value["browser_enabled"]) is not bool):
        raise ValueError("Set a positive review budget and an explicit browser boolean")
    return value


def prepare(config, output):
    """Create one new review directory; interrupted output is retained, never overwritten."""
    value = load(config)
    generated, inputs = {}, {}
    for name in ("paperfact-sync.service", "paperfact-nginx.conf",
                 "paperfact-backup-upload.service"):
        raw = (ROOT / (name + ".example")).read_bytes()
        inputs[name + ".example"] = hashlib.sha256(raw).hexdigest()
        text = raw.decode("utf-8").replace("\r\n", "\n")
        text = text.replace("sync.example.org", value["hostname"])
        text = text.replace("REPLACE_WITH_PRIVATE_BUCKET", value["backup_bucket"])
        text = text.replace("REPLACE_WITH_VERIFIED_SNAPSHOT", value["backup_snapshot"])
        if name == "paperfact-sync.service" and value["browser_enabled"]:
            lines = text.splitlines()
            base = next(line for line in lines if line.startswith("ExecStart="))
            browser = next(line[2:] for line in lines if line.startswith("# ExecStart="))
            text = text.replace(base + "\n", browser + "\n", 1)
        if "REPLACE_WITH_" in text:
            raise ValueError("Unresolved pilot template placeholder")
        generated[name] = text.encode("utf-8")
    review = dict(format=FORMAT, state="prepared_for_review", config=value,
                  template_sha256=inputs,
                  files={name: dict(sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))
                         for name, raw in generated.items()},
                  resource_changes=False, credentials_accessed=False,
                  budget_enforced=False, artifacts_verified=False,
                  pending=["owner target and cost approval", "project/IAM/DNS/bucket review",
                           "pinned server/mobile artifact verification", "TLS and mount acceptance",
                           "authority history/anchoring/fencing", "hosted recovery rehearsal",
                           "installed Windows/Mac/phone convergence"])
    generated["review.json"] = (json.dumps(review, indent=2, allow_nan=False) + "\n").encode()
    output = Path(output).absolute()
    output = output.parent.resolve(strict=True) / output.name
    output.mkdir(mode=0o700, exist_ok=False)
    for name, raw in generated.items():
        with (output / name).open("xb") as stream:
            stream.write(raw)
    return dict(state="prepared_for_review", files=len(generated), resource_changes=False,
                budget_enforced=False, artifacts_verified=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True,
                        help="Reviewed non-secret JSON; see pilot.example.json")
    parser.add_argument("--output", type=Path, required=True,
                        help="New review directory; never a live service/config directory")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare(args.config, args.output)))
        return 0
    except (ValueError, OSError, UnicodeError, RecursionError, StopIteration):
        print(json.dumps(dict(state="not_prepared", resource_changes=False,
                              message="Check configuration and use a new output directory. "
                                      "Interrupted output is retained for review.")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
