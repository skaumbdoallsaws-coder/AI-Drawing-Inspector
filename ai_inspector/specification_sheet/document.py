"""Compile one-page, evidence-bound product specification sheets."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from ai_inspector.operations_manual.evidence import OperationsManualEvidenceRepository
from .cad import format_extents, format_mass
from .slots import (
    CAD_ROWS,
    FEATURE_COUNT,
    MAX_ROWS,
    PROSE_SLOTS,
    SLOT_SCHEMA_VERSION,
    SOURCE_LABELS,
    SlotStore,
    TemplateStore,
    resolve,
    row_key,
    slot_name,
)
from ai_inspector.parts_manual.documentation import (
    DEFAULT_DOCUMENT_THEME,
    DEFAULT_PAGE_MASTERS,
)


SPECIFICATION_SHEET_DOCUMENT_SCHEMA_VERSION = 1
SPECIFICATION_SHEET_RENDER_PIPELINE_VERSION = 1
SPECIFICATION_SHEET_PAGE_WIDTH_PT = 612.0
SPECIFICATION_SHEET_PAGE_HEIGHT_PT = 792.0
_APPROVED_PROFILE_STATUSES = {
    "approved_for_prototype",
    "approved_for_prototype_description",
}


class SpecificationSheetError(RuntimeError):
    pass


def _stable_revision(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _read_profile(
    profile_root: str | Path, assembly_number: str, *, required: bool = True
) -> Optional[Dict[str, Any]]:
    root = Path(profile_root).resolve()
    safe_name = str(assembly_number or "").strip().lower()
    if not safe_name or any(value not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for value in safe_name):
        raise SpecificationSheetError("invalid specification-sheet assembly number")
    path = (root / "profiles" / f"{safe_name}.json").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise SpecificationSheetError("invalid specification-sheet profile path") from exc
    try:
        profile = json.loads(path.read_text("utf-8"))
    except FileNotFoundError as exc:
        if not required:
            return None
        raise SpecificationSheetError(
            f"no reviewed specification-sheet profile is registered for {assembly_number}"
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SpecificationSheetError("the specification-sheet profile is unreadable") from exc
    if not isinstance(profile, dict):
        raise SpecificationSheetError("the specification-sheet profile must be an object")
    if str(profile.get("assemblyNumber") or "").casefold() != safe_name.casefold():
        raise SpecificationSheetError("the specification-sheet profile assembly binding is invalid")
    return profile


def _claim(snapshot: Mapping[str, Any], claim_id: str) -> Dict[str, Any]:
    claim = (snapshot.get("claims") or {}).get(str(claim_id))
    if not isinstance(claim, Mapping):
        raise SpecificationSheetError(f"required specification claim is missing: {claim_id}")
    status = str(claim.get("status") or "")
    if status not in _APPROVED_PROFILE_STATUSES:
        raise SpecificationSheetError(
            f"specification claim {claim_id} is not approved for the review sheet"
        )
    return copy.deepcopy(dict(claim))


def _format_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SpecificationSheetError("a specification value is not numeric") from exc
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _format_claim_value(claim: Mapping[str, Any]) -> str:
    value = claim.get("value")
    unit = str(claim.get("unit") or "").strip()
    if isinstance(value, Mapping):
        ordered = [value.get(key) for key in ("width", "length", "height") if value.get(key) is not None]
        if not ordered:
            raise SpecificationSheetError("a structured specification value is empty")
        formatted = " x ".join(_format_number(item) for item in ordered)
    elif value is not None:
        formatted = _format_number(value)
    else:
        raise SpecificationSheetError("an approved specification value is missing")
    return f"{formatted} {unit}".strip()


def _citation_receipt(
    snapshot: Mapping[str, Any],
    claim_ids: Iterable[str],
) -> list[Dict[str, Any]]:
    source_claims: Dict[str, set[str]] = {}
    source_anchors: Dict[str, Dict[str, set[str]]] = {}
    source_pages: Dict[str, Dict[str, set[int]]] = {}
    for claim_id in sorted({str(value) for value in claim_ids if str(value).strip()}):
        claim = (snapshot.get("claims") or {}).get(claim_id) or {}
        for source_id in claim.get("sourceIds") or []:
            source_key = str(source_id)
            source_claims.setdefault(source_key, set()).add(claim_id)
            for location in claim.get("sourceLocations") or []:
                if not isinstance(location, Mapping) or str(location.get("sourceId") or "") != source_key:
                    continue
                anchor = str(location.get("anchor") or "").strip()
                if anchor:
                    source_anchors.setdefault(source_key, {}).setdefault(claim_id, set()).add(anchor)
                try:
                    page_number = int(location.get("page") or 0)
                except (TypeError, ValueError):
                    page_number = 0
                if page_number > 0:
                    source_pages.setdefault(source_key, {}).setdefault(claim_id, set()).add(page_number)

    sources = snapshot.get("sources") or {}
    authority_order = {
        "OEM_CURRENT": 0,
        "CAD_AUTHORED": 1,
        "USER_AUTHORED": 2,
    }
    ordered = sorted(
        source_claims,
        key=lambda source_id: (
            authority_order.get(str((sources.get(source_id) or {}).get("authority") or ""), 99),
            str((sources.get(source_id) or {}).get("title") or source_id).casefold(),
        ),
    )
    rows: list[Dict[str, Any]] = []
    for index, source_id in enumerate(ordered, start=1):
        source = sources.get(source_id) or {}
        claim_ids_for_source = sorted(source_claims[source_id])
        references = [
            {
                "claimId": claim_id,
                "sourcePageNumbers": sorted(source_pages.get(source_id, {}).get(claim_id, set())),
                "anchors": sorted(source_anchors.get(source_id, {}).get(claim_id, set())),
            }
            for claim_id in claim_ids_for_source
        ]
        rows.append(
            {
                "citationNumber": index,
                "sourceId": source_id,
                "title": str(source.get("title") or source_id),
                "kind": str(source.get("kind") or "registered_evidence"),
                "authority": str(source.get("authority") or "UNKNOWN"),
                "url": str(source.get("url") or "").strip() or None,
                "registeredLocation": str(
                    source.get("canonicalLocation")
                    or source.get("cachedLocation")
                    or ""
                ).strip() or None,
                "claimCount": len(claim_ids_for_source),
                "claimIds": claim_ids_for_source,
                "claimSourcePageReferences": references,
                "sourcePageNumbers": sorted(
                    {
                        page_number
                        for reference in references
                        for page_number in reference["sourcePageNumbers"]
                    }
                ),
            }
        )
    return rows


def specification_sheet_layout() -> Dict[str, Any]:
    return {
        "page": {
            "width": SPECIFICATION_SHEET_PAGE_WIDTH_PT,
            "height": SPECIFICATION_SHEET_PAGE_HEIGHT_PT,
            "aspectRatio": SPECIFICATION_SHEET_PAGE_WIDTH_PT / SPECIFICATION_SHEET_PAGE_HEIGHT_PT,
            "orientation": "portrait",
            "logicalUnit": "pt",
        },
        "shared": {
            "header": {"x": 0, "y": 0, "width": 612, "height": 64},
            "footer": {"x": 24, "y": 754, "width": 564, "height": 26},
            "content": {"x": 36, "y": 82, "width": 540, "height": 654},
        },
        "pageTypes": {
            "product_specification": {
                "illustration": {"x": 36, "y": 176, "width": 318, "height": 346},
                "specifications": {"x": 374, "y": 198, "width": 202, "height": 324},
            }
        },
    }


def _apply_scene(
    page: Dict[str, Any],
    documentation_scene: Optional[Mapping[str, Any]],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    scene = documentation_scene if isinstance(documentation_scene, Mapping) else {}
    composition_pages = scene.get("pages") if isinstance(scene.get("pages"), Mapping) else {}
    composition = copy.deepcopy(
        composition_pages.get(page["pageId"])
        if isinstance(composition_pages.get(page["pageId"]), Mapping)
        else {}
    )
    page["documentationComposition"] = composition
    page["documentationObjects"] = copy.deepcopy(
        composition.get("documentObjects")
        if isinstance(composition.get("documentObjects"), Mapping)
        else {}
    )
    page["pageMasterId"] = "reference"
    page["renderRequest"]["composition"] = copy.deepcopy(composition)
    theme = copy.deepcopy(
        scene.get("theme") if isinstance(scene.get("theme"), Mapping) else DEFAULT_DOCUMENT_THEME
    )
    page_masters = copy.deepcopy(
        scene.get("pageMasters")
        if isinstance(scene.get("pageMasters"), Mapping)
        else DEFAULT_PAGE_MASTERS
    )
    return theme, page_masters


# The page's text blocks and the slot each one shows. A text typed over a block before the slots existed (a scene
# text override) still counts, as a value the user typed in the viewport.
_BLOCK_SLOTS = {
    "spec-kicker": "kicker",
    "spec-title": "title",
    "spec-tagline": "tagline",
    "specifications-heading": "specifications.heading",
    "features-heading": "features.heading",
    **{f"spec-feature-{index}": f"feature.{index}.text" for index in range(1, FEATURE_COUNT + 1)},
}
_LEGACY_FEATURES_HEADING = "Designed for productive material handling"
_DEFAULT_CAPTION = "Assembled product visualization."
_TABLE_ROW_HEIGHT = 54.0


def _legacy_text_values(page: Dict[str, Any], stored: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Scene text overrides become workspace values (unless a value is already stored), and are taken out of the
    page's composition so nothing applies them twice."""
    values: Dict[str, Dict[str, Any]] = {}
    for composition in (page["documentationComposition"], page["renderRequest"].get("composition") or {}):
        overrides = composition.get("pageElementOverrides")
        if not isinstance(overrides, dict):
            continue
        for block_id, slot in _BLOCK_SLOTS.items():
            override = overrides.get(block_id)
            if not isinstance(override, dict) or "text" not in override:
                continue
            text = str(override.pop("text") or "").strip()
            if text and slot not in stored and slot not in values:
                values[slot] = {"value": text, "source": "workspace", "legacy": True}
    return values


def _profile_defaults(profile: Mapping[str, Any], snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """What a reviewed profile gives the sheet: the evidence values, the reviewed wording, the rows."""
    defaults: Dict[str, Dict[str, Any]] = {}
    identity_id = str(profile.get("identityClaimId") or "")
    identity = _claim(snapshot, identity_id)
    product_name = str(identity.get("statement") or "").strip()
    product_name = product_name.removeprefix("The target product is the ").rstrip(".")
    used = {identity_id}
    if product_name:
        defaults["title"] = {"value": product_name, "source": "evidence", "claimIds": [identity_id]}
    rows: list[Dict[str, Any]] = []
    for row in profile.get("specifications") or []:
        if not isinstance(row, Mapping):
            continue
        claim_id = str(row.get("claimId") or "")
        claim = _claim(snapshot, claim_id)
        used.add(claim_id)
        label = str(row.get("label") or claim.get("category") or "Specification")
        key = row_key(label, (item["key"] for item in rows))
        rows.append({"key": key, "label": label, "source": "profile", "claimId": claim_id,
                     "sourceIds": [str(value) for value in claim.get("sourceIds") or []]})
        defaults[f"spec.{key}.value"] = {"value": _format_claim_value(claim), "source": "evidence",
                                         "claimIds": [claim_id]}
    if not rows:
        raise SpecificationSheetError("the specification-sheet profile has no approved values")
    tagline = profile.get("tagline") if isinstance(profile.get("tagline"), Mapping) else {}
    tagline_ids = [str(value) for value in tagline.get("claimIds") or []]
    for claim_id in tagline_ids:
        _claim(snapshot, claim_id)
        used.add(claim_id)
    if str(tagline.get("text") or "").strip():
        defaults["tagline"] = {"value": str(tagline["text"]), "source": "evidence", "claimIds": tagline_ids}
    features = [row for row in profile.get("features") or [] if isinstance(row, Mapping)]
    if len(features) != FEATURE_COUNT:
        raise SpecificationSheetError("the one-page specification profile requires three features")
    for index, row in enumerate(features, start=1):
        claim_ids = [str(value) for value in row.get("claimIds") or []]
        for claim_id in claim_ids:
            _claim(snapshot, claim_id)
            used.add(claim_id)
        defaults[f"feature.{index}.title"] = {"value": str(row.get("title") or "Feature"), "source": "profile"}
        defaults[f"feature.{index}.text"] = {"value": str(row.get("text") or ""), "source": "evidence",
                                             "claimIds": claim_ids}
    figure = profile.get("figure") if isinstance(profile.get("figure"), Mapping) else {}
    defaults["caption"] = {"value": str(figure.get("caption") or _DEFAULT_CAPTION), "source": "profile"}
    defaults["features.heading"] = {"value": str(profile.get("featuresHeading") or _LEGACY_FEATURES_HEADING),
                                    "source": "profile"}
    return {"defaults": defaults, "rows": rows, "usedClaimIds": used, "productName": product_name}


def _cad_value(key: str, cad: Mapping[str, Any], units: str) -> Optional[str]:
    if key == "overall_dimensions" and cad.get("extents"):
        return format_extents(cad["extents"], units)
    if key == "weight" and cad.get("massKg"):
        return format_mass(float(cad["massKg"]), units)
    return None


def _slot_page_data(
    *,
    identity_name: str,
    profile: Optional[Mapping[str, Any]],
    snapshot: Optional[Mapping[str, Any]],
    stored: Mapping[str, Any],
    template: Optional[Mapping[str, Any]],
    legacy: Mapping[str, Mapping[str, Any]],
    cad: Mapping[str, Any],
) -> Dict[str, Any]:
    approved = (template or {}).get("approved") or {}
    units = stored.get("units") or approved.get("units") or "imperial"
    from_profile = _profile_defaults(profile, snapshot) if profile else None
    defaults: Dict[str, Dict[str, Any]] = dict(from_profile["defaults"]) if from_profile else {}
    defaults.setdefault("title", {"value": identity_name, "source": "library"})
    defaults.setdefault("caption", {"value": _DEFAULT_CAPTION, "source": "layout"})
    defaults["kicker"] = {"value": "PRODUCT SPECIFICATION", "source": "layout"}
    defaults["specifications.heading"] = {"value": "Specifications", "source": "layout"}

    profile_rows = {row["key"]: row for row in (from_profile or {}).get("rows") or []}
    template_rows = [dict(row, source="template") for row in approved.get("rows") or []]
    cad_rows = [{"key": key, "label": item["label"], "hint": item["hint"], "source": "layout"}
                for key, item in CAD_ROWS.items()]
    rows = stored.get("rows")
    if rows is None and template_rows and not profile_rows:
        # An approved type's names, then the CAD's rows the names leave out (the app knows those values).
        template_keys = {row["key"] for row in template_rows}
        rows = template_rows + [row for row in cad_rows if row["key"] not in template_keys]
    if rows is None:
        rows = list(profile_rows.values()) or template_rows or cad_rows
    template_by_key = {row["key"]: row for row in template_rows}
    cad_by_key = {row["key"]: row for row in cad_rows}
    sheet_rows = []
    for row in rows:
        key = row["key"]
        base = profile_rows.get(key) or template_by_key.get(key) or cad_by_key.get(key) or row
        source = row.get("source") or base.get("source") or "workspace"
        label = row.get("label") or base.get("label") or key.replace("_", " ")
        defaults[f"spec.{key}.label"] = {"value": label, "source": source}
        value_slot = f"spec.{key}.value"
        if value_slot not in defaults:
            cad_value = _cad_value(key, cad, units)
            hint = row.get("hint") or base.get("hint")
            if key == "weight" and not cad_value and cad.get("massNote"):
                hint = f"not from the CAD: {cad['massNote']}"
            defaults[value_slot] = ({"value": cad_value, "source": "cad"} if cad_value
                                    else {"value": None, "source": None})
            if hint:
                defaults[value_slot]["hint"] = hint
        unit = row.get("unit") or base.get("unit")
        if unit and not defaults[value_slot].get("value"):
            defaults[value_slot]["hint"] = ((defaults[value_slot].get("hint") or "") + f" (in {unit})").strip()
        sheet_rows.append({"key": key, "label": label, "unit": unit, "source": source,
                           "hint": row.get("hint") or base.get("hint"),
                           "claimId": (profile_rows.get(key) or {}).get("claimId"),
                           "sourceIds": (profile_rows.get(key) or {}).get("sourceIds") or []})

    order = list(PROSE_SLOTS) + [f"spec.{row['key']}.{part}" for row in sheet_rows for part in ("label", "value")]
    values = {**(stored.get("values") or {}), **legacy}
    resolved = resolve(defaults, values, order)
    labels = {row["key"]: resolved[f"spec.{row['key']}.label"]["value"] or row["label"] for row in sheet_rows}
    for slot in order:
        resolved[slot]["name"] = slot_name(slot, labels)
    return {"units": units, "rows": sheet_rows, "order": order, "slots": resolved, "labels": labels,
            "usedClaimIds": (from_profile or {}).get("usedClaimIds") or set()}


def _release_gate(order: Iterable[str], slots: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    open_slots, findings = [], []
    for slot in order:
        item = slots[slot]
        if item["open"]:
            entry = {"slot": slot, "name": item["name"]}
            if item.get("hint"):
                entry["hint"] = item["hint"]
            open_slots.append(entry)
            continue
        if item["unreviewed"]:
            what = "a public source" if item["source"] == "research" else "a Sage draft"
            findings.append({"severity": "warning", "topic": "unreviewed", "blocking": False, "slot": slot,
                             "message": f"{item['name']} is from {what} and not reviewed yet: {item['value'][:80]}"})
        if item.get("overrides"):
            original = item["overrides"]
            findings.append({"severity": "warning", "topic": "overrides_" + original["source"], "blocking": False,
                             "slot": slot,
                             "message": f"{item['name']} was changed from the {SOURCE_LABELS[original['source']]} "
                                        f"value '{str(original['value'])[:60]}' to '{item['value'][:60]}'."})
    def count(number: int, one: str, many: str) -> str:
        return f"{number} {one if number == 1 else many}"

    parts = []
    if open_slots:
        parts.append(count(len(open_slots), "open slot is", "open slots are") + " left out of the final PDF")
    unreviewed = sum(1 for item in findings if item["topic"] == "unreviewed")
    if unreviewed:
        parts.append(count(unreviewed, "value is", "values are") + " unreviewed")
    overrides = len(findings) - unreviewed
    if overrides:
        parts.append(count(overrides, "value was", "values were") + " typed over the CAD or the evidence")
    message = "Review export only; controlled release requires recorded approval."
    if parts:
        message += " " + "; ".join(parts) + "."
    return {"status": "REVIEW_READY", "reviewPdfAllowed": True, "controlledPdfAllowed": False,
            "message": message, "openSlots": open_slots, "findings": findings,
            "openSlotCount": len(open_slots), "blockingFindingCount": 0}


def build_specification_sheet_document(
    assembly_data: Mapping[str, Any],
    catalog: Mapping[str, Any],
    *,
    evidence_root: str | Path,
    profile_root: str | Path,
    slot_root: Optional[str | Path] = None,
    cad: Optional[Mapping[str, Any]] = None,
    library: Optional[Mapping[str, Any]] = None,
    documentation_scene: Optional[Mapping[str, Any]] = None,
    documentation_scene_revision: Optional[str] = None,
    appearance_revision: Optional[str] = None,
) -> Dict[str, Any]:
    assembly_number = str(catalog.get("assemblyNumber") or "").strip()
    profile = _read_profile(profile_root, assembly_number, required=False)
    snapshot = OperationsManualEvidenceRepository(evidence_root).snapshot() if profile else None
    stored = (SlotStore(slot_root, assembly_number).read() if slot_root
              else {"values": {}, "rows": None, "type": None, "units": None})
    sheet_type = stored.get("type") or None
    templates = TemplateStore(slot_root) if slot_root else None
    template = templates.get(sheet_type["key"]) if templates and sheet_type else None
    identity = assembly_data.get("identity") or {}
    identity_name = str((library or {}).get("displayName") or identity.get("description") or identity.get("name")
                        or assembly_number)

    occurrence_ids = [
        str(row.get("occurrenceId"))
        for row in catalog.get("occurrences") or []
        if isinstance(row, Mapping)
        and row.get("occurrenceId")
        and row.get("kind") == "part"
        and not row.get("suppressed")
    ]
    if not occurrence_ids:
        raise SpecificationSheetError("the assembly has no visible part occurrences")

    figure = (profile or {}).get("figure") if isinstance((profile or {}).get("figure"), Mapping) else {}
    layout = specification_sheet_layout()
    illustration_frame = layout["pageTypes"]["product_specification"]["illustration"]
    table_frame = layout["pageTypes"]["product_specification"]["specifications"]
    feature_width = 168.0
    page: Dict[str, Any] = {
        "pageId": "page-product-specification",
        "pageNumber": 1,
        "pageCount": 1,
        "pageType": "product_specification",
        "renderRequest": {
            "figureId": "SPEC-FIG-001",
            "scopeKind": "assembly",
            "manualGroupNames": [],
            "occurrenceIds": occurrence_ids,
            "occurrenceOrder": occurrence_ids,
            "pose": str(figure.get("pose") or "assembled"),
            "cameraPreset": str(figure.get("cameraPreset") or "isometric"),
            "explodeStrategy": "radial",
            "explodeFactor": 0.0,
            "displayStyle": "shaded",
            "illustrationStyle": str(figure.get("illustrationStyle") or "SHADED_COLOR"),
            "showItemCallouts": False,
            "calloutItems": [],
            "image": {
                "status": "required",
                "minimumWidthPx": 2200,
                "minimumHeightPx": 2200,
                "targetAspectRatio": 1.0,
                "targetForegroundOccupancy": 0.70,
                "minimumForegroundOccupancy": 0.60,
                "maximumForegroundOccupancy": 0.80,
                "maximumForegroundAxisOccupancy": 0.94,
                # A long machine (a robot arm, a conveyor) fills the frame's width before it reaches the area minimum.
                "axisConstrainedOccupancyPolicy": "allow_when_uniform_scale_exceeds_axis_limit",
                "axisConstrainedFillTolerance": 0.02,
                "background": "technical_white",
                "illustrationStyle": str(figure.get("illustrationStyle") or "SHADED_COLOR"),
                "allowAutomaticCameraSelection": True,
            },
        },
    }
    if appearance_revision:
        # The machine's finishes are in the picture: a new appearance makes the capture stale. Only when one is
        # set, so the captures of assemblies without an appearance stay valid.
        page["renderRequest"]["appearanceRevision"] = appearance_revision
    # The product picture depends on the model and the camera, not on the words: a text edit keeps the capture.
    figure_revision = _stable_revision({
        "assemblyNumber": assembly_number,
        "sourceRevision": catalog.get("sourceRevision"),
        "renderPipelineVersion": SPECIFICATION_SHEET_RENDER_PIPELINE_VERSION,
        "renderRequest": page["renderRequest"],
    })
    theme, page_masters = _apply_scene(page, documentation_scene)
    legacy = _legacy_text_values(page, stored.get("values") or {})
    data = _slot_page_data(identity_name=identity_name, profile=profile, snapshot=snapshot, stored=stored,
                           template=template, legacy=legacy, cad=cad or {})
    slots, rows = data["slots"], data["rows"]

    def value(slot: str) -> str:
        return str(slots[slot]["value"] or "")

    def text_block(block_id: str, block_type: str, slot: str, frame: Dict[str, Any], style: Dict[str, Any],
                   claim_ids: Iterable[str] = (), heading: bool = False) -> Dict[str, Any]:
        block = {"blockId": block_id, "blockType": block_type, "text": value(slot), "slot": slot,
                 "open": slots[slot]["open"], "frame": frame, "style": style,
                 "evidenceClaimIds": [str(item) for item in claim_ids]}
        if heading:
            block["lines"] = [value(slot)] if value(slot) else []
        return block

    product_name = value("title") or identity_name
    row_height = min(_TABLE_ROW_HEIGHT, float(table_frame["height"]) / max(1, len(rows)))
    profile_identity = str((profile or {}).get("identityClaimId") or "")
    page.update({
        "title": product_name,
        "productCategory": str((profile or {}).get("productCategory")
                               or str((sheet_type or {}).get("label") or "").upper() or "PRODUCT SPECIFICATION"),
        "specifications": [
            {"key": row["key"], "label": value(f"spec.{row['key']}.label"),
             "value": slots[f"spec.{row['key']}.value"]["value"],
             **({"claimId": row["claimId"], "sourceIds": row["sourceIds"]} if row.get("claimId") else {})}
            for row in rows
        ],
        "features": [
            {"title": value(f"feature.{index}.title"), "text": value(f"feature.{index}.text"),
             "claimIds": slots[f"feature.{index}.text"].get("claimIds") or []}
            for index in range(1, FEATURE_COUNT + 1)
        ],
        "evidenceClaimIds": sorted(data["usedClaimIds"]),
        "layoutBlocks": [
            text_block("spec-kicker", "spec_kicker", "kicker", {"x": 36, "y": 84, "width": 540, "height": 16},
                       {"fontSize": 8.5, "lineHeight": 12, "fontWeight": 700, "color": "#148FD0"}),
            text_block("spec-title", "spec_title", "title", {"x": 36, "y": 102, "width": 540, "height": 39},
                       {"fontSize": 22, "lineHeight": 28, "fontWeight": 700, "color": "#071B2A"},
                       [profile_identity] if profile_identity else []),
            text_block("spec-tagline", "paragraph", "tagline", {"x": 36, "y": 144, "width": 540, "height": 20},
                       {"fontSize": 9, "lineHeight": 12, "color": "#596A76"},
                       slots["tagline"].get("claimIds") or []),
            {
                "blockId": "spec-figure",
                "blockType": "cad_figure",
                "figureId": "SPEC-FIG-001",
                "caption": value("caption"),
                "slot": "caption",
                "open": slots["caption"]["open"],
                "frame": copy.deepcopy(illustration_frame),
                "evidenceClaimIds": [],
            },
            text_block("specifications-heading", "heading", "specifications.heading",
                       {"x": 374, "y": 170, "width": 202, "height": 28},
                       {"fontSize": 15, "lineHeight": 19, "fontWeight": 700, "color": "#071B2A"}, heading=True),
            {
                "blockId": "specifications-table",
                "blockType": "key_value_table",
                "columns": [],
                "columnWidths": [0.58, 0.42],
                "rows": [
                    {
                        "key": row["key"],
                        "cells": [value(f"spec.{row['key']}.label"), value(f"spec.{row['key']}.value")],
                        "slots": [f"spec.{row['key']}.label", f"spec.{row['key']}.value"],
                        "open": [slots[f"spec.{row['key']}.label"]["open"],
                                 slots[f"spec.{row['key']}.value"]["open"]],
                        "claimIds": [row["claimId"]] if row.get("claimId") else [],
                    }
                    for row in rows
                ],
                "rowHeights": [row_height for _row in rows],
                "frame": copy.deepcopy(table_frame),
                "evidenceClaimIds": [row["claimId"] for row in rows if row.get("claimId")],
            },
            text_block("features-heading", "heading", "features.heading",
                       {"x": 36, "y": 550, "width": 540, "height": 22},
                       {"fontSize": 13, "lineHeight": 17, "fontWeight": 700, "color": "#071B2A"}, heading=True),
            *[
                {
                    "blockId": f"spec-feature-{index}",
                    "blockType": "spec_feature",
                    "title": value(f"feature.{index}.title"),
                    "text": value(f"feature.{index}.text"),
                    "slots": {"title": f"feature.{index}.title", "text": f"feature.{index}.text"},
                    "open": {"title": slots[f"feature.{index}.title"]["open"],
                             "text": slots[f"feature.{index}.text"]["open"]},
                    "frame": {"x": 36 + (index - 1) * 186, "y": 582, "width": feature_width, "height": 132},
                    "evidenceClaimIds": slots[f"feature.{index}.text"].get("claimIds") or [],
                }
                for index in range(1, FEATURE_COUNT + 1)
            ],
        ],
    })

    if profile:
        manual_plan_revision = _stable_revision({
            "assemblyNumber": assembly_number,
            "sourceRevision": catalog.get("sourceRevision"),
            "evidenceRevision": snapshot["revision"],
            "profileRevision": _stable_revision(profile),
        })
    else:
        manual_plan_revision = _stable_revision({
            "assemblyNumber": assembly_number,
            "sourceRevision": catalog.get("sourceRevision"),
            "slotsVersion": SLOT_SCHEMA_VERSION,
        })
    used = data["usedClaimIds"]
    citations = _citation_receipt(snapshot, used) if profile else []
    template_state = None
    if sheet_type:
        template_state = {
            "type": sheet_type["key"], "label": sheet_type.get("label"), "source": sheet_type.get("source"),
            "approved": bool((template or {}).get("approved")),
            "approvedRows": len(((template or {}).get("approved") or {}).get("rows") or []),
            "proposal": copy.deepcopy((template or {}).get("proposal")),
        }
    document: Dict[str, Any] = {
        "schemaVersion": SPECIFICATION_SHEET_DOCUMENT_SCHEMA_VERSION,
        "renderPipelineVersion": SPECIFICATION_SHEET_RENDER_PIPELINE_VERSION,
        "documentType": "product_specification_sheet",
        "status": "review_ready",
        "sourceRevision": str(catalog.get("sourceRevision") or ""),
        "evidenceRevision": str(snapshot["revision"]) if snapshot else None,
        "profileRevision": _stable_revision(profile) if profile else None,
        "manualPlanRevision": manual_plan_revision,
        "figureRevision": figure_revision,
        "documentationSceneRevision": documentation_scene_revision,
        "title": f"{product_name} Specification Sheet",
        "documentNumber": str((profile or {}).get("documentNumber") or f"SS-{assembly_number}-001"),
        "revision": None,
        "product": {
            "name": product_name,
            "assemblyNumber": assembly_number,
            "model": str((profile or {}).get("assemblyNumber") or assembly_number),
            "category": page["productCategory"],
        },
        "sheet": {
            "hasProfile": bool(profile),
            "units": data["units"],
            "type": template_state,
            "rows": [{key: row[key] for key in ("key", "label", "unit", "hint", "source") if row.get(key)}
                     for row in rows],
            "maxRows": MAX_ROWS,
            "cad": {"extents": (cad or {}).get("extents"), "massKg": (cad or {}).get("massKg"),
                    "massNote": (cad or {}).get("massNote")},
        },
        "slots": slots,
        "slotOrder": data["order"],
        "theme": theme,
        "pageMasters": page_masters,
        "publicationLayout": layout,
        "pageCount": 1,
        "pages": [page],
        "evidenceCitations": citations,
        "evidenceSummary": {
            "approvedClaimCount": len(used),
            "citedClaimCount": len(used),
            "citedSourceCount": len(citations),
            "registeredClaimCount": len((snapshot or {}).get("claims") or {}),
            "registeredSourceCount": len((snapshot or {}).get("sources") or {}),
        },
        "releaseGate": _release_gate(data["order"], slots),
    }
    document["documentRevision"] = _stable_revision(document)
    return document
