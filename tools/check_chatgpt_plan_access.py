"""Isolated, one-request SIWC probe. Never loads API keys or engineering files.

Implements the published OAuth protocol independently; does not use the SIWC
DevKit. Tokens remain in memory and only non-secret registration metadata persists.
"""

import argparse
import html
import json
import re
import secrets
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_inspector.codex_runtime.chatgpt_protocol import (
    AUTH, API, DIRECT_SCOPE, SCOPES, SAFE_CODE, ProtocolError as ProbeError,
    provider_json, one_value, validate_callback, verify_identity, authorization_url,
)
EXPECTED = "InspectorPro subscription check passed."


def select_model(payload, preferred):
    models = [item["slug"] for item in payload.get("models", [])
              if isinstance(item, dict) and item.get("visibility") == "list"
              and isinstance(item.get("slug"), str) and SAFE_CODE.fullmatch(item["slug"])]
    if not models:
        raise ProbeError("no_visible_models")
    return (preferred if preferred in models else models[0]), len(models)


def stream_check(client, access_token, model):
    body = {"model": model, "store": False, "stream": True,
            "input": [{"role": "user", "content": "Reply with exactly: " + EXPECTED}]}
    headers = {"Authorization": "Bearer " + access_token}
    started = time.monotonic()
    with client.stream("POST", API + "/responses", headers=headers, json=body) as response:
        if response.status_code != 200:
            response.read()
            provider_json(response)
        received = 0
        text_parts = {}
        finished_parts = set()
        delta_count = 0
        for line in response.iter_lines():
            received += len(line)
            if received > 2_000_000 or time.monotonic() - started > 90:
                raise ProbeError("inference_budget_exceeded")
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if raw == "[DONE]":
                continue
            event = json.loads(raw)
            kind = event.get("type")
            if kind in {"error", "response.failed", "response.incomplete"}:
                raise ProbeError("inference_" + kind.replace(".", "_"))
            if kind in {"response.output_text.delta", "response.output_text.done"}:
                key = (event.get("output_index", 0), event.get("content_index", 0))
                if any(type(index) is not int or index < 0 for index in key):
                    raise ProbeError("invalid_stream_text_index")
                text = event.get("delta" if kind.endswith(".delta") else "text")
                if not isinstance(text, str):
                    raise ProbeError("invalid_stream_text")
                if kind.endswith(".done"):
                    text_parts[key] = text
                    finished_parts.add(key)
                else:
                    delta_count += 1
                    if key not in finished_parts:
                        text_parts[key] = text_parts.get(key, "") + text
            if kind == "response.completed":
                result = event.get("response", {})
                if result.get("status") != "completed":
                    raise ProbeError("inference_not_completed")
                messages = [item for item in result.get("output", []) if item.get("type") == "message"]
                # Some streaming responses deliver text before a terminal event
                # with no message snapshot. Never count deltas alone as success.
                answer = ("".join(part.get("text", "") for item in messages
                                  for part in item.get("content", []) if part.get("type") == "output_text")
                          if messages else "".join(text_parts[key] for key in sorted(text_parts)))
                diagnostics = {"inferenceCompleted": True, "expectedReplyMatched": answer.strip() == EXPECTED,
                               "responseTextSource": "completed_message" if messages else "streamed_text",
                               "responseTextCharacters": len(answer), "textDeltaCount": delta_count}
                if answer.strip() != EXPECTED:
                    raise ProbeError("unexpected_probe_answer", diagnostics=diagnostics)
                return {"answer": EXPECTED, "elapsedSeconds": round(time.monotonic() - started, 3), **diagnostics}
    raise ProbeError("incomplete_stream")


class Probe:
    def __init__(self, root, preferred):
        self.root, self.preferred = root, preferred
        root.mkdir(parents=True, exist_ok=True)
        self.host_file = root / "registration.json"
        if self.host_file.exists():
            self.registration = json.loads(self.host_file.read_text(encoding="utf-8"))
        else:
            self.registration = {"hostId": "urn:uuid:" + str(uuid.uuid4())}
            self.save_registration()
        self.state, self.nonce, self.verifier = (secrets.token_urlsafe(32) for _ in range(3))
        self.start_key = secrets.token_urlsafe(32)
        self.done = threading.Event()
        self.lock = threading.Lock()
        self.started = self.consumed = False
        self.result = {"status": "waiting_for_user", "inferenceRequests": 0,
                       "apiKeyFallback": False, "engineeringDataAccess": False,
                       "commercialApproval": "not_determined", "tokensPersisted": False}

    def save_registration(self):
        self.host_file.write_text(json.dumps(self.registration, indent=2), encoding="utf-8")

    def report(self, **fields):
        with self.lock:
            self.result.update(fields)
            (self.root / "evidence.json").write_text(json.dumps(self.result, indent=2), encoding="utf-8")

    def auth_url(self):
        return authorization_url(self.registration, self.origin, self.state, self.nonce, self.verifier)

    def finish_callback(self, query):
        tokens = None
        try:
            with self.lock:
                if self.consumed or not self.started:
                    raise ProbeError("callback_not_pending")
                code, client_id = validate_callback(query, self.state, self.registration.get("clientId"))
                self.consumed = True
            self.registration["clientId"] = client_id
            self.save_registration()
            self.report(status="verifying_sign_in")
            with httpx.Client(timeout=30, trust_env=False, follow_redirects=False,
                              headers={"User-Agent": "InspectorPro-SubscriptionProbe/1.0"}) as client:
                tokens = provider_json(client.post(AUTH + "/api/accounts/oauth/token", data={
                    "grant_type": "authorization_code", "client_id": client_id, "code": code,
                    "code_verifier": self.verifier, "redirect_uri": self.origin + "/auth/callback",
                    "resource": API}))
                jwks = provider_json(client.get(AUTH + "/.well-known/jwks.json"))
                verify_identity(tokens["id_token"], client_id, self.nonce, jwks)
                if DIRECT_SCOPE not in tokens.get("scope", "").split():
                    raise ProbeError("chatgpt_plan_permission_not_granted")
                if str(tokens.get("token_type", "")).lower() != "bearer":
                    raise ProbeError("unsupported_token_type")
                self.report(status="checking_model_access", identityVerified=True, planPermissionGranted=True)
                models = provider_json(client.get(API + "/models", headers={
                    "Authorization": "Bearer " + tokens["access_token"]}))
                model, count = select_model(models, self.preferred)
                self.report(status="checking_inference", model=model, visibleModelCount=count, inferenceRequests=1)
                result = stream_check(client, tokens["access_token"], model)
                self.report(status="passed", **result)
        except ProbeError as exc:
            self.report(status="failed", errorCode=exc.code, httpStatus=exc.status, **exc.diagnostics)
        except Exception as exc:
            # Never log provider bodies, callback queries, tokens or exception text.
            self.report(status="failed", errorCode="probe_exception", errorType=type(exc).__name__)
        finally:
            if isinstance(tokens, dict):
                tokens.clear()
            self.done.set()


def handler_for(probe):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, body=b"", location=None):
            self.send_response(status)
            self.send_header("Cache-Control", "no-store")
            # Same-origin form POSTs need a non-null Origin for the CSRF check.
            # Callback URLs can contain codes and must never become referrers.
            policy = "no-referrer" if urlsplit(self.path).path == "/auth/callback" else "same-origin"
            self.send_header("Referrer-Policy", policy)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https://auth.openai.com; frame-ancestors 'none'")
            self.send_header("Content-Type", "text/html; charset=utf-8")
            if location:
                self.send_header("Location", location)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            return self.headers.get("Host") == urlsplit(probe.origin).netloc

        def local_error(self, status, code, message):
            probe.report(lastLocalErrorCode=code, lastLocalHttpStatus=status)
            body = ("<!doctype html><html><head><meta charset='utf-8'>"
                    "<title>InspectorPro Sign-in Check</title></head><body>"
                    "<h1>Sign-in has not started</h1><p>" + html.escape(message)
                    + "</p><p>This is a local test-page error, not an OpenAI access decision.</p>"
                    "<p><a href='/'>Reload the sign-in page</a></p></body></html>").encode()
            return self.send(status, body)

        def do_POST(self):
            if not self.valid_host() or self.path != "/start":
                return self.send(403)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length < 512:
                    return self.send(400)
                # Drain the bounded request before rejecting it; an early close
                # can reset the socket on Windows and hide the error response.
                payload = self.rfile.read(length)
                if self.headers.get("Origin") != probe.origin:
                    return self.local_error(403, "local_origin_rejected",
                                            "Reload the local sign-in page and use its sign-in button.")
                form = parse_qs(payload.decode())
                if not secrets.compare_digest(one_value(form, "key"), probe.start_key):
                    return self.local_error(403, "local_form_expired",
                                            "This tab belongs to an earlier test session. Reload it to continue.")
                with probe.lock:
                    if probe.started:
                        return self.send(409)
                    probe.started = True
                probe.report(status="waiting_for_oauth")
                return self.send(303, location=probe.auth_url())
            except (ValueError, ProbeError):
                return self.send(400)

        def do_GET(self):
            if not self.valid_host():
                return self.send(403)
            url = urlsplit(self.path)
            if url.path == "/auth/callback":
                query = parse_qs(url.query, keep_blank_values=True)
                if len(url.query) > 16384:
                    return self.send(400)
                probe.finish_callback(query)
                return self.send(303, location="/result")
            if url.path not in {"/", "/result"}:
                return self.send(404)
            status = probe.result["status"]
            message = {
                "waiting_for_user": "Test one short AI request using your ChatGPT plan. No API-key fallback and no layout access.",
                "waiting_for_oauth": "Complete sign-in in the OpenAI page.",
                "passed": "Subscription request completed. Sage's existing API setup is unchanged.",
                "failed": "The check did not complete. No API-key fallback was attempted.",
            }.get(status, "Checking subscription access.")
            if status == "failed" and probe.result.get("inferenceCompleted"):
                message = ("Sign-in and the subscription request completed, but the reply did not match "
                           "the test phrase. Sage's existing API setup is unchanged.")
            form = ("<form method='post' action='/start'><input type='hidden' name='key' value='"
                    + probe.start_key + "'><button>Continue with ChatGPT</button></form>") if not probe.started else ""
            error = html.escape(probe.result.get("errorCode", ""))
            body = ("<!doctype html><html><head><meta charset='utf-8'><title>InspectorPro Subscription Check</title>"
                    "<style>body{font:17px system-ui;max-width:680px;margin:80px auto;padding:24px;color:#202124}"
                    "h1{font-size:26px}button{padding:12px 20px;border:1px solid #111;border-radius:6px;"
                    "background:#111;color:white;font:inherit;cursor:pointer}small{color:#555}</style></head>"
                    "<body><h1>InspectorPro Subscription Check</h1><p>" + message + "</p>" + form
                    + "<p>" + error + "</p><small>This technical test does not establish commercial approval. "
                    "Plan limits apply. No credentials are saved by this probe.</small></body></html>").encode()
            self.send(200, body)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path(".runtime/siwc-subscription-probe-01"))
    parser.add_argument("--dependency-dir", type=Path, default=Path(".runtime/siwc-probe-deps"))
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--wait-seconds", type=int, default=600)
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    sys.path.insert(0, str(args.dependency_dir.resolve()))
    import jwt  # Fail before opening login if the verifier is unavailable.
    if not callable(getattr(jwt, "decode", None)):
        raise RuntimeError("token_verifier_unavailable")

    probe = Probe(args.output_root, args.model)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(probe))
    probe.origin = "http://127.0.0.1:" + str(server.server_port)
    probe.report(localUrl=probe.origin)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        if args.open_browser:
            webbrowser.open(probe.origin)
        if not probe.done.wait(args.wait_seconds):
            probe.report(status="timed_out", errorCode="user_sign_in_timeout")
        else:
            time.sleep(3)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return 0 if probe.result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
