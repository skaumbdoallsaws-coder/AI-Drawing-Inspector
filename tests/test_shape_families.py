"""Basic shapes BS1 (docs/sage-basic-shapes-plan.md): the family builders, ai_inspector/industrial_assets/
shape_families.py. Every family builds with its defaults, passes the kernel's checks and gives a catalog entry the
app's own catalog reader accepts; ids depend only on the family and the rounded parameters."""
from __future__ import annotations

import json

import pytest

from ai_inspector.facility_layout.host import build_private_local_asset_catalog
from ai_inspector.industrial_assets import primitives as shapes
from ai_inspector.industrial_assets import shape_families as families

OVERHEAD = {"i_beam", "open_web_joist", "cable_tray", "pipe_run", "sprinkler_line", "high_bay_lights", "roof_deck",
            "roof_fascia"}
SHEETING = {"roof_deck", "roof_fascia"}
STRUCTURE = {"steel_column", "i_beam", "open_web_joist", "roof_deck", "roof_fascia"}


@pytest.fixture(scope="module")
def built():
    return {name: families.build_asset(name) for name in families.FAMILIES}


def test_the_plan_s_families_are_all_there():
    assert set(families.FAMILIES) == {
        "steel_column", "i_beam", "open_web_joist",                                         # structure
        "pedestrian_barrier", "low_traffic_barrier", "bollard", "guard_rail",              # safety
        "cable_tray", "pipe_run", "sprinkler_line", "high_bay_lights",                     # overhead services
        "roof_deck", "roof_fascia",                                                        # roof sheeting (switchable)
        "tank", "bin", "pallet_stack", "workbench"}                                        # simple equipment
    for item in families.listing():
        assert item["summary"] and item["category"] and item["parameters"]
        for spec in item["parameters"].values():
            assert "default" in spec and spec["description"]


def test_every_family_builds_with_its_defaults_and_passes_the_kernel_s_checks(built):
    for name, asset in built.items():
        report = shapes.verify(asset["payload"], asset["dimensions"])
        assert 0 < report["triangles"] == asset["triangles"] <= families.MAX_TRIANGLES, name
        entry = asset["entry"]
        assert entry["assetId"] == asset["assetId"] and entry["assetId"].startswith(f"asset-authored-"), name
        assert entry["artifact"] == f"generated/industrial_assets/authored/{entry['assetId'][6:]}.glb"
        assert entry["dimensions"] == asset["dimensions"]
        assert entry["source"] == {"evidenceStatus": "authored", "generator": families.GENERATOR,
                                   "kind": "authored-primitive", "family": name, "parameters": asset["parameters"]}
        assert entry["tags"][-2:] == ["authored", "unverified"]
        assert ("overhead" in entry["tags"]) == (name in OVERHEAD), name
        assert ("roof-sheeting" in entry["tags"]) == (name in SHEETING), name
        assert entry["description"].startswith("Authored ") and "Illustrative only;" in entry["description"]
        if name in STRUCTURE:
            assert entry["description"].endswith("Illustrative only; no structural sizing, load or fire rating.")
        assert all(ord(c) < 128 for c in json.dumps(entry)), name


def test_the_app_s_own_catalog_reader_accepts_every_entry(built, tmp_path):
    folder = tmp_path / "generated" / "industrial_assets"
    (folder / "local_library").mkdir(parents=True)
    (folder / "authored").mkdir()
    entries = [asset["entry"] for asset in built.values()]
    for asset in built.values():
        (tmp_path / asset["entry"]["artifact"]).write_bytes(asset["payload"])
    (folder / "local_library" / "catalog.json").write_text(json.dumps(
        {"schemaVersion": 1, "assets": entries, "summary": {"total": len(entries)}}), encoding="utf-8")
    catalog = {entry["assetId"]: entry for entry in build_private_local_asset_catalog(tmp_path)}
    for asset in built.values():
        bound = catalog[asset["assetId"]]
        assert bound["privateLocalVisual"] == {"enabled": True, "available": True}
        assert len(bound["assetDefinitionRevision"]) == 64
        aabb = bound["definition"]["geometry"]["aabb"]
        assert aabb["maximum"]["y"] == pytest.approx(asset["dimensions"]["height"])
        assert 2 * aabb["maximum"]["x"] == pytest.approx(asset["dimensions"]["width"])
        assert bound["tags"] == asset["entry"]["tags"]


def test_the_asset_id_depends_only_on_the_family_and_the_rounded_parameters():
    default = families.build_asset("pedestrian_barrier")
    spelled_out = families.build_asset("pedestrian_barrier", {"lengthMeters": 10, "heightMeters": 1.1000001,
                                                              "postSpacingMeters": 2.0, "color": "#F5C400"})
    assert spelled_out["assetId"] == default["assetId"] and spelled_out["payload"] == default["payload"]
    assert spelled_out["parameters"] == {"lengthMeters": 10.0, "heightMeters": 1.1, "postSpacingMeters": 2.0,
                                         "color": "#f5c400", "baseColor": "#26292c"}
    assert families.asset_id("pedestrian_barrier", {"lengthMeters": 10.0004}) == default["assetId"]
    other = families.asset_id("pedestrian_barrier", {"lengthMeters": 10.001})
    assert other != default["assetId"] and other.startswith("asset-authored-pedestrian-barrier-10001mm-")
    assert families.asset_id("pedestrian_barrier", {"color": "#ff0000"}) != default["assetId"]
    assert families.asset_id("low_traffic_barrier", {"lengthMeters": 10}) != default["assetId"]
    assert default["assetId"].startswith("asset-authored-pedestrian-barrier-10000mm-")


@pytest.mark.parametrize("name, parameters, message", [
    ("i_beam", {"lengthMeters": 400.5}, "lengthMeters: 400.5 is greater than the maximum of 400"),
    ("i_beam", {"lengthMeters": 0.1}, "lengthMeters: 0.1 is less than the minimum of 0.5"),
    ("bollard", {"color": "yellow"}, "color: 'yellow' does not match"),
    ("tank", {"volumeLiters": 1000}, "Additional properties are not allowed"),
    ("high_bay_lights", {"count": 2.5}, "count: 2.5 is not of type 'integer'"),
    ("pallet_stack", {"pallets": True}, "pallets: True is not of type 'integer'"),
    ("steel_column", {"basePlateMeters": 0.3}, "basePlateMeters must be at least as wide as the column section"),
    ("crane", {}, "Unknown shape family 'crane'"),
])
def test_parameters_outside_the_family_s_limits_are_refused(name, parameters, message):
    with pytest.raises(ValueError, match=message.replace("(", r"\(").replace(")", r"\)")):
        families.build_asset(name, parameters)


def test_the_factory_02_shapes_come_out_as_before():
    column = families.build_asset("steel_column")
    assert column["dimensions"] == {"width": 0.5, "height": 10.0, "depth": 0.5}
    assert column["entry"]["displayName"] == "Steel column 10 m"
    # f02_barriers.py: a 22 m pedestrian barrier had 12 posts, 1.1 m high on 0.24 m base plates.
    barrier = families.build_asset("pedestrian_barrier", {"lengthMeters": 22})
    assert barrier["dimensions"] == {"width": 22.0, "height": 1.1, "depth": 0.24}
    assert "12 posts at most 2 m apart with three rails" in barrier["entry"]["description"]
    # f02_roof.py: a 900 x 300 mm girder and a 750 mm Warren joist with 120 mm chords.
    girder = families.build_asset("i_beam", {"lengthMeters": 299.455})
    assert girder["dimensions"] == {"width": 299.455, "height": 0.9, "depth": 0.3}
    joist = families.build_asset("open_web_joist", {"lengthMeters": 200.04})
    assert joist["dimensions"] == {"width": 200.04, "height": 0.75, "depth": 0.12}
    # f02_services.py: 50 high-bays 6 m apart, lenses that glow.
    row = families.build_asset("high_bay_lights", {"count": 50})
    assert row["dimensions"]["width"] == pytest.approx(49 * 6 + 0.42, abs=1e-3)
    assert row["dimensions"]["height"] == pytest.approx(0.015 + 0.09 + 0.9)
    lens = next(m for m in shapes.gltf_json(row["payload"])["materials"] if m["name"] == "lens")
    assert lens["extras"]["facilityDefaultFinish"] == "light-cool-white-led"
    assert lens["emissiveFactor"] == [1, 0.97, 0.9]
    assert row["entry"]["displayName"] == "High-bay light row 50 x 6 m"
    assert families.build_asset("high_bay_lights")["entry"]["displayName"] == "High-bay light"


def test_other_shapes_are_the_size_asked_for():
    sizes = {
        ("tank", ()): {"width": 2.0, "height": 3.0, "depth": 2.0},
        ("bin", ()): {"width": 0.6, "height": 0.3, "depth": 0.4},
        ("pallet_stack", (("pallets", 4), ("loadHeightMeters", 1.0))): {"width": 1.2, "height": 4 * 0.144 + 1.0,
                                                                       "depth": 1.0},
        ("workbench", ()): {"width": 1.8, "height": 0.9, "depth": 0.75},
        ("roof_deck", (("widthMeters", 30), ("depthMeters", 12.5))): {"width": 30.0, "height": 0.08, "depth": 12.5},
        ("roof_fascia", ()): {"width": 20.0, "height": 1.9, "depth": 0.05},
        ("bollard", ()): {"width": 0.288, "height": 1.2, "depth": 0.288},
        ("cable_tray", ()): {"width": 20.0, "height": 0.04 + 0.10 + 0.45, "depth": 0.72},
        ("pipe_run", ()): {"width": 20.0, "height": 0.1 + 0.3, "depth": 0.1},
        ("sprinkler_line", ()): {"width": 20.0, "height": 0.07 + 0.06 + 0.25, "depth": 0.06},
    }
    for (name, parameters), expected in sizes.items():
        assert families.build_asset(name, dict(parameters))["dimensions"] == pytest.approx(expected), name
    # The bin is open at the top: outside and bottom 10 triangles, inside 10, rim 8.
    assert families.build_asset("bin")["triangles"] == 28
    assert "7 pendent heads at most 3 m apart" in families.build_asset("sprinkler_line")["entry"]["description"]
