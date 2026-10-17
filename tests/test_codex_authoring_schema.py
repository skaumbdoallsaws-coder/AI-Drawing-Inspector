import asyncio
from copy import deepcopy
import os

import pytest
from jsonschema import Draft202012Validator

from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
from ai_inspector.codex_runtime.edit_schemas import operation_batch_schema
from ai_inspector.facility_layout.operation_proposals import ALLOWED_OPERATIONS
from tests.test_codex_assisted_tools import setup


def errors(operation):
    return list(Draft202012Validator(operation_batch_schema()).iter_errors({"operations": [operation]}))


def test_schema_matches_backend_authority_and_has_no_native_execution():
    schema = operation_batch_schema()
    Draft202012Validator.check_schema(schema)
    variants = schema["properties"]["operations"]["items"]["oneOf"]
    names = {item["properties"]["op"]["const"] for item in variants}
    assert names == ALLOWED_OPERATIONS
    assert len(names) == len(variants)
    for name in ("clear_layout", "archive_layout", "set_facility_navigation", "execute_python", "save"):
        assert errors({"op": name})


def test_saved_ids_are_optional_only_when_the_kernel_generates_them():
    placement = {"assetId":"asset-test", "assetDefinitionRevision":"a"*64, "positionMode":"manual",
        "transform":{"position":{"x":0,"y":0,"z":0},"quaternion":{"x":0,"y":0,"z":0,"w":1},"scale":1},
        "snapRelationship":None,"metadata":{}}
    zone = {"zoneType":"workcell","label":"Cell","boundary":[{"x":0,"z":0},{"x":10,"z":0},{"x":10,"z":8}],
        "floorElevation":0,"anchors":[],"evidence":[]}
    for key, row, op in (("placement", placement, "place_asset"), ("zone", zone, "add_zone")):
        assert not errors({"op": op, key: row})
    placement["componentMaterials"] = {"representation":"overview","overrides":[]}
    assert errors({"op":"place_asset","placement":placement})
    assert errors({"op": "edit_zone", "patch": {"label": "No identity"}})


@pytest.mark.parametrize("op", [
    {"op": "edit_perimeter_walls", "patch": {"interiorColor": "#35393E"}},
    {"op": "edit_perimeter_walls", "patch": {"exteriorFinish": {"jointColor": "#C99B39"}}},
    {"op": "delete_floor_surface", "surfaceId": "fs-cardio"},
    {"op": "delete_interior_wall", "wallId": "iw-office"},
    {"op": "delete_decal", "artworkId": "lettering"},
    {"op": "delete_wall_artwork", "collection": "fittedArtworks", "artworkId": "lettering"},
    {"op": "upsert_floor_surface", "surface": {"surfaceId": "fs-cardio", "label": "Cardio",
        "boundary": [{"x":0,"z":0},{"x":10,"z":0},{"x":10,"z":8},{"x":0,"z":8}],
        "elevation": 0, "material": "rubber", "color": "#35393E", "roughness": .85}},
    {"op": "upsert_interior_wall", "wall": {"wallId": "iw-office", "label": "Office",
        "start": {"x":0,"z":0}, "end": {"x":10,"z":0}, "heightMeters": 3,
        "thicknessMeters": .2, "baseElevation": 0, "color": "#35393E", "openings": []}},
    {"op": "upsert_decal", "decal": {"artworkId": "lettering", "label": "Lettering",
        "imagePath": "/api/facility-decal-images/site-local/" + "a"*64 + ".png", "uv": [0,0,1,1],
        "target": {"wallId": "iw-office", "side": "left"}, "region": [0,0,1,1], "coverage": .95}},
])
def test_targeted_operations_are_exposed_with_closed_contracts(op):
    assert not errors(op)
    assert errors(dict(op, approved=True))


def test_material_proof_is_required_for_changes_not_reset():
    op = {"op": "set_component_materials", "placementId": "pl-test", "materials": {
        "representation": "overview", "overrides": [{"key": "m0-s0", "color": "#C99B39",
        "metalness": .5, "roughness": .5}]}}
    assert errors(op)
    assert not errors(dict(op, visualSha256="a"*64))
    assert errors(dict(op, visualSha256="A"*64))
    assert not errors(dict(op, materials=None))


def test_cell_groups_use_closed_metadata():
    op = {"op": "edit_zone", "zoneId": "zn-test", "patch": {"extensions": {
        "cellGroup": {"schemaVersion":1, "groupKind":"manufacturing_cell", "membership":"geometric",
        "envelopePadding":0, "autoNumber":{"seriesId":"series-test","baseName":"Cell","prefix":"",
        "start":1,"sequence":1,"padding":2}, "functionalInterfaces":{"gate":{"side":"north","evidenceStatus":"authored"}}}}}}
    assert not errors(op)
    op["patch"]["extensions"]["cellGroup"]["placementIds"] = ["pl-fake"]
    assert errors(op)


@pytest.mark.skipif(os.name != "nt", reason="Windows desktop font fixture")
def test_lettering_tool_is_wired_and_creates_no_layout_edit(setup):
    host, gateway, saved = setup
    assert isinstance(gateway, FacilityEditGateway)
    result = asyncio.run(gateway.call("prepare_facility_lettering", {"aspectRatio":3,
        "lettering":{"text":"TRAIN. RECOVER. RISE.","reference":"APEX","font":"Arial","align":"center","color":"#C99B39"}}))
    assert result["ok"], result
    assert result["data"]["engineeringChanges"] == 0 and result["data"]["saved"] is False
    assert result["data"]["imagePath"].startswith("/api/facility-decal-images/site-local/")
    assert host.service.get_layout(host.principal(), gateway.reference["siteId"], gateway.reference["layoutId"]) == saved
