"""Synthetic manifest checks: no browser or saved evidence required."""

from tools.facility_three_manifest import P0_VENDOR_PATHS, p0_manifest_entries_sha256


def _entry(path, byte_count=100, sha256="a" * 64):
    return f"| `{path}` | {byte_count} | `{sha256}` |\n"


def _manifest():
    return (
        "# Vendored Three.js Modules\n\n"
        "| File | Bytes | SHA-256 |\n"
        "| --- | ---: | --- |\n"
        + "".join(_entry(path) for path in P0_VENDOR_PATHS)
    )


def test_adding_unused_vendor_entry_keeps_p0_hash():
    manifest = _manifest()
    assert p0_manifest_entries_sha256(manifest) == p0_manifest_entries_sha256(
        manifest + _entry("examples/jsm/environments/RoomEnvironment.js")
    )


def test_changing_unused_vendor_entry_keeps_p0_hash():
    unused = "examples/jsm/postprocessing/UnrealBloomPass.js"
    before = _manifest() + _entry(unused)
    after = _manifest() + _entry(unused, byte_count=200, sha256="b" * 64)
    assert p0_manifest_entries_sha256(before) == p0_manifest_entries_sha256(after)


def test_changing_any_used_vendor_checksum_changes_p0_hash():
    manifest = _manifest()
    expected = p0_manifest_entries_sha256(manifest)
    for path in P0_VENDOR_PATHS:
        changed = manifest.replace(_entry(path), _entry(path, sha256="b" * 64))
        assert p0_manifest_entries_sha256(changed) != expected, path


def test_changing_any_used_vendor_byte_count_changes_p0_hash():
    manifest = _manifest()
    expected = p0_manifest_entries_sha256(manifest)
    for path in P0_VENDOR_PATHS:
        changed = manifest.replace(_entry(path), _entry(path, byte_count=101))
        assert p0_manifest_entries_sha256(changed) != expected, path


def test_missing_used_vendor_entry_raises():
    for path in P0_VENDOR_PATHS:
        manifest = _manifest().replace(_entry(path), "")
        try:
            p0_manifest_entries_sha256(manifest)
        except ValueError as error:
            assert "Missing or malformed" in str(error)
            assert path in str(error)
        else:
            raise AssertionError(f"Missing entry was accepted: {path}")


def test_malformed_used_vendor_entry_raises():
    path = P0_VENDOR_PATHS[0]
    manifest = _manifest().replace(_entry(path), _entry(path, sha256="invalid"))
    try:
        p0_manifest_entries_sha256(manifest)
    except ValueError as error:
        assert "Missing or malformed" in str(error)
        assert path in str(error)
    else:
        raise AssertionError("Malformed entry was accepted")


def test_duplicate_used_vendor_entry_raises():
    path = P0_VENDOR_PATHS[0]
    manifest = _manifest() + _entry(path, sha256="b" * 64)
    try:
        p0_manifest_entries_sha256(manifest)
    except ValueError as error:
        assert "Duplicate P0 entry" in str(error)
        assert path in str(error)
    else:
        raise AssertionError("Duplicate entry was accepted")


def test_manifest_order_line_endings_and_prose_do_not_change_p0_hash():
    reordered = "".join(_entry(path) for path in reversed(P0_VENDOR_PATHS))
    reordered = "Updated provenance text\r\n" + reordered.replace("\n", "\r\n")
    assert p0_manifest_entries_sha256(_manifest()) == p0_manifest_entries_sha256(
        reordered
    )
