"""Bootstrap the workspace before importing modules with configured paths."""

import argparse
import json
import os
import sys
from pathlib import Path


def _private_job(argv):
    # No CLI/config import, dotenv loading or research I/O before frame validation.
    from paper_daily.ai_job_intent import JobIntentError
    from paper_daily.cli_job_protocol import hello_line, read_frame, ready_line

    try:
        if len(argv) < 2:
            raise JobIntentError("invalid_expected_binding")
        identity, *command = argv
        hello = hello_line(identity)
        sys.stdout.write(hello.decode("ascii"))
        sys.stdout.flush()
        intent = read_frame(
            sys.stdin.buffer, expected_request_id=identity, expected_command=command
        )
    except (JobIntentError, OSError, AttributeError):
        print("AI job startup failed; please retry.", file=sys.stderr, flush=True)
        return 2
    from paper_daily import runtime

    with runtime.private_job_environment():
        from paper_daily import llm

        with llm.private_job_scope(intent.routes):
            sys.stdout.write(ready_line(identity).decode("ascii"))
            sys.stdout.flush()
            from paper_daily.cli import main as legacy_main

            return legacy_main(command)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "_desktop-job-v1":
        return _private_job(argv[1:])
    if argv and argv[0] == "diagnostics":
        from paper_daily.diagnostics import main as diagnostics_main

        return diagnostics_main(argv[1:])
    if argv and argv[0] == "app":
        from paper_daily.diagnostics import install_error_hooks

        install_error_hooks(phase="startup")
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
                "analysis.audit",
                "imports.propose",
                "imports.commit",
                "imports.discard",
                "operations.inspect",
                "review.notes.list",
                "review.notes.targets",
                "review.notes.open",
                "review.notes.read",
                "review.notes.sources",
                "review.notes.page",
                "review.notes.map",
                "review.notes.clear",
                "review.notes.save",
                "review.notes.decide",
                "review.claims.list",
                "review.claims.inspect",
                "review.claims.targets",
                "review.claims.open",
                "review.claims.read",
                "review.claims.save",
                "review.claims.verify",
                "review.claims.page",
                "review.claims.apply",
                "review.highlights.list",
                "review.highlights.inspect",
                "review.highlights.targets",
                "review.highlights.open",
                "review.highlights.read",
                "review.highlights.save",
                "review.highlights.verify",
                "review.highlights.page",
                "review.highlights.apply",
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
    from paper_daily.local_operations import MAX_BYTES, bootstrap, dispatch

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
        if args.operation != "analysis.audit" and not args.operation.startswith(
            ("review.notes.", "review.claims.", "review.highlights.")
        ):
            bootstrap()
        result = dispatch(args.operation, arguments)
    except (OSError, ValueError) as exc:
        result = {"ok": False, "error": {"code": "invalid_input", "message": str(exc)}}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
