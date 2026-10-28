"""Bounded authoring inputs for existing deterministic facility operations.

Document definitions remain authoritative for persisted entities. Add inputs
relax only IDs that the operation kernel generates; patches keep IDs immutable.
Extension inputs mirror their domain normalizers, never their compiled geometry.
"""
from copy import deepcopy
import json
from pathlib import Path


def obj(properties, required=None, **constraints):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else list(required),
            "additionalProperties": False, **constraints}


def array(items, maximum, minimum=0, **constraints):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum, **constraints}


def number(low, high):
    return {"type": "number", "minimum": low, "maximum": high}


def text(maximum=128, minimum=1, **constraints):
    return {"type": "string", "minLength": minimum, "maxLength": maximum, **constraints}


def nullable(value):
    return {"anyOf": [value, {"type": "null"}]}


def ref(name):
    return {"$ref": "#/$defs/" + name}


COLOR = text(7, 7, pattern=r"^#[0-9a-fA-F]{6}$")
POINT = obj({key: number(-10000, 10000) for key in ("x", "z")})
HEX_ID = text(64, 64, pattern="^[a-f0-9]{64}$")
ART_ID = text(80, pattern="^[a-z0-9-]{1,80}$")
LEGACY_IMAGE = text(100, pattern=r"^/generated/facility-wall-art/[a-f0-9]{64}\.png$")
IMAGE = text(256, pattern=r"^(/api/facility-decal-images/[A-Za-z0-9][A-Za-z0-9._:-]{0,127}|/generated/facility-wall-art)/[a-f0-9]{64}\.png$")
FRACTIONS = array(number(0, 1), 4, 4)
POSITION_MODE = {"enum": ["auto", "manual", "locked"]}


def extension_definitions():
    perimeter_target = obj({"edge": {"type": "integer", "minimum": 0, "maximum": 127},
                            "side": {"enum": ["interior", "exterior"]}})
    placed_target = obj({"placementId": ref("placementId"),
                        "face": {"enum": ["positive_x", "negative_x", "positive_z", "negative_z"]}})
    fitted = obj({"artworkId": ART_ID, "imagePath": LEGACY_IMAGE, "uv": FRACTIONS,
                  "target": {"oneOf": [perimeter_target, placed_target]}, "region": FRACTIONS,
                  "coverage": number(.95, 1)})
    artwork = deepcopy(fitted)
    artwork["properties"].update(label=ref("label"), imagePath=IMAGE,
        target={"oneOf": [perimeter_target, placed_target,
            obj({"wallId": text(79, pattern="^iw-[a-z0-9-]{1,76}$"), "side": {"enum": ["left", "right"]}})]},
        lettering=obj({"text": text(1000, pattern=r"^[^\u0000-\u0009\u000b-\u001f]*$"),
                       "reference": text(160, 0, pattern=r"^[^\u0000-\u0009\u000b-\u001f]*$"),
                       "font": {"enum": ["Arial", "Georgia"]}, "align": {"enum": ["left", "center", "right"]},
                       "color": COLOR}))
    artwork["required"].append("label")
    rectangle = {"edge": perimeter_target["properties"]["edge"], "startMeters": number(0, 30000),
                 "widthMeters": number(.01, 30000)}
    finish = obj({"color": COLOR, "jointColor": COLOR, "panelWidthMeters": number(.5, 10),
        "panelHeightMeters": number(.4, 5), "jointWidthMeters": number(.003, .05),
        "accentStrips": array(obj({**rectangle, "color": COLOR}), 64),
        "bands": array(obj({"bottomMeters": number(0, 30), "heightMeters": number(.05, 30), "color": COLOR}), 16),
        "wallFaces": array(obj({"placementId": ref("placementId"), "assetDefinitionRevision": HEX_ID,
                               "face": {"enum": ["positive_z", "negative_z"]}, "color": COLOR}), 64),
        "fittedArtworks": array(fitted, 48),
        "artworks": array(obj({**rectangle, "widthMeters": number(.3, 30000),
            "artworkId": ART_ID, "bottomMeters": number(0, 30), "heightMeters": number(.3, 30),
            "imagePath": LEGACY_IMAGE, "uv": FRACTIONS, "backingColor": COLOR, "borderColor": COLOR,
            "side": {"enum": ["exterior", "interior"]}},
            ["artworkId", "edge", "startMeters", "widthMeters", "bottomMeters", "heightMeters", "imagePath"]), 48)},
        ["color"])
    wall_properties = {"boundarySource": {"enum": ["plan", "polygon"]},
        "heightMeters": number(.5, 30), "thicknessMeters": number(.05, 2),
        "openings": array(obj({"edge": perimeter_target["properties"]["edge"],
                              "startMeters": number(0, 30000), "endMeters": number(0, 30000),
                              "heightMeters": number(0.5, 30)}, ["edge", "startMeters", "endMeters"]), 128),
        "exteriorFinish": finish, "interiorColor": COLOR}
    plan_walls = obj({**wall_properties, "boundarySource": {"const": "plan"}},
                     ["boundarySource", "heightMeters", "thicknessMeters"])
    polygon_walls = obj({**wall_properties, "boundarySource": {"const": "polygon"},
                        "boundary": array(POINT, 128, 3, uniqueItems=True)},
                       ["boundarySource", "boundary", "heightMeters", "thicknessMeters"])
    return {
        "decals": obj({"version": {"const": 1}, "artworks": array(artwork, 48)}),
        "perimeterWalls": {"oneOf": [plan_walls, polygon_walls]},
        "interiorWalls": obj({"version": {"const": 1}, "walls": array(obj({
            "wallId": text(79, pattern="^iw-[a-z0-9-]{1,76}$"), "label": ref("label"),
            "start": POINT, "end": POINT, "heightMeters": number(.5, 30),
            "thicknessMeters": number(.05, 2), "baseElevation": number(-1000, 1000), "color": COLOR,
            "openings": array(obj({"startMeters": number(0, 30000), "endMeters": number(0, 30000)}), 32)}), 128)}),
        "floorSurfaces": obj({"version": {"const": 1}, "surfaces": array(obj({
            "surfaceId": text(79, pattern="^fs-[a-z0-9-]{1,76}$"), "label": ref("label"),
            "boundary": array(POINT, 128, 3, uniqueItems=True), "elevation": number(-1000, 1000),
            "material": {"enum": ["concrete", "rubber", "turf", "paving", "wood", "solid"]},
            "color": COLOR, "roughness": number(0, 1)}), 128)}),
        "ground": obj({"schemaVersion": {"const": 1}, "surfaces": array(obj({
            "surfaceId": text(120, pattern="^[A-Za-z0-9_-]{1,120}$"), "color": COLOR,
            "slopeAxis": {"enum": ["x", "z"]},
            **{key: number(-10000, 10000) for key in
               ("minX", "maxX", "minZ", "maxZ", "startElevation", "endElevation")}}), 256, 1),
            # Images painted flat on the ground (a logo or a target on the yard), centred on a level surface.
            "marks": array(obj({"markId": text(83, pattern="^gm-[a-z0-9-]{1,80}$"), "label": text(120),
                                "imagePath": IMAGE, "uv": FRACTIONS, "x": number(-10000, 10000),
                                "z": number(-10000, 10000), "widthMeters": number(.3, 60),
                                "depthMeters": number(.3, 60), "rotationDegrees": number(-360, 360)}), 16)},
            ["schemaVersion", "surfaces"]),
        "planSettings": obj({"widthMeters": number(.5, 10000), "depthMeters": number(.5, 10000),
                             "gridSpacingMeters": number(.05, 10000), "majorGridSpacingMeters": number(.05, 10000)}),
    }


def operation_batch_schema():
    source = json.loads((Path(__file__).resolve().parents[2] /
        "static/contracts/facility-layout-schema-v1.json").read_text(encoding="utf-8"))
    definitions = deepcopy(source["$defs"])
    # Close named entity shapes; the domain contract's explicitly bounded
    # metadata maps remain data, not an alternate operations/authority surface.
    for definition in definitions.values():
        if "properties" in definition:
            definition["additionalProperties"] = False
    for entity, identity in (("placement", "placementId"), ("zone", "zoneId"),
            ("floorMarking", "markingId"), ("route", "routeId"), ("utilityNetwork", "utilityNetworkId"),
            ("utilityEndpointNode", "networkNodeId"), ("utilitySegment", "networkSegmentId"),
            ("processBinding", "processBindingId")):
        definitions[identity] = deepcopy(definitions[entity]["properties"][identity])
    zone = definitions["zone"]["properties"]
    interface = obj({"side": {"enum": ["north", "east", "south", "west"]}, "facing": POINT,
        "position": POINT, "accessEnvelope": array(POINT, 128, 3),
        "openingWidthMeters": {"type": "number", "exclusiveMinimum": 0, "maximum": 10000},
        "approachDepthMeters": {"type": "number", "exclusiveMinimum": 0, "maximum": 10000},
        "evidenceStatus": {"enum": ["authored", "derived", "inferred", "unknown"]}}, ["evidenceStatus"],
        anyOf=[{"required": ["side"]}, {"required": ["facing"]}])
    cell = obj({"schemaVersion": {"const": 1}, "groupKind": {"const": "manufacturing_cell"},
        "membership": {"const": "geometric"}, "envelopePadding": number(0, 10000),
        "autoNumber": obj({"seriesId": ref("stableId"), "baseName": text(80), "prefix": text(12, 0),
            "start": {"type": "integer", "minimum": 0, "maximum": 999999},
            "sequence": {"type": "integer", "minimum": 0, "maximum": 999999},
            "padding": {"type": "integer", "minimum": 1, "maximum": 6}}),
        "functionalInterfaces": obj({role: deepcopy(interface) for role in ("gate", "loading", "service")}, [])},
        ["schemaVersion", "groupKind", "membership", "envelopePadding", "autoNumber"])
    zone["extensions"] = obj({"style": obj({"fillColor": COLOR}), "cellGroup": nullable(cell)}, [])
    definitions["route"]["properties"]["label"] = ref("label")
    # The Python endpoint validator and aisle builder also accept world points.
    definitions["routeEndpoint"]["oneOf"].append(obj({"kind": {"const": "world_point"}, "position": ref("vector3")}))
    definitions.update(extension_definitions())

    def entity_shape(name, identity, *, patch=False):
        base = deepcopy(definitions[name])
        if "oneOf" in base:
            parts = [entity_shape(item["$ref"].split("/")[-1], identity, patch=patch) for item in base["oneOf"]]
            if not patch:
                return {"oneOf": parts}
            properties = {}
            for part in parts:
                for key, value in part["properties"].items():
                    if value is False:
                        continue
                    if key not in properties:
                        properties[key] = value
                    elif properties[key] != value:
                        properties[key] = {"anyOf": [properties[key], value]}
            return obj(properties, [], minProperties=1)
        if patch:
            base["properties"].pop(identity)
            base["required"], base["minProperties"] = [], 1
        else:
            base["required"].remove(identity)
        return base

    variants = []
    def operation(name, properties, required=None, description=None):
        required = list(properties) if required is None else list(required)
        schema = obj({"op": {"const": name}, **properties}, ["op", *required])
        if description:
            schema["description"] = description
        variants.append(schema)

    from .site_tools import schemas as site_schemas
    site = site_schemas()
    operation('set_site_context', {'siteContext':site['siteContext']}, description=
        'Replace the authored property context only after inspection; preserve unrelated areas, entrances and edge assignments. '
        'The existing georeference and imagery must remain unchanged. Location lookup/removal and image fetching are manual UI only. Review required.')
    operation('set_building_pose', {'buildingPose':site['buildingPose']}, description=
        'Move/turn the building in property-frame meters and true bearing, preserving every interior coordinate. Review required.')
    operation('upsert_site_area', {'area':site['siteArea']}, description=
        'Create or replace one outdoor polygon by stable areaId in the property frame, not the interior frame. '
        'Only a drive or sidewalk may cross a setback, and only through an entrance on that edge, within its width. '
        'Review required.')
    operation('delete_site_area', {'areaId':site['siteAreaId']}, description='Delete only the explicitly requested outdoor area. Review required.')
    operation('upsert_site_reference', {'reference':site['siteReference']}, description=
        'Create or replace one reference point by referenceId (rp-1, rp-2, ...) in property-frame metres: a feature '
        'a builder can find on site, with its source and accuracy in metres. measured is the same point measured '
        'independently (a survey) for the fit check. Review required.')
    operation('delete_site_reference', {'referenceId':site['siteReferenceId']}, description=
        'Delete only the explicitly requested reference point. Review required.')

    entities = (("zone", "zoneId", "zone", "add_zone", "edit_zone", "delete_zone"),
        ("floorMarking", "markingId", "floorMarking", "add_floor_marking", "edit_floor_marking", "delete_floor_marking"),
        ("route", "routeId", "route", "add_route", "edit_route", "delete_route"),
        ("utilityNetwork", "utilityNetworkId", "utilityNetwork", "add_utility_network", "edit_utility_network", "delete_utility_network"),
        ("utilityNode", "networkNodeId", "node", "add_utility_network_node", "edit_utility_network_node", "delete_utility_network_node"),
        ("utilitySegment", "networkSegmentId", "segment", "add_utility_network_segment", "edit_utility_network_segment", "delete_utility_network_segment"),
        ("processBinding", "processBindingId", "processBinding", "attach_process_binding", "edit_process_binding", "detach_process_binding"))
    for name, identity, key, add, edit, delete in entities:
        parent = {"utilityNetworkId": ref("utilityNetworkId")} if key in {"node", "segment"} else {}
        operation(add, {**parent, identity: ref(identity), key: entity_shape(name, identity)}, [*parent, key],
                  "Omit the new ID to generate it deterministically. Nested records in a full network still need their own IDs.")
        operation(edit, {**parent, identity: ref(identity), "patch": entity_shape(name, identity, patch=True)},
                  description="Shallow patch: nested objects/arrays replace that field. Preserve unrelated nested settings.")
        operation(delete, {**parent, identity: ref(identity)}, description="Delete this exact entity; existing reference checks still apply.")
    placement = definitions["placement"]["properties"]
    from ai_inspector.facility_layout.floor_paths import SCHEMA as floor_path_schema
    operation("add_floor_path", {"path": deepcopy(floor_path_schema)}, description=
        "Add a polyline, arc or full circle as editable floor line segments. For a circle use sweepDegrees=360. "
        "Arc zero degrees is +X; positive sweep turns toward +Z. World coordinates and widths are meters. "
        "The engine computes up to 128 segments per path; do not manually enumerate curved line segments. "
        "This is decorative paint, not an aisle/access corridor. Expanded entity count still controls review thresholds.")
    new_placement = entity_shape("placement", "placementId")
    new_placement["properties"]["componentMaterials"] = {"type": "null"}
    # orientation replaces the quaternion, and attachTo or seatAt the position and turn;
    # the gateway resolves them before validation.
    new_placement["properties"]["transform"]["required"].remove("quaternion")
    new_placement["properties"]["transform"]["required"].remove("position")
    orientation = {"oneOf": [obj({"facing": {"enum": ["north", "east", "south", "west"]}}),
                             obj({"yawDegrees": number(-360, 360)})]}
    orientation_help = (
        "Prefer orientation over a raw quaternion. Compass: north is +z (up on the plan), east is +x. "
        "facing turns the asset's reviewed front side (facilitySemantics.functionalSides.front) to that direction; "
        "assets without one fail, so use yawDegrees, which turns the unrotated model as a compass heading turns "
        "(90 turns its north side east), and say the orientation is unverified.")
    workstation_help = (
        " To put an item on a desk or worktop, give attachTo {supportPlacementId, surfaceId} with a surface from that "
        "asset's supportSurfaces (inspect_facility_asset): the item is centred on it at its height, turned to face the "
        "surface's user. To seat a chair at a desk whose facilitySemantics has a workstationSeat, give seatAt "
        "{deskPlacementId}. With either, leave out orientation and give placement.transform as only {scale: 1}.")
    operation("place_asset", {"placementId": ref("placementId"), "placement": new_placement,
              "orientation": orientation,
              "attachTo": obj({"supportPlacementId": ref("placementId"), "surfaceId": text(120)}),
              "seatAt": obj({"deskPlacementId": ref("placementId")})}, ["placement"],
              "Give orientation or placement.transform.quaternion. " + orientation_help + workstation_help +
              " For component finishes, first save the new placement, inspect its visual slots, then preview set_component_materials.")

    def transform_rule(rule):
        return {"properties": {"placement": {"properties": {"transform": rule}}}}
    computed = {"anyOf": [{"required": ["attachTo"]}, {"required": ["seatAt"]}]}
    variants[-1]["allOf"] = [
        {"if": computed,
         "then": {"not": {"required": ["orientation"]},
                  **transform_rule({"type": "object",
                                    "not": {"anyOf": [{"required": ["position"]}, {"required": ["quaternion"]}]}})},
         "else": transform_rule({"required": ["position"]})},
        {"if": {"not": {"anyOf": [{"required": ["orientation"]}, computed]}}, "then": transform_rule({"required": ["quaternion"]})},
        {"if": {"required": ["orientation"]}, "then": transform_rule({"not": {"required": ["quaternion"]}})},
        {"not": {"required": ["attachTo", "seatAt"]}}]
    # After place_asset's rules above, which attach to the last variant defined.
    array_placement = entity_shape("placement", "placementId")
    array_placement["properties"].pop("placementId", None)
    array_placement["properties"]["componentMaterials"] = {"type": "null"}
    operation("place_asset_array", {"arrayId": text(60, pattern="^[a-z0-9][a-z0-9-]{0,59}$"),
              "placement": array_placement,
              "step": obj({"x": number(-1000, 1000), "y": number(-1000, 1000), "z": number(-1000, 1000)}, ["x", "z"]),
              "count": {"type": "integer", "minimum": 1, "maximum": 200}}, ["arrayId", "placement", "step", "count"],
              "A straight row of count copies of one placement (rack bays, parked cars), each step metres on from the "
              "last. Ids are pl-<arrayId>-001 onward; placing the same arrayId again replaces that row. Give "
              "placement.transform with the first copy's position and its quaternion.")
    operation("delete_asset_array", {"arrayId": text(60, pattern="^[a-z0-9][a-z0-9-]{0,59}$")}, ["arrayId"],
              "Remove a whole row placed by place_asset_array.")
    operation("move_placement", {"placementId": ref("placementId"), "position": ref("vector3"),
                                "movementKind": {"enum": ["user", "automatic"]}}, ["placementId", "position"])
    operation("rotate_placement", {"placementId": ref("placementId"), "quaternion": ref("quaternion"),
                                  "orientation": orientation, "movementKind": {"enum": ["user", "automatic"]}},
              ["placementId"], "Give quaternion or orientation. " + orientation_help)
    variants[-1]["oneOf"] = [{"required": ["quaternion"]}, {"required": ["orientation"]}]
    operation("duplicate_placement", {"sourcePlacementId": ref("placementId"), "newPlacementId": ref("placementId"),
        "positionMode": POSITION_MODE, "transform": placement["transform"], "position": ref("vector3"),
        "quaternion": ref("quaternion"), "snapRelationship": placement["snapRelationship"]}, ["sourcePlacementId"])
    operation("delete_placement", {"placementId": ref("placementId")})
    operation("set_position_mode", {"placementId": ref("placementId"), "positionMode": POSITION_MODE})
    operation("set_snap_relationship", {"placementId": ref("placementId"), "snapRelationship": placement["snapRelationship"]})
    operation("replace_asset", {"placementId": ref("placementId"), "assetId": ref("stableId"),
        "assetDefinitionRevision": ref("revision"), "keepAppearance": {"type": "boolean"}},
        ["placementId", "assetId", "assetDefinitionRevision"])
    operation("set_appearance", {"placementIds": array(ref("placementId"), 50, 1, uniqueItems=True), "color": nullable(COLOR),
              "appearance": nullable(ref("facilityAppearance"))}, ["placementIds"],
              "Give exactly one of color (a plain color) or appearance (a finish from list_facility_library, plus only the "
              "adjustments you need, such as grain or sizeMeters). Null in either resets to the asset's own finish. "
              "Finishes are visual only and never change the asset's engineering material.")
    variants[-1]["oneOf"] = [{"required": ["color"]}, {"required": ["appearance"]}]
    operation("set_component_materials", {"placementId": ref("placementId"),
        "materials": nullable(placement["componentMaterials"]), "visualSha256": HEX_ID}, ["placementId", "materials"],
        "For nonnull materials supply the exact visualSha256 from inspect_facility_components. Preserve unrelated overrides. "
        "A part can take a plain finish (color, roughness, metalness) or a library finish (appearanceId).")
    variants[-1]["allOf"] = [{"if": {"properties": {"materials": {"not": {"type": "null"}}}},
                               "then": {"required": ["visualSha256"]}}]
    from ai_inspector.facility_layout.appearance_library import load_library
    adjustments = obj({"exposure": number(0, 5), "environmentIntensity": number(0, 5), "ambient": number(0, 5),
                       "directional": number(0, 5), "shadows": {"type": "boolean"},
                       "environmentRotationDegrees": number(-360, 360),
                       "background": {"anyOf": [{"enum": ["theme", "environment"]}, COLOR]}}, [])
    operation("set_scene", {"scene": nullable(obj({"version": {"const": 1},
              "sceneId": {"enum": sorted(load_library()["scenes"])}, "adjustments": adjustments}, ["version", "sceneId"]))},
              description="Choose the viewport scene saved with this layout: background, lighting, reflections and shadows. "
                          "It never moves or changes equipment. Null restores the Classic scene.")
    operation("rename_layout", {"displayName": ref("label")})
    for name, key, definition, reset in (("set_floor_surfaces", "surfaces", "floorSurfaces", False),
            ("set_interior_walls", "walls", "interiorWalls", False), ("set_perimeter_walls", "wallSettings", "perimeterWalls", True),
            ("set_ground", "ground", "ground", True), ("set_decals", "decals", "decals", False),
            ("set_plan_settings", "planSettings", "planSettings", False)):
        operation(name, {key: nullable(ref(definition)) if reset else ref(definition)},
                  description="Replaces this complete settings collection, not a merge. Include unchanged records to preserve them.")
    for name, key, definition, collection, identity in (
            ("floor_surface", "surface", "floorSurfaces", "surfaces", "surfaceId"),
            ("interior_wall", "wall", "interiorWalls", "walls", "wallId"),
            ("decal", "decal", "decals", "artworks", "artworkId")):
        row = definitions[definition]["properties"][collection]["items"]
        description = "Create or replace this exact row; preserve all other records."
        if name == "floor_surface":
            description += (" Floor finishes cannot overlap and elevation must equal the existing floor/ground. "
                "Do not layer finishes using tiny elevation offsets. Split an apron into nonoverlapping polygons; "
                "use floor markings for painted overlays on a finish.")
        operation("upsert_" + name, {key: deepcopy(row)}, description=description)
        operation("delete_" + name, {identity: deepcopy(row["properties"][identity])})
    wall_patch = deepcopy(definitions["perimeterWalls"]["oneOf"][1])
    wall_patch["required"], wall_patch["minProperties"] = [], 1
    wall_patch["properties"]["boundarySource"] = {"enum": ["plan", "polygon"]}
    wall_patch["properties"]["exteriorFinish"]["required"] = []
    operation("edit_perimeter_walls", {"patch": wall_patch},
              description="Merge settings and exteriorFinish fields. Unmentioned artwork and openings are preserved; arrays replace.")
    finish = wall_patch["properties"]["exteriorFinish"]["properties"]
    operation("upsert_wall_artwork", {"collection": {"enum": ["artworks", "fittedArtworks"]},
        "artwork": {"oneOf": [deepcopy(finish[key]["items"]) for key in ("artworks", "fittedArtworks")]}})
    variants[-1]["allOf"] = [{"if": {"properties": {"collection": {"const": key}}},
                              "then": {"properties": {"artwork": deepcopy(finish[key]["items"])}}}
                             for key in ("artworks", "fittedArtworks")]
    operation("delete_wall_artwork", {"collection": {"enum": ["artworks", "fittedArtworks"]}, "artworkId": ART_ID})
    aisle_properties = {"label": ref("label"), "aisleKind": {"enum": ["forklift", "pedestrian", "material"]},
        "centerline": array(ref("vector3"), 2048, 2), "corridorWidth": {"type": "number", "exclusiveMinimum": 0, "maximum": 1000},
        "direction": {"enum": ["one_way", "two_way"]}, "color": COLOR,
        "routingMode": {"enum": ["orthogonal", "polyline", "vehicle"]},
        "clearanceEvidenceStatus": {"enum": ["authored", "derived", "inferred", "unknown", "unverified"]},
        "sourceZoneId": nullable(ref("zoneId")), "targetZoneId": nullable(ref("zoneId")),
        "viaZoneIds": array(ref("zoneId"), 50, uniqueItems=True), "areaAccounting": {"const": "overlay"},
        "widthAuthority": {"enum": ["user_authored", "policy_authored", "unknown"]},
        "vehicleProfileRef": nullable(ref("vehicleProfileRef")),
        "sourceRevisions": definitions["route"]["properties"]["sourceRevisions"],
        "sweptEnvelope": nullable(definitions["route"]["properties"]["sweptEnvelope"])}
    operation("add_aisle", {"routeId": ref("routeId"), "aisle": obj(aisle_properties,
        ["label", "aisleKind", "centerline", "corridorWidth"])}, ["aisle"])
    operation("edit_aisle", {"routeId": ref("routeId"), "patch": obj(aisle_properties, [], minProperties=1)})
    schema = obj({"operations": array({"oneOf": variants}, 50, 1)})
    # Include only reachable definitions; every ref stays local and offline.
    selected = {}
    def collect(value):
        if isinstance(value, dict):
            target = value.get("$ref", "")
            if target.startswith("#/$defs/") and target[8:] not in selected:
                selected[target[8:]] = deepcopy(definitions[target[8:]])
                collect(selected[target[8:]])
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
    collect(schema)
    schema["$defs"] = selected
    return schema
