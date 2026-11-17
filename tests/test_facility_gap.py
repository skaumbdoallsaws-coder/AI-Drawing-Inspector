"""MB5c gap geometry: facing edges, real obstructions, and bounded read contract."""
import math
import asyncio
from types import SimpleNamespace

import pytest

from ai_inspector.codex_runtime.facility_gap import measure, tool_spec
from ai_inspector.codex_runtime.policy import PilotError

REF = {"siteId": "site", "layoutId": "layout", "revision": "a" * 64}


def column(identifier, x, z=0):
    return {"columnId": identifier, "shape": "rectangle", "center": {"x": x, "z": z},
            "widthMeters": 1, "depthMeters": 1, "rotationDegrees": 0}


def marking(identifier, x, z, width=1, depth=1):
    return {"markingId": identifier, "transform": {"position": {"x": x, "y": 0, "z": z},
            "rotationDegrees": 0}, "width": width, "depth": depth}


def zone(identifier, x0, x1, z0, z1, height=None):
    return {"zoneId": identifier, "boundary": [{"x": x, "z": z} for x, z in
            ((x0, z0), (x1, z0), (x1, z1), (x0, z1))],
            **({"heightLimit": height} if height is not None else {})}


def runtime(*, columns=(), markings=(), zones=(), placements=(), features=()):
    layout = {"extensions": {"facilityColumns": {"columns": list(columns)}},
              "floorMarkings": list(markings), "zones": list(zones), "placements": list(placements)}
    bundle = SimpleNamespace(layout_document=layout, shell_document={"features": list(features)})
    asset = {"geometry": {"footprintPolygons": [[{"x": x, "z": z} for x, z in
              ((-.5, -.5), (.5, -.5), (.5, .5), (-.5, .5))]],
              "heightInterval": {"minimumY": 0, "maximumY": 1}}}
    service = SimpleNamespace(_resolve_asset_definition=lambda *_: asset)
    return SimpleNamespace(resolve_context=lambda *_args, **_kwargs: bundle, service=service)


def call(source, from_ref=None, to_ref=None, **extra):
    return measure(source, None, REF, {"from": from_ref or {"kind": "column", "id": "col-a"},
                                       "to": to_ref or {"kind": "column", "id": "col-b"}, **extra})


def test_two_columns_have_a_clear_gap_and_boundary_contact_is_allowed():
    source = runtime(columns=[column("col-a", 0), column("col-b", 3)],
                     markings=[marking("fm-touch", 1.5, 1)])
    result = call(source)
    assert result["clear"] and result["width"] == pytest.approx(2)
    assert result["depth"] == pytest.approx(1) and result["orientation"] == pytest.approx(0)
    assert result["revision"] == REF["revision"] and len(result["corners"]) == 4


def test_marking_and_placement_intrusion_are_reported_not_shrunk():
    placed = {"placementId": "pl-obstacle", "assetId": "asset-box", "assetDefinitionRevision": "b"*64,
              "transform": {"position": {"x": 1.5, "y": 0, "z": 0},
                            "quaternion": {"w": 1, "x": 0, "y": 0, "z": 0}, "scale": 1}}
    source = runtime(columns=[column("col-a", 0), column("col-b", 3)],
                     markings=[marking("fm-obstacle", 1.5, 0, .2, .2)], placements=[placed])
    result = call(source)
    assert not result["clear"] and result["width"] == pytest.approx(2)
    assert result["obstructions"] == [{"kind": "marking", "id": "fm-obstacle"},
                                      {"kind": "placement", "id": "pl-obstacle"}]


def test_nonoverlapping_references_need_a_zone_region():
    source = runtime(columns=[column("col-a", 0, 0), column("col-b", 3, 3)],
                     zones=[zone("zn-region", .5, 2.5, -1, 4, height=2.5)])
    refs = ({"kind": "column", "id": "col-a", "edge": "+x"},
            {"kind": "column", "id": "col-b", "edge": "-x"})
    with pytest.raises(PilotError):
        call(source, *refs)
    result = call(source, *refs, region="zn-region", depth=2)
    assert result["width"] == pytest.approx(2) and result["depth"] == pytest.approx(2)
    assert result["heightLimit"] == 2.5


def test_wall_and_zone_edges_and_rotated_placements():
    feature = {"featureId": "wall-east", "featureKind": "wall", "geometry": {
        "boundary": [{"x": x, "z": z} for x, z in ((0, -.5), (.5, -.5), (.5, .5), (0, .5))]}}
    source = runtime(columns=[column("col-b", 3)], features=[feature],
                     zones=[zone("zn-left", -2, .5, -.5, .5)])
    wall = call(source, {"kind": "perimeter_wall", "id": "wall-east", "edge": "+x"},
                {"kind": "column", "id": "col-b"})
    assert wall["width"] == pytest.approx(2)
    edge = call(source, {"kind": "zone", "id": "zn-left", "edge": "+x"},
                {"kind": "column", "id": "col-b"})
    assert edge["width"] == pytest.approx(2)
    yaw = math.pi/4
    placements = [{"placementId": identifier, "assetId": "asset-box", "assetDefinitionRevision": "b"*64,
                   "transform": {"position": {"x": distance*math.cos(yaw), "y": 0,
                                              "z": -distance*math.sin(yaw)},
                                 "quaternion": {"w": math.cos(yaw/2), "x": 0,
                                                "y": math.sin(yaw/2), "z": 0}, "scale": 1}}
                  for identifier, distance in (("pl-a", 0), ("pl-b", 3))]
    rotated = call(runtime(placements=placements), {"kind": "placement", "id": "pl-a"},
                   {"kind": "placement", "id": "pl-b"})
    assert rotated["width"] == pytest.approx(2) and abs(rotated["orientation"]) == pytest.approx(45)


def test_tool_schema_requires_wall_and_zone_edges():
    from jsonschema import Draft202012Validator
    validator = Draft202012Validator(tool_spec()["input_schema"])
    assert not list(validator.iter_errors({"from": {"kind": "zone", "id": "zn-a", "edge": "+x"},
                                           "to": {"kind": "column", "id": "col-b"}}))
    assert list(validator.iter_errors({"from": {"kind": "zone", "id": "zn-a"},
                                       "to": {"kind": "column", "id": "col-b"}}))


def test_gateway_exposes_a_revision_bound_read_without_builder_budget(tmp_path, monkeypatch):
    from ai_inspector.codex_runtime.facility_tools import FacilityReadGateway
    from ai_inspector.facility_layout.host import LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    try:
        host.ensure_bootstrap()
        principal = host.principal()
        saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
        reference = {"siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved["revision"]}
        gateway = FacilityReadGateway(host.agent_runtime, principal, reference, turn_id="gap-test")
        source = runtime(columns=[column("col-a", 0), column("col-b", 3)])
        monkeypatch.setattr(host.agent_runtime, "resolve_context", source.resolve_context)
        answer = asyncio.run(gateway.call("measure_facility_gap", {"from": {"kind": "column", "id": "col-a"},
                                                              "to": {"kind": "column", "id": "col-b"}}))
        assert answer["ok"] and answer["data"]["width"] == 2
        assert "turnRemaining" not in answer
    finally:
        host.close()


def test_fits_within_is_portable_and_deducted_only_by_the_caller():
    from ai_inspector.industrial_assets.model_builder.recipe import normalize_recipe, portable_recipe
    from ai_inspector.industrial_assets.model_builder.build import build_model
    from tests.model_builder_test_support import recipe
    raw = recipe(fitsWithin={"width": .8, "depth": .8, "orientation": 30, "basis": "measured",
                             "clearances": {"sides": .1, "front": .1, "back": .1}})
    normal = normalize_recipe(raw, allowed_categories=["Material Handling"], allowed_appearance_ids=[])
    assert portable_recipe(normal)[0]["fitsWithin"] == normal["fitsWithin"]
    built = build_model(normal, allowed_categories=["Material Handling"], allowed_appearance_ids=[])
    assert any(item["code"] == "fit_exceeded" for item in built.lints)


def test_a_rotated_marking_turns_the_way_the_app_draws_it():
    # Thin 2 m marking at (2.2, 0.9) turned 30 degrees. The app (circulation.py) turns local +x toward +z, so its
    # low end reaches (1.33, 0.4), 0.1 m inside the gap (x 0.5..2.5, z -0.5..0.5). Turned the other way it would
    # stay clear of the gap.
    from ai_inspector.facility_layout.circulation import _floor_marking_polygon
    tilted = {"markingId": "fm-tilted", "transform": {"position": {"x": 2.2, "y": 0, "z": 0.9},
              "rotationDegrees": 30}, "width": 2.0, "depth": 0.05}
    assert _floor_marking_polygon(tilted).bounds[1] == pytest.approx(0.4 - 0.025 * math.cos(math.radians(30)), abs=1e-3)
    result = call(runtime(columns=[column("col-a", 0), column("col-b", 3)], markings=[tilted]))
    assert not result["clear"] and result["obstructions"] == [{"kind": "marking", "id": "fm-tilted"}]
