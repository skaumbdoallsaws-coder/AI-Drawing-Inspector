import threading
from http.server import ThreadingHTTPServer

import httpx
import pytest
from playwright.sync_api import sync_playwright

from tools.check_chatgpt_plan_access import AUTH, Probe, handler_for


@pytest.fixture
def local_probe(tmp_path):
    probe = Probe(tmp_path, "gpt-5.5")
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(probe))
    probe.origin = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield probe
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_browser_form_posts_and_redirects_to_local_authorization_stub(local_probe, monkeypatch):
    destination = local_probe.origin + "/authorization-stub"
    monkeypatch.setattr(local_probe, "auth_url", lambda: destination)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            # Substitute only the redirect destination. The real form, browser
            # headers and local authorization guards run unchanged.
            page.goto(local_probe.origin)
            with page.expect_response(lambda response: response.url == destination):
                with page.expect_response(lambda response: response.url == local_probe.origin + "/start") as pending:
                    page.get_by_role("button", name="Continue with ChatGPT").click()
            response = pending.value
            origin = response.request.headers.get("origin")
            assert response.status == 303, f"Local form returned {response.status}; Origin={origin!r}"
            assert origin == local_probe.origin
            assert page.url == destination
            assert response.headers["referrer-policy"] == "same-origin"
            assert AUTH in response.headers["content-security-policy"]
            assert local_probe.result["status"] == "waiting_for_oauth"
            assert local_probe.result["inferenceRequests"] == 0
        finally:
            browser.close()


@pytest.mark.parametrize("origin", [None, "null", "https://untrusted.example"])
def test_start_rejects_untrusted_origins(local_probe, origin):
    headers = {} if origin is None else {"Origin": origin}
    with httpx.Client(trust_env=False) as client:
        response = client.post(local_probe.origin + "/start", headers=headers,
                               data={"key": local_probe.start_key})
    assert response.status_code == 403
    assert "local test-page error" in response.text
    assert local_probe.result["lastLocalErrorCode"] == "local_origin_rejected"
    assert local_probe.started is False
    assert local_probe.result["inferenceRequests"] == 0


def test_start_rejects_stale_form_and_allows_fresh_form(local_probe):
    with httpx.Client(trust_env=False, headers={"Origin": local_probe.origin}) as client:
        stale = client.post(local_probe.origin + "/start", data={"key": "old-session-key"})
        assert stale.status_code == 403
        assert "earlier test session" in stale.text
        assert local_probe.result["lastLocalErrorCode"] == "local_form_expired"
        assert local_probe.started is False
        fresh = client.post(local_probe.origin + "/start", data={"key": local_probe.start_key})
        assert fresh.status_code == 303
        assert fresh.headers["Location"].startswith(AUTH + "/api/accounts/authorize?")
        assert local_probe.started is True
        duplicate = client.post(local_probe.origin + "/start", data={"key": local_probe.start_key})
        assert duplicate.status_code == 409


def test_rejects_untrusted_host(local_probe):
    with httpx.Client(trust_env=False) as client:
        response = client.get(local_probe.origin, headers={"Host": "untrusted.example"})
    assert response.status_code == 403
    assert local_probe.started is False


def test_callback_never_passes_authorization_code_as_referrer(local_probe, monkeypatch):
    monkeypatch.setattr(local_probe, "finish_callback", lambda query: None)
    with httpx.Client(trust_env=False) as client:
        response = client.get(local_probe.origin + "/auth/callback?code=private-test-code")
    assert response.status_code == 303
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Location"] == "/result"
    assert "private-test-code" not in response.text
