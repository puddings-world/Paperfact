"""Authenticated loopback device controls never expose account/token metadata."""

import json

import pytest
from test_sync_http import endpoint as endpoint_fixture
from test_sync_http import request

from paper_daily import sync_device_protocol as protocol
from paper_daily.sync_http import HttpTransport

endpoint = endpoint_fixture


def test_actual_http_pages_rename_clear_and_peer_revoke(endpoint):
    service, token, url = endpoint
    peer = service.enroll("workspace", "b")
    service.enroll("foreign", "c")
    with HttpTransport(url) as transport:
        first = transport.device_catalog(token, limit=1)
        assert first == {
            "workspace_id": "workspace",
            "current_device_id": "a",
            "devices": [{"device_id": "a", "label": None, "revoked": False}],
            "next_cursor": "a",
        }
        second = transport.device_catalog(token, after=first["next_cursor"], limit=1)
        assert second["devices"] == [{"device_id": "b", "label": None, "revoked": False}]
        assert second["next_cursor"] is None
        assert transport.rename_device(token, "b", "Reading laptop")["changed"]
        assert not transport.rename_device(token, "b", "Reading laptop")["changed"]
        assert transport.device_catalog(peer)["devices"][1]["label"] == "Reading laptop"
        assert transport.rename_device(token, "b", None)["label"] is None
        assert transport.rename_device(token, "a", "This desktop")["changed"]
        assert transport.revoke_peer(token, "b") == {
            "device_id": "b",
            "revoked": True,
            "changed": True,
        }
        assert not transport.revoke_peer(token, "b")["changed"]
        with pytest.raises(PermissionError):
            transport.device_catalog(peer)
        assert transport.device_catalog(token)["devices"][1]["revoked"] is True
    assert service.pull(token) == []
    assert token not in json.dumps(first) and peer not in json.dumps(second)


@pytest.mark.parametrize(
    "route,payload",
    [
        ("list", {"after": None, "limit": 50}),
        ("rename", {"device_id": "missing", "label": "Label"}),
        ("revoke", {"device_id": "missing"}),
    ],
)
def test_missing_invalid_and_revoked_callers_have_same_401(endpoint, route, payload):
    service, token, url = endpoint
    revoked = service.enroll("workspace", "revoked")
    service.revoke(revoked)
    responses = []
    for credential in ("unknown-device-token", revoked):
        status, headers, body = request(
            url, credential, path="/v1/devices/" + route, body=json.dumps(payload).encode()
        )
        assert status == 401 and headers["Cache-Control"] == "no-store"
        responses.append(body)
    assert responses == [b'{"error":"authentication_required"}'] * 2
    status, _, body = request(
        url, token, path="/v1/devices/" + route, headers=[("Content-Length", "0")]
    )
    assert status == 401 and body == responses[0]


@pytest.mark.parametrize("route", ["rename", "revoke"])
def test_foreign_and_absent_targets_are_indistinguishable(endpoint, route):
    service, token, url = endpoint
    service.enroll("foreign", "foreign-device")
    results = []
    for target in ("absent", "foreign-device"):
        payload = {"device_id": target}
        if route == "rename":
            payload["label"] = "Label"
        status, _, body = request(
            url, token, path="/v1/devices/" + route, body=json.dumps(payload).encode()
        )
        results.append((status, body))
    assert results == [(404, b'{"error":"not_found"}')] * 2


@pytest.mark.parametrize(
    "route,payload",
    [
        ("list", {"after": None, "limit": True}),
        ("list", {"after": None, "limit": 101}),
        ("list", {"after": "bad cursor", "limit": 1}),
        ("list", {"after": None, "limit": 1, "workspace_id": "foreign"}),
        ("rename", {"device_id": "a", "label": " "}),
        ("rename", {"device_id": "a", "label": "a\nb"}),
        ("rename", {"device_id": "a", "label": "x" * 65}),
        ("rename", {"device_id": "a", "label": "okay", "token": "extra"}),
        ("revoke", {"device_id": "a"}),
        ("revoke", {"device_id": "b", "workspace_id": "foreign"}),
    ],
)
def test_closed_device_requests_fail_without_mutation(endpoint, route, payload):
    service, token, url = endpoint
    before = service.device_catalog(token)
    status, _, body = request(
        url, token, path="/v1/devices/" + route, body=json.dumps(payload).encode()
    )
    assert status == 400 and body == b'{"error":"invalid_request"}'
    assert service.device_catalog(token) == before


@pytest.mark.parametrize("route", ["/v1/enroll", "/v1/revoke", "/v1/devices/enroll"])
def test_no_public_device_issuance_or_admin_authority(endpoint, route):
    _, token, url = endpoint
    assert request(url, token, path=route)[0] == 404


@pytest.mark.parametrize("change", ["fields", "boolean", "duplicate", "cursor", "label", "budget"])
def test_transport_rejects_untrusted_device_response(endpoint, monkeypatch, change):
    _, token, url = endpoint
    value = {
        "workspace_id": "workspace",
        "current_device_id": "a",
        "devices": [{"device_id": "a", "label": None, "revoked": False}],
        "next_cursor": None,
    }
    if change == "fields":
        value["token_hash"] = "forbidden"
    elif change == "boolean":
        value["devices"][0]["revoked"] = 0
    elif change == "duplicate":
        value["devices"] *= 2
    elif change == "cursor":
        value["next_cursor"] = "unrelated"
    elif change == "label":
        value["devices"][0]["label"] = "bad\rlabel"
    else:
        value["devices"] *= 101
    with HttpTransport(url) as transport:
        monkeypatch.setattr(transport, "_post", lambda *a: value)
        with pytest.raises(ValueError):
            transport.device_catalog(token)


def test_catalog_response_cannot_change_authenticated_binding():
    with pytest.raises(ValueError, match="binding"):
        protocol.catalog(
            {
                "workspace_id": "foreign",
                "current_device_id": "a",
                "devices": [],
                "next_cursor": None,
            },
            identity={"workspace_id": "workspace", "device_id": "a"},
        )
