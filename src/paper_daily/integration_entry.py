"""Bootstrap the workspace before importing modules with configured paths."""

import argparse
import json
import os
import sys
from pathlib import Path


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("mcp", "integration"):
        from paper_daily.cli import main as legacy_main

        return legacy_main(argv)
    parser = argparse.ArgumentParser(prog="paperfact " + argv[0])
    parser.add_argument(
        "--workspace",
        required=True,
        help="Absolute path to the same data folder used by the desktop",
    )
    if argv[0] == "integration":
        parser.add_argument(
            "operation",
            choices=(
                "config",
                "lists.list",
                "lists.read",
                "imports.propose",
                "imports.commit",
                "imports.discard",
                "operations.inspect",
            ),
        )
        parser.add_argument("--file", help="UTF-8 JSON arguments; otherwise read stdin")
    args = parser.parse_args(argv[1:])
    workspace = Path(args.workspace).expanduser()
    if not workspace.is_absolute():
        parser.error("--workspace must be an absolute path")
    configured = sys.modules.get("paper_daily.config")
    if configured is not None and configured.DATA_DIR.resolve() != workspace.resolve():
        parser.error("Workspace already bound in this process; start a new helper process")
    os.environ["PAPERFACT_DATA"] = str(workspace.resolve())
    # The helper installs no telemetry exporter. Explicitly disable optional SDK exporters.
    os.environ["OTEL_SDK_DISABLED"] = "true"
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if argv[0] == "mcp":
        from paper_daily.mcp_server import run

        run()
        return 0
    from paper_daily.integration_config import host_config
    from paper_daily.local_operations import MAX_BYTES, dispatch
    from paper_daily.store import init_db

    if args.operation == "config":
        print(json.dumps(host_config(), ensure_ascii=False, indent=2))
        return 0
    try:
        if args.file:
            with Path(args.file).open("rb") as source:
                raw = source.read(MAX_BYTES + 1)
        elif sys.stdin.isatty():
            raw = b"{}"
        else:
            raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("JSON input exceeds 2 MB")
        arguments = json.loads(raw.decode("utf-8-sig") or "{}")
        init_db()
        result = dispatch(args.operation, arguments)
    except (OSError, ValueError) as exc:
        result = {"ok": False, "error": {"code": "invalid_input", "message": str(exc)}}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
