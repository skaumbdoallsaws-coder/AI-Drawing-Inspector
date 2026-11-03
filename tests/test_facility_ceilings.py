"""Zone ceilings that lamps hang from (ceilings.py): the Private Gym's table pendants, 2026-11-02.

A pendant placed with its base at 1.7 m failed unsupported_mounting_surface: the gym's shell has only a floor. Now a
zone may have a ceiling, the checks see it as a "ceiling" mounting surface, and a hung item whose top meets it, inside
the zone, is accepted; collisions with the table below stay 3D.

Later the same day: a ceiling may name a finish (how the 3D view draws it), and a zone may have a roof
(set_zone_roof, the 3D view only).
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.plan_settings import shell_with_plan_boundary
from ai_inspector.facility_layout.spatial import diagnose_layout
from ai_inspector.facility_layout.validate import validate_layout

FIXTURES = Path(__file__).parent / "fixtures" / "facility_layout"
CEILING = 3.2


def box(asset_id, width, depth, height, mounting=("floor",)):
    half_w, half_d = width / 2, depth / 2
    footprint = [{"x": -half_w, "z": -half_d}, {"x": half_w, "z": -half_d},
                 {"x": half_w, "z": half_d}, {"x": -half_w, "z": half_d}]
    return {"assetId": asset_id, "category": "workstation",
            "coordinateFrame": {"allowedMountingSurfaces": list(mounting), "floorAnchor": {"x": 0, "y": 0, "z": 0}},
            "geometry": {"footprintPolygons": [footprint], "heightInterval": {"minimumY": 0, "maximumY": height}},
            "collision": {"geometry": {"footprintIndex": 0}, "verticalInterval": {"minimumY": 0, "maximumY": height}},
            "clearances": []}


# Scratch stand-ins for the gym's assets: a table, a dome pendant that only hangs, a bar pendant that may also stand.
ASSETS = [box("asset-test-table", 2.4, 1.2, 0.75),
          box("asset-test-pendant-dome", 0.455, 0.455, 1.3, ("ceiling",)),
          box("asset-test-pendant-bar", 1.56, 0.344, 1.2, ("floor", "ceiling")),
          box("asset-test-downlight", 0.15, 0.15, 0.015, ("ceiling",))]
HANGS = {"surfaceKind": "ceiling"}


def placement(placement_id, asset_id, x, z, y=0.0, metadata=None):
    return {"placementId": placement_id, "assetId": asset_id, "assetDefinitionRevision": "a" * 64,
            "transform": {"position": {"x": x, "y": y, "z": z}, "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1},
                          "scale": 1},
            "positionMode": "manual", "snapRelationship": None, "metadata": metadata or {}}


def rectangle(x0, z0, x1, z1):
    return [{"x": x0, "z": z0}, {"x": x1, "z": z0}, {"x": x1, "z": z1}, {"x": x0, "z": z1}]


def scene(ceiling=CEILING):
    """The spatial golden floor (20 x 20 m) as a cell (x 0-10) and a lounge (x 10-20) with a ceiling, a table in it."""
    golden = json.loads((FIXTURES / "spatial" / "golden_scenarios.json").read_text(encoding="ascii"))
    layout = deepcopy(golden["baseLayout"])
    layout["zones"][0]["boundary"] = rectangle(0, 0, 10, 20)
    layout["zones"].append({"zoneId": "zn-lounge", "zoneType": "workcell", "label": "Lounge",
                            "boundary": rectangle(10, 0, 20, 20), "floorElevation": 0.0, "anchors": [], "evidence": []})
    if ceiling is not None:
        # As set_zone_ceiling saves it (that operation is tested on a whole layout below).
        layout["zones"][1]["extensions"] = {"ceiling": {"heightMeters": ceiling}}
    layout["placements"] = [placement("pl-table", "asset-test-table", 15, 10)]
    return golden["shell"], layout


def errors(shell, layout, *hung):
    layout = deepcopy(layout)
    layout["placements"] += list(hung)
    result = diagnose_layout(layout, ASSETS, shell=shell_with_plan_boundary(shell, layout))
    return [(item["code"], item["message"]) for item in result["findings"] if item["severity"] == "error"]


def test_a_lamp_hangs_from_the_zone_ceiling_over_a_table():
    shell, layout = scene()
    # Its top meets the 3.2 m ceiling: the dome (1.3 m) from 1.9 m, the bar (1.2 m) from 2.0 m, both over the table.
    dome = placement("pl-dome", "asset-test-pendant-dome", 15, 10, y=CEILING - 1.3)
    bar = placement("pl-bar", "asset-test-pendant-bar", 15, 10.4, y=CEILING - 1.2, metadata={"mountingSurface": HANGS})
    assert errors(shell, layout, dome, bar) == [], "no mounting error, no collision with the table below"
    # The checks see the ceiling as a mounting surface the size of the zone; the shell authority is untouched.
    effective = shell_with_plan_boundary(shell, layout)
    ceiling = next(f for f in effective["features"] if f["featureId"] == "layout-ceiling-zn-lounge")
    assert (ceiling["featureKind"], ceiling["surfaceKind"], ceiling["geometry"]["elevation"]) == (
        "mounting_surface", "ceiling", CEILING)
    assert ceiling["geometry"]["boundary"] == rectangle(10, 0, 20, 20)
    assert not any(f["featureId"].startswith("layout-ceiling-") for f in shell["features"])
    # A ceiling over a raised zone floor counts from that floor.
    layout["zones"][1]["floorElevation"] = 0.5
    assert errors(shell, layout, dict(dome, transform=dict(dome["transform"], position={"x": 15, "y": 2.4, "z": 10}))) == []


def test_thin_recessed_downlights_sit_flush_with_the_ceiling():
    # The gym lounge's downlights: 0.015 m thin, the base at 3.185 m so the top meets 3.2 m; 28 at 3 m spacing.
    shell, layout = scene()
    lights = [placement(f"pl-down-{index:02d}", "asset-test-downlight", 10.5 + 3 * (index % 4), 1 + 3 * (index // 4),
                        y=CEILING - 0.015) for index in range(28)]
    assert errors(shell, layout, *lights) == []
    # 1 mm low, it is refused like any lamp off its ceiling.
    low = dict(lights[0], transform=dict(lights[0]["transform"], position={"x": 10.5, "y": 3.184, "z": 1}))
    assert [code for code, _ in errors(shell, layout, low)] == ["unsupported_mounting_surface"]


def test_a_catalog_asset_without_mounting_fields_hangs_when_its_placement_says_so():
    # Like the gym's: a private-manifest asset (no allowedMountingSurfaces, no floorAnchor) on a layout with a ground.
    from ai_inspector.facility_layout.host import _asset
    pendant = _asset(asset_id="asset-test-manifest-pendant", display_name="Test pendant", category="Lighting",
                     width=0.455, depth=0.455, height=1.3, description="Scratch pendant.")["definition"]
    assert "allowedMountingSurfaces" not in json.dumps(pendant)
    shell, layout = scene()
    layout["extensions"] = {"facilityGround": {"schemaVersion": 1, "surfaces": [
        {"surfaceId": "floor", "minX": 0, "maxX": 20, "minZ": 0, "maxZ": 20, "startElevation": 0, "endElevation": 0,
         "slopeAxis": "x", "color": "#808080"}]}}
    hung = placement("pl-dome", "asset-test-manifest-pendant", 15, 10, y=1.9, metadata={"mountingSurface": HANGS})

    def found(item):
        result = diagnose_layout(dict(layout, placements=layout["placements"] + [item]), ASSETS + [pendant],
                                 shell=shell_with_plan_boundary(shell, layout))
        return [entry["message"] for entry in result["findings"] if entry["severity"] == "error"]

    assert found(hung) == []
    # Without the placement's mountingSurface it stands on the ground: the 1.7 m failure the gym saw.
    assert found(dict(hung, metadata={})) == [
        "Placement requires one continuous, level ground surface at its support elevation."]


@pytest.mark.parametrize("case, message", [
    ("too low", "top does not meet its ceiling"),
    ("too high", "top does not meet its ceiling"),
    ("in the cell", "outside the requested mounting surface"),
    ("across the zone edge", "outside the requested mounting surface"),
    ("no ceiling", "does not exist in the Facility Shell"),
    ("bar without metadata", "does not coincide with its mounting surface"),
])
def test_a_hung_lamp_off_its_ceiling_is_refused(case, message):
    shell, layout = scene(None if case == "no ceiling" else CEILING)
    x, y = {"too low": (15, 1.7), "too high": (15, 2.0), "in the cell": (5, 1.9),
            "across the zone edge": (10.1, 1.9)}.get(case, (15, 1.9))
    if case == "bar without metadata":
        # An asset that may also stand on the floor stands unless the placement says it hangs.
        lamp = placement("pl-bar", "asset-test-pendant-bar", 15, 12, y=2.0)
    else:
        lamp = placement("pl-dome", "asset-test-pendant-dome", x, 12, y=y)
    found = errors(shell, layout, lamp)
    # Across the edge it is not inside one zone either.
    expected = ["unsupported_mounting_surface"] + (["zone_containment_violation"] if "edge" in case else [])
    assert [code for code, _ in found] == expected, found
    assert message in dict(found)["unsupported_mounting_surface"]


def test_collisions_with_the_table_below_stay_3d():
    # A 2 m ceiling hangs the dome down to 0.7 m, into the 0.75 m table: that is a collision, as before.
    shell, layout = scene(2.0)
    low = placement("pl-dome", "asset-test-pendant-dome", 15, 10, y=2.0 - 1.3)
    assert errors(shell, layout, low) == [("placement_collision", "Placement collision volumes overlap.")]
    # Beside the table at the same height, no collision.
    assert errors(shell, layout, dict(low, transform=dict(low["transform"], position={"x": 17.5, "y": 0.7, "z": 10}))) == []


def test_set_zone_ceiling_sets_changes_and_clears_it():
    layout = json.loads((FIXTURES / "empty_cell.json").read_text())
    zone = {"zoneId": "zn-lounge", "zoneType": "workcell", "label": "Lounge", "boundary": rectangle(0, 0, 6, 4),
            "floorElevation": 0.0, "anchors": [], "evidence": []}

    def run(doc, *operations):
        result = apply_facility_layout_operations(doc, list(operations))
        validate_layout(result["document"])
        return result

    done = run(layout, {"op": "add_zone", "zone": zone},
               {"op": "set_zone_ceiling", "zoneId": "zn-lounge", "heightMeters": 3.2})
    doc = done["document"]
    assert doc["zones"][0]["extensions"] == {"ceiling": {"heightMeters": 3.2}}
    assert done["operationResults"][1] == {"index": 1, "op": "set_zone_ceiling", "createdIds": [],
                                           "affectedIds": ["zn-lounge"]}
    doc = run(doc, {"op": "set_zone_ceiling", "zoneId": "zn-lounge", "heightMeters": 3.25})["document"]
    assert doc["zones"][0]["extensions"] == {"ceiling": {"heightMeters": 3.25}}
    # Clearing keeps the zone's other extensions and drops an empty one.
    kept = deepcopy(doc)
    kept["zones"][0]["extensions"]["note"] = {"x": 1}
    kept = run(kept, {"op": "set_zone_ceiling", "zoneId": "zn-lounge", "heightMeters": None})["document"]
    assert kept["zones"][0]["extensions"] == {"note": {"x": 1}}
    doc = run(doc, {"op": "set_zone_ceiling", "zoneId": "zn-lounge", "heightMeters": None})["document"]
    assert "extensions" not in doc["zones"][0]
    for bad, text in (({"heightMeters": 1.5}, "between 2 and 40"), ({"heightMeters": True}, "between 2 and 40"),
                      ({"heightMeters": 3, "label": "x"}, "Expected zoneId, heightMeters"),
                      ({"zoneId": "zn-missing", "heightMeters": 3}, "Zone")):
        with pytest.raises(FacilityLayoutError, match=text):
            apply_facility_layout_operations(doc, [dict({"op": "set_zone_ceiling", "zoneId": "zn-lounge"}, **bad)])
    # A saved ceiling out of range is refused on save, too.
    saved = deepcopy(doc)
    saved["zones"][0]["extensions"] = {"ceiling": {"heightMeters": 100}}
    with pytest.raises(FacilityLayoutError, match="between 2 and 40"):
        validate_layout(saved)


def test_sage_can_set_a_ceiling_and_is_told_how_to_hang_a_lamp():
    from jsonschema import Draft202012Validator
    from ai_inspector.codex_runtime.edit_schemas import operation_batch_schema
    from ai_inspector.facility_layout.operation_proposals import guard_operations
    schema = operation_batch_schema()
    validator = Draft202012Validator(schema)
    for height in (3.2, None):
        operations = [{"op": "set_zone_ceiling", "zoneId": "zn-lounge", "heightMeters": height}]
        assert not list(validator.iter_errors({"operations": operations}))
        guard_operations(operations)
    assert list(validator.iter_errors({"operations": [{"op": "set_zone_ceiling", "zoneId": "zn-lounge",
                                                       "heightMeters": 1}]}))
    variant = next(v for v in schema["properties"]["operations"]["items"]["oneOf"]
                   if v["properties"]["op"].get("const") == "set_zone_ceiling")
    assert "metadata.mountingSurface {surfaceKind: 'ceiling'}" in variant["description"]
    assert "allowedMountingSurfaces includes 'ceiling'" in variant["description"]


def test_a_sage_preview_of_a_ceiling_and_a_hung_lamp_is_accepted_and_saves(tmp_path):
    # Sage's own path (operation_proposals.create, the same checks a save runs): the ceiling, a table and a lamp over
    # it in one preview, with no error, then approved and saved. The catalog's workbench stands in for both.
    from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, LOCAL_SITE_ID, LOCAL_LAYOUT_ID
    from ai_inspector.facility_layout.operation_proposals import create
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    try:
        service, principal = host.service, host.principal()
        bench = next(item for item in host.ensure_bootstrap()["assetCatalog"] if item["assetId"] == "asset-workbench")

        def place(placement_id, y, metadata):
            return {"op": "place_asset", "placement": {
                "placementId": placement_id, "assetId": "asset-workbench",
                "assetDefinitionRevision": bench["assetDefinitionRevision"],
                "transform": {"position": {"x": 5, "y": y, "z": 5}, "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1},
                              "scale": 1},
                "positionMode": "manual", "snapRelationship": None, "metadata": metadata}}

        operations = [
            {"op": "add_zone", "zoneId": "zn-lounge", "zone": {
                "label": "Lounge", "zoneType": "workcell", "anchors": [], "evidence": [], "floorElevation": 0,
                "boundary": rectangle(0, 0, 10, 10)}},
            {"op": "set_zone_ceiling", "zoneId": "zn-lounge", "heightMeters": CEILING},
            place("pl-table", 0, {}),
            place("pl-lamp", CEILING - 1.0, {"mountingSurface": HANGS}),
        ]
        revision = service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["revision"]
        proposal = create(service, principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, revision, operations=operations)
        validation = proposal["alternative"]["validation"]
        assert validation["spatial"]["metrics"]["errorCount"] == 0, validation
        assert validation["spatial"]["metrics"]["placementCollisions"] == 0
        approval = service.approve_layout_proposal(
            principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, proposal["proposalId"],
            proposal["alternative"]["transactionBinding"], session_id="test-session", idempotency_key="ceiling-key", explicit_approval=True)
        saved = service.apply_layout_proposal(
            principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, approval["approvalToken"],
            proposal["alternative"]["transactionBinding"], session_id="test-session", idempotency_key="ceiling-key")["layout"]
        assert saved["zones"][0]["extensions"] == {"ceiling": {"heightMeters": CEILING}}
        lamp = next(item for item in saved["placements"] if item["placementId"] == "pl-lamp")
        assert lamp["transform"]["position"]["y"] == CEILING - 1.0
        assert lamp["metadata"]["mountingSurface"] == HANGS
        # 0.1 m lower, the preview is refused for the lamp's mounting, as a save would be.
        revision = service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["revision"]
        with pytest.raises(FacilityLayoutError) as refused:
            create(service, principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, revision, operations=[
                {"op": "delete_placement", "placementId": "pl-lamp"},
                place("pl-lamp", CEILING - 1.1, {"mountingSurface": HANGS})])
        assert refused.value.code == "spatial_validation_failed"
        assert "unsupported_mounting_surface" in json.dumps(refused.value.details)
    finally:
        host.close()


def _lounge_layout():
    layout = json.loads((FIXTURES / "empty_cell.json").read_text())
    zone = {"zoneId": "zn-lounge", "zoneType": "workcell", "label": "Lounge", "boundary": rectangle(0, 0, 6, 4),
            "floorElevation": 0.0, "anchors": [], "evidence": []}
    return apply_facility_layout_operations(layout, [{"op": "add_zone", "zone": zone}])["document"]


def _run(doc, *operations):
    result = apply_facility_layout_operations(doc, list(operations))
    validate_layout(result["document"])
    return result["document"]


def test_a_ceiling_finish_is_saved_with_it_and_left_out_means_charcoal():
    doc = _lounge_layout()
    for finish in ("acoustic-tile", "open-deck"):
        done = _run(doc, {"op": "set_zone_ceiling", "zoneId": "zn-lounge", "heightMeters": 3, "finish": finish})
        assert done["zones"][0]["extensions"] == {"ceiling": {"heightMeters": 3, "finish": finish}}
    # Setting it again without a finish sets the whole ceiling: no finish (drawn matte charcoal, as before).
    tiled = _run(doc, {"op": "set_zone_ceiling", "zoneId": "zn-lounge", "heightMeters": 3, "finish": "acoustic-tile"})
    plain = _run(tiled, {"op": "set_zone_ceiling", "zoneId": "zn-lounge", "heightMeters": 3.2})
    assert plain["zones"][0]["extensions"] == {"ceiling": {"heightMeters": 3.2}}
    cleared = _run(tiled, {"op": "set_zone_ceiling", "zoneId": "zn-lounge", "heightMeters": None})
    assert "extensions" not in cleared["zones"][0]
    for bad, text in (({"heightMeters": 3, "finish": "marble"}, "finish is one of: acoustic-tile, open-deck"),
                      ({"heightMeters": 3, "finish": None}, "finish is one of"),
                      ({"heightMeters": None, "finish": "open-deck"}, "alone, to remove the ceiling")):
        with pytest.raises(FacilityLayoutError, match=text):
            apply_facility_layout_operations(tiled, [dict({"op": "set_zone_ceiling", "zoneId": "zn-lounge"}, **bad)])
    saved = deepcopy(tiled)
    saved["zones"][0]["extensions"]["ceiling"]["finish"] = "wood"
    with pytest.raises(FacilityLayoutError, match="finish is one of"):
        validate_layout(saved)
    # Lamps hang from a tiled ceiling as from any other: the checks see the same mounting surface.
    shell, layout = scene()
    layout["zones"][1]["extensions"]["ceiling"]["finish"] = "acoustic-tile"
    feature = next(item for item in shell_with_plan_boundary(shell, layout)["features"]
                   if item["featureId"] == "layout-ceiling-zn-lounge")
    assert feature["geometry"]["elevation"] == CEILING
    assert errors(shell, layout, placement("pl-lamp", "asset-test-pendant-dome", 15, 10, CEILING - 1.3)) == []


def test_set_zone_roof_sets_changes_and_clears_it_beside_a_ceiling():
    doc = _run(_lounge_layout(), {"op": "set_zone_ceiling", "zoneId": "zn-lounge", "heightMeters": 3.6,
                                  "finish": "open-deck"},
               {"op": "set_zone_roof", "zoneId": "zn-lounge", "heightMeters": 3.6})
    assert doc["zones"][0]["extensions"] == {"ceiling": {"heightMeters": 3.6, "finish": "open-deck"},
                                             "roof": {"heightMeters": 3.6}}
    done = apply_facility_layout_operations(doc, [{"op": "set_zone_roof", "zoneId": "zn-lounge", "heightMeters": 4.25}])
    assert done["operationResults"][0] == {"index": 0, "op": "set_zone_roof", "createdIds": [],
                                           "affectedIds": ["zn-lounge"]}
    assert done["document"]["zones"][0]["extensions"]["roof"] == {"heightMeters": 4.25}
    # Removing the roof keeps the ceiling; removing both drops the emptied extensions.
    roofless = _run(doc, {"op": "set_zone_roof", "zoneId": "zn-lounge", "heightMeters": None})
    assert roofless["zones"][0]["extensions"] == {"ceiling": {"heightMeters": 3.6, "finish": "open-deck"}}
    bare = _run(roofless, {"op": "set_zone_ceiling", "zoneId": "zn-lounge", "heightMeters": None},
                {"op": "set_zone_roof", "zoneId": "zn-lounge", "heightMeters": None})
    assert "extensions" not in bare["zones"][0]
    for bad, text in (({"heightMeters": 1.5}, "roof's heightMeters must be between 2 and 40"),
                      ({"heightMeters": 41}, "between 2 and 40"), ({"heightMeters": "3"}, "between 2 and 40"),
                      ({"heightMeters": 3, "finish": "open-deck"}, "Expected zoneId and heightMeters"),
                      ({}, "Expected zoneId and heightMeters"),
                      ({"zoneId": "zn-missing", "heightMeters": 3}, "Zone")):
        with pytest.raises(FacilityLayoutError, match=text):
            apply_facility_layout_operations(doc, [dict({"op": "set_zone_roof", "zoneId": "zn-lounge"}, **bad)])
    for broken in ({"heightMeters": 100}, {"heightMeters": 3, "parapet": 1}, 3.6):
        saved = deepcopy(doc)
        saved["zones"][0]["extensions"]["roof"] = broken
        with pytest.raises(FacilityLayoutError, match="zone roof"):
            validate_layout(saved)
    # The checks do not see a roof: no mounting surface or other shell feature comes from it.
    shell, layout = scene(ceiling=None)
    plain = shell_with_plan_boundary(shell, layout)
    layout["zones"][1]["extensions"] = {"roof": {"heightMeters": 3.6}}
    assert shell_with_plan_boundary(shell, layout) == plain


def test_sage_can_set_a_ceiling_finish_and_a_roof():
    from jsonschema import Draft202012Validator
    from ai_inspector.codex_runtime.edit_schemas import operation_batch_schema
    from ai_inspector.facility_layout.operation_proposals import guard_operations
    schema = operation_batch_schema()
    validator = Draft202012Validator(schema)
    good = [{"op": "set_zone_ceiling", "zoneId": "zn-lounge", "heightMeters": 3, "finish": "acoustic-tile"},
            {"op": "set_zone_ceiling", "zoneId": "zn-lounge", "heightMeters": 3.6, "finish": "open-deck"},
            {"op": "set_zone_roof", "zoneId": "zn-lounge", "heightMeters": 3.6},
            {"op": "set_zone_roof", "zoneId": "zn-lounge", "heightMeters": None}]
    for operation in good:
        assert not list(validator.iter_errors({"operations": [operation]})), operation
        guard_operations([operation])
    for operation in ({"op": "set_zone_ceiling", "zoneId": "zn-lounge", "heightMeters": 3, "finish": "marble"},
                      {"op": "set_zone_roof", "zoneId": "zn-lounge", "heightMeters": 1},
                      {"op": "set_zone_roof", "zoneId": "zn-lounge"}):
        assert list(validator.iter_errors({"operations": [operation]})), operation
    variants = {v["properties"]["op"].get("const"): v for v in schema["properties"]["operations"]["items"]["oneOf"]}
    assert "'acoustic-tile' (a white suspended ceiling of 600 mm tiles)" in variants["set_zone_ceiling"]["description"]
    assert "flat commercial roof" in variants["set_zone_roof"]["description"]
    assert "roof sheeting layer" in variants["set_zone_roof"]["description"]


def test_a_sage_preview_of_a_tiled_ceiling_and_a_roof_saves(tmp_path):
    from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, LOCAL_SITE_ID, LOCAL_LAYOUT_ID
    from ai_inspector.facility_layout.operation_proposals import create
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    try:
        service, principal = host.service, host.principal()
        host.ensure_bootstrap()
        operations = [
            {"op": "add_zone", "zoneId": "zn-lounge", "zone": {
                "label": "Lounge", "zoneType": "workcell", "anchors": [], "evidence": [], "floorElevation": 0,
                "boundary": rectangle(0, 0, 10, 10)}},
            {"op": "set_zone_ceiling", "zoneId": "zn-lounge", "heightMeters": 3, "finish": "acoustic-tile"},
            {"op": "set_zone_roof", "zoneId": "zn-lounge", "heightMeters": 3.6},
        ]
        revision = service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["revision"]
        proposal = create(service, principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, revision, operations=operations)
        assert proposal["alternative"]["validation"]["spatial"]["metrics"]["errorCount"] == 0
        approval = service.approve_layout_proposal(
            principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, proposal["proposalId"],
            proposal["alternative"]["transactionBinding"], session_id="test-session", idempotency_key="roof-key",
            explicit_approval=True)
        saved = service.apply_layout_proposal(
            principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, approval["approvalToken"],
            proposal["alternative"]["transactionBinding"], session_id="test-session", idempotency_key="roof-key")["layout"]
        assert saved["zones"][0]["extensions"] == {"ceiling": {"heightMeters": 3, "finish": "acoustic-tile"},
                                                   "roof": {"heightMeters": 3.6}}
    finally:
        host.close()


# 2026-11-03: edit_zone replaced a zone's extensions whole, so a Sage recolour sending extensions {style} dropped the
# zone's ceiling and roof, and one copying the saved extensions (with them) was refused by the published schema.
STYLE = {"fillColor": "#5b8def"}
DECK = {"heightMeters": 3.6, "finish": "open-deck"}
ROOF = {"heightMeters": 3.6}


def _covered_lounge():
    return _run(_lounge_layout(), {"op": "set_zone_ceiling", "zoneId": "zn-lounge", **DECK},
                {"op": "set_zone_roof", "zoneId": "zn-lounge", **ROOF})


def _lounge(doc):
    return next(zone for zone in doc["zones"] if zone["zoneId"] == "zn-lounge")


def test_edit_zone_keeps_the_ceiling_and_roof():
    covered = _covered_lounge()
    group = {"schemaVersion": 1, "groupKind": "manufacturing_cell", "membership": "geometric", "envelopePadding": 0,
             "autoNumber": {"seriesId": "series-test", "baseName": "Cell", "prefix": "", "start": 1, "sequence": 1,
                            "padding": 2}}
    for sent in ({"style": STYLE}, {"style": STYLE, "ceiling": DECK, "roof": ROOF}, {"style": STYLE, "roof": ROOF}):
        doc = _run(covered, {"op": "edit_zone", "zoneId": "zn-lounge", "patch": {"extensions": sent}})
        assert _lounge(doc)["extensions"] == {"style": STYLE, "ceiling": DECK, "roof": ROOF}, sent
    regrouped = _run(covered, {"op": "edit_zone", "zoneId": "zn-lounge", "patch": {"extensions": {"cellGroup": group}}})
    assert _lounge(regrouped)["extensions"] == {"cellGroup": group, "ceiling": DECK, "roof": ROOF}
    # Other fields as before; the rest of the extensions are still replaced whole.
    renamed = _run(regrouped, {"op": "edit_zone", "zoneId": "zn-lounge", "patch": {"label": "Bar"}})
    assert _lounge(renamed)["label"] == "Bar" and _lounge(renamed)["extensions"] == _lounge(regrouped)["extensions"]
    plain = _run(_lounge_layout(), {"op": "edit_zone", "zoneId": "zn-lounge", "patch": {"extensions": {"style": STYLE}}})
    assert _lounge(plain)["extensions"] == {"style": STYLE}
    # Only set_zone_ceiling and set_zone_roof change them.
    for start, sent in ((covered, {"ceiling": {"heightMeters": 4}}), (covered, {"ceiling": {"heightMeters": 3.6}}),
                        (covered, {"roof": {"heightMeters": 5}}), (covered, {"roof": None}),
                        (_lounge_layout(), {"ceiling": {"heightMeters": 3}})):
        with pytest.raises(FacilityLayoutError) as refused:
            apply_facility_layout_operations(start, [{"op": "edit_zone", "zoneId": "zn-lounge",
                                                      "patch": {"extensions": {"style": STYLE, **sent}}}])
        assert refused.value.code == "zone_ceiling_or_roof_kept", sent
        assert "set_zone_" in str(refused.value)


def test_a_sage_recolour_through_the_gateway_keeps_the_ceiling_and_roof(tmp_path):
    import asyncio
    from jsonschema import Draft202012Validator
    from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
    from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, LOCAL_SITE_ID, LOCAL_LAYOUT_ID
    from ai_inspector.facility_layout.operation_proposals import create
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    try:
        service, principal = host.service, host.principal()
        host.ensure_bootstrap()

        def save(proposal, key):
            binding = proposal["alternative"]["transactionBinding"]
            approval = service.approve_layout_proposal(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
                proposal["proposalId"], binding, session_id="test-session", idempotency_key=key,
                explicit_approval=True)
            return service.apply_layout_proposal(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, approval["approvalToken"],
                binding, session_id="test-session", idempotency_key=key)["layout"]

        revision = service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["revision"]
        save(create(service, principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, revision, operations=[
            {"op": "add_zone", "zoneId": "zn-lounge", "zone": {
                "label": "Lounge", "zoneType": "workcell", "anchors": [], "evidence": [], "floorElevation": 0,
                "boundary": rectangle(0, 0, 10, 10)}},
            {"op": "set_zone_ceiling", "zoneId": "zn-lounge", **DECK},
            {"op": "set_zone_roof", "zoneId": "zn-lounge", **ROOF}]), "cover-key")
        for k, color in enumerate(("#5b8def", "#c99b39")):
            current = service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
            saved = _lounge(current["layout"])["extensions"]
            # As Sage builds it: the saved extensions with a new fill (k = 1), or only the style (k = 0).
            extensions = {**deepcopy(saved), "style": {"fillColor": color}} if k else {"style": {"fillColor": color}}
            arguments = {"operations": [{"op": "edit_zone", "zoneId": "zn-lounge", "patch": {"extensions": extensions}}]}
            gateway = FacilityEditGateway(host.agent_runtime, principal, {
                "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": current["revision"]},
                turn_id=f"recolour-{k}")
            schema = next(s for s in gateway.specs if s["name"] == "preview_facility_operations")["input_schema"]
            assert Draft202012Validator(schema).is_valid(arguments), extensions
            result = asyncio.run(gateway.call("preview_facility_operations", arguments))
            assert result["ok"], result
            proposal = service.get_layout_proposal_preview(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
                                                           result["data"]["proposalId"])
            after = save(proposal, f"recolour-key-{k}")
            assert _lounge(after)["extensions"] == {"style": {"fillColor": color}, "ceiling": DECK, "roof": ROOF}
        # A changed ceiling passes the schema but the operation refuses it.
        current = service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
        gateway = FacilityEditGateway(host.agent_runtime, principal, {
            "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": current["revision"]}, turn_id="raise")
        result = asyncio.run(gateway.call("preview_facility_operations", {"operations": [{"op": "edit_zone",
            "zoneId": "zn-lounge", "patch": {"extensions": {"style": STYLE, "ceiling": {"heightMeters": 4}}}}]}))
        assert not result["ok"] and "zone_ceiling_or_roof_kept" in json.dumps(result["error"]), result
        assert service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["revision"] == current["revision"]
    finally:
        host.close()


def test_edit_zone_refuses_extensions_that_are_not_an_object():
    # Codex review of 668b7a4: on a covered zone a list, null, text or number became {ceiling, roof}, clearing the
    # style; on a bare zone the same input failed later. Both are refused now, as the schema says.
    for start in (_covered_lounge(), _lounge_layout()):
        for sent in ([], None, "style", 3):
            with pytest.raises(FacilityLayoutError) as refused:
                apply_facility_layout_operations(start, [{"op": "edit_zone", "zoneId": "zn-lounge",
                                                          "patch": {"extensions": sent}}])
            assert refused.value.code == "invalid_zone_extensions", sent


def _http_lounge(tmp_path):
    """The bootstrap layout with a lounge and a bar saved through the HTTP API's operations save, then the lounge
    covered (open deck and roof); a client for that API and the revision before the covers."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ai_inspector.facility_layout.api import create_facility_layout_router
    from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, LOCAL_SITE_ID, LOCAL_LAYOUT_ID
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    host.ensure_bootstrap()
    principal = host.principal()
    app = FastAPI()
    app.include_router(create_facility_layout_router(service=host.service, principal_resolver=lambda request: principal))
    client = TestClient(app, headers={"X-InspectorPro-Session": "covers-test"})
    url = f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
    zone = {"anchors": [], "evidence": [], "floorElevation": 0, "zoneType": "workcell"}
    for operations in ([{"op": "add_zone", "zoneId": "zn-lounge",
                         "zone": {**zone, "label": "Lounge", "boundary": rectangle(0, 0, 10, 10)}},
                        {"op": "add_zone", "zoneId": "zn-bar",
                         "zone": {**zone, "label": "Bar", "boundary": rectangle(10, 0, 20, 10)}}],
                       [{"op": "set_zone_ceiling", "zoneId": "zn-lounge", **DECK},
                        {"op": "set_zone_roof", "zoneId": "zn-lounge", **ROOF}]):
        current = client.get(url).json()
        response = client.put(url, json={"baseRevision": current["revision"], "operations": operations})
        assert response.status_code == 200, response.text
    return host, client, url, current["revision"]


def test_a_whole_layout_save_keeps_the_ceiling_and_roof_and_a_saved_revision_restores_whole(tmp_path):
    # Codex review of 668b7a4: the HTTP PUT of a whole layout bypassed edit_zone's rule.
    host, client, url, bare_revision = _http_lounge(tmp_path)
    try:
        covered = client.get(url).json()
        document = deepcopy(covered["layout"])
        _lounge(document)["extensions"] = {"style": STYLE}
        saved = client.put(url, json={"baseRevision": covered["revision"], "layout": document})
        assert saved.status_code == 200, saved.text
        assert _lounge(saved.json()["layout"])["extensions"] == {"style": STYLE, "ceiling": DECK, "roof": ROOF}
        recoloured = client.get(url).json()
        for zone_id, extensions in (("zn-lounge", {"style": STYLE, "ceiling": {"heightMeters": 4}, "roof": ROOF}),
                                    ("zn-lounge", {"style": STYLE, "ceiling": DECK, "roof": None}),
                                    ("zn-bar", {"ceiling": {"heightMeters": 3}})):
            changed = deepcopy(recoloured["layout"])
            next(z for z in changed["zones"] if z["zoneId"] == zone_id)["extensions"] = extensions
            refused = client.put(url, json={"baseRevision": recoloured["revision"], "layout": changed})
            assert refused.status_code == 422 and refused.json()["error"]["code"] == "zone_ceiling_or_roof_kept", \
                (zone_id, extensions, refused.text)
            assert "set_zone_" in refused.json()["error"]["message"]
        assert client.get(url).json()["revision"] == recoloured["revision"]
        # Sent unchanged, nothing changes.
        same = client.put(url, json={"baseRevision": recoloured["revision"], "layout": recoloured["layout"]})
        assert same.status_code == 200 and same.json()["revision"] == recoloured["revision"]
        # A saved revision sent whole is a restore (an Undo): the one before the covers takes them off.
        earlier = client.get(url + "/revisions/" + bare_revision).json()["layout"]
        assert "ceiling" not in (_lounge(earlier).get("extensions") or {})
        restored = client.put(url, json={"baseRevision": recoloured["revision"], "layout": earlier})
        assert restored.status_code == 200, restored.text
        assert not (_lounge(restored.json()["layout"]).get("extensions") or {}).get("ceiling")
        assert not (_lounge(restored.json()["layout"]).get("extensions") or {}).get("roof")
        # And the covered revision sent whole puts them back (a Redo).
        redone = client.put(url, json={"baseRevision": restored.json()["revision"], "layout": covered["layout"]})
        assert redone.status_code == 200, redone.text
        assert _lounge(redone.json()["layout"])["extensions"] == {"ceiling": DECK, "roof": ROOF}
        # Edited, an old revision is no restore: a new label on the bare one keeps the covers now saved.
        edited = deepcopy(earlier)
        _lounge(edited)["label"] = "Lounge 2"
        kept = client.put(url, json={"baseRevision": redone.json()["revision"], "layout": edited})
        assert kept.status_code == 200, kept.text
        assert _lounge(kept.json()["layout"])["label"] == "Lounge 2"
        assert _lounge(kept.json()["layout"])["extensions"] == {"ceiling": DECK, "roof": ROOF}
    finally:
        host.close()


def test_a_whole_layout_save_leaves_malformed_zones_to_validation(tmp_path):
    # Codex review of 216cd26: a covered, styled zone sent with "extensions": null became {ceiling, roof} and saved
    # without its style (668b7a4 refused it); "zones": 3 and a list zoneId raised TypeError, not a 422; a zone without
    # an id sending its covers got zone_ceiling_or_roof_kept, not invalid_id. Validation answers as without the rule.
    host, client, url, _ = _http_lounge(tmp_path)
    try:
        covered = client.get(url).json()
        document = deepcopy(covered["layout"])
        _lounge(document)["extensions"] = {"style": STYLE, "ceiling": DECK, "roof": ROOF}
        styled = client.put(url, json={"baseRevision": covered["revision"], "layout": document})
        assert styled.status_code == 200, styled.text
        styled = styled.json()
        cases = (("extensions null", lambda doc: _lounge(doc).update(extensions=None), "invalid_layout_shape"),
                 ("extensions a list", lambda doc: _lounge(doc).update(extensions=[]), "invalid_layout_shape"),
                 ("zones a number", lambda doc: doc.update(zones=3), "invalid_layout_shape"),
                 ("a zone a number", lambda doc: doc["zones"].append(5), "invalid_layout_shape"),
                 ("zoneId a list", lambda doc: _lounge(doc).update(zoneId=[]), "invalid_id"),
                 ("no zoneId", lambda doc: _lounge(doc).pop("zoneId"), "invalid_id"),
                 ("zoneId malformed", lambda doc: _lounge(doc).update(zoneId="bad id!"), "invalid_id"))
        for name, change, code in cases:
            changed = deepcopy(styled["layout"])
            change(changed)
            refused = client.put(url, json={"baseRevision": styled["revision"], "layout": changed})
            assert refused.status_code == 422 and refused.json()["error"]["code"] == code, (name, refused.text)
        after = client.get(url).json()
        assert after["revision"] == styled["revision"]
        assert _lounge(after["layout"])["extensions"] == {"style": STYLE, "ceiling": DECK, "roof": ROOF}
    finally:
        host.close()


def test_a_whole_layout_save_with_a_changed_cover_and_a_kind_that_is_not_a_string_is_a_422(tmp_path):
    # Codex review of f950f83: a whole save that changes a ceiling height runs validation before refusing the change,
    # and a zoneType or layout status sent as a list or an object made validation's set test raise TypeError: HTTP 500,
    # not a 422. Each is refused as malformed now, and the saved layout is untouched.
    host, client, url, _ = _http_lounge(tmp_path)
    try:
        covered = client.get(url).json()
        higher = dict(DECK, heightMeters=DECK["heightMeters"] + 1)
        cases = (("zoneType a list", lambda doc: _lounge(doc).update(zoneType=[])),
                 ("zoneType an object", lambda doc: _lounge(doc).update(zoneType={})),
                 ("status a list", lambda doc: doc.update(status=[])),
                 ("status an object", lambda doc: doc.update(status={})))
        for name, change in cases:
            changed = deepcopy(covered["layout"])
            _lounge(changed)["extensions"]["ceiling"] = higher
            change(changed)
            refused = client.put(url, json={"baseRevision": covered["revision"], "layout": changed})
            assert refused.status_code == 422, (name, refused.status_code, refused.text)
            assert refused.json()["error"]["code"] == "invalid_layout_shape", (name, refused.text)
        # The cover change alone is still refused as a kept cover.
        changed = deepcopy(covered["layout"])
        _lounge(changed)["extensions"]["ceiling"] = higher
        refused = client.put(url, json={"baseRevision": covered["revision"], "layout": changed})
        assert refused.status_code == 422, refused.text
        assert refused.json()["error"]["code"] == "zone_ceiling_or_roof_kept", refused.text
        assert client.get(url).json()["revision"] == covered["revision"]
    finally:
        host.close()


def test_undo_and_redo_of_a_ceiling_and_roof_still_work(tmp_path):
    # Receipt-bound Undo (the UI's Undo after an approved or direct change, and Sage's) restores the revision before
    # set_zone_ceiling and set_zone_roof; doing them again sets them again; their own null removes them.
    from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, LOCAL_SITE_ID, LOCAL_LAYOUT_ID
    from ai_inspector.facility_layout.operation_proposals import create
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    try:
        service, principal = host.service, host.principal()
        host.ensure_bootstrap()

        def commit(key, **request):
            revision = service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["revision"]
            proposal = create(service, principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, revision, **request)
            binding = proposal["alternative"]["transactionBinding"]
            approval = service.approve_layout_proposal(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
                proposal["proposalId"], binding, session_id="test-session", idempotency_key=key, explicit_approval=True)
            return service.apply_layout_proposal(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, approval["approvalToken"],
                binding, session_id="test-session", idempotency_key=key)

        commit("lounge-key", operations=[{"op": "add_zone", "zoneId": "zn-lounge", "zone": {
            "label": "Lounge", "zoneType": "workcell", "anchors": [], "evidence": [], "floorElevation": 0,
            "boundary": rectangle(0, 0, 10, 10)}}])
        bare = _lounge(service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["layout"])
        covers = [{"op": "set_zone_ceiling", "zoneId": "zn-lounge", **DECK},
                  {"op": "set_zone_roof", "zoneId": "zn-lounge", **ROOF}]
        for round_ in range(2):
            done = commit(f"covers-key-{round_}", operations=covers)
            assert _lounge(done["layout"])["extensions"] == {"ceiling": DECK, "roof": ROOF}
            undone = commit(f"undo-key-{round_}", undo_receipt_id=done["receipt"]["receiptId"])
            assert _lounge(undone["layout"]) == bare
        commit("covers-again", operations=covers)
        cleared = commit("clear-key", operations=[{"op": "set_zone_ceiling", "zoneId": "zn-lounge", "heightMeters": None},
                                              {"op": "set_zone_roof", "zoneId": "zn-lounge", "heightMeters": None}])
        extensions = _lounge(cleared["layout"]).get("extensions") or {}
        assert "ceiling" not in extensions and "roof" not in extensions
    finally:
        host.close()
