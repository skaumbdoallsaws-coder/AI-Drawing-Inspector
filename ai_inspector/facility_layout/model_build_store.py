"""Build lifecycle in the shared import store, without an import/source record.

Only a reservation's own job tree is disposable. Publication moves a complete
validated folder atomically; no cancellation path can remove a published build.
"""
from copy import deepcopy
import os
import struct
import time
import uuid

from . import model_import_files as disk
from .errors import FacilityLayoutError
from ..industrial_assets.model_builder import drafts
from ..industrial_assets.model_builder.recipe import normalize_recipe
from ..industrial_assets.model_builder.imports import module

# Includes <=16 MiB, font <=2 MiB, two copies of GLB/result/pictures/metadata,
# and small JSON/atomic files. Reserve before copying inputs or starting work.
BUILD_RESERVATION = 160 * 1024 * 1024


def read(store, scope, draft_id, *, allow_expired=False):
    from .model_import_store import missing
    folder = store._folder(scope) / "drafts" / draft_id
    receipt = store._receipt(scope, draft_id)
    try:
        value = drafts.read_draft(folder, compact=receipt is not None)
        if value["scope"] != scope.key or value["draftId"] != draft_id:
            raise missing()
        if receipt is not None and receipt["assetId"] != value["assetId"]:
            raise ValueError("Build receipt differs from its draft")
        if not allow_expired and receipt is None and value["expires"] <= time.time():
            raise missing()
        return value
    except (ValueError, KeyError, TypeError, IndexError, AttributeError, OverflowError, RecursionError,
            struct.error, OSError, module("errors").ModelImportError):
        raise FacilityLayoutError("model_store_invalid", "The stored build draft failed its integrity check.",
                                  status_code=503) from None


def records(store, scope):
    """The published folder is the index; a crash needs no second record to recover."""
    from .model_import_store import DRAFT_ID
    for folder in (store._folder(scope) / "drafts").glob("md-*"):
        if not DRAFT_ID.fullmatch(folder.name):
            continue
        value = disk.read_json(folder / "draft.json", drafts.DRAFT_BYTES)
        if isinstance(value, dict) and value.get("kind") == "build":
            yield folder, value


def trim(store, scope, *, now=None, protect=()):
    now = time.time() if now is None else now
    unregistered = []
    protected = 0
    for folder, _ in records(store, scope):
        # A registration lease protects both complete and compacted drafts.
        if folder.name in protect or (store._folder(scope) / "locks" / (folder.name+".json")).exists():
            protected += store._receipt(scope, folder.name) is None
            continue
        value = read(store, scope, folder.name, allow_expired=True)
        if store._receipt(scope, folder.name) is not None:
            store._compact(scope, folder.name)
        else:
            unregistered.append((value["created"], folder.name, value["expires"], folder))
    unregistered.sort()
    # Leased and newly published drafts count toward the site's limit as well.
    excess = max(0, len(unregistered) + protected - 20)
    for index, (_, _, expires, folder) in enumerate(unregistered):
        if index < excess or expires <= now:
            disk.remove(folder)
            disk.remove(store._folder(scope) / "views" / folder.name)


def list_drafts(store, scope):
    store._authorize(scope)
    store.reconcile()
    with disk.coordinator(store.root):
        result = []
        for folder, _ in records(store, scope):
            value = read(store, scope, folder.name, allow_expired=True)
            if store._receipt(scope, folder.name) is None and value["expires"] > time.time():
                result.append({"draftId": value["draftId"], "name": value["recipe"]["name"],
                               "created": value["created"], "expires": value["expires"]})
        return sorted(result, key=lambda v: (v["created"], v["draftId"]), reverse=True)


def recent_registrations(store, scope, *, since):
    from .model_import_store import DRAFT_ID
    store._authorize(scope)
    with disk.coordinator(store.root):
        rows = []
        for path in (store._folder(scope) / "registrations").glob("md-*.json"):
            if not DRAFT_ID.fullmatch(path.stem):
                continue
            receipt = store._receipt(scope, path.stem)
            if receipt is None or receipt["at"] < since or not receipt["assetId"].startswith("asset-built-"):
                continue
            draft = read(store, scope, path.stem, allow_expired=True)
            rows.append({"draftId": path.stem, "assetId": receipt["assetId"],
                         "revision": receipt["revision"], "name": draft["recipe"]["name"],
                         "registered": receipt["at"]})
        return sorted(rows, key=lambda row: (row["registered"], row["draftId"]), reverse=True)[:20]


def summary(store, scope, draft_id):
    from ..industrial_assets.model_builder.errors import json_bytes, parse_json
    from ..industrial_assets.model_builder.job_io import read_bytes
    from ..industrial_assets.model_builder.protocol import RESULT_BYTES
    store._authorize(scope)
    with disk.coordinator(store.root):
        draft = store._draft(scope, draft_id)
        if draft.get("kind") != "build":
            raise FacilityLayoutError("model_recipe_missing", "That built draft is unavailable.", status_code=404)
        folder = store._folder(scope) / "drafts" / draft_id
        result = parse_json(read_bytes(folder, "result.json", RESULT_BYTES), RESULT_BYTES)
        drafts.result_matches(draft, result)
        parts = result["parts"]
        value = {"kind": "build", "draftId": draft_id, "name": draft["recipe"]["name"],
                 "dimensions": draft["catalogDimensions"], "triangles": draft["triangles"],
                 "shift": result["shift"], "partsTotal": len(parts),
                 "parts": [{"id": part["key"], "name": part["name"], "triangles": part["triangles"]}
                           for part in parts[:64]],
                 "materials": [{"name": material["name"], "color": material["baseColor"],
                                **({"defaultFinish": material["defaultFinish"]} if material.get("defaultFinish") else {})}
                               for material in result["materials"]],
                 "surfaces": draft["surfaces"], "footprint": draft["footprint"],
                 "lints": result["lints"], "warnings": result["warnings"],
                 "attribution": draft["attribution"]}
        value["nextPartsOffset"] = len(value["parts"]) if len(value["parts"]) < len(parts) else None
        while len(json_bytes(value)) > 48*1024:
            for field in ("parts", "lints", "warnings", "surfaces", "footprint", "materials"):
                if isinstance(value[field], list) and value[field]:
                    value[field].pop()
                    break
            else:
                raise FacilityLayoutError("model_summary_invalid", "The built draft summary is too large.",
                                          status_code=503)
            value["nextPartsOffset"] = len(value["parts"]) if len(value["parts"]) < len(parts) else None
        return value


def build(store, scope, recipe, cancel=None, *, categories, appearance_ids, include_catalog=None,
          derived_from=None, recheck=None):
    from .model_import_store import build_failure, quota, translate, ModelImportError
    from ..industrial_assets.model_builder_runner import prepare_build_draft
    store._authorize(scope, True)
    normalized = normalize_recipe(recipe, allowed_categories=categories, allowed_appearance_ids=appearance_ids)
    # Validate host metadata before reserving or starting a worker.
    from ..industrial_assets.model_builder.identity import build_provenance
    try:
        build_provenance(normalized, 1, derived_from)
    except ValueError:
        raise FacilityLayoutError("schema_invalid", "Invalid builder provenance.",
                                  details={"path": "$", "problem": "Check sizeBasis sources and derivedFrom."}) from None
    if cancel is not None and cancel.is_set():
        raise translate(ModelImportError("model_cancelled"))
    store.reconcile()
    lease = None
    try:
        with disk.coordinator(store.root):
            trim(store, scope)
            lease = store._claim(scope, "mbj-"+uuid.uuid4().hex[:24], BUILD_RESERVATION, cancel, kind="build")
        lease.check()
        destination = lease.job / "built"
        worker = store.build_worker or prepare_build_draft
        worker(normalized, destination, lease.cancel, dependency_root=store._dependencies(),
               categories=categories, appearance_ids=appearance_ids, include_catalog=include_catalog,
               scope=scope.key, created=time.time(), derived_from=derived_from)
        value = drafts.read_draft(destination)
        if value["recipe"] != normalized or value["scope"] != scope.key or value["buildProvenance"].get("derivedFrom") != derived_from:
            raise ValueError("Build draft differs from its requested inputs")
        if disk.size(lease.job) > lease.data["reserved"]:
            raise quota()
        lease.check()
        with disk.coordinator(store.root):
            store._authorize(scope, True)
            if recheck is not None:
                recheck()
            lease.check()
            target = store._folder(scope) / "drafts" / value["draftId"]
            disk.mkdir(target.parent)
            if target.exists():
                existing = read(store, scope, value["draftId"], allow_expired=True)
                # Times and draft-only references do not change content identity.
                if existing["identitySha256"] != value["identitySha256"] or existing["assetId"] != value["assetId"]:
                    raise FacilityLayoutError("asset_identity_conflict", "A different build has the same draft identity.", status_code=409)
                value = existing
            else:
                os.replace(destination, target)
            # Publication is the commit point. Never remove target on any error.
            store._resize(lease, store._owned_size(lease.data) + 1024*1024)
            trim(store, scope, protect=(value["draftId"],))
            result = drafts.public_result(target, value)
        lease.check()
        return deepcopy(result)
    except Exception as error:
        raise build_failure(error) from None
    finally:
        if lease is not None:
            lease.release()
            if lease.cancel.is_set():
                raise translate(ModelImportError("model_cancelled"))
