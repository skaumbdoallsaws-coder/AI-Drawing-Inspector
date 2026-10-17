"""Verify a real saved layout on a disposable store, never modifying the source."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.append(str(ROOT / ".runtime/codex-pilot-deps"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    source = args.layout.resolve()
    if not output.is_relative_to(ROOT / ".runtime") or output.exists():
        parser.error("Output must be a new directory under the repository .runtime")
    original = source.read_bytes()
    document = json.loads(original)
    output.mkdir(parents=True)
    store = output / "facility"
    authority_source = ROOT / ".runtime/facility-layout/authorities"
    if os.name == "nt":
        store = Path("\\\\?\\" + str(store))
        authority_source = Path("\\\\?\\" + str(authority_source))
    shutil.copytree(authority_source, store / "authorities")
    from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
    from ai_inspector.facility_layout.workstation_review import review_document
    from ai_inspector.facility_layout.operation_proposals import create
    host = LocalFacilityLayoutHost(store, private_assets=True, private_asset_root=ROOT)
    principal, site, layout_id = host.principal(), document["association"]["siteId"], document["layoutId"]
    try:
        host.layout_repository.create_layout(principal, site, document)
        current = host.service.get_layout(principal, site, layout_id)
        report = review_document(host.service, principal, site, document)
        (output / "review.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        diagnostics = host.service._diagnose_spatial(principal, site, document)
        assert not diagnostics["metrics"]["placementCollisions"]
        assert not diagnostics["metrics"]["obstructedAisleCount"]
        # Existing shop is the regression fixture; choose its mill by authored role,
        # not by a renderer index, and keep every unrelated transform unchanged.
        mill = next(p for p in document["placements"] if p.get("metadata", {}).get("role") == "machining_vf4_2")
        position = deepcopy(mill["transform"]["position"])
        position["x"] -= .1
        proposal = create(host.service, principal, site, layout_id, current["revision"],
            operations=[{"op": "move_placement", "placementId": mill["placementId"], "position": position}], edit_mode="direct")
        assert "workstationReview" in proposal["alternative"]["validation"]
        assert host.service.get_layout(principal, site, layout_id) == current

        def commit(candidate, key):
            binding = candidate["alternative"]["transactionBinding"]
            approval = host.service.approve_layout_proposal(principal, site, layout_id, candidate["proposalId"], binding,
                session_id="disposable-workstation-check", idempotency_key=key, explicit_approval=True)
            return host.service.apply_layout_proposal(principal, site, layout_id, approval["approvalToken"], binding,
                session_id="disposable-workstation-check", idempotency_key=key)

        saved = commit(proposal, "workstation-move")
        undo = create(host.service, principal, site, layout_id, saved["revision"], undo_receipt_id=saved["receipt"]["receiptId"])
        restored = commit(undo, "workstation-undo")
        assert restored["layout"]["placements"] == document["placements"]
        assert restored["layout"]["zones"] == document["zones"]
        assert restored["layout"]["floorMarkings"] == document["floorMarkings"]
        assert restored["layout"]["extensions"] == document["extensions"]
        summary = {"sourceSha256": hashlib.sha256(original).hexdigest(), "sourceUnchanged": source.read_bytes() == original,
            "assetCount": len(document["placements"]), "spatial": diagnostics["metrics"],
            "reviewStatus": report["status"], "workstations": report["totalWorkstations"],
            "findingCounts": report["findingCounts"], "realPreviewCommitUndo": True,
            "review": str(output / "review.json")}
        (output / "verification.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2))
    finally:
        host.close()
        assert source.read_bytes() == original, "Source layout changed during verification"


if __name__ == "__main__":
    main()
