"""Bounded authoring facts from the authorized, revision-bound facility document."""
from copy import deepcopy

from .policy import PilotError


COLLECTIONS = {
    "placements": (None, "placements", "placementId"),
    "zones": (None, "zones", "zoneId"),
    "routes": (None, "routes", "routeId"),
    "utilities": (None, "utilityNetworks", "utilityNetworkId"),
    "floor_markings": (None, "floorMarkings", "markingId"),
    "interior_walls": ("facilityInteriorWalls", "walls", "wallId"),
    "floor_surfaces": ("facilityFloorSurfaces", "surfaces", "surfaceId"),
    "decals": ("facilityDecals", "artworks", "artworkId"),
}
SINGLETONS = {
    "plan": "facilityPlan", "ground": "facilityGround",
    "perimeter_walls": "facilityPerimeterWalls", "navigation": "facilityNavigation",
}
READ_NAMES = frozenset({"inspect_facility_authoring", "inspect_facility_asset"})


def tool_specs():
    identity = {"type": "string", "minLength": 1, "maxLength": 128}
    return [{"name": "inspect_facility_authoring", "description":
        "Read exact editable records, colors, wall settings, artwork bindings and floor finishes from the saved layout. "
        "Use zones for zone fillColor; floor_surfaces for cosmetic material/color finishes; ground for physical elevations. "
        "Prefer targeted upsert operations to preserve unrelated records. Perimeter settings exclude generated panels. "
        "wall_artworks includes existing legacy perimeter graphics that must be preserved. All dimensions are meters. "
        "Use nextOffset with the same view/filters to page; offset is bound to this saved revision.",
        "input_schema": {"type": "object", "additionalProperties": False, "required": ["view"],
            "properties": {"view": {"enum": [*COLLECTIONS, *SINGLETONS, "wall_artworks", "overview"]},
                "ids": {"type": "array", "items": identity, "maxItems": 25, "uniqueItems": True},
                "query": {"type": "string", "maxLength": 120},
                "offset": {"type": "integer", "minimum": 0, "maximum": 100000},
                "pageSize": {"type": "integer", "minimum": 1, "maximum": 25}}}},
        {"name": "inspect_facility_asset", "description":
            "Read an authorized catalog asset's exact geometry, coordinate frame, capabilities, connectors and revision. "
            "Search with search_industrial_assets first. This does not import files or infer machine component roles.",
         "input_schema": {"type": "object", "additionalProperties": False, "required": ["assetId"],
            "properties": {"assetId": identity,
                "assetDefinitionRevision": {"type": "string", "pattern": "^[a-f0-9]{64}$"}}}}]


def _page(rows, args, id_key):
    ids, query = set(args.get("ids", [])), args.get("query", "").casefold()
    selected = []
    for row in rows:
        if ids and row.get(id_key) not in ids:
            continue
        labels = [row.get(k, "") for k in (id_key, "label", "displayName", "assetId")]
        labels.append(row.get("metadata", {}).get("instanceLabel", ""))
        if query and query not in " ".join(str(v) for v in labels).casefold():
            continue
        selected.append(row)
    selected.sort(key=lambda row: str(row.get(id_key, "")))
    offset, size = args.get("offset", 0), args.get("pageSize", 10)
    end = min(len(selected), offset + size)
    return {"records": deepcopy(selected[offset:end]), "total": len(selected),
            "nextOffset": end if end < len(selected) else None}


def read_authoring(runtime, principal, reference, name, arguments):
    from .facility_tools import read_bound_layout
    saved = read_bound_layout(runtime, principal, reference)
    layout = saved["layout"]
    base = {"identity": deepcopy(reference), "savedLayoutOnly": True, "readOnly": True}
    if name == "inspect_facility_asset":
        asset_id = arguments["assetId"]
        candidates = [a for a in runtime.asset_catalog_provider(principal, reference["siteId"])
                      if a.get("assetId") == asset_id]
        revision = arguments.get("assetDefinitionRevision")
        if revision is None:
            if len(candidates) != 1:
                raise PilotError("codex_asset_unavailable", "Search the authorized library for an exact asset revision.", 404)
            revision = candidates[0]["assetDefinitionRevision"]
        definition = runtime.service._resolve_asset_definition(principal, reference["siteId"], asset_id, revision)
        fields = ("assetId", "displayName", "category", "description", "tags", "geometry", "coordinateFrame",
                  "connectors", "clearances", "capabilities", "facilitySemantics", "utilities", "mounting")
        return dict(base, assetId=asset_id, assetDefinitionRevision=revision,
                    definition={k: deepcopy(definition[k]) for k in fields if k in definition})
    ext, view = layout.get("extensions", {}), arguments["view"]
    if view in {"overview", "plan"}:
        from ai_inspector.facility_layout.plan_settings import plan_settings_from_layout, plan_world_bounds
        plan = plan_settings_from_layout(layout)
        base["planWorldBounds"] = plan_world_bounds(plan,
            floor_y=layout["coordinateFrame"]["floorElevation"]) if plan else None
        base["floorAuthority"] = "ground" if "facilityGround" in ext else "plan" if plan else "shell"
    if view == "overview":
        return dict(base, plan=deepcopy(ext.get("facilityPlan")), coordinateFrame=deepcopy(layout["coordinateFrame"]),
            collections={key: len((layout if extension is None else ext.get(extension, {})).get(field, []))
                         for key, (extension, field, _) in COLLECTIONS.items()},
            availableSettings=[key for key, extension in SINGLETONS.items() if extension in ext])
    if view in SINGLETONS:
        value = deepcopy(ext.get(SINGLETONS[view]))
        if view == "perimeter_walls" and value:
            value.pop("panels", None)
        return dict(base, view=view, configuration=value)
    if view == "wall_artworks":
        finish = ext.get("facilityPerimeterWalls", {}).get("settings", {}).get("exteriorFinish", {})
        rows = [dict(row, collection=key) for key in ("artworks", "fittedArtworks") for row in finish.get(key, [])]
        return dict(base, view=view, **_page(rows, arguments, "artworkId"))
    extension, field, id_key = COLLECTIONS[view]
    document = layout if extension is None else ext.get(extension, {})
    rows = document.get(field, [])
    if view == "interior_walls":
        rows = [{key: value for key, value in row.items() if key != "panels"} for row in rows]
    return dict(base, view=view, **_page(rows, arguments, id_key))
