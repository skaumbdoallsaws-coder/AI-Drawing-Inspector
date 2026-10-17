"""Local account window for Sage. OAuth tokens stay in encrypted backend storage."""
import argparse
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import site
import sys
import threading
import time
import uuid
import webbrowser
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_inspector.codex_runtime.chatgpt_protocol import (
    AUTH, API, SAFE_CODE, ProtocolError, authorization_url, one_value,
    validate_callback, verify_identity, provider_json, model_catalog,
)
from ai_inspector.codex_runtime.chatgpt_accounts import (
    AccountStore, accept_login, public_status, sign_out, client,
)


class AccountWindow:
    def __init__(self, store):
        self.store, self.key = store, secrets.token_urlsafe(32)
        self.lock, self.pending = threading.Lock(), None
        self.generation = 0
        self.message = ""
        self.store.update(lambda data: None)

    def start(self, selected):
        with self.lock:
            if self.pending and time.monotonic() - self.pending["started"] < 600:
                raise ProtocolError("sign_in_already_pending")
            data = self.store.read()
            if selected != "new" and selected not in data["accounts"]:
                raise ProtocolError("account_not_found")
            identifier = str(uuid.uuid4()) if selected == "new" else selected
            registration = dict(data["accounts"].get(identifier, {}), hostId=data["hostId"])
            self.generation += 1
            self.pending = {"id": identifier, "registration": registration, "state": secrets.token_urlsafe(32),
                            "nonce": secrets.token_urlsafe(32), "verifier": secrets.token_urlsafe(32),
                            "started": time.monotonic(), "generation": self.generation}
            self.message = "Complete sign-in and plan-use permission on the OpenAI page."
            return authorization_url(registration, self.origin, self.pending["state"],
                                     self.pending["nonce"], self.pending["verifier"])

    def callback(self, query):
        with self.lock:
            pending = self.pending
            if not pending or time.monotonic() - pending["started"] > 600:
                raise ProtocolError("sign_in_expired")
            if not secrets.compare_digest(one_value(query, "state"), pending["state"]):
                raise ProtocolError("oauth_state_mismatch")
            self.pending = None
            code, client_id = validate_callback(query, pending["state"], pending["registration"].get("clientId"))
        registration = dict(pending["registration"], clientId=client_id)
        with client() as http:
            tokens = provider_json(http.post(AUTH + "/api/accounts/oauth/token", data={
                "grant_type": "authorization_code", "client_id": client_id, "code": code,
                "code_verifier": pending["verifier"], "redirect_uri": self.origin + "/auth/callback", "resource": API}))
            claims = verify_identity(tokens["id_token"], client_id, pending["nonce"],
                                     provider_json(http.get(AUTH + "/.well-known/jwks.json")))
            models = model_catalog(provider_json(http.get(API + "/models", headers={
                "Authorization": "Bearer " + tokens["access_token"]})))
            try:
                with self.lock:
                    if pending["generation"] != self.generation:
                        raise ProtocolError("sign_in_cancelled")
                    accept_login(self.store, pending["id"], registration, tokens, claims, models)
            finally:
                tokens.clear()
        self.message = "ChatGPT connected. Sage will use this account for its next subscription request."

    def page(self):
        status = public_status(self.store)
        options = "".join("<option value='" + html.escape(row["id"], quote=True) + "'"
                          + (" selected" if row["id"] == status["activeAccount"] else "") + ">"
                          + html.escape(row["label"]) + " (" + row["id"][:8] + ")</option>"
                          for row in status["accounts"])
        options += "<option value='new'>Use another ChatGPT account</option>"
        hidden = "<input type='hidden' name='key' value='" + self.key + "'>"
        return ("<!doctype html><html><head><meta charset='utf-8'><title>InspectorPro - ChatGPT Account</title>"
                "<style>body{font:16px system-ui;max-width:680px;margin:64px auto;padding:24px;color:#202124}"
                "h1{font-size:26px}button,select{font:inherit;padding:10px;margin:8px 8px 8px 0}"
                "button{background:#17191c;color:white;border:0;border-radius:4px}small{color:#555}</style></head>"
                "<body><h1>ChatGPT Account</h1><p>" + ("Connected" if status["signedIn"] else "Not connected")
                + "</p><p>" + html.escape(self.message) + "</p>"
                "<form method='post' action='/start'>" + hidden + "<label>Account <select name='account'>" + options
                + "</select></label><button>Continue with ChatGPT</button></form>"
                + ("<form method='post' action='/signout'>" + hidden + "<button>Sign out</button></form>" if status["signedIn"] else "")
                + "<p><a href='https://chatgpt.com/settings/usage' rel='noreferrer'>Plan usage and app permissions</a></p>"
                "<small>Credentials are encrypted for this Windows user. No API-key fallback. ChatGPT plan limits apply. "
                "This local development connection does not establish commercial-use approval.</small></body></html>").encode()


def handler_for(window):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, body=b"", location=None):
            self.send_response(status)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer" if urlsplit(self.path).path == "/auth/callback" else "same-origin")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https://auth.openai.com; frame-ancestors 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Type", "text/html; charset=utf-8")
            if location:
                self.send_header("Location", location)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            return self.headers.get("Host") == urlsplit(window.origin).netloc

        def do_GET(self):
            if not self.valid_host():
                return self.send(403)
            url = urlsplit(self.path)
            if url.path == "/auth/callback":
                try:
                    if len(url.query) > 16384:
                        raise ProtocolError("invalid_callback")
                    window.callback(parse_qs(url.query, keep_blank_values=True))
                except ProtocolError as exc:
                    window.message = "Sign-in did not complete: " + exc.code
                except Exception:
                    window.message = "Sign-in could not complete. No API fallback was attempted."
                return self.send(303, location="/")
            if url.path != "/":
                return self.send(404)
            return self.send(200, window.page())

        def do_POST(self):
            if not self.valid_host() or self.path not in {"/start", "/signout"}:
                return self.send(403)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length < 1024:
                    return self.send(400)
                data = self.rfile.read(length)
                if self.headers.get("Origin") != window.origin:
                    return self.send(403)
                form = parse_qs(data.decode())
                if not secrets.compare_digest(one_value(form, "key"), window.key):
                    window.message = "This tab expired. Reload it before signing in."
                    return self.send(403, window.page())
                if self.path == "/start":
                    return self.send(303, location=window.start(one_value(form, "account")))
                with window.lock:
                    window.pending = None
                    window.generation += 1
                    revoked = sign_out(window.store)
                window.message = ("Signed out." if revoked else "Signed out locally. Remote revocation was not confirmed; disconnect InspectorPro in ChatGPT Settings.")
                return self.send(303, location="/")
            except ProtocolError as exc:
                window.message = exc.code
                return self.send(400, window.page())
            except Exception:
                return self.send(400, b"Account operation failed. No API fallback was attempted.")
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--registration-file", type=Path)
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--wait-seconds", type=int, default=900)
    args = parser.parse_args()
    from desktop.runtime.application_profile import load_application_profile
    from desktop.runtime.codex_config import validate_package
    profile = load_application_profile(args.profile)
    config = profile.value["codexRuntime"]
    validate_package(config, Path(__file__).resolve().parents[1])
    sys.dont_write_bytecode = True
    site.addsitedir(config["dependencyRoot"])
    store = AccountStore(Path(profile.value["dataRoot"]) / "chatgpt-auth", profile.value["profileId"])
    if args.registration_file:
        registration = json.loads(args.registration_file.read_text(encoding="utf-8"))
        if (set(registration) != {"hostId", "clientId"} or not SAFE_CODE.fullmatch(registration["clientId"])
                or not registration["hostId"].startswith("urn:uuid:")):
            raise ValueError("registration_import_invalid")
        uuid.UUID(registration["hostId"][9:])
        def seed(data):
            if data["accounts"]:
                return
            data["hostId"] = registration["hostId"]
            identifier = str(uuid.uuid4())
            data["accounts"][identifier] = dict(registration, label="Previously verified account")
            data["active"] = identifier
        store.update(seed)
    window = AccountWindow(store)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(window))
    window.origin = f"http://127.0.0.1:{server.server_port}"
    worker = threading.Thread(target=server.serve_forever)
    worker.start()
    try:
        if args.open_browser:
            webbrowser.open(window.origin)
        threading.Event().wait(args.wait_seconds)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


if __name__ == "__main__":
    main()
