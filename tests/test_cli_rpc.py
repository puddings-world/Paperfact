import os
import sys

import pytest

from paper_daily.cli_rpc import Client


def test_protocol_ignores_notifications_and_refuses_server_tool_requests(tmp_path):
    script = """
import json, sys
request = json.loads(input())
print(json.dumps({"method":"notice"}), flush=True)
print(json.dumps({"id":99,"method":"run-a-tool","params":{}}), flush=True)
denial = json.loads(input())
print(json.dumps({"id":request["id"], "result":{"denied":denial["error"]["code"]}}), flush=True)
"""
    with Client([sys.executable, "-u", "-c", script], env=dict(os.environ), cwd=tmp_path) as client:
        assert client.request("initialize", {}) == {"denied": -32601}
    assert client.proc.poll() is not None


def test_protocol_timeout_stops_child_process(tmp_path):
    with (
        Client(
            [sys.executable, "-u", "-c", "import time; time.sleep(30)"],
            env=dict(os.environ),
            cwd=tmp_path,
        ) as client,
        pytest.raises(TimeoutError),
    ):
        client.request("initialize", {}, timeout=0.05)
    assert client.proc.poll() is not None


def test_protocol_errors_do_not_surface_credentials(tmp_path):
    script = """
import json
request = json.loads(input())
print(json.dumps({"id":request["id"],"error":{"message":"secret"}}), flush=True)
"""
    with (
        Client([sys.executable, "-u", "-c", script], env=dict(os.environ), cwd=tmp_path) as client,
        pytest.raises(ValueError) as exc,
    ):
        client.request("initialize", {})
    assert "secret" not in str(exc.value)


def test_exit_allows_server_to_release_resources_on_stdin_eof(tmp_path):
    script = """
import json, sys
from pathlib import Path
request = json.loads(input())
print(json.dumps({"id":request["id"],"result":{}}), flush=True)
sys.stdin.read()
Path("released").write_text("done")
"""
    with Client([sys.executable, "-u", "-c", script], env=dict(os.environ), cwd=tmp_path) as client:
        client.request("initialize", {})
    assert (tmp_path / "released").read_text() == "done"


def test_claude_control_only_gets_usage_and_denies_tool_requests(tmp_path):
    script = """
import json
for expected in ['initialize', 'get_usage']:
    request = json.loads(input())
    assert request['type'] == 'control_request'
    assert request['request']['subtype'] == expected
    if expected == 'get_usage':
        assert request['request']['skip_behaviors'] is True
        print(json.dumps({'type':'control_request','request_id':'tool',
                          'request':{'subtype':'can_use_tool'}}), flush=True)
        denied = json.loads(input())
        assert denied['response']['subtype'] == 'error'
    print(json.dumps({'type':'control_response','response':{
        'request_id':request['request_id'],'subtype':'success',
        'response':{'usage':5}}}), flush=True)
"""
    with Client([sys.executable, "-u", "-c", script], env=dict(os.environ), cwd=tmp_path) as client:
        client.control({"subtype": "initialize", "hooks": {}})
        assert client.control({"subtype": "get_usage", "skip_behaviors": True}) == {"usage": 5}
    assert client.proc.poll() is not None


def test_claude_usage_adapter_disables_tools_hooks_and_transcript_scan(monkeypatch):
    from paper_daily import ai_accounts, cli_rpc
    from paper_daily.ai_types import Settings

    observed = []

    class FakeClient:
        def __init__(self, argv, *, env, cwd):
            assert '--no-session-persistence' in argv and '--strict-mcp-config' in argv
            assert argv[argv.index('--tools') + 1] == ''
            assert json_value(argv[argv.index('--settings') + 1]) == {'disableAllHooks': True}
            assert cwd and env == {'fixture': 'env'}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def control(self, request):
            observed.append(request)
            return {'rate_limits': {'five_hour': {'utilization': 5}}}

    from json import loads as json_value

    monkeypatch.setattr(cli_rpc, 'Client', FakeClient)
    monkeypatch.setattr(ai_accounts, 'command', lambda backend: ['claude'])
    monkeypatch.setattr(ai_accounts, 'environment', lambda cfg: {'fixture': 'env'})
    assert ai_accounts.claude_usage(Settings('cli'))['rate_limits']['five_hour']['utilization'] == 5
    assert observed == [
        {'subtype': 'initialize', 'hooks': {}}, {'subtype': 'get_usage', 'skip_behaviors': True}
    ]
