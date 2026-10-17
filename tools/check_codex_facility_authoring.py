"""Offline authoring acceptance on a new copy of the saved Private Gym.

No server import, native process, model, credential access, or source-layout write.
The test-only approver exercises the existing HTTP approval/apply endpoints.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / ".runtime/facility-layout"
LAYOUT_RELATIVE = Path("layouts/local/site-local/layouts/fl-private-gym-20261007.json")
CASES = ("floor_surface_color", "floor_surface_outdoor", "floor_marking_generated_id", "zone_color",
         "ground_color", "perimeter_wall_color", "decal", "component_materials",
         "replace_asset", "multi_selection_appearance")
ENGINE_CASES = ("cell_group",)
COLOR = "#426b87"


def require(condition, code):
    if not condition:
        raise AssertionError(code)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def long_path(path):
    path = Path(path).absolute()
    return Path("\\\\?\\" + str(path)) if os.name == "nt" and not str(path).startswith("\\\\?\\") else path


def prepare_output(output, source):
    output, source = Path(output).absolute(), Path(source).resolve()
    for part in (output, *output.parents):
        require(not part.is_symlink() and not getattr(part, "is_junction", lambda: False)(),
                "output_link_refused")
    output = output.resolve()
    require(output != source and source not in output.parents and output not in source.parents,
            "source_output_overlap")
    require(not output.exists(), "output_must_be_new")
    output.mkdir(parents=True, exist_ok=False)
    return output


class SavedGym:
    """Own only disposable stores; load the actual private catalog read-only."""

    def __init__(self, output, source_root=SOURCE_ROOT):
        self.source_root = Path(source_root).resolve()
        self.source = self.source_root / LAYOUT_RELATIVE
        self.source_bytes = self.source.read_bytes()
        self.source_hash = hashlib.sha256(self.source_bytes).hexdigest()
        self.document = json.loads(self.source_bytes)
        require(self.document["layoutId"] == "fl-private-gym-20261007", "wrong_saved_fixture")
        self.output = prepare_output(output, self.source_root)
        self.host = None
        self.client = None
        try:
            store = long_path(self.output / "facility")
            shutil.copytree(long_path(self.source_root / "authorities"), store / "authorities")
            from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
            from ai_inspector.facility_layout.api import create_facility_layout_router
            from fastapi import FastAPI
            from fastapi.testclient import TestClient

            self.host = LocalFacilityLayoutHost(store, private_assets=True, private_asset_root=ROOT)
            self.principal = self.host.principal()
            self.site_id = self.document["association"]["siteId"]
            self.layout_id = self.document["layoutId"]
            self.initial = self.host.layout_repository.create_layout(
                self.principal, self.site_id, self.document)
            self.catalog = {row["assetId"]: row for row in self.host.authoritative_asset_catalog()}
            self.authority = {"principal": self.principal}
            app = FastAPI()
            app.include_router(create_facility_layout_router(service=self.host.service,
                principal_resolver=lambda request: self.authority["principal"]))
            self.client = TestClient(app, headers={"X-InspectorPro-Session": "authoring-test-approver"})
            self.url = f"/api/facility-layouts/{self.site_id}/{self.layout_id}"
            self.assert_source()
        except BaseException:
            self.close()
            raise

    def close(self):
        try:
            if self.client is not None:
                self.client.close()
            if self.host is not None:
                self.host.close()
        finally:
            self.assert_source()

    def assert_source(self):
        require(self.source.read_bytes() == self.source_bytes, "source_layout_changed")

    def current(self):
        return self.host.service.get_layout(self.principal, self.site_id, self.layout_id)

    def gateway(self, revision):
        from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
        return FacilityEditGateway(self.host.agent_runtime, self.principal, {
            "siteId": self.site_id, "layoutId": self.layout_id, "revision": revision},
            turn_id="offline-authoring-" + revision[:16])

    def preview(self, revision, *, operations=None, receipt_id=None, layer="gateway", gateway=None):
        if layer == "engine":
            from ai_inspector.facility_layout.operation_proposals import create
            result = create(self.host.service, self.principal, self.site_id, self.layout_id,
                revision, operations=operations, undo_receipt_id=receipt_id)
            proposal_id = result["proposalId"]
        else:
            gateway = gateway or self.gateway(revision)
            name, arguments = (("preview_facility_undo", {"receiptId": receipt_id}) if receipt_id else
                               ("preview_facility_operations", {"operations": operations}))
            result = asyncio.run(gateway.call(name, arguments))
            from jsonschema import Draft202012Validator
            from ai_inspector.codex_runtime.facility_tools import OUTPUT_SCHEMA
            spec = next(spec for spec in gateway.specs if spec["name"] == name)
            Draft202012Validator(spec.get("output_schema", OUTPUT_SCHEMA)).validate(result)
            require(result["ok"], "gateway:" + result.get("error", {}).get("code", "unknown"))
            require(result["data"]["saved"] is False and result["data"]["approvalRequired"],
                    "preview_not_proposal_only")
            require(gateway.proposal["proposalId"] == result["data"]["proposalId"], "proposal_reference")
            proposal_id = result["data"]["proposalId"]
        response = self.client.get(self.url + f"/proposals/{proposal_id}/preview")
        require(response.status_code == 200, "preview_http:" + str(response.status_code))
        return response.json()

    def approval(self, preview, key, *, explicit=True):
        return self.client.post(self.url + "/approvals", json={
            "proposalId": preview["proposalId"], "binding": preview["alternative"]["transactionBinding"],
            "idempotencyKey": key, "explicitApproval": explicit})

    def commit(self, preview, approval, key):
        return self.client.post(self.url + "/apply", json={
            "approvalToken": approval["approvalToken"],
            "binding": preview["alternative"]["transactionBinding"], "idempotencyKey": key})

    def approve_commit(self, preview, key):
        response = self.approval(preview, key)
        require(response.status_code == 200, "approval_http:" + str(response.status_code))
        approval = response.json()
        revision = self.current()["revision"]
        require(revision == preview["alternative"]["transactionBinding"]["baseRevision"],
                "approval_changed_saved_revision")
        response = self.commit(preview, approval, key)
        require(response.status_code == 200, "commit_http:" + str(response.status_code))
        committed = response.json()
        replay = self.commit(preview, approval, key)
        require(replay.status_code == 200 and replay.json()["replayed"], "commit_not_idempotent")
        require(replay.json()["revision"] == committed["revision"], "replay_changed_revision")
        receipt_id = committed["receipt"]["receiptId"]
        receipt = self.client.get(self.url + "/receipts/" + receipt_id)
        require(receipt.status_code == 200 and receipt.json()["receiptId"] == receipt_id,
                "receipt_not_persisted")
        self.assert_source()
        return committed


def case_operations(gym, name, *, gateway=None):
    layout = gym.current()["layout"]
    ext = layout["extensions"]
    chair = next(row for row in layout["placements"] if row["assetId"] == "asset-chair-black")
    if name in {"floor_surface_color", "floor_surface_outdoor"}:
        surfaces = deepcopy(ext.get("facilityFloorSurfaces", {"version": 1, "surfaces": []}))
        points = ((1, -5), (2, -5), (2, -4), (1, -4)) if name == "floor_surface_outdoor" else ((1, 1), (2, 1), (2, 2), (1, 2))
        surfaces["surfaces"].append({"surfaceId": "fs-codex-authoring-check", "label": "Authoring check",
            "boundary": [{"x": x, "z": z} for x, z in points],
            "elevation": 0, "material": "rubber", "color": COLOR, "roughness": .7})
        return [{"op": "set_floor_surfaces", "surfaces": surfaces}]
    if name == "floor_marking_generated_id":
        marking = deepcopy(layout["floorMarkings"][0])
        marking.pop("markingId")
        marking.update(label="Authoring check", fillColor=COLOR, strokeColor=COLOR, metadata={})
        return [{"op": "add_floor_marking", "floorMarking": marking}]
    if name in {"zone_color", "cell_group"}:
        zone = layout["zones"][0]
        extensions = deepcopy(zone.get("extensions", {}))
        if name == "zone_color":
            extensions.setdefault("style", {})["fillColor"] = COLOR
        else:
            extensions["cellGroup"] = {"schemaVersion": 1, "groupKind": "manufacturing_cell",
                "membership": "geometric", "envelopePadding": 0,
                "autoNumber": {"seriesId": "codex-authoring-cells", "baseName": "Authoring cell",
                    "prefix": "", "start": 1, "padding": 2, "sequence": 1},
                "functionalInterfaces": {"gate": {"side": "north", "evidenceStatus": "authored"}}}
        return [{"op": "edit_zone", "zoneId": zone["zoneId"], "patch": {"extensions": extensions}}]
    if name == "ground_color":
        ground = deepcopy(ext["facilityGround"])
        ground["surfaces"][0]["color"] = COLOR
        return [{"op": "set_ground", "ground": ground}]
    if name == "perimeter_wall_color":
        settings = deepcopy(ext["facilityPerimeterWalls"]["settings"])
        settings["interiorColor"] = COLOR
        return [{"op": "set_perimeter_walls", "wallSettings": settings}]
    if name == "decal":
        existing = ext["facilityPerimeterWalls"]["settings"]["exteriorFinish"]["fittedArtworks"][0]
        image = (ROOT / existing["imagePath"].lstrip("/")).resolve()
        require(image.is_relative_to(ROOT / "generated/facility-wall-art") and image.is_file(),
                "saved_decal_image_unavailable")
        require(digest(image) == image.stem, "saved_decal_image_hash_mismatch")
        decals = deepcopy(ext.get("facilityDecals", {"version": 1, "artworks": []}))
        decals["artworks"].append({"artworkId": "codex-authoring-check", "label": "Authoring check",
            "imagePath": existing["imagePath"], "target": deepcopy(existing["target"]),
            "uv": [0, 0, 1, 1], "region": [.1, .1, .3, .3], "coverage": 1})
        return [{"op": "set_decals", "decals": decals}]
    if name == "component_materials":
        arguments = {"placementId": chair["placementId"], "representation": "overview", "pageSize": 1}
        if gateway is not None:
            result = asyncio.run(gateway.call("inspect_facility_components", arguments))
            require(result["ok"], "component_discovery_failed")
            inspected = result["data"]
        else:
            from ai_inspector.codex_runtime.component_inventory import inspect_components
            inspected = inspect_components(gym.host.agent_runtime, gym.principal, {
                "siteId": gym.site_id, "layoutId": gym.layout_id,
                "revision": gym.current()["revision"]}, arguments)
        require(inspected["slots"] and len(inspected["visualSha256"]) == 64, "real_visual_slots_required")
        require(inspected["componentRolesVerified"] is False, "unexpected_component_role_claim")
        return [{"op": "set_component_materials", "placementId": chair["placementId"],
            "visualSha256": inspected["visualSha256"], "materials": {
            "representation": inspected["representation"], "overrides": [
                {"key": inspected["slots"][0]["key"], "color": COLOR, "roughness": .4, "metalness": .2}]}}]
    if name == "replace_asset":
        replacement = gym.catalog["asset-chair-black-reception-apex"]
        return [{"op": "replace_asset", "placementId": chair["placementId"],
            "assetId": replacement["assetId"], "assetDefinitionRevision": replacement["assetDefinitionRevision"],
            "keepAppearance": True}]
    if name == "multi_selection_appearance":
        ids = [row["placementId"] for row in layout["placements"] if row["assetId"] == "asset-chair-black"][:2]
        require(len(ids) == 2, "two_saved_chairs_required")
        return [{"op": "set_appearance", "placementIds": ids, "color": COLOR}]
    raise ValueError("unknown_authoring_case")


def assert_effect(name, operations, before, after, preview):
    op = operations[0]
    require(before != after, "no_saved_change")
    if name == "floor_marking_generated_id":
        require("markingId" not in op and "markingId" not in op["floorMarking"], "caller_supplied_id")
        old = {row["markingId"] for row in before["floorMarkings"]}
        added = [row for row in after["floorMarkings"] if row["markingId"] not in old]
        require(len(added) == 1 and added[0]["fillColor"] == COLOR, "marking_not_created")
        require(preview["alternative"]["operationReceipt"]["createdIds"] == [added[0]["markingId"]],
                "generated_id_not_bound")
        expected = deepcopy(op["floorMarking"])
        expected["markingId"] = added[0]["markingId"]
        require(added[0] == expected, "marking_payload_changed")
    elif name in {"floor_surface_color", "floor_surface_outdoor", "ground_color", "perimeter_wall_color", "decal"}:
        key, field = {"floor_surface_color": ("facilityFloorSurfaces", "surfaces"),
            "floor_surface_outdoor": ("facilityFloorSurfaces", "surfaces"),
            "ground_color": ("facilityGround", "ground"),
            "perimeter_wall_color": ("facilityPerimeterWalls", "wallSettings"),
            "decal": ("facilityDecals", "decals")}[name]
        value = after["extensions"][key]
        require((value["settings"] if name == "perimeter_wall_color" else value) == op[field],
                "extension_edit_not_exact")
        require(after["placements"] == before["placements"], "unrelated_placements_changed")
    elif name in {"zone_color", "cell_group"}:
        zone = next(row for row in after["zones"] if row["zoneId"] == op["zoneId"])
        require(zone["extensions"] == op["patch"]["extensions"], "zone_style_not_saved")
        require(after["placements"] == before["placements"], "zone_edit_moved_placements")
    else:
        ids = op.get("placementIds", [op.get("placementId")])
        for old, new in zip(before["placements"], after["placements"], strict=True):
            require(old["placementId"] == new["placementId"], "placement_identity_changed")
            if old["placementId"] not in ids:
                require(old == new, "unrelated_placement_changed")
            else:
                require(old["transform"] == new["transform"], "appearance_or_replacement_moved_asset")
                if name == "component_materials":
                    require(new["componentMaterials"] == op["materials"], "material_not_saved")
                elif name == "replace_asset":
                    require(new["assetId"] == op["assetId"] and
                            new["assetDefinitionRevision"] == op["assetDefinitionRevision"], "replacement_not_saved")
                else:
                    require(new["appearance"] == {"color": COLOR}, "multi_selection_not_saved")


def round_trip(gym, name, *, layer="gateway"):
    started = time.monotonic()
    before = gym.current()
    original = deepcopy(gym.initial["layout"])
    original["updatedAt"] = before["layout"]["updatedAt"]
    require(original == before["layout"], "previous_case_did_not_restore_copy")
    gateway = gym.gateway(before["revision"]) if layer == "gateway" else None
    operations = case_operations(gym, name, gateway=gateway)
    preview = gym.preview(before["revision"], operations=operations, layer=layer, gateway=gateway)
    require(gym.current() == before, "preview_wrote_layout")
    gym.assert_source()
    if name == "floor_marking_generated_id":
        repeated = gym.preview(before["revision"], operations=operations, layer=layer, gateway=gateway)
        require(repeated["proposalId"] == preview["proposalId"], "generated_id_preview_not_deterministic")
        require(repeated["alternative"]["transactionBinding"] == preview["alternative"]["transactionBinding"],
                "generated_id_diff_not_deterministic")
    denied = gym.approval(preview, name + "-not-approved", explicit=False)
    require(denied.status_code >= 400 and gym.current() == before, "implicit_approval_allowed")
    committed = gym.approve_commit(preview, name + "-commit")
    require(committed["revision"] != before["revision"], "commit_revision_unchanged")
    ghost = deepcopy(preview["alternative"]["ghostPreview"]["layout"])
    ghost["updatedAt"] = committed["layout"]["updatedAt"]
    require(ghost == committed["layout"], "committed_content_differs_from_preview")
    assert_effect(name, operations, before["layout"], committed["layout"], preview)
    undo = gym.preview(committed["revision"], receipt_id=committed["receipt"]["receiptId"], layer=layer)
    require(gym.current()["revision"] == committed["revision"], "undo_preview_wrote_layout")
    require(undo["alternative"]["strategy"] == "exact-undo-v1", "undo_not_receipt_bound")
    restored = gym.approve_commit(undo, name + "-undo")
    expected = deepcopy(before["layout"])
    expected["updatedAt"] = restored["layout"]["updatedAt"]
    require(expected == restored["layout"], "undo_not_exact_except_updatedAt")
    require(gym.current()["layout"] == restored["layout"], "restore_not_persisted")
    gym.assert_source()
    return {"case": name, "layer": layer, "status": "passed", "elapsedSeconds": round(time.monotonic()-started, 3),
        "proposalId": preview["proposalId"], "receiptId": committed["receipt"]["receiptId"],
        "undoReceiptId": restored["receipt"]["receiptId"], "sourceUnchanged": True,
        "restoredExactExceptUpdatedAt": True, "testOnlyExplicitApprover": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--dependency-dir", type=Path)
    parser.add_argument("--layer", choices=("gateway", "engine"), default="gateway")
    parser.add_argument("--case", choices=CASES + ENGINE_CASES, action="append", dest="cases")
    args = parser.parse_args(argv)
    if not args.output_root.resolve().is_relative_to(ROOT / ".runtime"):
        parser.error("Output must be a new directory inside the repository .runtime")
    sys.path.insert(0, str(ROOT))
    if args.dependency_dir:
        import site
        site.addsitedir(str(args.dependency_dir.resolve()))
    gym = SavedGym(args.output_root, args.source_root)
    evidence = {"status": "running", "paidInference": False, "nativeAppStarted": False,
        "sourceSha256": gym.source_hash, "layer": args.layer,
        "savedCounts": {key: len(gym.document[key]) for key in ("zones", "placements", "floorMarkings")},
        "cases": []}
    try:
        for name in args.cases or CASES:
            try:
                result = round_trip(gym, name, layer=args.layer)
            except Exception as error:
                result = {"case": name, "status": "failed", "errorType": type(error).__name__,
                    "code": getattr(error, "code", str(error) if isinstance(error, AssertionError) else "authoring_check_failed"),
                    "trace": [f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
                              for frame in traceback.extract_tb(error.__traceback__)[-5:]]}
                evidence["cases"].append(result)
                print(json.dumps(result), flush=True)
                raise
            evidence["cases"].append(result)
            print(json.dumps(result), flush=True)
        evidence["status"] = "passed"
    except Exception:
        evidence["status"] = "failed"
    finally:
        try:
            gym.close()
            evidence["sourceUnchanged"] = True
        except Exception:
            evidence["sourceUnchanged"] = False
            evidence["status"] = "failed"
        (gym.output / "authoring-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
