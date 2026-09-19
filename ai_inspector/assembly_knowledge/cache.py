"""Atomic cache and dependency fingerprints for assembly enrichment."""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .manifest import canonical_json_bytes, canonical_json_sha256


_CACHE_KEY_RE = re.compile(r"^[0-9a-f]{64}$")


class EnrichmentCacheError(RuntimeError):
    pass


def occurrence_dependency_fingerprints(
    documents: Mapping[str, Mapping[str, Any]],
) -> Dict[str, str]:
    structure = documents.get("product_structure.json", {})
    interfaces = documents.get("interface_graph.json", {})
    geometry = documents.get("geometry_summary.json", {})
    by_occurrence: Dict[str, Dict[str, Any]] = {}
    for item in structure.get("occurrences", []):
        if not isinstance(item, Mapping) or not isinstance(
            item.get("occurrenceId"), str
        ):
            continue
        occurrence_id = item["occurrenceId"]
        by_occurrence[occurrence_id] = {
            "structure": copy.deepcopy(dict(item)),
            "interfaces": [],
            "geometry": None,
        }
    for item in interfaces.get("interfaces", []):
        if not isinstance(item, Mapping):
            continue
        for occurrence_id in item.get("occurrenceIds", []):
            if occurrence_id in by_occurrence:
                by_occurrence[occurrence_id]["interfaces"].append(
                    copy.deepcopy(dict(item))
                )
    for item in geometry.get("occurrences", []):
        if not isinstance(item, Mapping):
            continue
        occurrence_id = item.get("occurrenceId")
        if occurrence_id in by_occurrence:
            by_occurrence[occurrence_id]["geometry"] = copy.deepcopy(dict(item))
    return {
        occurrence_id: canonical_json_sha256(
            {
                "geometry": payload["geometry"],
                "interfaces": sorted(
                    payload["interfaces"],
                    key=lambda item: str(item.get("interfaceId") or ""),
                ),
                "structure": payload["structure"],
            }
        )
        for occurrence_id, payload in sorted(by_occurrence.items())
    }


def changed_occurrence_ids(
    previous: Mapping[str, str],
    current: Mapping[str, str],
) -> list[str]:
    return sorted(
        occurrence_id
        for occurrence_id in set(previous) | set(current)
        if previous.get(occurrence_id) != current.get(occurrence_id)
    )


class AssemblyKnowledgeEnrichmentCache:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _path(self, cache_key: str) -> Path:
        if not isinstance(cache_key, str) or _CACHE_KEY_RE.fullmatch(cache_key) is None:
            raise EnrichmentCacheError("Invalid enrichment cache key.")
        target = (self.root / cache_key[:2] / f"{cache_key}.json").resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise EnrichmentCacheError("Cache path escapes the cache root.") from exc
        return target

    def read(self, cache_key: str) -> Optional[Dict[str, Any]]:
        path = self._path(cache_key)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="ascii"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise EnrichmentCacheError("Enrichment cache entry is unreadable.") from exc
        if (
            not isinstance(value, dict)
            or value.get("schemaVersion") != 1
            or value.get("cacheKey") != cache_key
        ):
            raise EnrichmentCacheError("Enrichment cache entry is invalid.")
        return value

    def write(
        self,
        cache_key: str,
        *,
        request_fingerprint: str,
        response: Mapping[str, Any],
        usage: Mapping[str, Any],
        provider: str,
        model: str,
        occurrence_fingerprints: Mapping[str, str],
    ) -> Dict[str, Any]:
        path = self._path(cache_key)
        value = {
            "schemaVersion": 1,
            "cacheKey": cache_key,
            "requestFingerprint": request_fingerprint,
            "provider": provider,
            "model": model,
            "response": copy.deepcopy(dict(response)),
            "usage": copy.deepcopy(dict(usage)),
            "occurrenceFingerprints": {
                key: occurrence_fingerprints[key]
                for key in sorted(occurrence_fingerprints)
            },
        }
        self._write_atomic(path, canonical_json_bytes(value))
        return value

    @staticmethod
    def _write_atomic(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
