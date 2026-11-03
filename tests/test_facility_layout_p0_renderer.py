import hashlib
import json
import re
from pathlib import Path

from tools.facility_three_manifest import P0_VENDOR_PATHS, p0_manifest_entries_sha256


ROOT = Path(__file__).resolve().parents[1]
RENDERING = ROOT / "tests" / "fixtures" / "facility_layout" / "rendering"
VENDOR = ROOT / "static" / "vendor" / "three" / "0.184.0"


def _load(path):
    return json.loads(path.read_text(encoding="ascii"))


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_entries():
    text = (VENDOR / "VERSIONS.md").read_text(encoding="ascii")
    pattern = re.compile(
        r"^\| `(?P<path>[^`]+)` \| (?P<bytes>\d+) \| "
        r"`(?P<sha>[0-9a-f]{64})` \|$",
        re.MULTILINE,
    )
    return {
        match.group("path"): {
            "bytes": int(match.group("bytes")),
            "sha256": match.group("sha"),
        }
        for match in pattern.finditer(text)
    }


def test_vendored_three_manifest_matches_every_pinned_file():
    entries = _manifest_entries()
    expected = {
        "build/three.core.min.js",
        "build/three.module.min.js",
        "examples/jsm/loaders/GLTFLoader.js",
        "examples/jsm/utils/BufferGeometryUtils.js",
        "examples/jsm/utils/SkeletonUtils.js",
        "examples/jsm/controls/OrbitControls.js",
        "examples/jsm/controls/PointerLockControls.js",
        "examples/jsm/loaders/STLLoader.js",
        "examples/jsm/renderers/CSS2DRenderer.js",
        # Appearance library (2026-10-19).
        "examples/jsm/environments/RoomEnvironment.js",
        "examples/jsm/loaders/HDRLoader.js",
        "examples/jsm/geometries/DecalGeometry.js",
        # Lighting L6, the glow halo (2026-10-31).
        "examples/jsm/postprocessing/UnrealBloomPass.js",
        "examples/jsm/postprocessing/Pass.js",
        "examples/jsm/shaders/CopyShader.js",
        "examples/jsm/shaders/LuminosityHighPassShader.js",
        "LICENSE",
        "package.json",
    }
    assert set(entries) == expected
    for relative, metadata in entries.items():
        path = VENDOR / relative
        assert path.is_file()
        assert path.stat().st_size == metadata["bytes"]
        assert _sha256(path) == metadata["sha256"]


def test_renderer_benchmark_is_reproducible_and_meets_p0_budget():
    spec = _load(RENDERING / "renderer-benchmark-spec.json")
    result = _load(RENDERING / "renderer-benchmark-results.json")
    assert result["errors"] == []
    assert result["network"]["blockedExternalRequests"] == []
    assert all(run["consoleErrors"] == [] for run in result["runs"])
    assert {
        scenario["placementCount"] for scenario in spec["scenarios"].values()
    } == {500, 5000}
    assert {
        scenario["prototypeCount"] for scenario in spec["scenarios"].values()
    } == {20}

    source = result["source"]
    assert source["runnerSha256"] == _sha256(
        ROOT / "tools" / "benchmark_facility_layout_renderers.py"
    )
    assert source["specSha256"] == _sha256(
        RENDERING / "renderer-benchmark-spec.json"
    )
    assert source["benchmarkHtmlSha256"] == _sha256(
        RENDERING / "renderer-benchmark.html"
    )

    metrics = result["summary"]
    for renderer in ("webgl", "svg", "canvas2d"):
        for scenario in ("edit-500", "navigate-5000"):
            assert metrics[renderer][scenario]["runCount"] == 5

    for scenario in ("edit-500", "navigate-5000"):
        placement_hashes = {
            metrics[renderer][scenario]["placementHashSha256"]
            for renderer in ("webgl", "svg", "canvas2d")
        }
        assert len(placement_hashes) == 1
        webgl = metrics["webgl"][scenario]
        assert webgl["frameIntervalMs"]["p95"] <= 22
        assert webgl["rendererMetrics"]["drawCallsPerFrame"] == 1
        assert webgl["rendererMetrics"]["contextLost"] is False

    assert metrics["canvas2d"]["edit-500"]["frameIntervalMs"]["p95"] > 22
    assert metrics["canvas2d"]["navigate-5000"]["frameIntervalMs"]["p95"] > 22


def test_offline_three_smoke_uses_only_local_pinned_modules():
    result = _load(RENDERING / "three-offline-smoke-result.json")
    source = result["source"]
    assert "manifestEntriesSha256" in source and "manifestEntryPaths" in source, (
        "P0 offline smoke evidence lacks scoped manifest entries "
        "(legacy manifestSha256 is not accepted); regenerate with "
        "python tools/verify_facility_three_offline.py"
    )
    assert result["schemaVersion"] == "facility-three-offline-smoke-v1"
    assert result["passed"] is True
    assert result["pageErrors"] == []
    assert result["consoleErrors"] == []
    assert result["network"]["blockedExternalRequests"] == []
    assert all(result["checks"].values())
    assert source["manifestEntryPaths"] == list(P0_VENDOR_PATHS)
    assert source["manifestEntriesSha256"] == p0_manifest_entries_sha256(
        (VENDOR / "VERSIONS.md").read_text(encoding="ascii")
    )
    assert result["source"]["fixtureSha256"] == _sha256(
        RENDERING / "three-offline-smoke.html"
    )
    assert result["source"]["moduleSha256"] == _sha256(
        VENDOR / "build" / "three.module.min.js"
    )
    assert result["source"]["loaderSha256"] == _sha256(
        VENDOR / "examples" / "jsm" / "loaders" / "GLTFLoader.js"
    )


def test_real_rack_instance_spike_uses_stable_deterministic_occurrences():
    fixture = _load(RENDERING / "repeated-rack-instance-spike.json")
    placements = fixture["placements"]
    assert fixture["source"]["authority"] == "inferred"
    assert fixture["source"]["purpose"] == "rendering_spike_only"
    assert fixture["coordinateSemantics"]["units"] == "m"
    assert fixture["coordinateSemantics"]["quaternionOrder"] == "xyzw"
    assert fixture["prototype"]["meshCount"] == 10
    assert fixture["prototype"]["geometryBytes"] == 13_493_420
    assert len(placements) == 6
    assert len({item["placementId"] for item in placements}) == len(placements)

    prototype_id = fixture["prototype"]["prototypeId"]
    for placement in placements:
        source = f"{prototype_id}|{placement['sourceOccurrenceName']}"
        expected = "pl-" + hashlib.sha256(source.encode("ascii")).hexdigest()[:16]
        assert placement["placementId"] == expected
        assert placement["scale"] == 1.0
        assert set(placement["position"]) == {"x", "y", "z"}
        assert set(placement["quaternion"]) == {"x", "y", "z", "w"}


def test_real_rack_instancing_browser_proof_is_nonblank_and_instance_aware():
    fixture = _load(RENDERING / "repeated-rack-instance-spike.json")
    result = _load(RENDERING / "rack-instancing-smoke-result.json")
    assert result["schemaVersion"] == "facility-rack-instancing-smoke-v1"
    assert result["passed"] is True
    assert result["pageErrors"] == []
    assert result["consoleErrors"] == []
    assert result["network"]["blockedExternalRequests"] == []
    assert all(result["checks"].values())
    assert result["source"]["fixtureSha256"] == _sha256(
        RENDERING / "repeated-rack-instance-spike.json"
    )
    assert result["source"]["pageSha256"] == _sha256(
        RENDERING / "rack-instancing-smoke.html"
    )
    assert result["source"]["scriptSha256"] == _sha256(
        RENDERING / "rack-instancing-smoke.js"
    )
    assert (
        result["source"]["prototypeSha256"]
        == fixture["prototype"]["geometrySha256"]
    )
    assert result["source"]["extractionSha256"] == fixture["prototype"][
        "extractionSha256"
    ]

    smoke = result["smoke"]
    assert smoke["prototypeMeshCount"] == fixture["prototype"]["meshCount"]
    assert smoke["placementCount"] == len(fixture["placements"])
    assert smoke["instancedDrawCalls"] < smoke["naiveDrawCalls"]
    assert smoke["drawCallReductionRatio"] >= 5
    assert smoke["raycast"]["placementId"] in {
        item["placementId"] for item in fixture["placements"]
    }
    assert smoke["changedPixelCount"] >= 1000
    screenshot = ROOT / result["screenshot"]["path"]
    assert screenshot.is_file()
    assert result["screenshot"]["sha256"] == _sha256(screenshot)


def test_benchmark_manifest_exposes_partial_evidence_without_overclaiming():
    manifest = _load(RENDERING.parent / "benchmark-fixture-manifest.json")
    assert manifest["schemaVersion"] == "facility-benchmark-fixture-manifest-v1"
    assert manifest["referenceHardware"]["standard"]["status"] == "named"
    assert manifest["referenceHardware"]["minimum"] == {
        "status": "unresolved",
        "releaseGateBlocked": True,
    }
    fixtures = {
        item["fixtureId"]: item for item in manifest["fixtures"]
    }
    assert set(fixtures) == {
        "legacy-heavy",
        "assem3-instanced",
        "industrial-cell",
        "unique-machines-100",
        "warehouse-500",
        "warehouse-5000",
        "forklift-routing",
        "utility-network",
        "lifecycle-churn",
        "degraded-runtime",
    }
    assert fixtures["assem3-instanced"]["status"] == "p0_spike_available"
    assert "stable_placement_to_instance_mapping" in fixtures[
        "assem3-instanced"
    ]["approvedClaims"]
    assert "release_scale_performance" in fixtures["assem3-instanced"][
        "forbiddenClaims"
    ]
    assert fixtures["warehouse-500"]["status"] == "placement_layer_spike_only"
    assert fixtures["warehouse-5000"]["status"] == "placement_layer_spike_only"
    assert "full_layer_release_performance" in fixtures["warehouse-500"][
        "forbiddenClaims"
    ]
    assert "clearance_stress_performance" in fixtures["warehouse-5000"][
        "forbiddenClaims"
    ]
    assert fixtures["legacy-heavy"]["artifacts"][0]["byteLength"] == 327_184_996
    assert fixtures["legacy-heavy"]["artifacts"][0]["sha256"] == (
        "da2be02acea430027324857e58db3ddee81713dcf9b54e38d45b830671898ce2"
    )
