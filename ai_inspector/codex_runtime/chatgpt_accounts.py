"""Profile-bound SIWC accounts, encrypted by Windows DPAPI with serialized renewal."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

import httpx

from .chatgpt_protocol import AUTH, API, DIRECT_SCOPE, ProtocolError, provider_json, verify_identity, model_catalog
from .policy import PilotError

AUTH_MODE = "INSPECTORPRO_CODEX_AUTH_MODE"
SUBSCRIPTION_FLAG = "INSPECTORPRO_CODEX_ALLOW_SUBSCRIPTION_INFERENCE"
PROFILE_ID = "INSPECTORPRO_CODEX_AUTH_PROFILE_ID"
AUTH_ROOT = "INSPECTORPRO_CODEX_AUTH_ROOT"


def subscription_mode():
    return os.getenv(AUTH_MODE, "api_key") == "chatgpt_plan"


def account_target(profile_id):
    if not isinstance(profile_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", profile_id):
        raise ValueError("chatgpt_profile_invalid")
    return "InspectorPro/ChatGPT/" + profile_id


class AccountStore:
    def __init__(self, root, profile_id, *, protect=None, unprotect=None):
        from desktop.runtime.profile import local_path
        self.entropy = account_target(profile_id).encode()
        self.root = local_path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = local_path(self.root / "accounts.sqlite")
        self._protect, self._unprotect = protect, unprotect

    def seal(self, raw):
        if self._protect:
            return self._protect(raw)
        import win32crypt
        return win32crypt.CryptProtectData(raw, "InspectorPro ChatGPT account", self.entropy, None, None, 1)

    def unseal(self, raw):
        if self._unprotect:
            return self._unprotect(raw)
        import win32crypt
        return win32crypt.CryptUnprotectData(raw, self.entropy, None, None, 1)[1]

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=35)
        try:
            db.execute("PRAGMA secure_delete=ON")
            db.execute("CREATE TABLE IF NOT EXISTS account_state (id INTEGER PRIMARY KEY CHECK(id=1), sealed BLOB NOT NULL)")
            with db:
                yield db
        finally:
            db.close()

    def _read(self, db):
        row = db.execute("SELECT sealed FROM account_state WHERE id=1").fetchone()
        if not row:
            return {"version": 1, "hostId": "urn:uuid:" + str(uuid.uuid4()), "active": None, "accounts": {}}
        try:
            data = json.loads(self.unseal(row[0]))
            if data["version"] != 1 or not isinstance(data["accounts"], dict):
                raise ValueError()
            return data
        except Exception:
            raise PilotError("chatgpt_credentials_unavailable", "The saved ChatGPT account cannot be unlocked by this Windows user.") from None

    def read(self):
        with self.connection() as db:
            return self._read(db)

    def update(self, action):
        with self.connection() as db:
            # A transaction also serializes rotating refresh tokens across the
            # account window, backend and independently launched verification.
            db.execute("BEGIN IMMEDIATE")
            data = self._read(db)
            result = action(data)
            sealed = self.seal(json.dumps(data, allow_nan=False).encode())
            db.execute("INSERT OR REPLACE INTO account_state VALUES (1,?)", (sealed,))
            return result


def configured_store():
    root, profile_id = os.getenv(AUTH_ROOT, ""), os.getenv(PROFILE_ID, "")
    if not root or not Path(root).is_absolute() or not profile_id:
        raise PilotError("chatgpt_configuration_required", "Configure the desktop ChatGPT account before using subscription sign-in.")
    return AccountStore(root, profile_id)


def client():
    return httpx.Client(timeout=httpx.Timeout(20, connect=10), trust_env=False, follow_redirects=False,
                        headers={"User-Agent": "InspectorPro/0.1.0"})


def token_record(tokens, *, previous=None):
    previous = previous or {}
    scope = tokens.get("scope", previous.get("scope", ""))
    if DIRECT_SCOPE not in scope.split():
        raise ProtocolError("chatgpt_plan_permission_not_granted")
    if str(tokens.get("token_type", "")).lower() != "bearer":
        raise ProtocolError("unsupported_token_type")
    lifetime = tokens.get("expires_in")
    if type(lifetime) not in (int, float) or not math.isfinite(lifetime) or not 0 < lifetime <= 2592000:
        raise ProtocolError("invalid_token_lifetime")
    result = {"scope": scope, "expiresAt": time.time() + lifetime}
    for source, target in (("access_token", "accessToken"), ("refresh_token", "refreshToken"), ("id_token", "idToken")):
        value = tokens.get(source, previous.get(target))
        if not isinstance(value, str) or not 1 <= len(value) <= 65536 or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ProtocolError("invalid_token_response")
        result[target] = value
    return result


def accept_login(store, registration_id, registration, tokens, claims, models):
    record = token_record(tokens)
    if not models:
        raise ProtocolError("no_visible_models")
    def commit(data):
        prior = data["accounts"].get(registration_id)
        if prior and (prior.get("clientId") != registration["clientId"] or
                      (prior.get("subject") and prior["subject"] != claims["sub"])):
            raise ProtocolError("oauth_account_mismatch")
        account = {"clientId": registration["clientId"], "hostId": registration["hostId"],
                   "subject": claims["sub"], "label": str(claims.get("email") or claims.get("name") or "ChatGPT account")[:160],
                   "sessionId": str(uuid.uuid4()), "models": models, **record}
        data["accounts"][registration_id] = account
        data["active"] = registration_id
    store.update(commit)


def public_status(store):
    data = store.read()
    active = data["accounts"].get(data.get("active"), {})
    return {"authMode": "chatgpt_plan", "signedIn": bool(active.get("accessToken")),
            "activeAccount": data.get("active"), "apiFallback": False,
            "accounts": [{"id": key, "label": value.get("label", "ChatGPT account"),
                          "signedIn": bool(value.get("accessToken"))} for key, value in data["accounts"].items()],
            "models": active.get("models", [])}


@dataclass(frozen=True)
class SubscriptionCredential:
    access_token: str = field(repr=False)
    binding: str
    registration_id: str
    session_id: str
    store: AccountStore = field(repr=False, compare=False)

    def check(self):
        data = self.store.read()
        account = data["accounts"].get(self.registration_id, {})
        if (data.get("active") != self.registration_id or account.get("sessionId") != self.session_id
                or not account.get("accessToken")):
            raise PilotError("chatgpt_account_changed", "The ChatGPT account changed or signed out. Start a new Sage request.", 409)


def subscription_credential(model, *, store=None, client_factory=client):
    store = store or configured_store()
    def obtain(data):
        registration_id = data.get("active")
        account = data["accounts"].get(registration_id, {})
        if not account.get("refreshToken") or not account.get("accessToken"):
            return {"error": "chatgpt_sign_in_required"}
        if model not in {entry["slug"] for entry in account.get("models", [])}:
            return {"error": "chatgpt_model_unavailable"}
        if account["expiresAt"] <= time.time() + 300:
            try:
                with client_factory() as http:
                    tokens = provider_json(http.post(AUTH + "/api/accounts/oauth/token", data={
                        "grant_type": "refresh_token", "client_id": account["clientId"],
                        "refresh_token": account["refreshToken"], "resource": API}))
                    fresh = token_record(tokens, previous=account)
                    if "id_token" in tokens:
                        claims = verify_identity(tokens["id_token"], account["clientId"], None,
                                                 provider_json(http.get(AUTH + "/.well-known/jwks.json")))
                        if claims["sub"] != account["subject"]:
                            raise ProtocolError("oauth_account_mismatch")
                    account.update(fresh)
                    account["models"] = model_catalog(provider_json(http.get(API + "/models", headers={
                        "Authorization": "Bearer " + account["accessToken"]})))
            except Exception:
                # Fail closed without retrying a rotated credential or selecting
                # an API key. Reauthorization retains this registration's ID.
                for name in ("accessToken", "refreshToken", "idToken"):
                    account.pop(name, None)
                account["sessionId"] = str(uuid.uuid4())
                return {"error": "chatgpt_sign_in_required"}
        if model not in {entry["slug"] for entry in account.get("models", [])}:
            return {"error": "chatgpt_model_unavailable"}
        binding = hashlib.sha256((account["clientId"] + "\0" + account["subject"]).encode()).hexdigest()
        return {"token": account["accessToken"], "binding": binding,
                "registration": registration_id, "session": account["sessionId"]}
    result = store.update(obtain)
    if result.get("error"):
        raise PilotError(result["error"], "Open Sage > ChatGPT account to sign in or select an available model. No API fallback was used.", 401)
    return SubscriptionCredential(result["token"], result["binding"], result["registration"], result["session"], store)


def sign_out(store, *, client_factory=client):
    def clear(data):
        account = data["accounts"].get(data.get("active"), {})
        previous = (account.get("clientId"), account.get("refreshToken"))
        for name in ("accessToken", "refreshToken", "idToken"):
            account.pop(name, None)
        account["sessionId"] = str(uuid.uuid4())
        data["active"] = None
        return previous
    client_id, refresh_token = store.update(clear)
    if not refresh_token:
        return True
    for attempt in range(2):
        try:
            with client_factory() as http:
                discovery = provider_json(http.get(AUTH + "/.well-known/openid-configuration"))
                if discovery.get("revocation_endpoint") != AUTH + "/api/accounts/oauth/revoke":
                    return False
                response = http.post(discovery["revocation_endpoint"], data={
                    "token": refresh_token, "token_type_hint": "refresh_token", "client_id": client_id})
                if response.status_code == 200:
                    return True
                if response.status_code < 500:
                    return False
        except httpx.HTTPError:
            pass
        if attempt == 0:
            time.sleep(0.5)
    return False
