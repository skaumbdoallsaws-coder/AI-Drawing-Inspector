"""Public SIWC protocol helpers; no credentials are read, stored or logged here."""
import base64
import hashlib
import re
import secrets
from urllib.parse import urlencode

AUTH = "https://auth.openai.com"
API = "https://api.openai.com/v1"
DIRECT_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = "openid profile email offline_access resource.invoke " + DIRECT_SCOPE
SAFE_CODE = re.compile(r"[A-Za-z0-9_.-]{1,120}\Z")


class ProtocolError(Exception):
    def __init__(self, code, status=None, diagnostics=None):
        self.code, self.status, self.diagnostics = code, status, diagnostics or {}


def provider_json(response):
    if response.status_code != 200:
        code = "provider_request_rejected"
        try:
            error = response.json().get("error", {})
            candidate = error.get("code", "") if isinstance(error, dict) else error
            if isinstance(candidate, str) and SAFE_CODE.fullmatch(candidate):
                code = candidate
        except (ValueError, AttributeError):
            pass
        raise ProtocolError(code, response.status_code)
    return response.json()


def one_value(query, key, optional=False):
    values = query.get(key, [])
    if len(values) == 1 and values[0]:
        return values[0]
    if not values and optional:
        return None
    raise ProtocolError("invalid_callback")


def validate_callback(query, state, saved_client):
    if not secrets.compare_digest(one_value(query, "state"), state):
        raise ProtocolError("oauth_state_mismatch")
    error = one_value(query, "error", optional=True)
    if error:
        raise ProtocolError("oauth_access_denied" if error == "access_denied" else "oauth_rejected")
    client_id = one_value(query, "client_id", optional=True) or saved_client
    if not client_id or client_id == "dynamic_agent_client" or not SAFE_CODE.fullmatch(client_id):
        raise ProtocolError("registration_incomplete")
    if saved_client and client_id != saved_client:
        raise ProtocolError("oauth_client_mismatch")
    return one_value(query, "code"), client_id


def verify_identity(token, client_id, nonce, jwks):
    import jwt
    header = jwt.get_unverified_header(token)
    if header.get("alg") != "RS256":
        raise ProtocolError("unsupported_id_token_algorithm")
    keys = [key for key in jwks["keys"] if key.get("kid") == header.get("kid")]
    if len(keys) != 1:
        raise ProtocolError("id_token_key_not_found")
    key = jwt.PyJWK.from_dict(keys[0], algorithm="RS256").key
    claims = jwt.decode(token, key, algorithms=["RS256"], audience=client_id, issuer=AUTH,
                        options={"require": ["iss", "aud", "exp", "iat", "sub"] + (["nonce"] if nonce else [])})
    if nonce and not secrets.compare_digest(str(claims["nonce"]), nonce):
        raise ProtocolError("id_token_nonce_mismatch")
    return claims


def authorization_url(registration, origin, state, nonce, verifier):
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {"client_id": registration.get("clientId", "dynamic_agent_client"),
              "ext_agent_host_id": registration["hostId"], "response_type": "code",
              "redirect_uri": origin + "/auth/callback", "scope": SCOPES,
              "resource": API, "state": state, "nonce": nonce,
              "code_challenge_method": "S256", "code_challenge": challenge}
    if not registration.get("clientId"):
        params["agent_name_hint"] = "InspectorPro"
    elif registration.get("idToken"):
        params["id_token_hint"] = registration["idToken"]
    return AUTH + "/api/accounts/authorize?" + urlencode(params)


def model_catalog(payload):
    return [{"slug": item["slug"], "displayName": str(item.get("display_name") or item["slug"])[:120]}
            for item in payload.get("models", []) if isinstance(item, dict) and item.get("visibility") == "list"
            and isinstance(item.get("slug"), str) and SAFE_CODE.fullmatch(item["slug"])]
