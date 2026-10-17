"""Author Factory 02 process movement using the existing navigation contracts.

This is an offline, one-layout authoring tool, not a new Sage capability.
Semantic stops are inferred; geometry comes from the deterministic compiler.
Default is dry-run. --apply requires every journey to pass before guarded Save.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from shutil import copytree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.authority_repository import _native_fs_path
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools.audit_independent_factory_layer2 import operator_bindings, label, write_json

LAYOUT_ID = "fl-independent-factory-20260928"
MANUAL_ID = "fl-reference-manual-20260812"
SITE = "site-local"
SOURCE_HASH = "a217107d22b3d78b6fa186d532138d8d8a169280c47a1a39d4a568eb2dcac3a0"
EVIDENCE = "evidence:factory02-layer3-process-proposal-20260929"
STORE = ROOT / ".runtime/facility-layout"


def recipes(doc):
    """Use the assignments corrected in Layer 2; do not guess from proximity."""
    by_id = {p["placementId"]: p for p in doc["placements"]}
    names = {}
    for p in doc["placements"]:
        names.setdefault(label(p), []).append(p)

    def exact(name):
        matches = names.get(name, [])
        if len(matches) != 1:
            raise ValueError("Expected one placement for " + name)
        return matches[0]

    rows = []
    for binding in operator_bindings(doc):
        actor = by_id[binding["operatorId"]]
        tag = label(actor).split()[0]
        if binding["kind"] == "machine_observer":
            group, purpose = "machining", "Tool retrieval and return to the reviewed machine side"
            stops = [(exact(tag + " tools"), "north")]
        elif binding["kind"] == "gate_observer":
            group, purpose = "cell-staging", "External input/output staging check; no entry into the robot enclosure"
            stops = [(exact(tag + " input"), "south"), (exact(tag + " output"), "south")]
        elif tag.startswith("A"):
            group, purpose = "assembly", "Kit retrieval, bench work, test-bench visit and output staging"
            stops = [(exact(tag + " kit cart"), "south"), (actor, "home"),
                     (exact(tag + " test bench"), "south"), (exact(tag + " output lift"), "east")]
        elif tag.startswith("Q"):
            group, purpose = "inspection", "Sample retrieval, gauging-table visit and return to inspection workstation"
            stops = [(exact(tag + " sample cart"), "north"), (exact(tag + " gauging table"), "north")]
        else:
            group, purpose = "packing", "Packing output staging and pallet-truck visit"
            stops = [(exact(tag + " shipment"), "west"), (exact(tag + " pallet truck"), "west")]
        rows.append({"actor": actor, "target": by_id[binding["targetId"]],
                     "group": group, "purpose": purpose, "stops": stops})
    if len(rows) != 40:
        raise ValueError("The reviewed layout must contain all 40 assigned operators.")
    return rows


def anchor(placement, side):
    home = side == "home"
    return {
        "navigationAnchorId": "na-layer3-" + placement["placementId"] + "-" + side,
        "anchorKind": "actor_home" if home else "station_operate",
        "ownerRef": {"ownerKind": "placement", "ownerId": placement["placementId"]},
        "interactionKind": "none",
        "positionAuthority": "derived", "localPosition": None,
        "derivedPositionRef": {"sourceKind": "placement_transform" if home else "placement_access",
            "sourceId": placement["placementId"], "sourceRevision": placement["assetDefinitionRevision"]},
        "approachDirections": ["any" if home else side], "actorClasses": ["pedestrian"],
        "evidenceStatus": "derived", "evidence": ["evidence:deterministic-placement-access-v1"],
        "reviewStatus": "pending",
    }


def build_candidate(doc):
    if doc["layoutId"] != LAYOUT_ID or doc.get("extensions", {}).get("facilityNavigation"):
        raise ValueError("Requires the unchanged Factory 02 sheet without previous navigation intent.")
    operations, manifest = [], []
    base_revision = layout_revision(doc)
    nav = {"schemaVersion": 1, "anchors": [], "movementPrograms": [],
           "manualPathConstraints": [], "handoffPrograms": []}
    for row in recipes(doc):
        actor = row["actor"]
        pid = "nmp-layer3-" + actor["placementId"]
        stops = [(actor, "home"), *row["stops"]]
        ordered = [anchor(p, side) for p, side in stops]
        known = {a["navigationAnchorId"] for a in nav["anchors"]}
        for item in ordered:
            if item["navigationAnchorId"] not in known:
                nav["anchors"].append(item)
                known.add(item["navigationAnchorId"])
        program = {
            "movementProgramId": pid, "actorPlacementId": actor["placementId"], "actorClass": "pedestrian",
            "actorProfileRef": {"profileKind": "pedestrian", "profileId": "pedestrian-profile:" + actor["assetId"],
                                "profileRevision": actor["assetDefinitionRevision"]},
            "orderedStops": [{"stopId": f"nst-{pid}-{i}", "navigationAnchorId": a["navigationAnchorId"],
                              "interactionKind": "none", "required": True} for i, a in enumerate(ordered)],
            "loopMode": "task_cycle", "requiredRouteIds": [],
            "requiredAnchorIds": list(dict.fromkeys(a["navigationAnchorId"] for a in ordered)),
            "forbiddenZoneIds": [], "forbiddenRouteIds": [], "manualPathConstraintIds": [], "handoffProgramIds": [],
            "sourceRevisions": {"layout": base_revision, "actor_profile": actor["assetDefinitionRevision"]},
            "evidenceStatus": "inferred", "evidence": [EVIDENCE], "reviewStatus": "pending",
        }
        nav["movementPrograms"].append(program)
        op = {"op": "set_facility_navigation", "authoringSource": "sage_semantic", "facilityNavigation": deepcopy(nav)}
        operations.append(op)
        manifest.append({"movementProgramId": pid, "actorPlacementId": actor["placementId"],
                         "label": label(actor), "group": row["group"], "purpose": row["purpose"],
                         "workstationId": row["target"]["placementId"],
                         "stopPlacementIds": [p["placementId"] for p, _ in stops]})
    candidate = apply_facility_layout_operations(doc, operations)["document"]
    candidate["extensions"]["facilityProcessPresentation"] = {
        "schemaVersion": 1,
        "label": "Factory 02 - Proposed mechanical subassembly process",
        "evidenceStatus": "inferred", "reviewStatus": "pending", "productionEligible": False,
        "qualification": "Proposed station visits only; no material transformation, task timing, traffic or safety simulation.",
        "groups": [{"groupId": group, "label": title, "movementProgramIds": [
            r["movementProgramId"] for r in manifest if r["group"] in kinds
        ]} for group, title, kinds in [
            ("machining", "Machining - 12 operators", {"machining"}),
            ("cell-staging", "Robot-cell staging - 12 attendants", {"cell-staging"}),
            ("downstream", "Assembly, inspection and packing - 16 operators", {"assembly", "inspection", "packing"}),
        ]],
        "programs": manifest,
    }
    return candidate, operations, manifest


def validate_programs(host, before, candidate, output, manifest):
    service, principal = host.service, host.principal()
    base = layout_revision(before)
    results = []
    for row in manifest:
        start = time.perf_counter()
        request = {"movementProgramId": row["movementProgramId"], "prototypeMode": True}
        compiled = service.compile_navigation_snapshot(principal, SITE, LAYOUT_ID, base, request)
        package_id = compiled["summary"]["navigationPackageId"]
        planned = service.plan_actor_journey(principal, SITE, LAYOUT_ID, base,
            {**request, "navigationPackageId": package_id})
        summary = planned["summary"]
        journey = service.get_actor_journey(principal, SITE, LAYOUT_ID, summary["journeySolutionId"])
        write_json(output / (row["movementProgramId"] + ".json"), journey)
        results.append({**row, "summary": summary, "seconds": round(time.perf_counter()-start, 3)})
        write_json(output / "journeys.json", results)
        print(json.dumps({"actor": row["label"], "outcome": summary["outcome"], "seconds": results[-1]["seconds"]}), flush=True)
    return results


def publish_validated(output):
    """Promote the exact inspected copy only after complete recorded validation."""
    report = json.loads((output / "report.json").read_text())
    if report.get("status") != "validated" or report.get("accepted") != 40 or report.get("programs") != 40:
        raise ValueError("A complete validated forty-program run is required.")
    directory = STORE / "layouts/local/site-local/layouts"
    target, manual = directory / (LAYOUT_ID + ".json"), directory / (MANUAL_ID + ".json")
    original, manual_bytes = target.read_bytes(), manual.read_bytes()
    if hashlib.sha256(original).hexdigest() != SOURCE_HASH:
        raise ValueError("Factory 02 changed; refusing stale publication.")
    before = json.loads(original)
    candidate = json.loads((output / "validation-store/layouts/local/site-local/layouts" / (LAYOUT_ID + ".json")).read_text())
    expected, _, manifest = build_candidate(before)
    for field in set(expected) | set(candidate):
        if field != "updatedAt" and expected.get(field) != candidate.get(field):
            raise ValueError("Validated candidate differs from the authored intent: " + field)
    revision = layout_revision(candidate)
    for row in manifest:
        journey = json.loads((output / (row["movementProgramId"] + ".json")).read_text())
        if (journey.get("outcome") != "accepted" or journey.get("generationLayoutRevision") != revision
                or journey.get("movementProgramId") != row["movementProgramId"]
                or journey.get("actorPlacementId") != row["actorPlacementId"]):
            raise ValueError("Missing or stale accepted journey: " + row["label"])
    live = LocalFacilityLayoutHost(STORE, private_assets=True, private_asset_root=ROOT)
    try:
        if target.read_bytes() != original or manual.read_bytes() != manual_bytes:
            raise ValueError("Saved bytes changed before publication.")
        saved = live.service.save_layout(live.principal(), SITE, LAYOUT_ID, candidate, layout_revision(before))
    finally:
        live.close()
    if manual.read_bytes() != manual_bytes:
        raise ValueError("Original manual layout changed during publication.")
    receipt = {"status": "saved", "saveCalls": 1, "layoutId": LAYOUT_ID,
               "baseRevision": layout_revision(before), "validatedRevision": revision,
               "savedRevision": saved["revision"], "manualUnchanged": True,
               "manualSha256": hashlib.sha256(manual_bytes).hexdigest(),
               "geometryUnchanged": True, "programs": len(manifest)}
    write_json(output / "saved.json", saved["layout"])
    write_json(output / "publication.json", receipt)
    print(json.dumps(receipt), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--publish-validated", action="store_true")
    args = parser.parse_args()
    if args.publish_validated:
        if args.apply:
            parser.error("Choose --apply or --publish-validated, not both.")
        publish_validated(args.output)
        return
    args.output.mkdir(parents=True, exist_ok=False)
    directory = STORE / "layouts/local/site-local/layouts"
    target, manual = directory / (LAYOUT_ID + ".json"), directory / (MANUAL_ID + ".json")
    original_bytes, manual_bytes = target.read_bytes(), manual.read_bytes()
    if hashlib.sha256(original_bytes).hexdigest() != SOURCE_HASH:
        raise ValueError("Factory 02 changed since Layer 2/wall review; refusing overwrite.")
    before = json.loads(original_bytes)
    write_json(args.output / "before.json", before)
    print("Building navigation intent", flush=True)
    candidate, operations, manifest = build_candidate(before)
    write_json(args.output / "candidate.json", candidate)
    write_json(args.output / "operations.json", operations)
    write_json(args.output / "programs.json", manifest)
    print("Opening isolated facility host", flush=True)
    validation_store = args.output / "validation-store"
    copytree(_native_fs_path(STORE / "authorities"), _native_fs_path((validation_store / "authorities").resolve()))
    copytree(_native_fs_path(STORE / "layouts/local"), _native_fs_path((validation_store / "layouts/local").resolve()))
    host = LocalFacilityLayoutHost(validation_store, private_assets=True, private_asset_root=ROOT)
    report = {"status": "validating", "layoutId": LAYOUT_ID, "baseRevision": layout_revision(before),
              "authorship": "offline coordinate-free process proposal by coding agent; no live Sage conversation",
              "processAuthority": "inferred; pending review", "saveCalls": 0}
    try:
        deps = host.service.validate_dependencies(host.principal(), SITE, candidate)
        isolated = host.service.save_layout(host.principal(), SITE, LAYOUT_ID, candidate, layout_revision(before))
        candidate = isolated["layout"]
        results = validate_programs(host, candidate, candidate, args.output, manifest)
        report.update(dependencies=deps.to_dict(), programs=len(results),
                      accepted=sum(r["summary"]["outcome"] == "accepted" for r in results))
        assert report["accepted"] == report["programs"], "One or more movement programs were refused."
        for field in before:
            if field not in {"extensions", "updatedAt"}:
                assert candidate[field] == before[field], field
        report["status"] = "validated"
        if args.apply:
            if target.read_bytes() != original_bytes or manual.read_bytes() != manual_bytes:
                raise ValueError("Saved layouts changed during validation; refusing overwrite.")
            live = LocalFacilityLayoutHost(STORE, private_assets=True, private_asset_root=ROOT)
            try:
                saved = live.service.save_layout(live.principal(), SITE, LAYOUT_ID, candidate, layout_revision(before))
            finally:
                live.close()
            report.update(status="saved", savedRevision=saved["revision"], saveCalls=1)
            write_json(args.output / "saved.json", saved["layout"])
        assert manual.read_bytes() == manual_bytes
        report["manualUnchanged"] = True
    except Exception as error:
        report.update(status="failed", error=str(error), details=getattr(error, "details", None))
        raise
    finally:
        write_json(args.output / "report.json", report)
        host.close()
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
