"""Host-only catalog resolution for builder composition. No publication or Sage tools.

Providers are trusted host configuration, never recipe arguments. Tests use an
explicit temporary root and providers; the worker receives no catalog path.
"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import re

from .model_builder import include_contract as contract
from .model_builder.errors import ModelBuildError, json_bytes, parse_json, require
from .model_builder.imports import module

SUMMARY_BYTES = 48 * 1024


class IncludeCatalog:
    def __init__(self, project_root, *, catalog_provider=None, records_provider=None):
        self.root = Path(project_root).resolve()
        self.catalog_provider = catalog_provider or self._catalog
        self.records_provider = records_provider or self._records

    def _catalog(self):
        from ai_inspector.facility_layout.host import build_private_local_asset_catalog
        return build_private_local_asset_catalog(self.root)

    def _records(self):
        from ai_inspector.facility_layout.host import PRIVATE_ASSET_MANIFEST, _PRIVATE_LOCAL_ASSET_SPECS
        from ai_inspector.facility_layout.private_catalog import private_asset_spec
        from .model_builder.job_io import read_bytes
        target = self.root / PRIVATE_ASSET_MANIFEST
        records = []
        if target.exists():
            value = parse_json(read_bytes(target.parent, target.name, 32*1024*1024), 32*1024*1024)
            require(type(value) is dict and value.get("schemaVersion") == 1 and type(value.get("assets")) is list,
                    "$.include", "Invalid private catalog", "include_invalid")
            seen = set()
            for index, raw in enumerate(value["assets"]):
                private_asset_spec(raw, index=index, seen=seen)
                records.append(raw)
        # Legacy built-in records have artifacts but no evidence of authorship.
        # They may be inspected; composition must still pass the licence gate.
        for spec in _PRIVATE_LOCAL_ASSET_SPECS:
            records.append({"assetId": spec["asset_id"], "artifact": spec["artifact"],
                            "sourceToCanonical": list(spec["source_to_canonical"])})
        return records

    def _record(self, asset_id, path):
        try:
            rows = [v for v in self.catalog_provider() if v.get("assetId") == asset_id]
            records = [v for v in self.records_provider() if v.get("assetId") == asset_id]
        except ModelBuildError:
            raise
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise ModelBuildError("include_invalid", path, "Catalog metadata is unavailable: " + asset_id) from None
        require(len(rows) == len(records) == 1, path, "Catalog include is missing: " + asset_id, "include_missing")
        return deepcopy(rows[0]), deepcopy(records[0])

    def resolve(self, asset_id, *, revision=None, artifact_sha256=None, path="$.include", for_build=True):
        from ai_inspector.codex_runtime.component_inventory import catalog_visual_path
        from ai_inspector.codex_runtime.policy import PilotError
        from ai_inspector.facility_layout.private_catalog import validate_attribution
        require(isinstance(asset_id, str) and re.fullmatch(r"asset-[A-Za-z0-9._-]{1,122}", asset_id),
                path, "Invalid include asset id")
        row, raw = self._record(asset_id, path)
        current = row.get("assetDefinitionRevision")
        require(isinstance(current, str) and re.fullmatch("[0-9a-f]{64}", current), path,
                "Catalog include has no revision", "include_invalid")
        require(revision is None or revision == current, path + ".revision",
                "Include revision changed: " + asset_id, "include_mismatch")
        try:
            artifact = catalog_visual_path(str(raw["artifact"]), self.root)
            from .model_builder.job_io import read_bytes
            require(artifact.stat().st_size <= contract.INCLUDE_BYTES, path,
                    "Include exceeds 8 MiB: " + asset_id, "budget_exceeded")
            payload = read_bytes(artifact.parent, artifact.name, contract.INCLUDE_BYTES)
        except ModelBuildError:
            raise
        except OSError:
            raise ModelBuildError("include_missing", path, "Catalog artifact is missing: " + asset_id) from None
        except (KeyError, ValueError, PilotError):
            raise ModelBuildError("include_invalid", path, "Unsafe catalog artifact: " + asset_id) from None
        digest = sha256(payload).hexdigest()
        require(artifact_sha256 is None or artifact_sha256 == digest, path + ".artifactSha256",
                "Include artifact changed: " + asset_id, "include_mismatch")
        require((row, raw) == self._record(asset_id, path), path,
                "Catalog changed while resolving include: " + asset_id, "include_mismatch")
        supplied_credit = raw.get("attribution", row.get("attribution"))
        try:
            credit = validate_attribution(supplied_credit) if supplied_credit is not None else None
        except ValueError:
            raise ModelBuildError("include_licence", path, "Invalid catalog credit: " + asset_id) from None
        source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
        own = (source.get("kind") in ("authored-primitive", "basic-shape", "basic shape", "authored-recipe")
               or isinstance(raw.get("buildProvenance"), dict) and bool(raw["buildProvenance"])) and credit is None
        category = credit.get("licenseClass", "unknown") if credit is not None else "own" if own else "unknown"
        # Do not trust an "own" string in the GLB, a recipe, or an unrecognised catalog field.
        if for_build:
            require(category in ("own", "cc0", "cc-by", "cc-by-sa"), path,
                    "Unsupported include licence (" + category + "): " + asset_id, "include_licence")
            for field in ("license", "licenseUrl"):
                stated = module("licence").license_class(credit.get(field, "")) if credit else "unknown"
                require(stated in ("unknown", "other", category), path,
                        "Conflicting include licence evidence: " + asset_id, "include_licence")
        attribution = credit if category in ("cc-by", "cc-by-sa") else None
        frame = row.get("definition", {}).get("coordinateFrame", {}).get("sourceToCanonical")
        matrix = raw.get("sourceToCanonical", frame)
        require(frame is None or frame == matrix, path,
                "Catalog artifact frame disagrees with its bound definition", "include_mismatch")
        return {"manifest": {"id": "", "assetId": asset_id, "revision": current, "artifactSha256": digest,
                             "sourceToCanonical": matrix, "attribution": attribution,
                             "hasSurfaces": bool(raw.get("supportSurfaces") or row.get("supportSurfaces")
                                                 or row.get("definition", {}).get("supportSurfaces"))},
                "payload": payload, "catalogAttribution": credit,
                "size": deepcopy(row.get("dimensions") or row.get("definition", {}).get("dimensions")
                                 or raw.get("dimensions"))}

    def resolve_recipe(self, recipe):
        sources, total = {}, 0
        for entry, path, _ in contract.entries(recipe):
            item = self.resolve(entry["include"], revision=entry["revision"],
                                artifact_sha256=entry["artifactSha256"], path=path)
            item["manifest"]["id"] = entry["id"]
            total += len(item["payload"])
            require(total <= contract.TOTAL_INCLUDE_BYTES, path, "Includes exceed 16 MiB", "budget_exceeded")
            sources[entry["id"]] = item
        return contract.prepare_sources(recipe, sources)[0]


def inspect_model_include(request, *, catalog):
    """Read artifact identities and selectors, with bounded, revision-pinned paging."""
    require(type(request) is dict and set(request) <= {"assetId", "offset", "limit", "revision", "artifactSha256"}
            and "assetId" in request, "$", "Invalid include inspection request")
    offset, limit = request.get("offset", 0), request.get("limit", 100)
    require(type(offset) is int and 0 <= offset <= 4096, "$.offset", "Invalid page offset")
    require(type(limit) is int and 1 <= limit <= 200, "$.limit", "Page limit must be 1-200")
    for key in ("revision", "artifactSha256"):
        require(key not in request or isinstance(request[key], str) and re.fullmatch("[0-9a-f]{64}", request[key]),
                "$." + key, "Invalid identity pin")
    item = catalog.resolve(request["assetId"], revision=request.get("revision"),
                           artifact_sha256=request.get("artifactSha256"), for_build=False)
    info = contract.artifact_info(item["payload"])
    record = item["manifest"]
    result = {"assetId": record["assetId"], "representation": "artifact", "revision": record["revision"],
              "artifactSha256": record["artifactSha256"], "attribution": item["catalogAttribution"],
              "size": item["size"], "total": len(info["parts"]), "nextOffset": None, "parts": []}
    for part in info["parts"][offset:offset+limit]:
        result["parts"].append({key: part[key] for key in ("key", "name", "material", "triangles")})
        next_offset = offset + len(result["parts"])
        result["nextOffset"] = next_offset if next_offset < result["total"] else None
        if len(json_bytes(result)) > SUMMARY_BYTES:
            result["parts"].pop()
            result["nextOffset"] = offset + len(result["parts"])
            break
    require(len(json_bytes(result)) <= SUMMARY_BYTES and (offset >= result["total"] or bool(result["parts"])),
            "$", "Include summary exceeds 48 KiB", "budget_exceeded")
    return result
