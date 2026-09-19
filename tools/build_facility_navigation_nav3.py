from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.host import (
    LOCAL_SITE_ID,
    LocalFacilityLayoutHost,
)
from ai_inspector.facility_layout.navigation_compiler import (
    compile_navigation_snapshot,
    navigation_snapshot_summary,
)


RUNTIME_ROOT = ROOT / ".runtime" / "facility-layout"
REFERENCE = (
    RUNTIME_ROOT
    / "layouts"
    / "local"
    / LOCAL_SITE_ID
    / "layouts"
    / "fl-reference-manual-20260812.json"
)
OUTPUT = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "navigation"
    / "nav3-reference-compile-v1.json"
)
EXPECTED_REFERENCE_SHA256 = (
    "a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _operator_profile(context) -> tuple[str, float]:
    matches = [
        (revision, definition)
        for (asset_id, revision), definition in context.asset_definitions.items()
        if asset_id == "asset-operator"
    ]
    if len(matches) != 1:
        raise RuntimeError("The reference requires one exact operator definition.")
    revision, definition = matches[0]
    geometry = definition.get("geometry")
    polygons = geometry.get("footprintPolygons") if isinstance(geometry, dict) else None
    vertices = [
        (float(point["x"]), float(point["z"]))
        for polygon in polygons or []
        for point in polygon
        if isinstance(point, dict)
    ]
    if len(vertices) < 3:
        raise RuntimeError("The operator footprint is unavailable.")
    return revision, max(math.hypot(x, z) for x, z in vertices)


def build(*, repeats: int) -> dict:
    before = _sha(REFERENCE)
    if before != EXPECTED_REFERENCE_SHA256:
        raise RuntimeError("The archived manual reference SHA changed.")
    layout = json.loads(REFERENCE.read_text(encoding="ascii"))
    host = LocalFacilityLayoutHost(RUNTIME_ROOT, private_assets=True)
    context = host.service._spatial_context(
        host.principal(),
        LOCAL_SITE_ID,
        layout,
    )
    profile_revision, radius = _operator_profile(context)
    shell_revision = str(layout["sourceShellRef"]["shellRevision"])
    policy_revision = str(layout["policySetRef"]["policySetRevision"])
    samples = []
    packages = []
    for _ in range(repeats):
        started = perf_counter()
        package = compile_navigation_snapshot(
            layout,
            shell=context.shell,
            asset_definitions=context.asset_definitions,
            actor_class="pedestrian",
            actor_profile_revision=profile_revision,
            navigation_radius_meters=radius,
            shell_revision=shell_revision,
            policy_revision=policy_revision,
            evidence_authority=context.evidence_authority,
        )
        samples.append(round((perf_counter() - started) * 1000.0, 3))
        packages.append(package)
    fingerprints = {item["packageFingerprint"] for item in packages}
    if len(fingerprints) != 1:
        raise RuntimeError("Identical reference inputs produced different packages.")
    after = _sha(REFERENCE)
    if after != before:
        raise RuntimeError("NAV3 modified the archived manual reference.")
    package = packages[-1]
    sorted_samples = sorted(samples)
    p95_index = max(0, math.ceil(0.95 * len(sorted_samples)) - 1)
    evidence = {
        "schemaVersion": "facility-navigation-nav3-reference-evidence-v1",
        "referenceLayoutId": layout["layoutId"],
        "referenceSha256Before": before,
        "referenceSha256After": after,
        "referenceCounts": {
            "zones": len(layout["zones"]),
            "routes": len(layout["routes"]),
            "placements": len(layout["placements"]),
            "floorMarkings": len(layout["floorMarkings"]),
        },
        "actorProfileRevision": profile_revision,
        "navigationRadiusMeters": round(radius, 9),
        "repeatCount": repeats,
        "compileMilliseconds": samples,
        "p95Milliseconds": sorted_samples[p95_index],
        "summary": navigation_snapshot_summary(package),
        "metrics": package["metrics"],
        "directionFacts": {
            "strongComponentCount": package["directionFacts"]["strongComponentCount"],
            "oneWayEdgeCount": package["directionFacts"]["oneWayEdgeCount"],
        },
        "findingCodes": sorted({item["code"] for item in package["findings"]}),
        "packageFingerprint": package["packageFingerprint"],
        "canonicalBytes": package["canonicalBytes"],
        "qualification": package["qualification"],
        "checks": {
            "referenceUnchanged": before == after,
            "byteReproducible": len(fingerprints) == 1,
            "insideFrozenCompileBudget": sorted_samples[p95_index] <= 5000.0,
            "insidePackageBudget": package["canonicalBytes"] <= 16 * 1024 * 1024,
            "infrastructureOnlyWithoutAuthoredProgram": (
                package["metrics"]["sourceObstacleCount"] == 0
                and package["metrics"]["walkableRegionCount"] == 0
            ),
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    if not all(evidence["checks"].values()):
        raise RuntimeError("One or more NAV3 reference gates failed.")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    evidence = build(repeats=args.repeats)
    print(json.dumps(evidence["checks"], indent=2, sort_keys=True))
    print(json.dumps({
        "p95Milliseconds": evidence["p95Milliseconds"],
        "metrics": evidence["metrics"],
        "canonicalBytes": evidence["canonicalBytes"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
