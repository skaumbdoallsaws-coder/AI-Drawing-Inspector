"""Opt-in, current-Windows-user EasyPost credentials, independent of Sage auth.

Host wiring: construct with an explicit dedicated local root and a stable,
host-derived owner_id (include tenant/profile identity when applicable). Account
routes may call status/replace/remove/validate; a quote route calls make_provider
for EACH request, never caching the returned provider. No endpoints or network
requests are implemented here. A validator must be cancellation-cooperative and
map provider responses to the small ValidationOutcome protocol, never raw text.

Precedence: saved local record > development environment > unconfigured. A
removed local record suppresses environment fallback; unreadable local state
also never falls back. With local storage explicitly disabled, only the existing
environment configuration is used; no credential files are read or written.

DPAPI protects data at rest, not a compromised Windows logon or process. Python
cannot guarantee erasure of in-memory strings. Removal affects future resolution;
it cannot recall a provider request or key already handed to trusted host code,
nor securely erase historical filesystem backups of the encrypted record.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
from typing import Callable, Literal, Protocol
from urllib.parse import quote
import uuid

from pydantic import SecretStr

from .service import PackagingError, now

# The user records whether the configured key is a Test or Production key (checked in the EasyPost dashboard).
# EasyPost reports a mode only in responses, so the recorded mode is checked against every response.
ACCOUNT_MODES = ("test", "production")
MODE_ENVIRONMENT = "INSPECTORPRO_PACKAGING_EASYPOST_MODE"


def account_reference(source, generation):
    """Opaque, non-secret identity of the configured account; changes when the key is replaced or removed."""
    if not generation:
        return None
    return hashlib.sha256(f"InspectorPro/Packaging/account-ref/v1/{source}/{generation}".encode()).hexdigest()[:32]


ENVIRONMENT_KEY = "INSPECTORPRO_PACKAGING_EASYPOST_KEY"
ValidationOutcome = Literal["valid", "invalid_key", "account_disabled", "unavailable"]
_OUTCOMES = {"valid", "invalid_key", "account_disabled", "unavailable"}
_STATES = _OUTCOMES | {"not_validated"}
_MAX_SEALED_BYTES = 65536
_MAX_STORE_BYTES = 1048576
_ERRORS = {
    "carrier_secure_store_disabled": ("Secure local carrier storage has not been enabled.", 403),
    "carrier_secure_store_unavailable": ("Current-user Windows credential protection is unavailable.", 503),
    "carrier_credentials_unavailable": ("The saved carrier credentials could not be read or updated. No environment fallback was used.", 503),
    "carrier_key_invalid": ("Enter a nonempty carrier key without whitespace or control characters.", 422),
    "carrier_alias_invalid": ("Use a short account alias, not a credential or credential fragment.", 422),
    "provider_not_configured": ("Carrier credentials are not configured. Local packaging remains available.", 503),
    "carrier_credentials_invalid": ("The configured carrier key was rejected. Replace it or explicitly validate again.", 409),
    "carrier_account_disabled": ("The carrier account is disabled. Contact the provider or select another account.", 403),
    "carrier_validation_unavailable": ("Carrier access could not be verified. Explicitly validate again before requesting rates.", 503),
    "carrier_credentials_changed": ("Carrier credentials changed during validation. Validate the current selection again.", 409),
    "carrier_mode_invalid": ("Record the carrier key as a test or production key.", 422),
}


class CredentialValidator(Protocol):
    async def __call__(self, api_key: str) -> ValidationOutcome: ...


def carrier_owner(principal):
    """Encode the authenticated identity tuple without ambiguous separators."""
    return json.dumps([principal.tenant_id, principal.principal_id], ensure_ascii=True, separators=(",", ":"))


def _error(code):
    message, status = _ERRORS[code]
    return PackagingError(code, message, status)


def _key(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 4096
            or any(ord(char) < 33 or ord(char) > 126 for char in value)):
        raise _error("carrier_key_invalid")
    return value


def _alias(value, key):
    if (not isinstance(value, str) or not 1 <= len(value) <= 80 or value != value.strip()
            or any(ord(char) < 32 or ord(char) > 126 for char in value)
            or key in value or re.search(r"EZ[AT]K[A-Za-z0-9_-]*", value, re.IGNORECASE)):
        raise _error("carrier_alias_invalid")
    return value


@dataclass(frozen=True, slots=True)
class EasyPostCredential:
    """Host-only secret handle. SecretStr stays redacted in repr/str/JSON encoders."""

    api_key: SecretStr = field(repr=False)
    source: str
    account_alias: str
    _check: Callable[[], None] = field(repr=False, compare=False)
    # Opaque, non-secret identity; changes whenever the stored key is replaced or removed.
    account_ref: str | None = None
    # The mode the user recorded for this key, and the mode EasyPost last reported for it.
    declared_mode: str | None = None
    observed_mode: str | None = None

    def check(self):
        """Recheck removal, replacement, and any explicit validation denial."""
        self._check()


class EasyPostCredentialStore:
    def __init__(self, root: Path, owner_id: str, *, enabled=False, protect=None, unprotect=None):
        """protect/unprotect(bytes, entropy) are injection hooks for offline tests.

        Production uses DPAPI's current-user scope with UI forbidden, NEVER
        CRYPTPROTECT_LOCAL_MACHINE. Enabling this store is a host decision, not
        authority taken from a document, renderer-supplied owner, or model tool.
        """
        if (type(enabled) is not bool or not isinstance(owner_id, str) or not 1 <= len(owner_id) <= 512
                or any(ord(c) < 32 or ord(c) > 126 for c in owner_id)
                or (protect is None) != (unprotect is None)
                or (protect is not None and (not callable(protect) or not callable(unprotect)))):
            raise ValueError("Invalid carrier credential store configuration.")
        from desktop.runtime.profile import local_path
        try:
            self.root = local_path(root)
        except (ValueError, OSError, TypeError):
            raise ValueError("Use an explicit absolute local credential directory without links.") from None
        if os.name == "nt" and self.root.drive and not str(self.root).startswith("\\\\?\\"):
            self.root = Path("\\\\?\\" + str(self.root))
        self.enabled = enabled
        self._owner = hashlib.sha256(owner_id.encode()).hexdigest()
        self._entropy = ("InspectorPro/Packaging/EasyPost/v1/" + self._owner).encode()
        self.path = self.root / ("easypost-" + self._owner + ".sqlite")
        self._protect, self._unprotect = protect, unprotect
        self._environment_validation = None
        self._environment_mode = None  # (generation, mode fields): process-local, like environment validation
        self._lock = threading.RLock()

    def _codec(self):
        if self._protect is not None:
            return self._protect, self._unprotect
        try:
            if os.name != "nt":
                raise ImportError()
            import win32crypt
        except ImportError:
            raise _error("carrier_secure_store_unavailable") from None
        return (
            lambda raw, entropy: win32crypt.CryptProtectData(
                raw, "InspectorPro packaging carrier credentials", entropy, None, None, 1),
            lambda raw, entropy: win32crypt.CryptUnprotectData(raw, entropy, None, None, 1)[1],
        )

    def _paths(self):
        for directory in (self.root, *self.root.parents):
            try:
                metadata = directory.lstat()
            except FileNotFoundError:
                continue
            if (not stat.S_ISDIR(metadata.st_mode)
                    or getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
                raise ValueError("Unsafe credential storage directory")
        for path in (self.path, Path(str(self.path) + "-journal"), Path(str(self.path) + "-wal"),
                     Path(str(self.path) + "-shm")):
            # SQLite removes journals concurrently; inspect each entry once,
            # without following even dangling links or Windows reparse points.
            try:
                metadata = path.lstat()
            except FileNotFoundError:
                continue
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                    or getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
                raise ValueError("Unsafe credential storage path")
            if path == self.path and metadata.st_size > _MAX_STORE_BYTES:
                raise ValueError("Oversized credential storage")

    def _connect(self, *, readonly=False):
        location = self.path.as_uri()
        if os.name == "nt":
            location = "file:" + quote(str(self.path), safe="")
        uri = location + ("?mode=ro" if readonly else "?mode=rwc")
        return sqlite3.connect(uri, uri=True, timeout=2)

    def _seal(self, data):
        protect, _ = self._codec()
        try:
            raw = json.dumps(data, ensure_ascii=True, allow_nan=False).encode()
            sealed = protect(raw, self._entropy)
            if not isinstance(sealed, bytes) or not 1 <= len(sealed) <= _MAX_SEALED_BYTES or raw in sealed:
                raise ValueError("Invalid protected credential record")
            return sealed
        except Exception:
            raise _error("carrier_credentials_unavailable") from None

    def _read(self, db):
        row = db.execute("SELECT sealed FROM carrier_credentials WHERE id=1").fetchone()
        if row is None:
            # An existing store with no record is not permission to change accounts.
            raise ValueError("Missing credential record")
        sealed = row[0]
        if not isinstance(sealed, bytes) or not 1 <= len(sealed) <= _MAX_SEALED_BYTES:
            raise ValueError("Invalid protected credential record")
        _, unprotect = self._codec()
        raw = unprotect(sealed, self._entropy)
        if not isinstance(raw, bytes) or len(raw) > 16384:
            raise ValueError("Invalid credential record")
        data = json.loads(raw)
        expected = {"version", "owner", "generation", "key", "account_alias", "validation"}
        if (not isinstance(data, dict) or set(data) != expected or type(data["version"]) is not int
                or data["version"] != 1 or data["owner"] != self._owner
                or not isinstance(data["generation"], str) or not re.fullmatch(r"[a-f0-9]{32}", data["generation"])
                or type(data["validation"]) is not str or data["validation"] not in _STATES):
            raise ValueError("Invalid credential record")
        if data["key"] is None:
            if data["account_alias"] is not None or data["validation"] != "not_validated":
                raise ValueError("Invalid removal record")
        else:
            _alias(data["account_alias"], _key(data["key"]))
        return data

    @staticmethod
    def _ensure_modes(db):
        # Not sealed: a mode is not secret. A separate table, so an older build that reads only
        # carrier_credentials still opens this store unchanged.
        db.execute("CREATE TABLE IF NOT EXISTS carrier_account_modes (account_ref TEXT PRIMARY KEY, "
                   "declared TEXT NOT NULL, observed TEXT, observed_at TEXT)")

    @staticmethod
    def _mode_row(db, account_ref):
        if account_ref is None or not db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='carrier_account_modes'").fetchone():
            return None
        row = db.execute("SELECT declared, observed, observed_at FROM carrier_account_modes WHERE account_ref=?",
                         (account_ref,)).fetchone()
        if row is None:
            return None
        declared, observed, at = row
        if declared not in ACCOUNT_MODES or observed not in (None, *ACCOUNT_MODES) or not (at is None or isinstance(at, str)):
            raise ValueError("Invalid account mode record")
        return {"declared_mode": declared, "observed_mode": observed, "observed_at": at}

    @contextmanager
    def _write_connection(self):
        if not self.enabled:
            raise _error("carrier_secure_store_disabled")
        self._codec()
        db = None
        try:
            self._paths()
            self.root.mkdir(parents=True, exist_ok=True)
            self._paths()
            db = self._connect()
            db.execute("PRAGMA secure_delete=ON")
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS carrier_credentials (id INTEGER PRIMARY KEY CHECK(id=1), sealed BLOB NOT NULL)")
            yield db
            db.commit()
        except PackagingError:
            raise
        except Exception:
            raise _error("carrier_credentials_unavailable") from None
        finally:
            if db is not None:
                db.close()

    def _local(self):
        if not self.enabled:
            return None
        self._codec()
        db = None
        try:
            self._paths()
            if not self.path.exists():
                return None
            db = self._connect(readonly=True)
            data = self._read(db)
            if data["key"] is not None:  # Mode fields ride along for status/resolve only; they are never sealed.
                data = {**data, **(self._mode_row(db, account_reference("secure_store", data["generation"])) or {})}
            return data
        except Exception:
            raise _error("carrier_credentials_unavailable") from None
        finally:
            if db is not None:
                db.close()

    def _selection(self):
        data = self._local()
        if data is not None:
            return {**data, "source": "secure_store" if data["key"] is not None else "none",
                    "environment_fallback_suppressed": data["key"] is None}
        key = os.environ.get(ENVIRONMENT_KEY, "")
        if not key:
            return {"key": None, "source": "none", "account_alias": None, "validation": "not_validated",
                    "generation": None, "environment_fallback_suppressed": False}
        try:
            key = _key(key)
        except PackagingError:
            raise _error("carrier_credentials_unavailable") from None
        generation = hashlib.sha256(key.encode()).hexdigest()
        cached = self._environment_validation
        declared = os.environ.get(MODE_ENVIRONMENT, "")
        mode = {"declared_mode": declared if declared in ACCOUNT_MODES else None, "observed_mode": None, "observed_at": None}
        if self._environment_mode and self._environment_mode[0] == generation:
            mode = self._environment_mode[1]
        return {"key": key, "source": "environment", "account_alias": "Development environment",
                "validation": cached[1] if cached and cached[0] == generation else "not_validated",
                "generation": generation, "environment_fallback_suppressed": False, **mode}

    @staticmethod
    def _require_key(selection, *, validating=False):
        if selection["key"] is None:
            raise _error("provider_not_configured")
        if not validating:
            code = {"invalid_key": "carrier_credentials_invalid", "account_disabled": "carrier_account_disabled",
                    "unavailable": "carrier_validation_unavailable"}.get(selection["validation"])
            if code:
                raise _error(code)

    def status(self):
        """Public, allowlisted metadata only; configured does not mean validated."""
        with self._lock:
            try:
                selected = self._selection()
            except PackagingError as exc:
                return {"provider": "EasyPost", "configured": False, "source": "unavailable", "account_alias": None,
                        "validation": "unavailable", "account_disabled": False, "quote_enabled": False,
                        "secure_store_enabled": self.enabled, "purchases_enabled": False, "error_code": exc.code,
                        "declared_mode": None, "observed_mode": None, "observed_at": None, "mode_mismatch": False}
            configured = selected["key"] is not None
            state = selected["validation"] if configured else "not_configured"
            declared = selected.get("declared_mode") if configured else None
            observed = selected.get("observed_mode") if configured else None
            return {"provider": "EasyPost", "configured": configured, "source": selected["source"],
                    "account_alias": selected["account_alias"], "validation": state,
                    "account_ref": account_reference(selected["source"], selected["generation"]) if configured else None,
                    "account_disabled": state == "account_disabled",
                    "quote_enabled": configured and state in {"not_validated", "valid"},
                    "secure_store_enabled": self.enabled, "purchases_enabled": False,
                    "environment_fallback_suppressed": selected["environment_fallback_suppressed"],
                    # Recorded by the user; observed from EasyPost's last response. The alias is only a label.
                    "declared_mode": declared, "observed_mode": observed,
                    "observed_at": selected.get("observed_at") if configured else None,
                    "mode_mismatch": bool(declared and observed and declared != observed)}

    def replace(self, api_key: str, *, account_alias="EasyPost account", mode=None):
        """Explicit local save/replace; never contacts the provider or other auth. mode records the key as a
        test or production key; without it the mode stays unrecorded and quotes are refused until it is recorded."""
        if not self.enabled:
            raise _error("carrier_secure_store_disabled")
        key = _key(api_key)
        alias = _alias(account_alias, key)
        if mode is not None and mode not in ACCOUNT_MODES:
            raise _error("carrier_mode_invalid")
        return self._replace(key, alias, mode)

    def remove(self):
        """Persist a removal tombstone, including when an environment key exists."""
        if not self.enabled:
            raise _error("carrier_secure_store_disabled")
        return self._replace(None, None)

    def _replace(self, key, alias, mode=None):
        with self._lock:
            data = {"version": 1, "owner": self._owner, "generation": uuid.uuid4().hex, "key": key,
                    "account_alias": alias, "validation": "not_validated"}
            sealed = self._seal(data)
            with self._write_connection() as db:
                db.execute("INSERT OR REPLACE INTO carrier_credentials VALUES (1,?)", (sealed,))
                self._ensure_modes(db)
                db.execute("DELETE FROM carrier_account_modes")  # Only the current key's mode is kept.
                if key is not None and mode is not None:
                    db.execute("INSERT INTO carrier_account_modes VALUES (?,?,NULL,NULL)",
                               (account_reference("secure_store", data["generation"]), mode))
            return self.status()

    def declare_mode(self, mode):
        """Record the configured key as a test or production key, as the user checked it. Never contacts the provider.
        The mode EasyPost last reported is kept, so a recorded mode that contradicts it still blocks quotes."""
        if mode not in ACCOUNT_MODES:
            raise _error("carrier_mode_invalid")
        with self._lock:
            selected = self._selection()
            self._require_key(selected, validating=True)
            ref = account_reference(selected["source"], selected["generation"])
            if selected["source"] == "secure_store":
                with self._write_connection() as db:
                    if self._read(db)["generation"] != selected["generation"]:
                        raise _error("carrier_credentials_changed")
                    self._ensure_modes(db)
                    previous = self._mode_row(db, ref) or {}
                    db.execute("DELETE FROM carrier_account_modes WHERE account_ref<>?", (ref,))
                    db.execute("INSERT OR REPLACE INTO carrier_account_modes VALUES (?,?,?,?)",
                               (ref, mode, previous.get("observed_mode"), previous.get("observed_at")))
            else:
                self._environment_mode = (selected["generation"], {"declared_mode": mode,
                                          "observed_mode": selected.get("observed_mode"), "observed_at": selected.get("observed_at")})
            return self.status()

    def observe_mode(self, account_ref, observed):
        """Record the mode EasyPost reported for this key; ignored when the key changed since the request."""
        if observed not in ACCOUNT_MODES:
            return self.status()
        with self._lock:
            selected = self._selection()
            if (selected["key"] is None or not selected.get("declared_mode")
                    or account_reference(selected["source"], selected["generation"]) != account_ref):
                return self.status()
            at = now()
            if selected["source"] == "secure_store":
                with self._write_connection() as db:
                    if self._read(db)["generation"] != selected["generation"]:
                        return self.status()
                    self._ensure_modes(db)
                    db.execute("UPDATE carrier_account_modes SET observed=?, observed_at=? WHERE account_ref=?",
                               (observed, at, account_ref))
            else:
                self._environment_mode = (selected["generation"], {"declared_mode": selected["declared_mode"],
                                          "observed_mode": observed, "observed_at": at})
            return self.status()

    def resolve(self) -> EasyPostCredential:
        """Resolve afresh for host code; raw key access requires get_secret_value()."""
        with self._lock:
            selected = self._selection()
            self._require_key(selected)
            source, generation = selected["source"], selected["generation"]

            def check():
                with self._lock:
                    current = self._selection()
                    if (current["source"], current["generation"]) != (source, generation):
                        raise _error("carrier_credentials_changed")
                    self._require_key(current)

            return EasyPostCredential(SecretStr(selected["key"]), source, selected["account_alias"], check,
                                      account_reference(source, generation), selected.get("declared_mode"),
                                      selected.get("observed_mode"))

    async def validate(self, validator: CredentialValidator, *, timeout_seconds=15):
        """Explicit, bounded host-supplied account check; no implicit network client.

        Validation failure does not remove the configured key. Invalid key,
        provider-disabled account, and unavailable validation are distinct and
        block subsequent quote resolution until replacement or revalidation.
        Environment validation is process-local and never persists its key.
        """
        if (not callable(validator) or type(timeout_seconds) not in (int, float)
                or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 30):
            raise ValueError("Use a bounded asynchronous carrier validator.")
        with self._lock:
            selected = self._selection()
            self._require_key(selected, validating=True)
        try:
            outcome = await asyncio.wait_for(validator(selected["key"]), timeout_seconds)
            if type(outcome) is not str or outcome not in _OUTCOMES:
                outcome = "unavailable"
        except asyncio.CancelledError:
            raise
        except Exception:
            outcome = "unavailable"
        with self._lock:
            if selected["source"] == "secure_store":
                with self._write_connection() as db:
                    current = self._read(db)
                    if current["generation"] != selected["generation"]:
                        raise _error("carrier_credentials_changed")
                    current["validation"] = outcome
                    db.execute("UPDATE carrier_credentials SET sealed=? WHERE id=1", (self._seal(current),))
            else:
                current = self._selection()
                if (current["source"], current["generation"]) != (selected["source"], selected["generation"]):
                    raise _error("carrier_credentials_changed")
                self._environment_validation = (selected["generation"], outcome)
            return self.status()

    def make_provider(self, *, transport=None):
        """Create a fresh quote-only provider; account UI should use store.status()."""
        from .rating import EasyPostRating
        credential = self.resolve()
        credential.check()
        return EasyPostRating(key=credential.api_key.get_secret_value(), transport=transport,
                              account_ref=credential.account_ref, declared_mode=credential.declared_mode)
