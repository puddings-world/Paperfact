"""Verify a CLI report round trip with one isolated loopback model completion."""

import hashlib
import json
import subprocess
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REQUESTED = "synthetic-requested-model"
RETURNED = "synthetic-returned-model"
KEY = "paperfact-synthetic-acceptance-key"
QUOTE = "The synthetic prior study did not test an independent collection."


def verify(command, folder, env, package):
    """Exercise the supplied executable; never use a real account or provider."""
    from paper_daily.research_generation import list_recovery_requests

    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    workspace = folder / "workspace"
    workspace.mkdir()
    environment = {**env, "PAPERFACT_DATA": str(workspace), "NO_PROXY": "127.0.0.1"}
    calls, errors = [], []

    class Model(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):  # noqa: N802
            self.connection.settimeout(2)
            try:
                if (self.path != "/v1/chat/completions"
                        or self.headers.get("Authorization") != "Bearer " + KEY):
                    raise ValueError("Unexpected synthetic route")
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 1024 * 1024:
                    raise ValueError("Synthetic request exceeds its byte budget")
                request = json.loads(self.rfile.read(size))
                if request["model"] != REQUESTED or calls:
                    raise ValueError("Unexpected or repeated model completion")
                prompt = json.loads(request["messages"][-1]["content"])
                original = next(item for item in prompt["original_pages"]
                                if any(QUOTE in page["text"] for page in item["pages"]))
                source = next(item for item in prompt["sources"]
                              if item["id"] == original["source_id"])
                page = next(page["page"] for page in original["pages"] if QUOTE in page["text"])
                calls.append(source["document_hash"])
                section = dict(heading="Synthetic source evidence", statements=[dict(
                    text="Independent evaluation was missing.", interpretation="reported",
                    passages=[dict(source_id=source["id"], quote=QUOTE, page=page, anchor=None)],
                )])
                content = json.dumps(dict(sections=[section]))
                result = dict(model=RETURNED, choices=[dict(
                    message=dict(role="assistant", content=content), finish_reason="stop",
                )], usage=dict(prompt_tokens=1, completion_tokens=1))
                body = json.dumps(result).encode("utf-8")
                self.send_response(200)
            except (ValueError, KeyError, TypeError, StopIteration) as error:
                errors.append(type(error).__name__)
                body = b'{"error":"synthetic acceptance rejected request"}'
                self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Model)
    thread = threading.Thread(target=server.serve_forever,
                              kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()

    def run(*arguments, input=None):
        result = subprocess.run([*map(str, command), *map(str, arguments)],
                                env=environment, input=input, capture_output=True, timeout=45)
        if result.returncode:
            raise RuntimeError("Source-report acceptance command failed: " + arguments[0])
        return result.stdout.decode("utf-8")

    try:
        run("list-import", package)
        settings = dict(active_profile="fixture", profiles=dict(fixture=dict(
            backend="openai", model=REQUESTED, api_key=KEY, isolated=True,
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
        )))
        from verify_private_report import run as run_private

        from paper_daily.ai_job_intent import FrozenRoutes
        from paper_daily.ai_types import Settings

        arguments = ("survey", "demo", "--sources", "--source-paper", "demo:paperfact")
        # A child that ignores the private route must fail instead of using disk settings.
        disabled = dict(backend="none", model="wrong-disk-model", isolated=True)
        (workspace / "llm.json").write_text(json.dumps(disabled), encoding="utf-8")
        selected = Settings("openai", model=REQUESTED, api_key=KEY, isolated=True,
                            base_url=f"http://127.0.0.1:{server.server_port}/v1")
        routes = FrozenRoutes(selected, {"survey": selected},
                              account_directory=str(workspace / "ai-accounts"))
        generated = run_private(command, arguments, environment, routes)
        if KEY in generated or KEY in json.dumps(environment) or KEY in str(command):
            raise AssertionError("Synthetic credential escaped the private handoff")
        if "Source-aware survey: saved" not in generated:
            raise AssertionError("The synthetic report was not saved")
        if json.loads((workspace / "llm.json").read_text(encoding="utf-8")) != disabled:
            raise AssertionError("Private handoff rewrote child settings")
        (workspace / "llm.json").write_text(json.dumps(settings), encoding="utf-8")
        archive = folder / "report.zip"
        run("list-export", "demo", "--out", archive)
        with zipfile.ZipFile(archive) as data:
            tables = json.loads(data.read("tables.json"))
            report = json.loads(data.read("files/" + tables["survey_reports"][0]["path"]))["report"]
            manifest = json.loads(data.read("manifest.json"))
            originals = manifest["survey_sources"]
            if not originals or any(hashlib.sha256(data.read("files/" + item["path"])).hexdigest()
                                    != item["sha256"] for item in originals):
                raise AssertionError("Exported report originals differ")
        passage = report["sections"][0]["statements"][0]["passages"][0]
        if (report["generation"] != dict(task="survey", backend="openai",
                                        requested_model=REQUESTED, returned_model=RETURNED)
                or passage["quote"] != QUOTE or passage["location"]["state"] != "located"
                or calls != [originals[0]["sha256"]] or errors):
            raise AssertionError("Report source/model provenance differs")
        audited = json.loads(run("integration", "analysis.audit", "--workspace", workspace,
                                 input=json.dumps(dict(list_id="demo")).encode("utf-8")))
        if (not audited["ok"] or audited["result"]["originals_verified"] != 1
                or audited["result"]["verified_located_passages"] != 1
                or audited["result"]["semantics"] != "not_checked"):
            raise AssertionError("Read-only saved list audit differs")
        records = list_recovery_requests(workspace / "papers.db")
        if len(records) != 1:
            raise AssertionError("Exactly one completed report must be retained")
        retained = json.loads(run("survey", "demo", "--retained", records[0]["request_id"]))
        if retained != report or "Source-aware survey: cached" not in run(*arguments):
            raise AssertionError("Retained report or cached retry differs")
        if calls != [originals[0]["sha256"]] or errors:
            raise AssertionError("A read or cached retry repeated model completion")
        return dict(saved=True, quote_located=True, originals_verified=True,
                    requested_model=REQUESTED, returned_model=RETURNED,
                    retained_read=True, cached_without_completion=True,
                    private_handoff=True, child_disk_settings_ignored=True,
                    list_audit_verified=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        if thread.is_alive():
            raise RuntimeError("Synthetic model server did not stop")
