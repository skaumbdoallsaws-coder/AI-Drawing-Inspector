"""Canonical serialization, hashing, and stable identities for knowledge packages."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic, ASCII-only JSON bytes.

    NaN and infinity are rejected because their JSON spellings are not portable
    and cannot be accepted as geometry or identity-bearing values.
    """

    text = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (text + "\n").encode("ascii")


def canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def stable_id(prefix: str, value: Any, *, digest_length: int = 20) -> str:
    if not isinstance(prefix, str) or not prefix or not prefix.isascii():
        raise ValueError("stable ID prefix must be non-empty ASCII")
    if digest_length < 8 or digest_length > 64:
        raise ValueError("digest_length must be between 8 and 64")
    return f"{prefix}-{canonical_json_sha256(value)[:digest_length]}"


def make_package_id(
    product_id: str,
    source_revision: str,
    configuration: str,
    adapter_version: str,
) -> str:
    return stable_id(
        "akp",
        {
            "adapterVersion": adapter_version,
            "configuration": configuration,
            "productId": product_id,
            "sourceRevision": source_revision,
        },
        digest_length=24,
    )


def package_revision(
    package_index: Mapping[str, Any],
    documents: Mapping[str, Mapping[str, Any]],
    asset_hashes: Mapping[str, str],
) -> str:
    """Hash a complete package without trusting its claimed revision.

    The index's computed revision and hash indexes are removed before hashing;
    they are represented by independently recomputed document and asset hashes.
    """

    clean_index = copy.deepcopy(dict(package_index))
    clean_index.pop("packageRevision", None)
    clean_index.pop("documentHashes", None)
    clean_index.pop("assetHashes", None)
    normalized_documents = {}
    for path, document in sorted(documents.items()):
        clean_document = copy.deepcopy(dict(document))
        # review_receipt.json binds events to the package it reviews. Exclude
        # that self-reference from the package hash while retaining every
        # review event and its content.
        if str(path) == "review_receipt.json":
            clean_document.pop("packageRevision", None)
        normalized_documents[str(path)] = clean_document
    document_hashes = {
        path: canonical_json_sha256(document)
        for path, document in normalized_documents.items()
    }
    normalized_asset_hashes = {
        str(path): str(asset_hash).lower()
        for path, asset_hash in sorted(asset_hashes.items())
    }
    return canonical_json_sha256(
        {
            "assetHashes": normalized_asset_hashes,
            "documents": document_hashes,
            "package": clean_index,
        }
    )


def refresh_package_revision(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    asset_hashes: Mapping[str, str] | None = None,
    package_updates: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return a deep-copied package with all computed hashes refreshed."""

    copied = {
        str(name): copy.deepcopy(dict(document))
        for name, document in documents.items()
    }
    package = copied["package.json"]
    if package_updates:
        package.update(copy.deepcopy(dict(package_updates)))
    if asset_hashes is not None:
        package["assetHashes"] = {
            str(path): str(digest).lower()
            for path, digest in sorted(asset_hashes.items())
        }
    structured = {
        name: document for name, document in copied.items() if name != "package.json"
    }
    if "review_receipt.json" in structured:
        structured["review_receipt.json"]["packageRevision"] = "0" * 64
    revision = package_revision(
        package,
        structured,
        package.get("assetHashes", {}),
    )
    if "review_receipt.json" in structured:
        structured["review_receipt.json"]["packageRevision"] = revision
    package["packageRevision"] = revision
    package["documentHashes"] = {
        name: canonical_json_sha256(document)
        for name, document in sorted(structured.items())
    }
    return copied
