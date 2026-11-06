"""Offline credential tests, NOT proof of credentialed carrier rates.

Fernet substitutes for DPAPI in portable tests. The separate Windows test uses
only a synthetic key in disposable storage, never another application's auth.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import traceback
from types import SimpleNamespace
from urllib.parse import quote

from cryptography.fernet import Fernet
import pytest

from ai_inspector.packaging_shipping import credentials
from ai_inspector.packaging_shipping.credentials import EasyPostCredentialStore, ENVIRONMENT_KEY
from ai_inspector.packaging_shipping.service import PackagingError


KEY = "EZTK_SYNTHETIC_PACKAGING_SECRET_NOT_A_REAL_KEY_123456"
OTHER_KEY = "EZTK_SECOND_SYNTHETIC_PACKAGING_SECRET_NOT_REAL_98765"
ENV_KEY = "EZTK_SYNTHETIC_DEVELOPMENT_KEY_NOT_REAL_24680"
ALIAS = "Synthetic packaging account"


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    monkeypatch.delenv(ENVIRONMENT_KEY, raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("Credential tests must not contact providers or start processes")

    original_connect = socket.socket.connect

    def local_only(sock, address):
        if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
            forbidden()
        return original_connect(sock, address)

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", local_only)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)


@pytest.fixture
def codec():
    cipher = Fernet(Fernet.generate_key())

    def protect(raw, entropy):
        return cipher.encrypt(entropy + b"\x00" + raw)

    def unprotect(raw, entropy):
        plain = cipher.decrypt(raw)
        if not plain.startswith(entropy + b"\x00"):
            raise ValueError("Synthetic owner separation failure")
        return plain[len(entropy) + 1:]

    return protect, unprotect


@pytest.fixture
def store(tmp_path, codec):
    return EasyPostCredentialStore(tmp_path / "carrier-credentials", "tenant-a/profile-test/user-a",
                                   enabled=True, protect=codec[0], unprotect=codec[1])


def restarted(store, codec, *, owner="tenant-a/profile-test/user-a"):
    return EasyPostCredentialStore(store.root, owner, enabled=True, protect=codec[0], unprotect=codec[1])


def assert_redacted(value):
    text = str(value)
    for secret in (KEY, OTHER_KEY, ENV_KEY):
        assert secret not in text


def test_host_owner_encoding_keeps_colon_containing_identities_separate(tmp_path, codec):
    one = credentials.carrier_owner(SimpleNamespace(tenant_id="a:b", principal_id="c"))
    two = credentials.carrier_owner(SimpleNamespace(tenant_id="a", principal_id="b:c"))
    assert one != two
    assert json.loads(one) == ["a:b", "c"]
    first = EasyPostCredentialStore(tmp_path / "scoped", one, enabled=True, protect=codec[0], unprotect=codec[1])
    second = EasyPostCredentialStore(tmp_path / "scoped", two, enabled=True, protect=codec[0], unprotect=codec[1])
    first.replace(KEY, account_alias=ALIAS)
    assert first.path != second.path
    assert first.status()["configured"] is True
    assert second.status()["configured"] is False


def assert_no_plaintext_files(root):
    inspected = 0
    for path in root.rglob("*"):
        if path.is_file():
            inspected += 1
            raw = path.read_bytes()
            for value in (KEY, OTHER_KEY, ENV_KEY, ALIAS):
                assert value.encode() not in raw, path.name
    assert inspected > 0, "The encrypted store must actually be inspected"


def open_store(store):
    uri = "file:" + quote(str(store.path), safe="") if os.name == "nt" else store.path.as_uri()
    return sqlite3.connect(uri, uri=True)


def test_local_storage_is_opt_in_and_environment_fallback_remains(tmp_path, monkeypatch):
    root = tmp_path / "not-created"
    store = EasyPostCredentialStore(root, "user-a")
    assert store.status()["source"] == "none" and not root.exists()
    monkeypatch.setenv(ENVIRONMENT_KEY, ENV_KEY)
    status = store.status()
    assert status["configured"] and status["source"] == "environment"
    assert status["account_alias"] == "Development environment"
    assert status["validation"] == "not_validated" and not status["purchases_enabled"]
    assert store.resolve().api_key.get_secret_value() == ENV_KEY
    for operation in (lambda: store.replace(KEY), store.remove):
        with pytest.raises(PackagingError) as caught:
            operation()
        assert caught.value.code == "carrier_secure_store_disabled"
    assert not root.exists()
    assert_redacted(status)


def test_encrypted_restart_and_redacted_secret_handle(store, codec):
    status = store.replace(KEY, account_alias=ALIAS)
    assert status["configured"] and status["source"] == "secure_store"
    assert status["account_alias"] == ALIAS and status["validation"] == "not_validated"
    fresh = restarted(store, codec)
    handle = fresh.resolve()
    assert handle.api_key.get_secret_value() == KEY
    assert handle.source == "secure_store" and handle.account_alias == ALIAS
    handle.check()
    assert_redacted(repr(handle))
    assert_redacted(str(handle.api_key))
    assert_redacted(json.dumps({"key": handle.api_key}, default=str))
    assert_no_plaintext_files(store.root)
    with open_store(store) as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(carrier_credentials)")]
        assert columns == ["id", "sealed"]


def test_precedence_replacement_and_removal_never_silently_reactivate_environment(store, codec, monkeypatch):
    monkeypatch.setenv(ENVIRONMENT_KEY, ENV_KEY)
    environment_handle = store.resolve()
    assert environment_handle.source == "environment"
    store.replace(KEY, account_alias=ALIAS)
    local_handle = store.resolve()
    with pytest.raises(PackagingError, match="changed"):
        environment_handle.check()
    store.replace(OTHER_KEY, account_alias=ALIAS)
    assert restarted(store, codec).resolve().api_key.get_secret_value() == OTHER_KEY
    with pytest.raises(PackagingError, match="changed"):
        local_handle.check()
    removed = store.remove()
    assert not removed["configured"] and removed["source"] == "none"
    assert removed["environment_fallback_suppressed"]
    fresh = restarted(store, codec)
    assert fresh.status() == removed
    with pytest.raises(PackagingError) as caught:
        fresh.resolve()
    assert caught.value.code == "provider_not_configured"
    fresh.replace(KEY, account_alias=ALIAS)
    assert fresh.resolve().api_key.get_secret_value() == KEY
    assert_no_plaintext_files(store.root)


def test_removing_before_first_save_also_suppresses_environment(store, monkeypatch):
    monkeypatch.setenv(ENVIRONMENT_KEY, ENV_KEY)
    assert store.status()["source"] == "environment"
    assert not store.remove()["configured"]
    assert not store.remove()["configured"]


def test_same_key_replacement_revokes_old_handle(store):
    store.replace(KEY)
    old = store.resolve()
    store.replace(KEY)
    with pytest.raises(PackagingError) as caught:
        old.check()
    assert caught.value.code == "carrier_credentials_changed"


def test_owner_and_profile_namespaces_are_separate_and_other_auth_is_untouched(store, codec):
    store.root.mkdir()
    other_auth = store.root / "accounts.sqlite"
    other_auth.write_bytes(b"Synthetic unrelated Sage auth sentinel")
    store.replace(KEY, account_alias=ALIAS)
    other = restarted(store, codec, owner="tenant-a/profile-other/user-a")
    assert other.path != store.path and not other.status()["configured"]
    other.replace(OTHER_KEY, account_alias="Other synthetic account")
    store.remove()
    assert other.resolve().api_key.get_secret_value() == OTHER_KEY
    assert other_auth.read_bytes() == b"Synthetic unrelated Sage auth sentinel"
    assert_no_plaintext_files(store.root)


def test_copied_ciphertext_cannot_cross_owner_or_crypto_user(store, codec, monkeypatch):
    store.replace(KEY)
    other = restarted(store, codec, owner="tenant-b/profile-test/user-a")
    other.path.write_bytes(store.path.read_bytes())
    monkeypatch.setenv(ENVIRONMENT_KEY, ENV_KEY)
    assert other.status()["source"] == "unavailable"
    different_cipher = Fernet(Fernet.generate_key())
    wrong_user = EasyPostCredentialStore(store.root, "tenant-a/profile-test/user-a", enabled=True,
        protect=lambda raw, entropy: different_cipher.encrypt(raw),
        unprotect=lambda raw, entropy: different_cipher.decrypt(raw))
    assert wrong_user.status()["source"] == "unavailable"
    with pytest.raises(PackagingError) as caught:
        wrong_user.resolve()
    assert caught.value.code == "carrier_credentials_unavailable"


@pytest.mark.parametrize("damage", ["ciphertext", "schema", "empty_record", "decryption", "read_denied", "oversized"])
def test_read_failure_is_closed_sanitized_and_never_falls_back(store, monkeypatch, damage):
    store.replace(KEY)
    monkeypatch.setenv(ENVIRONMENT_KEY, ENV_KEY)
    if damage == "ciphertext":
        with open_store(store) as db:
            db.execute("UPDATE carrier_credentials SET sealed=?", (b"damaged-ciphertext",))
    elif damage in {"schema", "empty_record"}:
        with open_store(store) as db:
            db.execute("DROP TABLE carrier_credentials" if damage == "schema" else "DELETE FROM carrier_credentials")
    elif damage == "oversized":
        with store.path.open("ab") as stream:
            stream.write(b"x" * 1048576)
    else:
        def fail(*args, **kwargs):
            raise PermissionError(KEY)
        if damage == "decryption":
            monkeypatch.setattr(store, "_unprotect", fail)
        else:
            monkeypatch.setattr(credentials.sqlite3, "connect", fail)
    status = store.status()
    assert not status["configured"] and status["source"] == "unavailable"
    assert status["validation"] == "unavailable" and not status["quote_enabled"]
    with pytest.raises(PackagingError) as caught:
        store.resolve()
    assert caught.value.code == "carrier_credentials_unavailable"
    assert_redacted(status)
    assert_redacted("".join(traceback.format_exception(caught.value)))


@pytest.mark.parametrize("value", [None, "", " key", "key ", "line\nbreak", "a" * 4097, "non-ascii-\u00e9"])
def test_invalid_key_is_rejected_without_storage(store, value):
    with pytest.raises(PackagingError) as caught:
        store.replace(value)
    assert caught.value.code == "carrier_key_invalid"
    assert not store.root.exists()


@pytest.mark.parametrize("alias", ["", " trailing ", "line\nbreak", "a" * 81, KEY, "Account " + KEY, "EZAK_key_fragment"])
def test_alias_cannot_publish_credentials_or_control_text(store, alias):
    with pytest.raises(PackagingError) as caught:
        store.replace(KEY, account_alias=alias)
    assert caught.value.code == "carrier_alias_invalid"
    assert_redacted(str(caught.value))
    assert not store.root.exists()


def test_protection_failure_preserves_previous_record_without_plaintext(store, codec, monkeypatch):
    store.replace(KEY, account_alias=ALIAS)
    before = store.path.read_bytes()

    def fail(*args):
        raise RuntimeError(OTHER_KEY)

    monkeypatch.setattr(store, "_protect", fail)
    with pytest.raises(PackagingError) as caught:
        store.replace(OTHER_KEY)
    assert store.path.read_bytes() == before
    assert restarted(store, codec).resolve().api_key.get_secret_value() == KEY
    assert_redacted("".join(traceback.format_exception(caught.value)))
    assert_no_plaintext_files(store.root)


def test_plaintext_protector_is_refused(store, monkeypatch):
    monkeypatch.setattr(store, "_protect", lambda raw, entropy: raw)
    with pytest.raises(PackagingError):
        store.replace(KEY)
    assert not store.path.exists()


@pytest.mark.parametrize("outcome,code", [("valid", None), ("invalid_key", "carrier_credentials_invalid"),
                                         ("account_disabled", "carrier_account_disabled"),
                                         ("unavailable", "carrier_validation_unavailable")])
def test_explicit_validation_persists_distinct_account_states(store, codec, outcome, code):
    store.replace(KEY, account_alias=ALIAS)
    handle = store.resolve()

    async def validator(key):
        assert key == KEY
        return outcome

    status = asyncio.run(store.validate(validator))
    assert status["configured"] and status["validation"] == outcome
    assert status["account_disabled"] is (outcome == "account_disabled")
    assert restarted(store, codec).status() == status
    if code:
        with pytest.raises(PackagingError) as caught:
            handle.check()
        assert caught.value.code == code
        with pytest.raises(PackagingError) as caught:
            restarted(store, codec).resolve()
        assert caught.value.code == code
    else:
        handle.check()
    assert_redacted(status)
    assert_no_plaintext_files(store.root)


def test_revalidation_can_restore_a_disabled_account(store):
    store.replace(KEY)

    async def disabled(key):
        return "account_disabled"

    async def valid(key):
        return "valid"

    assert asyncio.run(store.validate(disabled))["account_disabled"]
    assert asyncio.run(store.validate(valid))["validation"] == "valid"
    assert store.resolve().api_key.get_secret_value() == KEY


@pytest.mark.parametrize("failure", ["exception", "provider_payload", "timeout"])
def test_validation_failures_never_publish_raw_provider_text(store, failure, caplog):
    store.replace(KEY)

    async def validator(key):
        if failure == "exception":
            raise RuntimeError(key)
        if failure == "provider_payload":
            return {"error": key}
        await asyncio.Future()

    status = asyncio.run(store.validate(validator, timeout_seconds=0.01))
    assert status["validation"] == "unavailable" and not status["account_disabled"]
    assert_redacted(status)
    assert_redacted(caplog.text)


def test_validation_cancellation_leaves_no_fabricated_outcome(store):
    store.replace(KEY)

    async def exercise():
        entered = asyncio.Event()

        async def validator(key):
            entered.set()
            await asyncio.Future()

        task = asyncio.create_task(store.validate(validator))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert store.status()["validation"] == "not_validated"


@pytest.mark.parametrize("change", ["replace", "remove"])
def test_validation_cannot_apply_to_replaced_or_removed_credentials(store, codec, change):
    store.replace(KEY)
    other = restarted(store, codec)

    async def validator(key):
        if change == "replace":
            other.replace(OTHER_KEY)
        else:
            other.remove()
        return "valid"

    with pytest.raises(PackagingError) as caught:
        asyncio.run(store.validate(validator))
    assert caught.value.code == "carrier_credentials_changed"
    assert other.status()["validation"] == ("not_validated" if change == "replace" else "not_configured")


def test_environment_validation_never_persists_a_key_and_tracks_changes(tmp_path, monkeypatch):
    store = EasyPostCredentialStore(tmp_path / "never-created", "user-a")
    monkeypatch.setenv(ENVIRONMENT_KEY, ENV_KEY)

    async def valid(key):
        assert key == ENV_KEY
        return "valid"

    assert asyncio.run(store.validate(valid))["validation"] == "valid"
    monkeypatch.setenv(ENVIRONMENT_KEY, OTHER_KEY)
    assert store.status()["validation"] == "not_validated"
    assert not store.root.exists()


def test_validation_rejects_environment_replacement(tmp_path, monkeypatch):
    store = EasyPostCredentialStore(tmp_path / "never-created", "user-a")
    monkeypatch.setenv(ENVIRONMENT_KEY, ENV_KEY)

    async def validator(key):
        monkeypatch.setenv(ENVIRONMENT_KEY, OTHER_KEY)
        return "account_disabled"

    with pytest.raises(PackagingError) as caught:
        asyncio.run(store.validate(validator))
    assert caught.value.code == "carrier_credentials_changed"
    assert store.status()["validation"] == "not_validated"


def test_separate_instances_replace_atomically(store, codec):
    def save(index):
        fresh = restarted(store, codec)
        fresh.replace(KEY if index % 2 else OTHER_KEY, account_alias=ALIAS)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(save, range(12)))
    assert restarted(store, codec).resolve().api_key.get_secret_value() in {KEY, OTHER_KEY}
    assert_no_plaintext_files(store.root)


def test_disappearing_sqlite_journal_is_not_a_read_failure(store, monkeypatch):
    store.replace(KEY)
    original = Path.lstat

    def disappearing(path, *args, **kwargs):
        if str(path) == str(store.path) + "-journal":
            raise FileNotFoundError("Synthetic concurrently deleted journal")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", disappearing)
    assert store.status()["configured"]
    store.replace(OTHER_KEY)
    assert store.resolve().api_key.get_secret_value() == OTHER_KEY


def test_deeply_nested_local_store_restart(tmp_path, codec):
    root = tmp_path / ("long-directory-" + "a" * 60) / ("nested-" + "b" * 60)
    store = EasyPostCredentialStore(root, "tenant-a/profile-test/user-a", enabled=True,
                                   protect=codec[0], unprotect=codec[1])
    assert len(str(store.path)) > 260
    store.replace(KEY, account_alias=ALIAS)
    assert restarted(store, codec).resolve().api_key.get_secret_value() == KEY
    assert_no_plaintext_files(store.root)
    store.remove()
    assert not restarted(store, codec).status()["configured"]


def test_provider_factory_is_explicit_fresh_and_quote_only(store):
    store.replace(KEY)
    first = store.make_provider()
    assert first.status()["configured"] and not first.status()["purchases_enabled"]
    assert_redacted(repr(first))
    assert_redacted(first.status())
    store.replace(OTHER_KEY)
    second = store.make_provider()
    assert first is not second and second._key == OTHER_KEY
    store.remove()
    with pytest.raises(PackagingError) as caught:
        store.make_provider()
    assert caught.value.code == "provider_not_configured"


def test_dpapi_uses_packaging_entropy_and_current_user_ui_forbidden_flags(tmp_path, monkeypatch):
    calls = []
    raw_by_blob = {}

    def protect(raw, description, entropy, reserved, prompt, flags):
        calls.append((description, entropy, reserved, prompt, flags))
        blob = b"test-protected-ciphertext"
        raw_by_blob[blob] = raw
        return blob

    def unprotect(blob, entropy, reserved, prompt, flags):
        assert entropy == calls[-1][1] and flags == 1
        return "description", raw_by_blob[blob]

    monkeypatch.setattr(credentials, "os", SimpleNamespace(name="nt", environ=os.environ))
    monkeypatch.setitem(sys.modules, "win32crypt", SimpleNamespace(CryptProtectData=protect, CryptUnprotectData=unprotect))
    store = EasyPostCredentialStore(tmp_path / "dpapi-contract", "owner-test", enabled=True)
    store.replace(KEY)
    assert store.resolve().api_key.get_secret_value() == KEY
    assert calls[0][0] == "InspectorPro packaging carrier credentials"
    assert calls[0][1].startswith(b"InspectorPro/Packaging/EasyPost/v1/")
    assert calls[0][2:] == (None, None, 1)  # UI forbidden; no LOCAL_MACHINE flag (4).


def test_unsupported_platform_never_writes_plaintext_or_falls_back(store, monkeypatch):
    monkeypatch.setattr(store, "_protect", None)
    monkeypatch.setattr(store, "_unprotect", None)
    monkeypatch.setattr(credentials, "os", SimpleNamespace(name="posix", environ=os.environ))
    monkeypatch.setenv(ENVIRONMENT_KEY, ENV_KEY)
    assert store.status()["source"] == "unavailable"
    with pytest.raises(PackagingError) as caught:
        store.replace(KEY)
    assert caught.value.code == "carrier_secure_store_unavailable"
    assert not store.path.exists()


def test_hardlinked_store_is_refused_without_touching_target(store, monkeypatch):
    store.root.mkdir()
    target = store.root / "unrelated-auth.sqlite"
    target.write_bytes(b"unrelated synthetic auth")
    try:
        os.link(target, store.path)
    except OSError:
        pytest.skip("Hard links unavailable in this test filesystem")
    monkeypatch.setenv(ENVIRONMENT_KEY, ENV_KEY)
    assert store.status()["source"] == "unavailable"
    with pytest.raises(PackagingError):
        store.replace(KEY)
    assert target.read_bytes() == b"unrelated synthetic auth"


@pytest.mark.parametrize("options", [{"enabled": 1}, {"owner_id": ""}, {"owner_id": "line\nbreak"},
                                     {"protect": lambda raw, entropy: raw}, {"root": "relative/store"}])
def test_invalid_host_configuration_is_rejected(tmp_path, options):
    args = {"root": tmp_path / "secure", "owner_id": "owner-test", **options}
    with pytest.raises(ValueError):
        EasyPostCredentialStore(**args)
    assert not (tmp_path / "secure").exists()


@pytest.mark.skipif(os.name != "nt", reason="Real DPAPI requires Windows; portable tests use Fernet")
def test_real_windows_dpapi_synthetic_restart(tmp_path):
    win32crypt = pytest.importorskip("win32crypt")
    try:
        probe = win32crypt.CryptProtectData(b"synthetic-capability-probe", "test", b"packaging-test", None, None, 1)
        assert win32crypt.CryptUnprotectData(probe, b"packaging-test", None, None, 1)[1] == b"synthetic-capability-probe"
    except Exception:
        pytest.skip("DPAPI is unavailable for this test logon; no credentialed-provider claim")
    root = tmp_path / "real-dpapi-synthetic"
    store = EasyPostCredentialStore(root, "synthetic-owner", enabled=True)
    store.replace(KEY, account_alias=ALIAS)
    assert EasyPostCredentialStore(root, "synthetic-owner", enabled=True).resolve().api_key.get_secret_value() == KEY
    assert_no_plaintext_files(store.root)
    store.remove()
    assert not EasyPostCredentialStore(root, "synthetic-owner", enabled=True).status()["configured"]
