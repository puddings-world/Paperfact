"""Synthetic same-origin browser sessions; no browser profile or production key."""

import json
import secrets
from types import SimpleNamespace

import httpx
import pytest
from test_sync_http import running

from paper_daily.sync_browser import SESSION_SECONDS, BrowserSessions
from paper_daily.sync_http import HttpTransport, make_server
from paper_daily.sync_pairing import Invitation
from paper_daily.sync_service import ReferenceService


@pytest.fixture
def browser(tmp_path, monkeypatch):
    service = ReferenceService(tmp_path / "authority.sqlite")
    owner = service.enroll("workspace", "desktop")
    now = [1_000_000]
    monkeypatch.setattr(service, "_pair_now", lambda: now[0])
    code = secrets.token_urlsafe(32)
    grant = service.create_pairing(owner, code)
    key = secrets.token_bytes(32)
    origin = "https://sync.example.org"
    sessions = BrowserSessions(service, origin, key, clock=lambda: now[0])
    packet = Invitation(origin, code=code, **grant).encoded()
    with running(make_server(service, browser=sessions)) as url:
        yield SimpleNamespace(service=service, owner=owner, now=now, key=key, origin=origin,
                              sessions=sessions, packet=packet, url=url)


def post(fixture, path, value=None, cookie=None, headers=None):
    values = {"Origin": fixture.origin, "X-Paperfact-Browser": "1",
              "Sec-Fetch-Site": "same-origin"}
    if cookie and path not in {"pairing/prepare", "pairing/complete", "session/forget"}:
        values["X-Paperfact-Workspace"] = fixture.identity["workspace_id"]
        values["X-Paperfact-Device"] = fixture.identity["device_id"]
    if cookie:
        values["Cookie"] = fixture.sessions.cookie_name + "=" + cookie
    for key, value_ in (headers or {}).items():
        if value_ is None:
            values.pop(key, None)
        else:
            values[key] = value_
    return httpx.post(fixture.url + "/v1/browser/" + path,
                      json={} if value is None else value, headers=values, trust_env=False)


def cookie(response):
    assert response.status_code == 200, response.status_code
    return response.headers["set-cookie"].split(";", 1)[0].partition("=")[2]


def prepared(fixture):
    response = post(fixture, "pairing/prepare", {"invitation": fixture.packet})
    fixture.identity = response.json()
    return response.json(), cookie(response)


def test_actual_prepare_complete_pull_and_bearer_coexist_without_javascript_secrets(browser):
    identity, pending = prepared(browser)
    assert len(browser.service.device_catalog(browser.owner)["devices"]) == 1
    assert set(identity) == {"workspace_id", "device_id"}
    repeated = post(browser, "pairing/prepare", {"invitation": browser.packet}, pending)
    assert repeated.json() == identity and cookie(repeated) == pending
    denied = post(browser, "session/info", cookie=pending)
    assert denied.status_code == 403  # Pending cookie is not a research credential.
    completed = post(browser, "pairing/complete", cookie=pending)
    active = cookie(completed)
    assert completed.json() == identity
    header = completed.headers["set-cookie"]
    for flag in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/", f"Max-Age={SESSION_SECONDS}"):
        assert flag in header
    assert "Domain=" not in header and header.startswith("__Host-paperfact-device=")
    assert "credential" not in completed.text and browser.owner not in header
    assert cookie(post(browser, "pairing/complete", cookie=active)) == active
    assert post(browser, "session/info", cookie=active).json() == identity
    assert post(browser, "pull", {"after": 0, "limit": 10}, active).json() == []
    assert len(browser.service.device_catalog(browser.owner)["devices"]) == 2
    with HttpTransport(browser.url) as transport:
        assert transport.session_info(browser.owner)["device_id"] == "desktop"
    assert completed.headers["Cache-Control"] == "no-store"
    assert "access-control-allow-origin" not in completed.headers


def test_lost_complete_reply_restarts_after_invitation_expiry_and_issuer_revocation(browser):
    identity, pending = prepared(browser)
    assert post(browser, "pairing/complete", cookie=pending).status_code == 200
    browser.now[0] += 601
    browser.service.revoke(browser.owner)
    restarted = ReferenceService(browser.service.path)
    sessions = BrowserSessions(restarted, browser.origin, browser.key, clock=lambda: browser.now[0])
    with running(make_server(restarted, browser=sessions)) as url:
        browser.url, browser.sessions = url, sessions
        result = post(browser, "pairing/complete", cookie=pending)
        assert result.json() == identity
        active = cookie(result)
        assert post(browser, "session/info", cookie=active).json() == identity
    with restarted._transaction() as conn:
        assert conn.execute("SELECT count(*) FROM sync_devices").fetchone()[0] == 2


def test_second_claim_and_expired_unused_grant_never_create_extra_devices(browser):
    _identity, first = prepared(browser)
    _second_identity, second = prepared(browser)
    assert post(browser, "pairing/complete", cookie=first).status_code == 200
    assert post(browser, "pairing/complete", cookie=second).status_code == 403
    assert len(browser.service.device_catalog(browser.owner)["devices"]) == 2
    code = secrets.token_urlsafe(32)
    grant = browser.service.create_pairing(browser.owner, code)
    browser.packet = Invitation(browser.origin, code=code, **grant).encoded()
    _identity, unused = prepared(browser)
    browser.now[0] += 601
    assert post(browser, "pairing/complete", cookie=unused).status_code == 403
    assert len(browser.service.device_catalog(browser.owner)["devices"]) == 2


def test_csrf_cross_origin_missing_headers_and_mixed_authorization_are_refused(browser):
    for headers in ({"Origin": None}, {"Origin": "https://sync.example.org.attacker.invalid"},
                    {"X-Paperfact-Browser": None}, {"Sec-Fetch-Site": "same-site"},
                    {"Authorization": "Bearer " + browser.owner}):
        response = post(browser, "pairing/prepare", {"invitation": browser.packet}, headers=headers)
        assert response.status_code == 403 and "set-cookie" not in response.headers
    assert len(browser.service.device_catalog(browser.owner)["devices"]) == 1
    response = httpx.post(browser.url + "/v1/browser/pairing/prepare", trust_env=False,
                          content=json.dumps({"invitation": browser.packet}),
                          headers={"Origin": browser.origin, "X-Paperfact-Browser": "1",
                                   "Content-Type": "text/plain"})
    assert response.status_code == 415


def test_cookie_tampering_expiry_origin_key_and_duplicate_cookie_refuse_delivery(browser):
    _identity, pending = prepared(browser)
    active = cookie(post(browser, "pairing/complete", cookie=pending))
    tampered = ("A" if active[0] != "A" else "B") + active[1:]
    assert post(browser, "session/info", cookie=tampered).status_code == 403
    assert post(browser, "session/info").status_code == 403
    name = browser.sessions.cookie_name
    assert post(browser, "session/info", headers={"Cookie": f"{name}={active}; {name}={active}"}
                ).status_code == 403
    for session in (BrowserSessions(browser.service, browser.origin, secrets.token_bytes(32)),
                    BrowserSessions(browser.service, "https://other.example.org", browser.key)):
        with pytest.raises(PermissionError):
            session.credential(active)
    browser.now[0] += SESSION_SECONDS + 1
    assert post(browser, "session/info", cookie=active).status_code == 403


def test_revoke_and_explicit_forget_do_not_delete_research_or_reissue_device(browser):
    identity, pending = prepared(browser)
    active = cookie(post(browser, "pairing/complete", cookie=pending))
    browser.service.revoke_peer(browser.owner, identity["device_id"])
    assert post(browser, "session/info", cookie=active).status_code == 403
    assert post(browser, "pairing/complete", cookie=pending).status_code == 403
    response = post(browser, "session/forget", cookie=active)
    assert response.json() == {"forgotten": True}
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert browser.service.pull(browser.owner) == []
    assert len(browser.service.device_catalog(browser.owner)["devices"]) == 2


def test_adapter_is_opt_in_and_refuses_cross_authority_configuration(browser, tmp_path):
    with running(make_server(browser.service)) as url:
        response = httpx.post(url + "/v1/browser/session/info", json={}, trust_env=False)
        assert response.status_code == 404
    with pytest.raises(ValueError):
        make_server(ReferenceService(tmp_path / "other.sqlite"), browser=browser.sessions)
    with pytest.raises(ValueError):
        BrowserSessions(browser.service, "http://remote.example.org", browser.key)
    with pytest.raises(ValueError):
        BrowserSessions(browser.service, browser.origin, b"short")


def test_shared_cookie_cannot_change_another_tabs_research_or_pending_identity(browser):
    first, pending = prepared(browser)
    active = cookie(post(browser, "pairing/complete", cookie=pending))
    assert post(browser, "session/info", cookie=active).json() == first
    token = browser.service.enroll("another-workspace", "another-desktop")
    code = secrets.token_urlsafe(32)
    grant = browser.service.create_pairing(token, code)
    packet = Invitation(browser.origin, code=code, **grant).encoded()
    other = post(browser, "pairing/prepare", {"invitation": packet})
    other_pending = cookie(other)
    assert post(browser, "pairing/complete", cookie=other_pending, headers={
        "X-Paperfact-Workspace": first["workspace_id"],
        "X-Paperfact-Device": first["device_id"],
    }).status_code == 403
    assert len(browser.service.device_catalog(token)["devices"]) == 1
    second = post(browser, "pairing/complete", cookie=other_pending)
    other_active = cookie(second)
    # The original tab's expected IDs stay fixed while the browser cookie changes.
    assert post(browser, "pull", {"after": 0, "limit": 10}, other_active).status_code == 403
    assert post(browser, "session/info", cookie=other_active, headers={
        "X-Paperfact-Workspace": second.json()["workspace_id"],
        "X-Paperfact-Device": second.json()["device_id"],
    }).json() == second.json()


def test_proxy_throttle_is_retryable_and_never_echoes_response_or_credentials():
    seen = []
    def reply(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(429, text="synthetic private upstream details")
        return httpx.Response(200, stream=httpx.ByteStream(
            json.dumps({"workspace_id": "workspace", "device_id": "phone"}).encode()),
            headers={"content-type": "application/json"})
    with HttpTransport("https://sync.example.org") as transport:
        transport._client.close()
        transport._client = httpx.Client(transport=httpx.MockTransport(reply))
        with pytest.raises(ConnectionError, match="busy; retry later") as failure:
            transport.session_info("synthetic-private-device-key")
        assert "synthetic" not in str(failure.value)
        assert transport.session_info("synthetic-private-device-key")["device_id"] == "phone"
    assert len(seen) == 2
