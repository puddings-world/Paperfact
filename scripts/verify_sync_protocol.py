"""Verify a packaged loopback sync listener with synthetic, private device state."""

import http.client
import json
import os
import re
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

HEADER = "X-Paperfact-Sync-Instance"


def _graph_operations(identity):
    from paper_daily.sync_content import content_id

    paper_id = "11111111-1111-4111-8111-111111111111"
    scope = {"kind": "paper", "id": paper_id}
    def operation(kind, entity_id, op_id, payload, parents):
        return dict(version=2, operation_id=op_id, **identity, entity_type=kind,
                    entity_id=entity_id, action="put", base_revision=0, depends_on=None,
                    incarnation=op_id, parents=parents, structure_revision=0, payload=payload)

    paper = operation("paper", paper_id, "packaged-paper-created", dict(
        title="Synthetic packaged research", authors=[], year=2026, venue=None,
        abstract=None, doi=None, arxiv_id=None, s2_id=None, page_url=None,
        pdf_url=None, source="fixture"), [])
    raw = json.dumps(dict(checked="2026-11-15T00:00:00+00:00",
                          edges=[["DOI:10.1/a", "S2:fixture"]],
                          citations={"DOI:10.1/a": 3}, unplaced=1), indent=2)
    graph = operation("research_content", content_id(scope, "citation_graph", "main"),
                      "packaged-graph-created", dict(scope=scope, feature="citation_graph",
                      key="main", data={"value": raw}, source_document_hash=None),
                      [dict(kind="paper", id=paper_id, incarnation=paper["incarnation"])])
    return paper, graph


def _run(command, env, output):
    result = subprocess.run(
        list(map(str, command)), env=env, stdin=subprocess.DEVNULL,
        capture_output=True, timeout=25,
    )
    output.write_bytes(result.stdout + result.stderr)
    if result.returncode or b"Traceback (most recent call last)" in output.read_bytes():
        raise RuntimeError("Packaged sync command failed; inspect its private local log")


@contextmanager
def _listener(command, state, env, log):
    with log.open("wb") as stream:
        process = subprocess.Popen(
            [*map(str, command), "sync-admin", "serve", "--state", str(state), "--port", "0"],
            env=env, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
        )
        try:
            deadline = time.monotonic() + 20
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Packaged sync listener exited before readiness")
                with log.open("rb") as observed:
                    line = observed.readline(4097)
                if len(line) > 4096:
                    raise ValueError("Packaged sync readiness exceeds its bound")
                if line.endswith(b"\n"):
                    receipt = json.loads(line)
                    if (set(receipt) != {"state", "url"} or receipt["state"] != "serving"
                            or not re.fullmatch(r"http://127\.0\.0\.1:[0-9]{1,5}", receipt["url"])):
                        raise ValueError("Invalid packaged sync readiness")
                    yield receipt["url"]
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError("Packaged sync listener did not become ready")
                time.sleep(0.05)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def _post(endpoint, token, route, value, instance=None):
    connection = http.client.HTTPConnection("127.0.0.1", int(endpoint.rsplit(":", 1)[1]), timeout=5)
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    if instance is not None:
        headers[HEADER] = instance
    try:
        connection.request("POST", route, json.dumps(value).encode(), headers)
        response = connection.getresponse()
        body = response.read(4097)
        offers = response.headers.get_all(HEADER, [])
        if len(body) > 4096 or len(offers) != 1 or not re.fullmatch("[0-9a-f]{32}", offers[0]):
            raise ValueError("Invalid packaged sync response bounds or execution identity")
        return response.status, offers[0], json.loads(body)
    finally:
        connection.close()


def verify(command, folder, env):
    """Only launch owned children; never inherit real credentials or access research."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    state, credential = folder / "authority", folder / "device.json"
    _run([*command, "sync-admin", "init", "--state", state], env, folder / "init.log")
    identity = {"workspace_id": "packaged-workspace", "device_id": "packaged-device"}
    with _listener(command, state, env, folder / "first-listener.log") as endpoint:
        _run([
            *command, "sync-admin", "issue", "--state", state, "--endpoint", endpoint,
            "--workspace", identity["workspace_id"], "--device", identity["device_id"],
            "--output", credential,
        ], env, folder / "issue.log")
        token = json.loads(credential.read_text(encoding="utf-8"))["token"]
        status, first, body = _post(endpoint, token, "/v1/session/info", {})
        if status != 200 or body != identity:
            raise AssertionError("Packaged sync device identity differs")
        status, offered, body = _post(endpoint, token, "/v1/pull", {"after": 0, "limit": 1}, first)
        if status != 200 or offered != first or body != []:
            raise AssertionError("Packaged sync initial pull failed")
        paper, graph = _graph_operations(identity)
        for sequence, operation in enumerate((paper, graph), start=1):
            status, offered, event = _post(endpoint, token, "/v1/push",
                                           {"operation": operation}, first)
            if (status != 200 or offered != first or event.get("outcome") != "accepted"
                    or event.get("sequence") != sequence or event.get("operation") != operation):
                raise AssertionError("Packaged citation graph write failed")
        status, offered, retry = _post(endpoint, token, "/v1/push", {"operation": graph}, first)
        if status != 200 or offered != first or retry != event:
            raise AssertionError("Packaged citation graph retry differs")
        status, offered, tail = _post(endpoint, token, "/v1/pull", {"after": 2, "limit": 1}, first)
        if status != 200 or offered != first or tail != []:
            raise AssertionError("Packaged citation graph retry duplicated an event")
        status, offered, body = _post(endpoint, token, "/v1/pull", {"after": 1, "limit": 1}, first)
        if status != 200 or offered != first or body != [event]:
            raise AssertionError("Packaged citation graph pull differs")
    with _listener(command, state, env, folder / "second-listener.log") as endpoint:
        status, second, body = _post(endpoint, token, "/v1/pull", {"after": 0, "limit": 1}, first)
        if status != 428 or second == first or body != {"error": "sync_session_changed"}:
            raise AssertionError("Packaged sync accepted a stale execution")
        status, offered, body = _post(endpoint, token, "/v1/session/info", {})
        if status != 200 or offered != second or body != identity:
            raise AssertionError("Packaged sync reconnect identity differs")
        status, offered, body = _post(endpoint, token, "/v1/pull", {"after": 1, "limit": 1}, second)
        if status != 200 or offered != second or body != [event]:
            raise AssertionError("Packaged sync reconnect failed")
    return dict(authenticated_pull=True, stale_execution_refused=True, reconnected=True,
                citation_graph=True, citation_graph_retry=True, citation_graph_restart=True)
