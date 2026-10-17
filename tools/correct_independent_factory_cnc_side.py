"""Targeted CAD-reviewed CNC orientation correction. Dry-run unless --apply.

The observed work side is inferred from this exact GLB, not manufacturer-approved
interface, ergonomic, reach, clearance, or installed-configuration evidence.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.audit_independent_factory_layer2 import (
    LAYOUT_ID, SOURCE_ID, SITE, LocalFacilityLayoutHost,
    apply_facility_layout_operations, audit, heading_error, label,
    layout_revision, position, write_json, _rotate_vector,
)

BASE_REVISION = "5d6e4bbf96076a6752abfab93d7d763c3a9e0be6962c9bbafac6f17082239517"
ASSET_ID = "asset-cnc-mill"
ASSET_REVISION = "2c33d6899de6e048418bb848df6d36d96f2ac067cfb0b7aa5b0798efd5f90186"
MACHINE_IDS = tuple(f"pl-independent-{677 + 3 * i:04d}" for i in range(6))
MODEL_PATH = ROOT / "generated/industrial_assets/p0_spike/cnc_vmc/User Library-CNC Milling machine_colored.glb"


def reviewed_side_check(machine, operator):
    if (machine["assetId"], machine["assetDefinitionRevision"]) != (ASSET_ID, ASSET_REVISION):
        raise ValueError("No CAD-side review exists for this asset revision.")
    q = machine["transform"]["quaternion"]
    front = _rotate_vector((0, 0, -1), tuple(q[k] for k in ("x", "y", "z", "w")))
    m, p = position(machine), position(operator)
    dx, dz = p["x"] - m["x"], p["z"] - m["z"]
    distance = math.hypot(dx, dz)
    if distance < 1e-8:
        raise ValueError("Coincident machine/operator cannot establish a work side.")
    alignment = (dx * front[0] + dz * front[2]) / distance
    heading = heading_error(operator, m)
    return {"machineId": machine["placementId"], "operatorId": operator["placementId"],
            "observedLocalFront": "-Z", "worldFront": list(front),
            "operatorSideAlignment": round(alignment, 6),
            "operatorHeadingErrorDegrees": round(heading, 6),
            "passed": alignment > 0.99 and heading < 1,
            "evidenceStatus": "inferred", "approvedOperatingStation": False}


def checks(doc):
    by_label = {label(p): p for p in doc["placements"]}
    return [reviewed_side_check(p, by_label[label(p).split()[0] + " operator"])
            for p in doc["placements"] if p["assetId"] == ASSET_ID]


def correction_operations(doc):
    if doc["layoutId"] != LAYOUT_ID or layout_revision(doc) != BASE_REVISION:
        raise ValueError("Factory 02 revision changed; refusing to overwrite it.")
    machines = [p for p in doc["placements"] if p["assetId"] == ASSET_ID]
    if {p["placementId"] for p in machines} != set(MACHINE_IDS):
        raise ValueError("The reviewed six-machine set changed.")
    if not all(not row["passed"] and row["operatorSideAlignment"] == -1 for row in checks(doc)):
        raise ValueError("The reviewed wrong-side condition changed.")
    return [{"op": "rotate_placement", "placementId": p["placementId"],
             "quaternion": {"x": 0, "y": 1, "z": 0, "w": 0}, "movementKind": "user"}
            for p in machines]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "report.json").exists():
        raise ValueError("Choose a new evidence directory; existing results are immutable.")
    store = ROOT / ".runtime/facility-layout"
    directory = store / "layouts/local/site-local/layouts"
    target, original = directory / (LAYOUT_ID + ".json"), directory / (SOURCE_ID + ".json")
    before_bytes, original_bytes = target.read_bytes(), original.read_bytes()
    before = json.loads(before_bytes)
    default = json.loads((directory / "registry.json").read_text())["defaultLayoutId"]
    operations = correction_operations(before)
    after = apply_facility_layout_operations(before, operations,
        updated_at=datetime.now(timezone.utc).isoformat())["document"]
    # Prove the change is exactly six orientations, not translations or other edits.
    restored = deepcopy(after)
    prior = {p["placementId"]: p for p in before["placements"]}
    for p in restored["placements"]:
        if p["placementId"] in MACHINE_IDS:
            assert position(p) == position(prior[p["placementId"]])
            p["transform"]["quaternion"] = prior[p["placementId"]]["transform"]["quaternion"]
    restored["updatedAt"] = before["updatedAt"]
    assert restored == before
    assert len(checks(after)) == 6 and all(r["passed"] for r in checks(after))
    host = LocalFacilityLayoutHost(store, private_assets=True, private_asset_root=ROOT)
    try:
        principal = host.principal()
        catalog = {(a["assetId"], a["assetDefinitionRevision"]): a for a in host.authoritative_asset_catalog()}
        spatial = host.service._diagnose_spatial(principal, SITE, after)
        routing = host.service._diagnose_routing(principal, SITE, after)
        dependencies = host.service.validate_dependencies(principal, SITE, after).to_dict()
        host.service._require_spatially_valid(spatial)
        host.service._require_routing_valid(routing)
        report = {"status": "dry-run", "baseRevision": BASE_REVISION,
            "modelSha256": hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest(),
            "modelPath": str(MODEL_PATH.relative_to(ROOT)), "assetRevision": ASSET_REVISION,
            "evidence": "../before/cnc-minus-z.png shows the loading opening and control pendant; +/-X views confirm the operator is on the rear side.",
            "evidenceStatus": "inferred", "before": checks(before), "after": checks(after),
            "layer2": audit(after, catalog), "spatial": spatial, "routing": routing,
            "dependencies": dependencies, "changedMachineIds": list(MACHINE_IDS),
            "unchangedPlacements": 824, "onlySixOrientationsChanged": True,
            "originalSha256": hashlib.sha256(original_bytes).hexdigest(),
            "limitations": ["No certified machine interface, operating clearance, ergonomic reach or process capability conclusion.",
                            "This is a correction of the independently authored sheet, not a new Sage capability."]}
        write_json(args.output / "before.json", before)
        write_json(args.output / "after.json", after)
        write_json(args.output / "operations.json", operations)
        write_json(args.output / "report.json", report)
        if args.apply:
            if target.read_bytes() != before_bytes or original.read_bytes() != original_bytes:
                raise ValueError("Layout changed during review; no Save attempted.")
            saved = host.service.save_layout(principal, SITE, LAYOUT_ID, after, BASE_REVISION)
            write_json(args.output / "saved.json", saved["layout"])
            report.update(status="saved", savedRevision=saved["revision"])
        assert original.read_bytes() == original_bytes
        assert json.loads((directory / "registry.json").read_text())["defaultLayoutId"] == default
        report["originalUnchanged"] = True
        write_json(args.output / "report.json", report)
        print(json.dumps({"status": report["status"], "savedRevision": report.get("savedRevision"),
                          "changedMachines": len(operations), "checks": report["after"]}))
    finally:
        host.close()


if __name__ == "__main__":
    main()
