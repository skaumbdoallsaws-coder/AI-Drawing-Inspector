"""Robot articulation resolution, authored profiles, and fail-closed refusal."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.robot_articulation import (
    ARTICULATION_UNAVAILABLE,
    ROBOT_ARTICULATION_SCHEMA_VERSION,
    FacilityRobotArticulationError,
    normalize_articulation_profile,
    read_gltf_document,
    resolve_articulation,
    summarize_asset_articulation,
)

ROOT = Path(__file__).resolve().parents[1]
ROBOT_GLB = (
    ROOT
    / "generated/industrial_assets/local_library/abb-irb6650-robot"
    / "User Library-6-axis robot abb6650_320_125_colored.glb"
)
ROBOT_ASSET_ID = "asset-abb-irb6650-robot"
ROBOT_REVISION = "886e29b92be913ed483751e827c510fe6521c4459545fb056f02091cdf73c2b9"


def _flat_document(node_count: int = 3) -> dict:
    return {"nodes": [{"name": f"part-{index}", "mesh": index} for index in range(node_count)]}


def _profile(node_names, **overrides) -> dict:
    joints = [
        {
            "role": "base",
            "nodeName": node_names[0],
            "parentRole": None,
            "axis": [0.0, 1.0, 0.0],
            "pivot": [0.0, 0.0, 0.0],
            "limitsDegrees": [-180.0, 180.0],
        },
        {
            "role": "shoulder",
            "nodeName": node_names[1],
            "parentRole": "base",
            "axis": [1.0, 0.0, 0.0],
            "pivot": [0.0, 0.4, 0.0],
            "limitsDegrees": [-90.0, 90.0],
        },
        {
            "role": "elbow",
            "nodeName": node_names[2],
            "parentRole": "shoulder",
            "axis": [1.0, 0.0, 0.0],
            "pivot": [0.0, 1.2, 0.0],
            "limitsDegrees": [-120.0, 120.0],
        },
        {
            "role": "wrist",
            "nodeName": node_names[0],
            "parentRole": "elbow",
            "axis": [1.0, 0.0, 0.0],
            "pivot": [0.0, 1.8, 0.0],
            "limitsDegrees": [-180.0, 180.0],
        },
    ]
    profile = {
        "schemaVersion": ROBOT_ARTICULATION_SCHEMA_VERSION,
        "assetId": ROBOT_ASSET_ID,
        "assetDefinitionRevision": ROBOT_REVISION,
        "joints": joints,
    }
    profile.update(overrides)
    return profile


# --------------------------------------------------------------- asset facts --
def test_reference_robot_asset_carries_no_articulation_evidence() -> None:
    """The shipped ABB IRB 6650 GLB is kinematically inert. Freeze that fact."""
    document = read_gltf_document(ROBOT_GLB)
    summary = summarize_asset_articulation(document)

    assert summary["animationCount"] == 0
    assert summary["skinCount"] == 0
    assert summary["parentedNodeCount"] == 0
    assert summary["transformedNodeCount"] == 0
    assert summary["nodeCount"] == 13
    assert summary["articulationEvidence"] is False


def test_resolution_fails_closed_for_the_reference_robot() -> None:
    document = read_gltf_document(ROBOT_GLB)

    with pytest.raises(FacilityRobotArticulationError) as excinfo:
        resolve_articulation(
            asset_id=ROBOT_ASSET_ID,
            asset_definition_revision=ROBOT_REVISION,
            gltf_document=document,
        )

    assert excinfo.value.code == ARTICULATION_UNAVAILABLE
    details = excinfo.value.details or {}
    assert details["nodeCount"] == 13
    assert details["animationCount"] == 0
    assert details["parentedNodeCount"] == 0
    assert "remedy" in details


# ------------------------------------------------------------ mode selection --
def test_animation_clips_take_precedence() -> None:
    document = dict(
        _flat_document(),
        animations=[
            {"name": "pick_place_cycle", "channels": [{"sampler": 0, "target": {"node": 0, "path": "rotation"}}]}
        ],
    )

    resolved = resolve_articulation(
        asset_id=ROBOT_ASSET_ID,
        asset_definition_revision=ROBOT_REVISION,
        gltf_document=document,
    )

    assert resolved["mode"] == "asset_animation_clips"
    assert resolved["clipNames"] == ["pick_place_cycle"]


def test_node_hierarchy_alone_does_not_qualify_as_articulated() -> None:
    """Structure is not kinematics: parented nodes carry no axes or pivots."""
    document = {
        "nodes": [
            {"name": "base", "children": [1]},
            {"name": "arm", "translation": [0.0, 1.0, 0.0]},
        ]
    }

    with pytest.raises(FacilityRobotArticulationError) as excinfo:
        resolve_articulation(
            asset_id=ROBOT_ASSET_ID,
            asset_definition_revision=ROBOT_REVISION,
            gltf_document=document,
        )

    assert excinfo.value.code == ARTICULATION_UNAVAILABLE
    assert (excinfo.value.details or {})["parentedNodeCount"] == 1


def test_animation_without_channels_does_not_qualify() -> None:
    document = dict(_flat_document(), animations=[{"name": "empty", "channels": []}])

    with pytest.raises(FacilityRobotArticulationError) as excinfo:
        resolve_articulation(
            asset_id=ROBOT_ASSET_ID,
            asset_definition_revision=ROBOT_REVISION,
            gltf_document=document,
        )

    assert excinfo.value.code == ARTICULATION_UNAVAILABLE


def test_authored_profile_resolves_against_a_flat_asset() -> None:
    document = _flat_document()
    names = [node["name"] for node in document["nodes"]]

    resolved = resolve_articulation(
        asset_id=ROBOT_ASSET_ID,
        asset_definition_revision=ROBOT_REVISION,
        gltf_document=document,
        authored_profile=_profile(names),
    )

    assert resolved["mode"] == "authored_profile"
    assert len(resolved["profile"]["profileRevision"]) == 64
    assert "do not establish reach capacity" in resolved["profile"]["qualification"]


# --------------------------------------------------------- profile integrity --
def test_profile_revision_is_deterministic() -> None:
    names = [node["name"] for node in _flat_document()["nodes"]]

    first = normalize_articulation_profile(_profile(names))
    second = normalize_articulation_profile(_profile(names))

    assert first["profileRevision"] == second["profileRevision"]


def test_profile_revision_changes_with_joint_limits() -> None:
    names = [node["name"] for node in _flat_document()["nodes"]]
    baseline = normalize_articulation_profile(_profile(names))

    altered = _profile(names)
    altered["joints"][1]["limitsDegrees"] = [-45.0, 45.0]

    assert normalize_articulation_profile(altered)["profileRevision"] != baseline["profileRevision"]


def test_profile_missing_a_required_role_is_refused() -> None:
    names = [node["name"] for node in _flat_document()["nodes"]]
    incomplete = _profile(names)
    incomplete["joints"] = [
        joint for joint in incomplete["joints"] if joint["role"] != "elbow"
    ]

    with pytest.raises(FacilityRobotArticulationError) as excinfo:
        normalize_articulation_profile(incomplete)

    assert excinfo.value.code == "facility_robot_profile_incomplete"
    assert "elbow" in (excinfo.value.details or {})["missingRoles"]


def test_profile_bound_to_another_revision_is_refused() -> None:
    document = _flat_document()
    names = [node["name"] for node in document["nodes"]]

    with pytest.raises(FacilityRobotArticulationError) as excinfo:
        resolve_articulation(
            asset_id=ROBOT_ASSET_ID,
            asset_definition_revision="f" * 64,
            gltf_document=document,
            authored_profile=_profile(names),
        )

    assert excinfo.value.code == "facility_robot_profile_mismatch"


def test_profile_referencing_absent_nodes_is_refused() -> None:
    document = _flat_document()

    with pytest.raises(FacilityRobotArticulationError) as excinfo:
        resolve_articulation(
            asset_id=ROBOT_ASSET_ID,
            asset_definition_revision=ROBOT_REVISION,
            gltf_document=document,
            authored_profile=_profile(["ghost-node", "part-1", "part-2"]),
        )

    assert excinfo.value.code == "facility_robot_profile_mismatch"
    assert "ghost-node" in (excinfo.value.details or {})["unknownNodes"]


def test_profile_with_a_parent_cycle_is_refused() -> None:
    names = [node["name"] for node in _flat_document()["nodes"]]
    cyclic = _profile(names)
    by_role = {joint["role"]: joint for joint in cyclic["joints"]}
    by_role["base"]["parentRole"] = "wrist"

    with pytest.raises(FacilityRobotArticulationError) as excinfo:
        normalize_articulation_profile(cyclic)

    assert excinfo.value.code == "facility_robot_profile_invalid"


def test_profile_requires_a_non_zero_axis() -> None:
    names = [node["name"] for node in _flat_document()["nodes"]]
    degenerate = _profile(names)
    degenerate["joints"][0]["axis"] = [0.0, 0.0, 0.0]

    with pytest.raises(FacilityRobotArticulationError):
        normalize_articulation_profile(degenerate)


# ------------------------------------------------ reviewed capability inventory --
INVENTORY = (
    ROOT / "tests/fixtures/facility_layout/robot_articulation_capability_inventory.json"
)


def test_capability_inventory_matches_the_library() -> None:
    """The inventory is a reviewed snapshot, not a tripwire.

    An asset gaining animation channels is a welcome capability change. This
    asserts the recorded review is still accurate, so the fixture is
    regenerated and re-reviewed deliberately rather than failing the suite.
    """
    fixture = json.loads(INVENTORY.read_text(encoding="utf-8"))
    recorded = {row["assetDirectory"]: row for row in fixture["assets"]}

    library = ROOT / "generated/industrial_assets/local_library"
    observed = {}
    for glb in sorted(library.rglob("*.glb")):
        summary = summarize_asset_articulation(read_gltf_document(glb))
        observed[glb.parent.name] = summary["articulationEvidence"]

    unreviewed = sorted(set(observed) - set(recorded))
    assert unreviewed == [], f"assets absent from the reviewed inventory: {unreviewed}"

    changed = sorted(
        name
        for name, evidence in observed.items()
        if evidence != recorded[name]["articulationEvidence"]
    )
    assert changed == [], (
        f"articulation capability changed for {changed}; regenerate and "
        "re-review tests/fixtures/facility_layout/"
        "robot_articulation_capability_inventory.json"
    )


def test_reference_robot_is_recorded_as_unarticulated() -> None:
    fixture = json.loads(INVENTORY.read_text(encoding="utf-8"))
    row = next(r for r in fixture["assets"] if r["assetDirectory"] == "abb-irb6650-robot")

    assert row["articulationEvidence"] is False
    assert row["animationChannelCount"] == 0
    assert fixture["reviewStatus"] == "reviewed"
