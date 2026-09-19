import importlib.util
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "tools" / "motion_package_build.py"
RAW_PATH = ROOT / "generated" / "engine_motion" / "motion_exports" / "engine_motion_crank_cycle_trimmed_45_raw.json"
STALE_ASSEMBLY_PATH = ROOT / "generated" / "engine_motion" / "split" / "assemblies" / "100001" / "revA" / "100001_assembly.json"
STALE_GLB_PATH = ROOT / "generated" / "engine_motion" / "glb_assets" / "Engine_Motion_Study_colored.glb"


def _load_builder():
    spec = importlib.util.spec_from_file_location("motion_package_build", BUILDER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _args(skip_rest_pose_check=False):
    return SimpleNamespace(
        raw=str(RAW_PATH),
        assembly=str(STALE_ASSEMBLY_PATH),
        glb=str(STALE_GLB_PATH),
        motion_id="engine4cyl_crank_cycle",
        name="Four-cylinder crank-slider cycle",
        skip_rest_pose_check=skip_rest_pose_check,
    )


def test_current_glb_raw_pair_requires_reexport_at_sample0():
    builder = _load_builder()
    try:
        builder.build_package(_args(skip_rest_pose_check=False))
    except ValueError as exc:
        assert "Rest-pose mismatch" in str(exc)
        assert "Re-export the GLB" in str(exc)
    else:
        raise AssertionError("expected rest-pose mismatch to fail the build")


def test_builder_defaults_target_sample0_asset_pair():
    builder = _load_builder()
    assert builder.DEFAULT_ASSEMBLY_PATH.replace("\\", "/").endswith(
        "generated/engine_motion/glb_assets_sample0/Engine_Motion_Study_sample0_assembly.json"
    )
    assert builder.DEFAULT_GLB_PATH.replace("\\", "/").endswith(
        "generated/engine_motion/glb_assets_sample0/Engine_Motion_Study_sample0_colored.glb"
    )


def test_engine_motion_package_binds_rendered_glb_nodes():
    builder = _load_builder()
    package = builder.build_package(_args(skip_rest_pose_check=True))

    assert package["motionId"] == "engine4cyl_crank_cycle"
    assert sorted(package.keys()) == sorted(
        [
            "contractVersion",
            "motionId",
            "name",
            "description",
            "source",
            "glbAsset",
            "frame",
            "driver",
            "components",
            "sampling",
            "samples",
            "events",
            "semanticGroups",
            "derived",
        ]
    )
    assert package["frame"]["space"] == "glb_asset_root"
    assert package["frame"]["convention"] == "y_up_right_handed"
    assert package["glbAsset"]["fileName"] == "Engine_Motion_Study_colored.glb"
    assert len(package["glbAsset"]["sha256"]) == 64
    assert package["glbAsset"]["byteLength"] > 0
    assert package["sampling"]["count"] == 45
    assert package["sampling"]["endpointDuplicatesStart"] is True
    assert package["driver"]["axis"]["direction"] == [-1.0, 0.0, 0.0]

    moving = package["components"]["moving"]
    fixed = package["components"]["fixed"]
    assert len(moving) == 37
    assert len(fixed) == 1
    assert {c["id"] for c in fixed} == {"Lower block-1"}
    assert set(package["components"]) == {"moving", "fixed"}

    for comp in moving:
        assert set(comp).issubset({"id", "displayName", "swInstancePath", "sourceFile", "configuration", "partNumber", "glbNodes"})
        assert comp["glbNodes"] == [comp["id"]]
        node_samples = package["samples"][comp["id"]]
        assert set(node_samples) == {"p", "q"}
        assert len(node_samples["p"]) == 45
        assert len(node_samples["q"]) == 45
        assert node_samples["p"][0] == node_samples["p"][-1]
        assert abs(abs(sum(a * b for a, b in zip(node_samples["q"][0], node_samples["q"][-1]))) - 1.0) < 1e-8
        for qa, qb in zip(node_samples["q"], node_samples["q"][1:]):
            assert sum(a * b for a, b in zip(qa, qb)) >= 0.0
        for q in node_samples["q"]:
            assert abs(sum(v * v for v in q) - 1.0) < 1e-8

    groups = {g["id"]: g for g in package["semanticGroups"]}
    assert "crank_slider_instance1" in groups
    assert "Socket Head Cap Screw-1" in groups["crank_slider_instance1"]["componentIds"]
    assert "Socket Head Cap Screw-2" in groups["crank_slider_instance1"]["componentIds"]
    assert "crank_slider_instance4" in groups
    assert "pin_bore_fai_affected" in groups

    declared = {c["id"] for c in moving + fixed}
    assert set(package["samples"]) == {c["id"] for c in moving}
    assert package["driver"]["componentId"] in declared
    for event in package["events"]:
        assert set(event) == {"angleDeg", "id", "label", "componentIds"}
        assert set(event.get("componentIds", [])).issubset(declared)
    for group in package["semanticGroups"]:
        assert set(group["componentIds"]).issubset(declared)


def test_solidworks_row_rotation_is_transposed_for_three_quaternion():
    builder = _load_builder()
    raw = builder._load_json(RAW_PATH)
    package = builder.build_package(_args(skip_rest_pose_check=True))
    crank = None
    for component in raw["samples"][10]["components"]:
        if component["name"] == "crankshaft-1":
            crank = component["transform"]
            break
    assert crank is not None

    q_three = builder._quat_from_sw_row_rotation(crank)
    sw_row = builder._sw_row_matrix(crank)
    q_direct_row = builder._quat_from_col_rotation_values(
        sw_row[0][0], sw_row[0][1], sw_row[0][2],
        sw_row[1][0], sw_row[1][1], sw_row[1][2],
        sw_row[2][0], sw_row[2][1], sw_row[2][2],
    )
    package_q = package["samples"]["crankshaft-1"]["q"][10]

    assert abs(abs(sum(a * b for a, b in zip(package_q, q_three))) - 1.0) < 1e-8
    assert abs(sum(a * b for a, b in zip(q_three, q_direct_row))) < 0.5


def test_joint_closure_canary_passes_and_rejects_flipped_rotation():
    # The shipped tracks must keep every crank-slider joint coincident (the
    # same constraint the SolidWorks Concentric mates enforce). The canary
    # solves for fixed shared points per joint pair in least squares.
    builder = _load_builder()
    package, _summary, diagnostics = builder._build(_args(skip_rest_pose_check=True))
    v = diagnostics["validation"]
    assert v["jointClosureOk"] is True
    assert v["jointClosureMaxMm"] < 1.0
    # 4 rods + 4 caps on the crank, 4 pins in rods, 4 pistons on pins.
    assert v["jointClosurePairCount"] == 16

    # Negative control: conjugating one rod's quaternions (the transposed /
    # inverted-rotation failure mode) must blow the residual far past the
    # limit, proving the canary can actually catch a broken convention.
    doctored = dict(package["samples"])
    rod = package["samples"]["connecting rod-1"]
    doctored["connecting rod-1"] = {
        "p": rod["p"],
        "q": [[-q[0], -q[1], -q[2], q[3]] for q in rod["q"]],
    }
    moving_ids = [c["id"] for c in package["components"]["moving"]]
    metrics = builder._joint_closure_metrics(doctored, moving_ids)
    assert metrics["jointClosureOk"] is False
    assert metrics["jointClosureMaxMm"] > 10.0


def _run_direct():
    test_current_glb_raw_pair_requires_reexport_at_sample0()
    test_builder_defaults_target_sample0_asset_pair()
    test_engine_motion_package_binds_rendered_glb_nodes()
    test_solidworks_row_rotation_is_transposed_for_three_quaternion()
    test_joint_closure_canary_passes_and_rejects_flipped_rotation()


if __name__ == "__main__":
    _run_direct()
    print("direct tests passed")
