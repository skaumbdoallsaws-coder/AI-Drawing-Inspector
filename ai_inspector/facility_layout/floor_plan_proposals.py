"""Floor-plan import, FP2: a drawing converted for review (docs/facility-floor-plan-import-plan.md, sections 4 and 8).

`stage_conversion` runs the converter (floor_plan_conversion) on the saved layout's underlay and its stored drawing:

- stage "candidates": what would be converted, and why the rest is not. Nothing is stored or proposed.
- stage "proposal": the same, then the conversion's record is stored (floor_plan_store.store_conversion: the drawing,
  alignment, layer roles and settings, each candidate with the drawing entities it came from and the native id it
  gets, and the digest of the operations) and the operations are proposed with that record as their origin
  (operation_proposals.create). Approving and applying go through the existing proposal routes. A record written
  for a proposal that could not be made is removed again.

The origin makes the proposal review-only: it is never direct-applicable, and the approval refuses direct consent for
it. It is bound into the proposal's id and binding, and every time the proposal is prepared again (opened, approved,
applied) `verify_origin` checks that the drawing, the conversion record, the underlay's alignment and layer roles and
the converter are still the ones it was made from, so a stale or altered conversion is converted again, never applied.
"""
from __future__ import annotations

import json
import threading
from collections import OrderedDict

from .errors import FacilityConflictError, FacilityValidationError
from .authorization import require_facility_action
from .floor_plan_conversion import (CONVERTER_VERSION, MAX_OPERATIONS, MAX_PACKAGE_BYTES, ConversionSettingsError,
                                    ConversionTooLargeError, _digest, conversion_id, convert, normalize_settings,
                                    origin_for)
from .floor_plan_references import DIGEST, REFERENCE_ID, layout_references
from .floor_plan_store import (CONVERSION_ID, IMPORT_ID, STORE_FOLDER, artifact_file, delete_conversion,
                               load_conversion, store_conversion, stored_import)

STAGES = ("candidates", "proposal")
# A conversion is a server-built package: up to the kernel's transaction limit, like a planner's package.
PACKAGE_LIMITS = (MAX_OPERATIONS, MAX_PACKAGE_BYTES)
ORIGIN_KIND = "floor-plan-conversion"
ORIGIN_FIELDS = frozenset({"kind", "conversionId", "referenceId", "importId", "sourceSha256", "geometrySha256",
                           "alignmentSha256", "layersSha256", "settingsSha256", "converterVersion"})
RECORD_SCHEMA = "inspectorpro.facility.floorPlanConversion"
_BODY_FIELDS = {"baseRevision", "settings", "stage"}
_KEPT_GEOMETRIES = 2


class _Geometries:
    """The last drawings converted, parsed: a geometry file is named by its digest and never rewritten, and the
    review asks again after every change of settings. The converter only reads them."""

    def __init__(self):
        self.lock = threading.Lock()
        self.entries = OrderedDict()

    def get(self, path):
        key = str(path)
        with self.lock:
            if key in self.entries:
                self.entries.move_to_end(key)
                return self.entries[key]
        with open(path, "r", encoding="utf-8") as stream:
            geometry = json.load(stream)
        with self.lock:
            self.entries[key] = geometry
            while len(self.entries) > _KEPT_GEOMETRIES:
                self.entries.popitem(last=False)
        return geometry


_GEOMETRIES = _Geometries()


def _store_root(service):
    return service.layout_repository.root / STORE_FOLDER


def _request(value):
    if not isinstance(value, dict) or not {"baseRevision", "settings"} <= set(value) or set(value) - _BODY_FIELDS:
        raise FacilityValidationError("invalid_request_body", "Send baseRevision and settings, and optionally stage.")
    revision = value["baseRevision"]
    if not isinstance(revision, str) or not 1 <= len(revision) <= 128:
        raise FacilityValidationError("invalid_request_body", "baseRevision must be the saved layout's revision.")
    stage = value.get("stage", "candidates")
    if stage not in STAGES:
        raise FacilityValidationError("invalid_request_body", "stage must be candidates or proposal.")
    try:
        settings = normalize_settings(value["settings"])
    except ConversionSettingsError as error:
        raise FacilityValidationError("floor_plan_conversion_settings_invalid", str(error)) from None
    return revision, settings, stage


def _stale(message):
    return FacilityConflictError("floor_plan_conversion_stale", message)


def conversion_for(service, principal, site_id, layout_id, import_id, base_revision, settings):
    """(result, reference, record) for the saved layout at BASE_REVISION and its underlay of IMPORT_ID."""
    current = service.get_layout(principal, site_id, layout_id)
    if current["revision"] != base_revision:
        raise FacilityConflictError("revision_conflict", "The layout changed. Convert again from the saved layout.",
                                    details={"currentRevision": current["revision"]})
    layout = current["layout"]
    reference = next((item for item in layout_references(layout).values() if item.get("importId") == import_id),
                     None)
    if reference is None:
        raise _stale("Add this drawing to the plan and save the layout before converting it.")
    if (reference.get("alignment") or {}).get("confirmed") is not True:
        # A drawing whose unit is open is drawn at 1 m a unit: its walls would be at a guessed size.
        raise FacilityValidationError("floor_plan_unit_unconfirmed", "Choose the drawing's unit, or set its scale "
                                      "from a known length, and save the layout before converting it.")
    path, record = artifact_file(_store_root(service), principal, site_id, import_id, "geometry")
    if record.get("geometrySha256") != reference.get("geometrySha256"):
        raise _stale("The underlay shows another reading of this drawing. Import it again.")
    try:
        result = convert(_GEOMETRIES.get(path), reference, layout, settings, import_id=import_id)
    except ConversionTooLargeError as error:
        raise FacilityValidationError("floor_plan_conversion_too_large", str(error)) from None
    return result, reference, record


def _candidates(result):
    rows = []
    for kind, key in (("outline", "outlines"), ("wall", "walls"), ("room", "rooms"), ("door", "doors")):
        for row in result[key]:
            rows.append({"kind": kind, "candidateId": row["candidateId"], "state": row["state"],
                         "reason": row.get("reason"), "sources": row["sources"], "layers": row["layers"]})
    return rows


def stage_conversion(service, principal, site_id, layout_id, import_id, body):
    """The conversion route's work (floor_plan_imports): candidates, or candidates and a proposal to review."""
    from .operation_proposals import create, fingerprint

    base_revision, settings, stage = _request(body)
    result, reference, record = conversion_for(service, principal, site_id, layout_id, import_id, base_revision,
                                               settings)
    operations = result.pop("operations")
    response = {"baseRevision": base_revision, "stage": stage, "conversion": result}
    if stage == "candidates":
        return response
    blocked = result["summary"]["blocked"]
    if blocked:
        raise FacilityValidationError("floor_plan_conversion_" + blocked["code"], blocked["message"])
    require_facility_action(principal, tenant_id=principal.tenant_id, site_id=site_id, action="proposal.create")
    conversion = conversion_id(import_id, reference, layout_id, base_revision, settings)
    origin = origin_for(conversion, reference, record, settings)
    written = store_conversion(_store_root(service), principal, site_id, {
        "schema": RECORD_SCHEMA, "schemaVersion": 1, "conversionId": conversion, "layoutId": layout_id,
        "baseRevision": base_revision, "origin": origin, "sourceName": record.get("sourceName"),
        "alignment": reference["alignment"], "layers": reference["layers"], "settings": settings,
        "operationsSha256": fingerprint(operations), "operationCount": len(operations),
        "candidates": _candidates(result), "unconvertedCounts": result["unconvertedCounts"]})
    try:
        proposal = create(service, principal, site_id, layout_id, base_revision, operations=operations,
                          edit_mode="preview", limits=PACKAGE_LIMITS, origin=origin)
    except Exception:
        if written:  # an earlier proposal may be bound to a record this call found stored
            delete_conversion(_store_root(service), principal, site_id, conversion)
        raise
    alternative = proposal["alternative"]
    response["conversionId"] = conversion
    response["proposal"] = {"proposalId": proposal["proposalId"], "baseRevision": base_revision,
                            "expiresAt": proposal["expiresAt"], "approvalRequired": True,
                            "directApplyPolicy": alternative["directApplyPolicy"],
                            "metrics": alternative["metrics"]}
    return response


def normalize_origin(value) -> dict:
    """The stored form of a conversion origin (floor_plan_conversion.origin_for); raises FacilityValidationError."""
    def invalid():
        return FacilityValidationError("operation_proposal_origin_invalid", "The change's origin is not one this "
                                       "server makes.")
    if not isinstance(value, dict) or set(value) != ORIGIN_FIELDS or value.get("kind") != ORIGIN_KIND:
        raise invalid()
    patterns = {"conversionId": CONVERSION_ID, "importId": IMPORT_ID, "referenceId": REFERENCE_ID,
                "sourceSha256": DIGEST, "geometrySha256": DIGEST, "alignmentSha256": DIGEST, "layersSha256": DIGEST,
                "settingsSha256": DIGEST}
    for key, pattern in patterns.items():
        if not isinstance(value[key], str) or not pattern.fullmatch(value[key]):
            raise invalid()
    if not isinstance(value["converterVersion"], str) or not 1 <= len(value["converterVersion"]) <= 64:
        raise invalid()
    return {key: value[key] for key in sorted(ORIGIN_FIELDS)}


def verify_origin(service, principal, site_id, layout_id, base_revision, origin, operations) -> dict:
    """Refuse a conversion proposal whose drawing, record, underlay or converter is no longer the one it was made
    from. Returns the origin's stored form (operation_proposals.prepare calls this every time)."""
    from .operation_proposals import fingerprint

    origin = normalize_origin(origin)
    if origin["converterVersion"] != CONVERTER_VERSION:
        raise _stale("The converter changed since this conversion was made. Convert the drawing again.")
    root = _store_root(service)
    record = stored_import(root, principal, site_id, origin["importId"])
    if (record is None or record.get("sourceSha256") != origin["sourceSha256"]
            or record.get("geometrySha256") != origin["geometrySha256"]):
        raise FacilityConflictError("floor_plan_artifact_missing", "The drawing this change was converted from is "
                                    "no longer stored for this site. Import it again and convert again.")
    kept = load_conversion(root, principal, site_id, origin["conversionId"])
    try:
        matches = (kept is not None and kept.get("origin") == origin and kept.get("layoutId") == layout_id
                   and kept.get("baseRevision") == base_revision and isinstance(operations, list)
                   and kept.get("operationsSha256") == fingerprint(operations)
                   and _digest(kept.get("settings")) == origin["settingsSha256"])
    except (TypeError, ValueError):
        matches = False
    if not matches:
        raise FacilityConflictError("floor_plan_conversion_missing", "The record of this conversion is missing or "
                                    "does not match the change. Convert the drawing again.")
    current = service.get_layout(principal, site_id, layout_id)
    if current["revision"] != base_revision:
        raise FacilityConflictError("revision_conflict", "The layout changed since this conversion was made.",
                                    details={"currentRevision": current["revision"]})
    reference = layout_references(current["layout"]).get(origin["referenceId"])
    if (reference is None or reference.get("importId") != origin["importId"]
            or _digest(reference.get("alignment")) != origin["alignmentSha256"]
            or _digest(reference.get("layers")) != origin["layersSha256"]):
        raise _stale("The underlay moved or its layers changed since this conversion was made. Convert again.")
    return origin
