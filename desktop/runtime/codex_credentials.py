"""API-only credentials in the current Windows user's Credential Manager vault."""
import ctypes
from ctypes import wintypes
import re


def credential_target(profile_id):
    if not isinstance(profile_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', profile_id):
        raise ValueError('desktop_codex_credential_target_invalid')
    return 'InspectorPro/Codex/' + profile_id


def validate_key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[!-~]{32,2048}', value):
        raise ValueError('desktop_codex_credential_invalid')
    return value


class Credential(ctypes.Structure):
    _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
                ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
                ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
                ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)), ('Persist', wintypes.DWORD),
                ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
                ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]


def _vault():
    try:
        vault = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
        vault.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.POINTER(ctypes.POINTER(Credential))]
        vault.CredReadW.restype = wintypes.BOOL
        vault.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
        vault.CredWriteW.restype = wintypes.BOOL
        vault.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        vault.CredDeleteW.restype = wintypes.BOOL
        vault.CredFree.argtypes = [ctypes.c_void_p]
        vault.CredFree.restype = None
        return vault
    except Exception:
        raise ValueError('desktop_codex_windows_vault_unavailable') from None


def read_api_key(profile_id):
    target = credential_target(profile_id)
    vault = _vault()
    pointer = ctypes.POINTER(Credential)()
    if not vault.CredReadW(target, 1, 0, ctypes.byref(pointer)):
        raise ValueError('desktop_codex_credential_unavailable')
    try:
        item = pointer.contents
        if item.Type != 1 or not 32 <= item.CredentialBlobSize <= 2048:
            raise ValueError()
        return validate_key(ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize).decode('ascii'))
    except Exception:
        raise ValueError('desktop_codex_credential_invalid') from None
    finally:
        if pointer.contents.CredentialBlob and pointer.contents.CredentialBlobSize:
            ctypes.memset(pointer.contents.CredentialBlob, 0, pointer.contents.CredentialBlobSize)
        vault.CredFree(pointer)


def store_api_key(profile_id, key):
    target, key = credential_target(profile_id), validate_key(key)
    vault = _vault()
    blob = (ctypes.c_ubyte * len(key))(*key.encode('ascii'))
    item = Credential(Type=1, TargetName=target, CredentialBlobSize=len(blob),
                      CredentialBlob=blob, Persist=2, UserName='api-key')
    try:
        if not vault.CredWriteW(ctypes.byref(item), 0):
            raise ValueError('desktop_codex_credential_write_failed')
    finally:
        ctypes.memset(blob, 0, len(blob))


def test_credential_target(profile_id):
    if not isinstance(profile_id, str) or not re.fullmatch(r'codex-test-[a-f0-9]{32}', profile_id):
        raise ValueError('desktop_codex_test_credential_target_invalid')
    return credential_target(profile_id)


def store_test_api_key(profile_id, key):
    """Refuse an existing target; never replace a normal or prior test credential."""
    target = test_credential_target(profile_id)
    validate_key(key)
    vault = _vault()
    pointer = ctypes.POINTER(Credential)()
    if vault.CredReadW(target, 1, 0, ctypes.byref(pointer)):
        if pointer and pointer.contents.CredentialBlob and pointer.contents.CredentialBlobSize:
            ctypes.memset(pointer.contents.CredentialBlob, 0, pointer.contents.CredentialBlobSize)
        vault.CredFree(pointer)
        raise ValueError('desktop_codex_test_credential_exists')
    if ctypes.get_last_error() != 1168:  # ERROR_NOT_FOUND is the only safe absence result.
        raise ValueError('desktop_codex_test_credential_probe_failed')
    store_api_key(profile_id, key)


def delete_test_api_key(profile_id):
    """Delete one exact random test target, never enumerate or accept vault paths."""
    target = test_credential_target(profile_id)
    if _vault().CredDeleteW(target, 1, 0):
        return True
    if ctypes.get_last_error() == 1168:
        return False  # Already absent; cleanup remains idempotent.
    raise ValueError('desktop_codex_test_credential_delete_failed')
