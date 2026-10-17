"""Closed pilot configuration and an isolated, credential-minimal child runtime."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re


RUNTIME_VERSION = "0.162.1"
READONLY_PROFILE = "inspectorpro-readonly"
VERIFIED_MODELS = frozenset({"gpt-5.5", "gpt-6.1-sol"})
FLAG = "INSPECTORPRO_CODEX_READONLY_PILOT"
LIVE_FLAG = "INSPECTORPRO_CODEX_ALLOW_PAID_INFERENCE"
DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "shell_snapshot", "code_mode", "code_mode_host",
    "computer_use", "browser_use", "browser_use_external", "browser_use_full_cdp_access",
    "apps", "plugins", "remote_plugin", "multi_agent", "multi_agent_v2",
    "image_generation", "view_image", "artifact", "in_app_browser", "in_app_local_automation",
    "hooks", "memories", "goals", "tool_suggest",
    "skill_mcp_dependency_install", "skill_search", "daemon_auto_start",
    "request_permissions_tool", "unbounded_connection_retries",
)


class PilotError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 503):
        super().__init__(message)
        self.code, self.status_code = code, status_code


def enabled() -> bool:
    return os.environ.get(FLAG) == "1"


def live_allowed() -> bool:
    from .chatgpt_accounts import subscription_mode, SUBSCRIPTION_FLAG
    return os.getenv(SUBSCRIPTION_FLAG if subscription_mode() else LIVE_FLAG) == "1"


@dataclass(frozen=True)
class PilotSettings:
    binary: Path
    root: Path
    model: str
    timeout_seconds: int = 120
    max_calls: int = 8
    auth_mode: str = "api_key"

    @classmethod
    def from_environment(cls):
        binary = os.environ.get("INSPECTORPRO_CODEX_BINARY", "")
        root = os.environ.get("INSPECTORPRO_CODEX_PILOT_ROOT", "")
        model = os.environ.get("INSPECTORPRO_CODEX_MODEL", "")
        auth_mode = os.environ.get("INSPECTORPRO_CODEX_AUTH_MODE", "api_key")
        if auth_mode not in {"api_key", "chatgpt_plan"}:
            raise PilotError("codex_auth_mode_invalid", "Select an explicitly supported Sage sign-in method.")
        if not binary or not root or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,100}", model):
            raise PilotError("codex_configuration_required", "Configure the isolated Codex runtime, data folder, and model.")
        if model not in VERIFIED_MODELS:
            raise PilotError("codex_model_not_verified", "This model's native tool permissions have not been verified for the pilot.")
        if not Path(binary).is_absolute() or not Path(binary).is_file() or not Path(root).is_absolute():
            raise PilotError("codex_configuration_invalid", "Codex runtime paths must be explicit absolute paths.")
        data = Path(root).resolve()
        home = Path.home().resolve()
        if data in {home, Path(data.anchor), home / ".codex"}:
            raise PilotError("codex_configuration_invalid", "Use a dedicated pilot data directory, not a user profile.")
        editing = os.environ.get("INSPECTORPRO_CODEX_EDIT_PREVIEWS") == "1"
        return cls(Path(binary).resolve(), data, model,
                   timeout_seconds=240 if editing else 120, max_calls=24 if editing else 8, auth_mode=auth_mode)


def child_environment(root: Path, token: str, *, api_key: str | None = None, access_token: str | None = None) -> dict[str, str]:
    """Do not inherit proxy, model gateway, user Codex config, or other API keys."""
    for name in ("home", "temp", "appdata", "localappdata", "workspace"):
        (root / name).mkdir(parents=True, exist_ok=True)
    system = os.environ.get("SYSTEMROOT", os.environ.get("SystemRoot", "C:/Windows"))
    env = {"SYSTEMROOT": system, "WINDIR": system,
           "PATH": str(Path(system) / "System32"),
           "HOME": str(root), "USERPROFILE": str(root),
           "CODEX_HOME": str(root / "home"), "APPDATA": str(root / "appdata"),
           "LOCALAPPDATA": str(root / "localappdata"),
           "TEMP": str(root / "temp"), "TMP": str(root / "temp"),
           "INSPECTORPRO_CODEX_MCP_TOKEN": token}
    if api_key and access_token:
        raise PilotError("codex_auth_mode_conflict", "Only one inference credential may be passed to Codex.")
    if access_token:
        env["INSPECTORPRO_CHATGPT_ACCESS_TOKEN"] = access_token
    elif api_key:
        env["INSPECTORPRO_CODEX_API_KEY"] = api_key
    return env


def runtime_config(url: str, model: str, *, offline: bool = False, auth_mode: str = "api_key") -> dict:
    from .facility_tools import tool_specs
    return {
        "model": model, "model_provider": "inspectorpro",
        "model_providers": {"inspectorpro": {
            "name": "InspectorPro ChatGPT Plan" if auth_mode == "chatgpt_plan" else "InspectorPro API",
            "base_url": "http://127.0.0.1:9/v1" if offline else "https://api.openai.com/v1",
            "wire_api": "responses", "requires_openai_auth": False,
            "supports_websockets": False,
            **({} if offline else {"env_key": "INSPECTORPRO_CHATGPT_ACCESS_TOKEN" if auth_mode == "chatgpt_plan" else "INSPECTORPRO_CODEX_API_KEY"}),
            "request_max_retries": 0, "stream_max_retries": 0,
        }},
        "approval_policy": "never", "approvals_reviewer": "user",
        "default_permissions": READONLY_PROFILE,
        "permissions": {READONLY_PROFILE: {
            "filesystem": {":root": "deny", ":workspace_roots": {".": "read"}},
            "network": {"enabled": False},
        }},
        "web_search": "disabled", "project_doc_max_bytes": 0,
        "analytics": {"enabled": False}, "feedback": {"enabled": False},
        "features": {key: False for key in DISABLED_FEATURES},
        "mcp_servers": {"inspectorpro": {
            "url": url, "bearer_token_env_var": "INSPECTORPRO_CODEX_MCP_TOKEN",
            "required": True, "startup_timeout_sec": 15, "tool_timeout_sec": 90,
            "enabled_tools": [spec["name"] for spec in tool_specs()],
        }},
    }
