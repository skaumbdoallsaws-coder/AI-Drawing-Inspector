"""Deterministic Gate G4 asset search and placement compilation."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import re
from typing import Any, Mapping, Sequence

from .canonical import canonicalize_layout
from .fit_analysis import analyze_facility_asset_fit
from .knowledge_foundation import (
    FacilityKnowledgeContractError,
    canonical_facility_knowledge_bytes,
)
from .spatial import (
    placement_spatial_records,
    polygon_contains_polygon,
    polygons_intersect,
)


G4_ASSET_PLACEMENT_SCOPE = "department_resources"
G4_FACILITY_ASSET_PLACEMENT_TOOL = "generate_facility_asset_placement_draft"
G4_MAXIMUM_ASSET_QUANTITY = 50
G4_ORIENTATION_MODES = frozenset(
    {
        "auto",
        "long_side_east_west",
        "long_side_north_south",
        "front_facing",
    }
)
G4_RESOURCE_ROLES = frozenset(
    {
        "production",
        "storage",
        "staging",
        "inspection",
        "support",
        "material_handling",
        "unspecified",
    }
)
G4_ACCESS_REQUIREMENTS = frozenset(
    {"physical_only", "registered_access_required"}
)

_ACTION = re.compile(
    r"\b(?:place|add|stage|position|locate|install)\b",
    re.IGNORECASE,
)
_NON_ASSET_FACILITY_ENTITY = re.compile(
    r"\b(?:aisles?|lanes?|corridors?|paths?|walkways?|routes?|crossings?|"
    r"crosswalks?|departments?|subzones?|zones?|child\s+areas?|"
    r"floor\s+markings?)\b",
    re.IGNORECASE,
)
_COORDINATE = re.compile(
    r"(?:\b(?:x|z)\s*=\s*-?\d|\bcoordinates?\b|\bworld\s+point\b|"
    r"\b-?\d+(?:\.\d+)?\s*(?:degrees?|deg)\b)",
    re.IGNORECASE,
)
_UNSUPPORTED_AUTHORITY = re.compile(
    r"\b(?:osha|fire\s+code|building\s+code|regulatory|compliant|"
    r"code[-\s]+compliant|safe\s+access|whatever\s+clearance|"
    r"typical\s+(?:service|maintenance|operator)?\s*clearance)\b",
    re.IGNORECASE,
)
_ACCESS = re.compile(
    r"\b(?:service|maintenance|operator)\s+(?:access|clearance|envelope)\b|"
    r"\baccess\s+(?:clearance|envelope)\b",
    re.IGNORECASE,
)
_EXPLICIT_CLEARANCE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:m|mm|ft|feet|foot|in|inch|inches)\b"
    r"[^.!?]{0,32}\b(?:access|clearance|service|maintenance)\b|"
    r"\b(?:access|clearance|service|maintenance)\b[^.!?]{0,32}"
    r"\d+(?:\.\d+)?\s*(?:m|mm|ft|feet|foot|in|inch|inches)\b",
    re.IGNORECASE,
)
_FACING = re.compile(
    r"\b(?:front\s+)?fac(?:e|ing)\s+(?P<direction>north|east|south|west)\b",
    re.IGNORECASE,
)
_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
}


class FacilityAssetPlacementError(FacilityKnowledgeContractError):
    """A G4 asset request is ambiguous, unsupported, or infeasible."""


def _revision(value: Any) -> str:
    return hashlib.sha256(canonical_facility_knowledge_bytes(value)).hexdigest()


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}-{_revision(value)[:24]}"


def _words(value: Any) -> list[str]:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
    result = []
    for token in text.split():
        if token.endswith("ies") and len(token) > 4:
            token = token[:-3] + "y"
        elif token.endswith("ches") and len(token) > 5:
            token = token[:-2]
        elif token.endswith("ses") and len(token) > 4:
            token = token[:-2]
        elif token.endswith("s") and not token.endswith("ss") and len(token) > 3:
            token = token[:-1]
        result.append(token)
    return result


def _phrase(value: Any) -> str:
    return " ".join(_words(value))


def _asset_definition(record: Mapping[str, Any]) -> dict[str, Any]:
    nested = record.get("definition")
    definition = (
        deepcopy(dict(nested))
        if isinstance(nested, Mapping)
        else deepcopy(dict(record))
    )
    asset_id = str(record.get("assetId") or definition.get("assetId") or "")
    revision = str(
        record.get("assetDefinitionRevision")
        or definition.get("assetDefinitionRevision")
        or ""
    )
    if not asset_id or not revision:
        raise FacilityAssetPlacementError(
            "facility_asset_identity_invalid",
            "Every G4 catalog record requires an exact asset ID and revision.",
        )
    definition["assetId"] = asset_id
    definition["assetDefinitionRevision"] = revision
    return definition


def _catalog_records(
    asset_catalog: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for raw in asset_catalog:
        if not isinstance(raw, Mapping):
            continue
        definition = _asset_definition(raw)
        key = (definition["assetId"], definition["assetDefinitionRevision"])
        if key in seen:
            continue
        seen.add(key)
        nested = raw.get("definition")
        source = nested if isinstance(nested, Mapping) else raw
        result.append(
            {
                "assetId": definition["assetId"],
                "assetDefinitionRevision": definition[
                    "assetDefinitionRevision"
                ],
                "displayName": str(
                    raw.get("displayName")
                    or source.get("displayName")
                    or definition["assetId"]
                ).strip(),
                "category": str(
                    raw.get("category") or source.get("category") or "unknown"
                ).strip(),
                "tags": [
                    str(item).strip()
                    for item in source.get("tags", [])
                    if str(item).strip()
                ]
                if isinstance(source.get("tags"), list)
                else [],
                "facilitySemantics": deepcopy(
                    raw.get("facilitySemantics")
                    if isinstance(raw.get("facilitySemantics"), Mapping)
                    else source.get("facilitySemantics")
                    if isinstance(source.get("facilitySemantics"), Mapping)
                    else {}
                ),
                "previewPlanningEligible": (
                    raw.get("previewPlanningEligible") is True
                ),
                "definition": definition,
            }
        )
    return sorted(
        result,
        key=lambda item: (item["displayName"].casefold(), item["assetId"]),
    )


def _resolve_zone(layout: Mapping[str, Any], label: str) -> dict[str, Any]:
    key = _phrase(label)
    matches = [
        deepcopy(dict(zone))
        for zone in layout.get("zones", [])
        if isinstance(zone, Mapping) and _phrase(zone.get("label")) == key
    ]
    if not matches:
        raise FacilityAssetPlacementError(
            "facility_asset_target_area_not_found",
            f"No active department or child area is labelled '{label}'.",
            details={
                "availableLabels": [
                    str(item.get("label") or "")
                    for item in layout.get("zones", [])
                    if isinstance(item, Mapping) and item.get("label")
                ][:50]
            },
        )
    if len(matches) != 1:
        raise FacilityAssetPlacementError(
            "facility_asset_target_area_ambiguous",
            f"More than one active area is labelled '{label}'.",
        )
    return matches[0]


def _resolve_exact_asset(
    asset_catalog: Sequence[Mapping[str, Any]],
    asset_id: str,
    revision: str,
) -> dict[str, Any]:
    matches = [
        item
        for item in _catalog_records(asset_catalog)
        if item["assetId"] == asset_id
        and item["assetDefinitionRevision"] == revision
    ]
    if len(matches) != 1:
        raise FacilityAssetPlacementError(
            "facility_asset_revision_unavailable",
            "The exact authorized asset revision is unavailable.",
            details={"assetId": asset_id, "assetDefinitionRevision": revision},
        )
    readiness = matches[0]["definition"].get("readiness")
    placement_ready = (
        isinstance(readiness, Mapping)
        and isinstance(readiness.get("placementReady"), Mapping)
        and readiness["placementReady"].get("value") is True
        and not readiness["placementReady"].get("blockers")
    )
    if not placement_ready and not matches[0]["previewPlanningEligible"]:
        raise FacilityAssetPlacementError(
            "facility_asset_not_placement_ready",
            f"Asset '{matches[0]['displayName']}' is not placement-ready.",
        )
    return matches[0]


def build_asset_catalog_snapshot(
    asset_catalog: Sequence[Mapping[str, Any]],
    references: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return the exact, minimal catalog records needed to replay a G4 run."""

    snapshot = []
    seen = set()
    for reference in references:
        asset_id = str(
            reference.get("asset_id") or reference.get("assetId") or ""
        ).strip()
        revision = str(
            reference.get("asset_definition_revision")
            or reference.get("assetDefinitionRevision")
            or ""
        ).strip()
        key = (asset_id, revision)
        if key in seen:
            continue
        asset = _resolve_exact_asset(asset_catalog, asset_id, revision)
        seen.add(key)
        snapshot.append(
            {
                "assetId": asset["assetId"],
                "assetDefinitionRevision": asset["assetDefinitionRevision"],
                "displayName": asset["displayName"],
                "category": asset["category"],
                "tags": deepcopy(asset["tags"]),
                "facilitySemantics": deepcopy(asset["facilitySemantics"]),
                "previewPlanningEligible": asset[
                    "previewPlanningEligible"
                ],
                "definition": deepcopy(asset["definition"]),
            }
        )
    return snapshot


def _closed_request(request: Mapping[str, Any]) -> None:
    allowed = {
        "request_id",
        "asset_id",
        "asset_definition_revision",
        "quantity",
        "target_area",
        "orientation_mode",
        "facing_direction",
        "resource_role",
        "access_requirement",
        "preserve_hierarchy",
        "execution_mode",
    }
    unknown = sorted(set(request) - allowed)
    if unknown:
        raise FacilityAssetPlacementError(
            "facility_asset_model_geometry_refused",
            "G4 accepts asset, target-area, role, and semantic orientation intent only.",
            details={"fields": unknown},
        )


def normalize_asset_placement_request(
    request: Mapping[str, Any],
    layout: Mapping[str, Any],
    asset_catalog: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise FacilityAssetPlacementError(
            "facility_asset_request_invalid", "G4 asset intent must be an object."
        )
    _closed_request(request)
    if request.get("preserve_hierarchy") is not True:
        raise FacilityAssetPlacementError(
            "facility_asset_hierarchy_preservation_required",
            "G4 must preserve department and child-area geometry.",
        )
    if str(request.get("execution_mode") or "") != "authorized_draft_run":
        raise FacilityAssetPlacementError(
            "facility_asset_execution_mode_invalid",
            "G4 requires authorized_draft_run mode.",
        )
    quantity = request.get("quantity")
    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or not 1 <= quantity <= G4_MAXIMUM_ASSET_QUANTITY
    ):
        raise FacilityAssetPlacementError(
            "facility_asset_quantity_invalid",
            f"Asset quantity must be from 1 through {G4_MAXIMUM_ASSET_QUANTITY}.",
        )
    asset = _resolve_exact_asset(
        asset_catalog,
        str(request.get("asset_id") or "").strip(),
        str(request.get("asset_definition_revision") or "").strip(),
    )
    target = _resolve_zone(layout, str(request.get("target_area") or "").strip())
    orientation_mode = str(request.get("orientation_mode") or "auto")
    if orientation_mode not in G4_ORIENTATION_MODES:
        raise FacilityAssetPlacementError(
            "facility_asset_orientation_invalid",
            "Asset orientation intent is unsupported.",
        )
    facing_direction = request.get("facing_direction")
    if facing_direction is not None:
        facing_direction = str(facing_direction).strip().lower()
    if orientation_mode == "front_facing":
        if facing_direction not in {"north", "east", "south", "west"}:
            raise FacilityAssetPlacementError(
                "facility_asset_facing_direction_required",
                "Front-facing orientation requires north, east, south, or west.",
            )
        sides = asset["facilitySemantics"].get("functionalSides")
        front = sides.get("front") if isinstance(sides, Mapping) else None
        if not isinstance(front, Mapping) or front.get("side") not in {
            "north",
            "east",
            "south",
            "west",
        }:
            raise FacilityAssetPlacementError(
                "facility_asset_front_orientation_unavailable",
                f"Asset '{asset['displayName']}' has no registered front-side orientation.",
            )
    elif facing_direction is not None:
        raise FacilityAssetPlacementError(
            "facility_asset_facing_direction_unexpected",
            "facing_direction is valid only with front_facing orientation.",
        )
    resource_role = str(request.get("resource_role") or "unspecified")
    if resource_role not in G4_RESOURCE_ROLES:
        raise FacilityAssetPlacementError(
            "facility_asset_resource_role_invalid",
            "Asset resource role is unsupported.",
        )
    access_requirement = str(
        request.get("access_requirement") or "physical_only"
    )
    if access_requirement not in G4_ACCESS_REQUIREMENTS:
        raise FacilityAssetPlacementError(
            "facility_asset_access_requirement_invalid",
            "Asset access requirement is unsupported.",
        )
    request_id = str(request.get("request_id") or "").strip() or _stable_id(
        "g4-request",
        {
            "assetId": asset["assetId"],
            "revision": asset["assetDefinitionRevision"],
            "quantity": quantity,
            "targetZoneId": target["zoneId"],
            "orientation": orientation_mode,
            "facing": facing_direction,
            "role": resource_role,
            "access": access_requirement,
        },
    )
    return {
        "scope": G4_ASSET_PLACEMENT_SCOPE,
        "requestId": request_id,
        "assetId": asset["assetId"],
        "assetDefinitionRevision": asset["assetDefinitionRevision"],
        "displayName": asset["displayName"],
        "quantity": quantity,
        "targetArea": str(target.get("label") or ""),
        "targetZoneId": str(target.get("zoneId") or ""),
        "orientationMode": orientation_mode,
        "facingDirection": facing_direction,
        "resourceRole": resource_role,
        "accessRequirement": access_requirement,
        "preserveHierarchy": True,
        "executionMode": "authorized_draft_run",
    }


def asset_placement_tool_spec() -> dict[str, Any]:
    return {
        "name": G4_FACILITY_ASSET_PLACEMENT_TOOL,
        "description": (
            "Place an exact revisioned industrial asset inside one named department "
            "or child area in the active unsaved Facility generation run. Supply no "
            "coordinates, transforms, angles, or clearances. InspectorPro resolves "
            "authoritative footprints, computes bounded collision-free geometry, "
            "preserves the hierarchy, and reports access as validated or unverified."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "asset_id": {"type": "string", "minLength": 1},
                "asset_definition_revision": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "quantity": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": G4_MAXIMUM_ASSET_QUANTITY,
                },
                "target_area": {"type": "string", "minLength": 1},
                "orientation_mode": {
                    "type": "string",
                    "enum": sorted(G4_ORIENTATION_MODES),
                },
                "facing_direction": {
                    "type": ["string", "null"],
                    "enum": ["north", "east", "south", "west", None],
                },
                "resource_role": {
                    "type": "string",
                    "enum": sorted(G4_RESOURCE_ROLES),
                },
                "access_requirement": {
                    "type": "string",
                    "enum": sorted(G4_ACCESS_REQUIREMENTS),
                },
                "preserve_hierarchy": {"type": "boolean", "const": True},
                "execution_mode": {
                    "type": "string",
                    "const": "authorized_draft_run",
                },
            },
            "required": [
                "asset_id",
                "asset_definition_revision",
                "quantity",
                "target_area",
                "orientation_mode",
                "facing_direction",
                "resource_role",
                "access_requirement",
                "preserve_hierarchy",
                "execution_mode",
            ],
            "additionalProperties": False,
        },
    }


def _target_match(message: str, layout: Mapping[str, Any]) -> tuple[str, tuple[int, int]] | None:
    matches = []
    for zone in layout.get("zones", []):
        if not isinstance(zone, Mapping) or not zone.get("label"):
            continue
        label = str(zone["label"])
        pattern = re.compile(
            r"\b(?:in|inside|within|into|to)\s+(?:the\s+)?"
            + re.escape(label)
            + r"(?=$|[\s,.;])",
            re.IGNORECASE,
        )
        for found in pattern.finditer(message):
            matches.append((label, found.span(), len(label)))
    if not matches:
        return None
    matches.sort(key=lambda item: (-item[2], item[1][0], item[0].casefold()))
    best = matches[0]
    competing = {
        label.casefold()
        for label, span, length in matches
        if span[0] == best[1][0] and length == best[2]
    }
    if len(competing) > 1:
        return None
    return best[0], best[1]


def _quantity_and_asset_phrase(segment: str) -> tuple[int | None, str, bool]:
    cleaned = re.sub(r"^\s*(?:exactly\s+)?", "", segment, flags=re.IGNORECASE)
    match = re.match(r"(?P<count>\d{1,3}|[a-z]+)\b\s*(?P<rest>.*)", cleaned, re.I)
    if match is None:
        return None, cleaned.strip(" ,;:"), False
    raw = match.group("count").casefold()
    explicit = True
    if raw.isdigit():
        count = int(raw)
    elif raw in {"a", "an"}:
        count = 1
    elif raw in _NUMBER_WORDS:
        count = _NUMBER_WORDS[raw]
    else:
        count = None
        explicit = False
    return count, (match.group("rest") if explicit else cleaned).strip(" ,;:"), explicit


def _select_asset_from_phrase(
    phrase: str,
    catalog: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    records = _catalog_records(catalog)
    phrase_words = _words(phrase)
    while phrase_words and phrase_words[0] in {"the", "new", "registered", "catalog"}:
        phrase_words.pop(0)
    query = " ".join(phrase_words)
    exact = [item for item in records if _phrase(item["displayName"]) == query]
    if len(exact) == 1:
        return exact[0], exact
    contained = []
    for item in records:
        names = [item["displayName"], item["assetId"], *item["tags"]]
        aliases = [_phrase(value) for value in names if _phrase(value)]
        scores = [len(alias.split()) for alias in aliases if alias and alias in query]
        if scores:
            contained.append((max(scores), item))
    if contained:
        best_score = max(item[0] for item in contained)
        best = [item[1] for item in contained if item[0] == best_score]
        if len(best) == 1:
            return best[0], best
        return None, best
    query_tokens = set(phrase_words)
    fallback = []
    for item in records:
        haystack = set(
            _words(item["displayName"])
            + _words(item["category"])
            + [word for tag in item["tags"] for word in _words(tag)]
        )
        meaningful = query_tokens - {
            "asset", "equipment", "machine", "unit", "item", "resource",
        }
        if meaningful and meaningful.issubset(haystack):
            fallback.append(item)
    if len(fallback) == 1:
        return fallback[0], fallback
    return None, fallback


def parse_asset_placement_turn(
    message: str,
    layout: Mapping[str, Any],
    asset_catalog: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    text = re.sub(r"\s+", " ", str(message or "").strip())
    action = _ACTION.search(text)
    if action is None:
        return {"kind": "not_applicable"}
    if _NON_ASSET_FACILITY_ENTITY.search(text):
        return {"kind": "not_applicable"}
    if _COORDINATE.search(text):
        return {
            "kind": "refuse",
            "code": "facility_asset_coordinate_ownership",
            "response": (
                "**I cannot accept asset coordinates, angles, or transforms from chat.** "
                "Name the exact catalog asset, quantity, target area, and semantic "
                "orientation; InspectorPro will compute the placement."
            ),
        }
    if _UNSUPPORTED_AUTHORITY.search(text):
        return {
            "kind": "refuse",
            "code": "facility_asset_unsupported_compliance_claim",
            "response": (
                "**I cannot claim or invent equipment safety or code clearance.** "
                "Bind an approved access or clearance record to the exact asset "
                "revision before requiring that result. Nothing changed."
            ),
        }
    if _EXPLICIT_CLEARANCE.search(text):
        return {
            "kind": "ask",
            "code": "facility_asset_clearance_not_registered",
            "response": (
                "**G4 cannot reinterpret a chat dimension as an approved equipment "
                "access envelope.** Register that requirement against the exact asset "
                "revision, or ask for physical-footprint placement with access left "
                "explicitly unverified."
            ),
        }
    target = _target_match(text, layout)
    if target is None:
        return {
            "kind": "ask",
            "code": "facility_asset_target_area_required",
            "response": (
                "**Name one existing department or child area for the asset placement.** "
                "Nothing changed."
            ),
        }
    target_label, target_span = target
    asset_segment = text[action.end():target_span[0]]
    quantity, asset_phrase, explicit_quantity = _quantity_and_asset_phrase(
        asset_segment
    )
    selected, candidates = _select_asset_from_phrase(asset_phrase, asset_catalog)
    if selected is None:
        names = [item["displayName"] for item in candidates[:8]]
        detail = " Matches include " + ", ".join(names) + "." if names else ""
        return {
            "kind": "ask",
            "code": (
                "facility_asset_selection_ambiguous"
                if candidates
                else "facility_asset_not_found"
            ),
            "response": (
                "**I need one exact authorized catalog asset.**"
                + detail
                + " Use its full display name; nothing changed."
            ),
        }
    if quantity is None:
        display_words = _words(selected["displayName"])
        phrase_words = _words(asset_phrase)
        plural = bool(phrase_words and str(asset_phrase).strip().casefold().endswith("s"))
        if phrase_words == display_words and not plural:
            quantity = 1
        else:
            return {
                "kind": "ask",
                "code": "facility_asset_quantity_required",
                "response": (
                    "**Give the exact quantity to place.** Nothing changed."
                ),
            }
    if not 1 <= quantity <= G4_MAXIMUM_ASSET_QUANTITY:
        return {
            "kind": "ask",
            "code": "facility_asset_quantity_invalid",
            "response": (
                f"**Give an asset quantity from 1 through {G4_MAXIMUM_ASSET_QUANTITY}.**"
            ),
        }
    orientation_mode = "auto"
    facing_direction = None
    if re.search(r"\blong\s+side\s+(?:east[-\s]+west|west[-\s]+east)\b", text, re.I):
        orientation_mode = "long_side_east_west"
    elif re.search(r"\blong\s+side\s+(?:north[-\s]+south|south[-\s]+north)\b", text, re.I):
        orientation_mode = "long_side_north_south"
    else:
        facing = _FACING.search(text)
        if facing is not None:
            orientation_mode = "front_facing"
            facing_direction = facing.group("direction").lower()
    resource_role = "staging" if action.group(0).casefold() == "stage" else "unspecified"
    if re.search(r"\b(?:storage|store)\b", text, re.I):
        resource_role = "storage"
    elif re.search(r"\binspection\b", text, re.I):
        resource_role = "inspection"
    elif re.search(r"\bproduction\b", text, re.I):
        resource_role = "production"
    access_requirement = (
        "registered_access_required" if _ACCESS.search(text) else "physical_only"
    )
    request = {
        "asset_id": selected["assetId"],
        "asset_definition_revision": selected["assetDefinitionRevision"],
        "quantity": quantity,
        "target_area": target_label,
        "orientation_mode": orientation_mode,
        "facing_direction": facing_direction,
        "resource_role": resource_role,
        "access_requirement": access_requirement,
        "preserve_hierarchy": True,
        "execution_mode": "authorized_draft_run",
    }
    try:
        normalized = normalize_asset_placement_request(
            request, layout, asset_catalog
        )
    except FacilityAssetPlacementError as exc:
        return {
            "kind": "ask",
            "code": exc.code,
            "response": f"**I could not prepare that asset placement.** {exc} Nothing changed.",
        }
    if not explicit_quantity and quantity == 1:
        normalized["assumptions"] = ["single_quantity_from_singular_asset_name"]
    else:
        normalized["assumptions"] = []
    return {"kind": "build", "request": normalized}


def _asset_dimensions(definition: Mapping[str, Any]) -> tuple[float, float]:
    geometry = definition.get("geometry")
    aabb = geometry.get("aabb") if isinstance(geometry, Mapping) else None
    if not isinstance(aabb, Mapping):
        raise FacilityAssetPlacementError(
            "facility_asset_geometry_unavailable",
            "The selected asset has no authoritative footprint dimensions.",
        )
    minimum = aabb.get("minimum")
    maximum = aabb.get("maximum")
    try:
        width = float(maximum["x"]) - float(minimum["x"])
        depth = float(maximum["z"]) - float(minimum["z"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FacilityAssetPlacementError(
            "facility_asset_geometry_unavailable",
            "The selected asset has no authoritative footprint dimensions.",
        ) from exc
    if width <= 0 or depth <= 0:
        raise FacilityAssetPlacementError(
            "facility_asset_geometry_unavailable",
            "The selected asset footprint is not positive.",
        )
    return width, depth


def _orientation_degrees(
    request: Mapping[str, Any], asset: Mapping[str, Any]
) -> list[int]:
    mode = request["orientationMode"]
    if mode == "auto":
        return [0, 90, 180, 270]
    width, depth = _asset_dimensions(asset["definition"])
    if mode == "long_side_east_west":
        return [0, 180] if width >= depth else [90, 270]
    if mode == "long_side_north_south":
        return [90, 270] if width >= depth else [0, 180]
    sides = asset["facilitySemantics"].get("functionalSides")
    front = sides.get("front") if isinstance(sides, Mapping) else None
    local_side = str(front.get("side") or "") if isinstance(front, Mapping) else ""
    headings = {"north": 0, "east": 90, "south": 180, "west": 270}
    if local_side not in headings or request["facingDirection"] not in headings:
        raise FacilityAssetPlacementError(
            "facility_asset_front_orientation_unavailable",
            f"Asset '{asset['displayName']}' has no registered front-side orientation.",
        )
    return [
        (headings[str(request["facingDirection"])] - headings[local_side]) % 360
    ]


def _collection_revision(layout: Mapping[str, Any], field: str) -> str:
    return _revision(layout.get(field, []))


def _existing_placement_revisions(layout: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(item["placementId"]): _revision(item)
        for item in layout.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }


def compile_asset_placement_program(
    layout: Mapping[str, Any],
    requests: Sequence[Mapping[str, Any]],
    asset_catalog: Sequence[Mapping[str, Any]],
    *,
    evidence_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(requests, Sequence) or isinstance(requests, (str, bytes)) or not requests:
        raise FacilityAssetPlacementError(
            "facility_asset_program_invalid",
            "G4 requires at least one asset-placement request.",
        )
    base = canonicalize_layout(deepcopy(dict(layout)))
    working = deepcopy(base)
    catalog = _catalog_records(asset_catalog)
    catalog_payload = [item["definition"] for item in catalog]
    operations: list[dict[str, Any]] = []
    placements: list[dict[str, Any]] = []
    request_summaries: list[dict[str, Any]] = []
    assumptions: list[str] = []
    for request_index, raw in enumerate(requests):
        source = deepcopy(dict(raw))
        source.setdefault("request_id", f"asset-request-{request_index + 1:03d}")
        source.setdefault("preserve_hierarchy", True)
        source.setdefault("execution_mode", "authorized_draft_run")
        normalized = normalize_asset_placement_request(source, base, asset_catalog)
        asset = _resolve_exact_asset(
            asset_catalog,
            normalized["assetId"],
            normalized["assetDefinitionRevision"],
        )
        orientations = _orientation_degrees(normalized, asset)
        request_placements = []
        for occurrence in range(normalized["quantity"]):
            fit = analyze_facility_asset_fit(
                working,
                catalog_payload,
                asset_id=normalized["assetId"],
                asset_definition_revision=normalized["assetDefinitionRevision"],
                zone_id=normalized["targetZoneId"],
                evidence_authority=evidence_authority,
                orientations_degrees=orientations,
                maximum_results=8,
            )
            candidates = list(fit.get("candidates") or [])
            if normalized["accessRequirement"] == "registered_access_required":
                candidates = [item for item in candidates if item.get("clearanceValidated") is True]
                if not candidates:
                    raise FacilityAssetPlacementError(
                        "facility_asset_access_evidence_unavailable",
                        f"No bounded placement for '{asset['displayName']}' has registered, authoritative access-clearance evidence.",
                        details={
                            "assetId": normalized["assetId"],
                            "targetZoneId": normalized["targetZoneId"],
                            "fitStatus": fit.get("status"),
                        },
                    )
            if not candidates:
                raise FacilityAssetPlacementError(
                    "facility_asset_set_unplaceable",
                    f"The deterministic fit engine could not place all requested '{asset['displayName']}' occurrences in '{normalized['targetArea']}'.",
                    details={
                        "placedCount": occurrence,
                        "requestedCount": normalized["quantity"],
                        "rejectionCounts": deepcopy(fit.get("rejectionCounts") or {}),
                    },
                )
            candidate = candidates[0]
            placement_id = _stable_id(
                "pl-g4",
                {
                    "layoutId": base.get("layoutId"),
                    "requestId": normalized["requestId"],
                    "occurrenceIndex": occurrence,
                    "assetId": normalized["assetId"],
                    "targetZoneId": normalized["targetZoneId"],
                },
            )
            access_status = (
                "validated"
                if candidate.get("clearanceValidated") is True
                else "unverified"
            )
            placement = {
                "placementId": placement_id,
                "assetId": normalized["assetId"],
                "assetDefinitionRevision": normalized["assetDefinitionRevision"],
                "transform": deepcopy(candidate["transform"]),
                "positionMode": "auto",
                "snapRelationship": None,
                "metadata": {
                    "generatedBy": "facility_asset_placement_g4",
                    "gate": "G4",
                    "requestId": normalized["requestId"],
                    "occurrenceIndex": occurrence + 1,
                    "instanceLabel": f"{asset['displayName']} {occurrence + 1:02d}",
                    "targetZoneId": normalized["targetZoneId"],
                    "targetArea": normalized["targetArea"],
                    "resourceRole": normalized["resourceRole"],
                    "orientationMode": normalized["orientationMode"],
                    "orientationDegrees": int(candidate["orientationDegrees"]),
                    "accessStatus": access_status,
                    "clearanceEvidenceComplete": candidate.get("clearanceEvidenceComplete") is True,
                    "fitCandidateId": str(candidate.get("candidateId") or ""),
                },
            }
            operation = {"op": "place_asset", "placement": placement}
            # The compiler needs the accepted placement for the next fit query,
            # but applying one kernel transaction per occurrence repeatedly
            # canonicalizes the entire growing layout. The returned immutable
            # operation list is still applied by the coordinator; this working
            # copy exists only for deterministic candidate exclusion.
            working.setdefault("placements", []).append(deepcopy(placement))
            operations.append(operation)
            summary = {
                "placementId": placement_id,
                "assetId": normalized["assetId"],
                "assetDefinitionRevision": normalized["assetDefinitionRevision"],
                "displayName": asset["displayName"],
                "targetZoneId": normalized["targetZoneId"],
                "targetArea": normalized["targetArea"],
                "orientationDegrees": int(candidate["orientationDegrees"]),
                "orientationMode": normalized["orientationMode"],
                "accessStatus": access_status,
                "geometricValid": True,
                "clearanceEvidenceComplete": candidate.get("clearanceEvidenceComplete") is True,
            }
            placements.append(summary)
            request_placements.append(summary)
        request_summaries.append(
            {
                "requestId": normalized["requestId"],
                "assetId": normalized["assetId"],
                "assetDefinitionRevision": normalized["assetDefinitionRevision"],
                "displayName": asset["displayName"],
                "quantity": normalized["quantity"],
                "targetArea": normalized["targetArea"],
                "targetZoneId": normalized["targetZoneId"],
                "resourceRole": normalized["resourceRole"],
                "orientationMode": normalized["orientationMode"],
                "accessRequirement": normalized["accessRequirement"],
                "placementIds": [item["placementId"] for item in request_placements],
            }
        )
        assumptions.extend(raw.get("assumptions", []) if isinstance(raw.get("assumptions"), list) else [])
    working = canonicalize_layout(working)
    preserved_fields = (
        "zones",
        "routes",
        "floorMarkings",
        "utilityNetworks",
        "processBindings",
        "groups",
    )
    expected = {
        "scope": G4_ASSET_PLACEMENT_SCOPE,
        "requestCount": len(request_summaries),
        "placementCount": len(placements),
        "requests": request_summaries,
        "placements": placements,
        "preservedCollectionRevisions": {
            field: _collection_revision(base, field) for field in preserved_fields
        },
        "preservedPlacementRevisions": _existing_placement_revisions(base),
        "saved": False,
    }
    validation = validate_asset_placement_result(
        working,
        expected,
        asset_catalog,
        evidence_authority=evidence_authority,
    )
    if validation["status"] != "valid":
        raise FacilityAssetPlacementError(
            "facility_asset_program_validation_failed",
            "Compiled G4 placements failed deterministic post-validation.",
            details={"errors": validation["errors"]},
        )
    replay_input: dict[str, Any] = {
        "scope": G4_ASSET_PLACEMENT_SCOPE,
        "requests": [deepcopy(dict(item)) for item in requests],
        "assetCatalog": build_asset_catalog_snapshot(
            asset_catalog, request_summaries
        ),
    }
    if isinstance(evidence_authority, Mapping):
        replay_input["evidenceAuthority"] = deepcopy(
            dict(evidence_authority)
        )
    return {
        "stageId": G4_ASSET_PLACEMENT_SCOPE,
        "selectedCommandIds": ["assets"],
        "operations": operations,
        "plannedInstanceCount": len(placements),
        "normalizedRequest": replay_input,
        "assumptions": list(dict.fromkeys(str(item) for item in assumptions)),
        "validationPlan": [
            "exact_asset_revision",
            "target_zone_containment",
            "physical_collision_free",
            "protected_route_avoidance",
            "semantic_orientation",
            "access_evidence_classification",
            "g3_hierarchy_byte_parity",
            "existing_placement_byte_parity",
        ],
        "expectedSummary": expected,
    }


def validate_asset_placement_result(
    layout: Mapping[str, Any],
    expected: Mapping[str, Any],
    asset_catalog: Sequence[Mapping[str, Any]],
    *,
    evidence_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    placements_by_id = {
        str(item.get("placementId")): item
        for item in layout.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }
    zones_by_id = {
        str(item.get("zoneId")): item
        for item in layout.get("zones", [])
        if isinstance(item, Mapping) and item.get("zoneId")
    }
    assets = {
        (item["assetId"], item["assetDefinitionRevision"]): item["definition"]
        for item in _catalog_records(asset_catalog)
    }
    for field, before_revision in expected.get("preservedCollectionRevisions", {}).items():
        if _collection_revision(layout, str(field)) != before_revision:
            errors.append(f"{field}_changed")
    for placement_id, before_revision in expected.get("preservedPlacementRevisions", {}).items():
        current = placements_by_id.get(str(placement_id))
        if current is None or _revision(current) != before_revision:
            errors.append(f"existing_placement_changed:{placement_id}")
    new_records: dict[str, list[Any]] = {}
    for item in expected.get("placements", []):
        placement_id = str(item.get("placementId") or "")
        placement = placements_by_id.get(placement_id)
        if placement is None:
            errors.append(f"placement_missing:{placement_id}")
            continue
        key = (
            str(item.get("assetId") or ""),
            str(item.get("assetDefinitionRevision") or ""),
        )
        asset = assets.get(key)
        if asset is None:
            errors.append(f"asset_revision_unavailable:{placement_id}")
            continue
        metadata = placement.get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        if (
            placement.get("assetId") != key[0]
            or placement.get("assetDefinitionRevision") != key[1]
            or metadata.get("targetZoneId") != item.get("targetZoneId")
            or metadata.get("orientationDegrees") != item.get("orientationDegrees")
            or metadata.get("accessStatus") != item.get("accessStatus")
        ):
            errors.append(f"placement_identity_or_metadata_mismatch:{placement_id}")
        zone = zones_by_id.get(str(item.get("targetZoneId") or ""))
        if zone is None:
            errors.append(f"target_zone_missing:{placement_id}")
            continue
        boundary = tuple(
            (float(point["x"]), float(point["z"]))
            for point in zone.get("boundary", [])
            if isinstance(point, Mapping)
        )
        try:
            records = list(placement_spatial_records(placement, asset))
        except (TypeError, ValueError):
            records = []
        if not records or not all(
            polygon_contains_polygon(boundary, record.polygon)
            for record in records
        ):
            errors.append(f"placement_outside_target_zone:{placement_id}")
        new_records[placement_id] = records
    all_physical = []
    for placement_id, placement in placements_by_id.items():
        asset = assets.get(
            (
                str(placement.get("assetId") or ""),
                str(placement.get("assetDefinitionRevision") or ""),
            )
        )
        if asset is None:
            continue
        try:
            records = placement_spatial_records(placement, asset)
        except (TypeError, ValueError):
            continue
        for record in records:
            all_physical.append((placement_id, record))
    new_ids = set(new_records)
    for index, (left_id, left) in enumerate(all_physical):
        for right_id, right in all_physical[index + 1:]:
            if left_id == right_id or not ({left_id, right_id} & new_ids):
                continue
            vertical_overlap = not (
                left.interval[1] <= right.interval[0]
                or right.interval[1] <= left.interval[0]
            )
            if vertical_overlap and polygons_intersect(left.polygon, right.polygon):
                errors.append(f"placement_collision:{left_id}:{right_id}")
    return {
        "status": "valid" if not errors else "invalid",
        "placementCount": len(expected.get("placements", [])),
        "validatedPlacementCount": len(new_records),
        "accessValidatedCount": sum(
            item.get("accessStatus") == "validated"
            for item in expected.get("placements", [])
        ),
        "accessUnverifiedCount": sum(
            item.get("accessStatus") == "unverified"
            for item in expected.get("placements", [])
        ),
        "hierarchyPreserved": not any(
            error.startswith("zones_changed") for error in errors
        ),
        "errors": sorted(set(errors)),
    }


__all__ = [
    "G4_ACCESS_REQUIREMENTS",
    "G4_ASSET_PLACEMENT_SCOPE",
    "G4_FACILITY_ASSET_PLACEMENT_TOOL",
    "G4_MAXIMUM_ASSET_QUANTITY",
    "G4_ORIENTATION_MODES",
    "G4_RESOURCE_ROLES",
    "FacilityAssetPlacementError",
    "asset_placement_tool_spec",
    "build_asset_catalog_snapshot",
    "compile_asset_placement_program",
    "normalize_asset_placement_request",
    "parse_asset_placement_turn",
    "validate_asset_placement_result",
]
