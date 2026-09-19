from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


def test_plant_walkthrough_reuses_the_live_cooling_tower_scene():
    assert "function _trainTickPlantSpatialWalkthrough" in INDEX
    assert "_trainTickPlantSpatialWalkthrough(time || 0)" in INDEX
    assert "function _trainDisposePlantSpatialWalkthrough" in INDEX
    assert "_trainDisposePlantSpatialWalkthrough();" in INDEX
    assert "_trainSchedulePlantSpatialWalkthroughRefresh();" in INDEX


def test_plant_walkthrough_uses_deterministic_collision_and_world_scale():
    assert "InspectorProFacilityThree" in INDEX
    assert "helper.findWalkthroughSpawn" in INDEX
    assert "helper.walkthroughPostureProfiles(modelScale)" in INDEX
    assert "bodyHeight: 1.95 * modelScale" in INDEX
    assert "radius: 0.3 * modelScale" in INDEX
    assert "runtime.footY + runtime.currentEyeHeight" in INDEX
    assert "helper.resolveMultiLevelWalkthroughMovement" in INDEX
    assert "maximumStepUp = 0.24 * modelScale" in INDEX
    assert "maximumStepDown = 0.34 * modelScale" in INDEX
    assert "_trainPlantSparseCollisionVolumes" in INDEX
    assert "walkableKindByMesh.set(mesh, 'stair')" in INDEX
    assert "preferredEntryId === 'stair-access'" in INDEX
    assert "stairEntry" in INDEX


def test_plant_walkthrough_supports_collision_checked_postures():
    assert "function _trainRequestPlantWalkPosture" in INDEX
    assert "helper.resolveWalkthroughPostureChange" in INDEX
    assert "_trainRequestPlantWalkPosture('standing')" in INDEX
    assert "_trainRequestPlantWalkPosture(runtime.posture === 'crawling'" in INDEX
    assert "<kbd>C</kbd><span>Crouch</span>" in INDEX
    assert "<kbd>Z</kbd><span>Crawl</span>" in INDEX
    assert "<kbd>Space</kbd><span>Stand</span>" in INDEX
    assert "Geometry clearance:" in INDEX
    assert "1 - Math.exp(-14 * seconds)" in INDEX


def test_sparse_collision_cells_preserve_open_vertical_spans():
    assert "existing.intervals.push({ minimumY, maximumY });" in INDEX
    assert "const mergeTolerance = 0.04 * modelScale;" in INDEX
    assert ":span:${spanIndex + 1}`" in INDEX


def test_plant_walkthrough_has_accessible_controls_and_camera_restore():
    assert "data-plant-process-command" not in INDEX  # assigned through dataset APIs
    assert "walkButton.dataset.plantProcessCommand = 'walkthrough';" in INDEX
    assert "button.dataset.plantProcessCommand = 'operator-viewpoints';" in INDEX
    assert "runtime.walkButton.setAttribute('aria-pressed'" in INDEX
    assert "camera.position.copy(runtime.previousCamera.position);" in INDEX
    assert "controls.target.copy(runtime.previousCamera.target);" in INDEX
    assert "Return to overview" in INDEX


def test_plant_operator_views_cover_the_process_systems():
    for label in (
        "Tower overview",
        "Hot-water inlet",
        "Stair and service platform",
        "Cooling cells",
        "Basin and cold return",
        "Drain and overflow",
    ):
        assert label in INDEX
