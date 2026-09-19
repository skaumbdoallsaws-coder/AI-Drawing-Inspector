from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.canonical import (
    canonicalize_layout,
    layout_revision,
)
from ai_inspector.facility_layout.design_base import capture_facility_design_base
from ai_inspector.facility_layout.design_brief import (
    canonical_design_bytes,
    create_facility_design_brief,
    design_revision,
)
from ai_inspector.facility_layout.design_candidates import (
    deterministic_design_operation_builder,
)
from ai_inspector.facility_layout.design_evaluator import route_path_distance_meters
from ai_inspector.facility_layout.design_fixture import (
    REFERENCE_MANUAL_LAYOUT_PATH,
    REVIEWED_REFERENCE_MATERIAL_TRAVEL_FIXTURE_PATH,
    REVIEWED_REFERENCE_MATERIAL_TRAVEL_LAYOUT_ID,
    reference_manual_layout,
    reviewed_material_travel_source_provider,
    reviewed_reference_material_travel_layout,
)
from ai_inspector.facility_layout.design_intent import (
    FACILITY_DESIGN_INTENT_SCHEMA_VERSION,
    classify_facility_design_turn,
    compile_facility_design_brief_body,
)
from ai_inspector.facility_layout.design_repository import FacilityDesignRepository
from ai_inspector.facility_layout.design_runtime import (
    FacilityDesignRuntime,
)
from ai_inspector.facility_layout.design_source import (
    build_facility_design_source_bundle,
)
from ai_inspector.facility_layout.design_service import (
    FACILITY_DESIGN_EDITOR_FRAME_VERSION,
    FacilityDesignLoopService,
    FacilityDesignServiceError,
)
from ai_inspector.facility_layout.facility_draft_lease import (
    FacilityDraftLeaseRepository,
)
from ai_inspector.facility_layout.feature_flags import FacilityLayoutFeatureFlags
from ai_inspector.facility_layout.routing import persisted_route_fingerprint


ROOT = Path(__file__).resolve().parents[1]
APPROVAL_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "design_loop"
    / "fdl-reference-approval-receipt-v1.json"
)
PRIMARY_FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "design_loop"
    / "fdl-material-travel-v1.json"
)
GENERALIZATION_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "design_loop"
    / "fdl9-generalization-controls-v1.json"
)
CREATED_AT = "2026-09-06T00:00:00Z"


def _objective_fixture() -> dict:
    return json.loads(
        REVIEWED_REFERENCE_MATERIAL_TRAVEL_FIXTURE_PATH.read_text(
            encoding="utf-8"
        )
    )


def _reference_base_and_brief() -> tuple[dict, dict]:
    fixture = _objective_fixture()
    layout = reviewed_reference_material_travel_layout(site_id="site-local")
    revision = layout_revision(layout)
    base = capture_facility_design_base(
        base_id="fdb-reference-material-travel-v1",
        base_kind="saved_layout",
        tenant_id="local",
        site_id="site-local",
        workspace_id="workspace-local",
        document=layout,
        saved_layout_revision=revision,
        source_ref={
            "repositoryRecordRevision": revision,
            "savedLayoutRevision": revision,
        },
        captured_at=CREATED_AT,
    )
    transfer = fixture["transferEvidence"]
    intent = {
        "schema_version": FACILITY_DESIGN_INTENT_SCHEMA_VERSION,
        "operation": "create_material_travel_brief",
        "source_label": transfer["sourcePlacementId"],
        "target_label": transfer["targetPlacementId"],
        "loaded_trips_per_shift": transfer["loadedTripsPerShift"][
            "loadedTripsPerShift"
        ],
        "shift_name": "Reference Day Shift",
        "locked_entity_labels": [
            transfer["sourcePlacementId"],
            transfer["targetPlacementId"],
        ],
        "movable_placement_labels": [],
        "mutable_route_labels": transfer["routeIds"],
    }
    body = compile_facility_design_brief_body(
        intent=intent,
        design_base=base,
        source_turn_ref="turn-reference-1",
    )
    brief = create_facility_design_brief(
        brief_id="fdbf-reference-material-travel-v1",
        semantic_body=body,
        source_turn_refs=["turn-reference-1"],
        principal_id="shadrack",
        created_at=CREATED_AT,
    )
    return base, brief


def _points(values: list[list[float]]) -> list[dict[str, float]]:
    return [
        {"x": float(point[0]), "y": 0.0, "z": float(point[1])}
        for point in values
    ]


def _authoritative_catalog_assets(records: list[dict]) -> list[dict]:
    result = []
    for raw in records:
        connectors = []
        if raw["assetId"] == "asset-fifo-buffer":
            connectors = [
                {
                    "connectorId": "material-output",
                    "connectorKind": "material",
                    "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "facing": {"x": 1.0, "y": 0.0, "z": 0.0},
                    "role": "output",
                    "allowedRouteKinds": ["material"],
                    "evidenceStatus": "authored",
                },
                {
                    "connectorId": "material-input",
                    "connectorKind": "material",
                    "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "facing": {"x": -1.0, "y": 0.0, "z": 0.0},
                    "role": "input",
                    "allowedRouteKinds": ["material"],
                    "evidenceStatus": "authored",
                },
            ]
        result.append(
            {
                "assetId": raw["assetId"],
                "assetDefinitionRevision": raw["assetDefinitionRevision"],
                "definition": {
                    "documentKind": "industrial_asset_definition",
                    "assetId": raw["assetId"],
                    "geometry": deepcopy(raw["geometry"]),
                    "connectors": connectors,
                },
            }
        )
    return result


def _generalization_case(case: dict) -> tuple[dict, dict, dict, list[dict]]:
    fixture = json.loads(PRIMARY_FIXTURE_PATH.read_text(encoding="utf-8"))
    layout = deepcopy(fixture["facilityLayout"])
    namespace = case["labelNamespace"]
    layout["layoutId"] = f"fl-fdl9-{case['caseId']}"
    layout["displayName"] = f"{namespace} FDL9 Control"
    layout["association"]["siteId"] = "site-local"
    layout["association"]["areaId"] = f"area-fdl9-{case['caseId']}"
    layout["coordinateFrame"]["datumId"] = f"datum-fdl9-{case['caseId']}"
    layout["placements"][0]["transform"]["position"] = {
        "x": 4.0,
        "y": 0.0,
        "z": 14.0,
    }
    layout["placements"][1]["transform"]["position"] = {
        "x": 56.0,
        "y": 0.0,
        "z": 14.0,
    }
    if case["caseId"] == "loop-multiple-buffers":
        layout["placements"][5]["transform"]["position"] = {
            "x": 44.0,
            "y": 0.0,
            "z": 14.0,
        }
    for index, zone in enumerate(layout["zones"], start=1):
        zone["label"] = f"{namespace} Area {index}"
    for index, placement in enumerate(layout["placements"], start=1):
        placement["metadata"] = {
            "instanceLabel": f"{namespace} Asset {index}"
        }
    for index, route in enumerate(layout["routes"], start=1):
        route["label"] = f"{namespace} Flow {index}"
        route["centerline"] = _points(case["baselineRoutes"][route["routeId"]])
        if route["routeId"] != fixture["transferEvidence"]["routeIds"][0]:
            route["sourceEndpoint"] = {
                "kind": "world_point",
                "position": deepcopy(route["centerline"][0]),
            }
        if route["routeId"] != fixture["transferEvidence"]["routeIds"][-1]:
            route["targetEndpoint"] = {
                "kind": "world_point",
                "position": deepcopy(route["centerline"][-1]),
            }
        route["routeFingerprint"] = persisted_route_fingerprint(route)
    obstacle = (
        [28.0, 0.0, 32.0, 30.0]
        if case["caseId"] == "sealed-transfer"
        else case.get("obstacleBounds")
    )
    if obstacle:
        x1, z1, x2, z2 = (float(value) for value in obstacle)
        layout["zones"].append(
            {
                "zoneId": f"zn-fdl9-{case['caseId']}-barrier",
                "zoneType": "exclusion",
                "label": f"{namespace} Barrier",
                "boundary": [
                    {"x": x1, "z": z1},
                    {"x": x2, "z": z1},
                    {"x": x2, "z": z2},
                    {"x": x1, "z": z2},
                ],
                "floorElevation": 0.0,
                "anchors": [],
                "evidence": [],
            }
        )
    catalog_assets = deepcopy(fixture["catalogAssets"])
    template = deepcopy(layout["placements"][-1])
    if int(case["extraPlacementCount"]):
        layout["extensions"]["facilityPlan"].update(
            {"widthMeters": 120.0, "depthMeters": 80.0}
        )
        template["assetId"] = "asset-fdl9-dense-marker"
        template["assetDefinitionRevision"] = "05" * 32
        catalog_assets.append(
            {
                "assetId": "asset-fdl9-dense-marker",
                "assetDefinitionRevision": "05" * 32,
                "geometry": {
                    "obb": {
                        "center": {"x": 0.0, "y": 0.1, "z": 0.0},
                        "halfExtents": {"x": 0.2, "y": 0.1, "z": 0.2},
                        "yawRadians": 0.0,
                    }
                },
            }
        )
    for index in range(int(case["extraPlacementCount"])):
        item = deepcopy(template)
        item["placementId"] = f"pl-{case['caseId']}-dense-{index + 1:04d}"
        item["transform"]["position"] = {
            "x": float(65 + (index % 25) * 2),
            "y": 0.0,
            "z": float(2 + ((index // 25) % 25) * 3),
        }
        item["metadata"] = {
            "instanceLabel": f"{namespace} Dense Unit {index + 1:04d}"
        }
        layout["placements"].append(item)
    buffer_template = deepcopy(layout["placements"][2])
    for index in range(int(case["extraBufferCount"])):
        item = deepcopy(buffer_template)
        item["placementId"] = f"pl-{case['caseId']}-buffer-{index + 1}"
        item["transform"]["position"] = {
            "x": 4.0,
            "y": 0.0,
            "z": float(4 + index * 8),
        }
        item["metadata"] = {
            "instanceLabel": f"{namespace} Candidate Buffer {index + 1}"
        }
        layout["placements"].append(item)
    layout = canonicalize_layout(layout)

    process_map = deepcopy(fixture["processMap"])
    for index, node in enumerate(process_map["nodes"], start=1):
        node["label"] = f"{namespace} Operation {index}"
    transfer = deepcopy(fixture["transferEvidence"])
    transfer["loadedTripsPerShift"] = {
        "loadedTripsPerShift": int(case["loadedTripsPerShift"]),
        "shiftId": f"shift-{case['caseId']}",
        "evidenceRef": f"evidence-{case['caseId']}-frequency",
        "evidenceStatus": "authored",
        "reviewStatus": "accepted",
    }
    revision = layout_revision(layout)
    base = capture_facility_design_base(
        base_id=f"fdb-{case['caseId']}",
        base_kind="saved_layout",
        tenant_id="local",
        site_id="site-local",
        workspace_id="workspace-local",
        document=layout,
        saved_layout_revision=revision,
        source_ref={
            "repositoryRecordRevision": revision,
            "savedLayoutRevision": revision,
        },
        captured_at=CREATED_AT,
    )
    intent = {
        "schema_version": FACILITY_DESIGN_INTENT_SCHEMA_VERSION,
        "operation": "create_material_travel_brief",
        "source_label": transfer["sourcePlacementId"],
        "target_label": transfer["targetPlacementId"],
        "loaded_trips_per_shift": int(case["loadedTripsPerShift"]),
        "shift_name": f"{namespace} Shift",
        "locked_entity_labels": [
            "pl-cnc-mill-03",
            "pl-inspection-station-02",
        ],
        "movable_placement_labels": [],
        "mutable_route_labels": transfer["routeIds"],
    }
    body = compile_facility_design_brief_body(
        intent=intent,
        design_base=base,
        source_turn_ref=f"turn-{case['caseId']}",
    )
    brief = create_facility_design_brief(
        brief_id=f"fdbf-{case['caseId']}",
        semantic_body=body,
        source_turn_refs=[f"turn-{case['caseId']}"],
        principal_id="shadrack",
        created_at=CREATED_AT,
    )
    source_bundle = build_facility_design_source_bundle(
        design_base=base,
        design_brief=brief,
        asset_definitions=_authoritative_catalog_assets(catalog_assets),
        process_map_resolver=lambda _product_id, _map_id, _revision: process_map,
    )
    return base, brief, source_bundle, []


def _editor_frame(base: dict) -> dict:
    revision = base["layoutRevision"]
    return {
        "schemaVersion": FACILITY_DESIGN_EDITOR_FRAME_VERSION,
        "baseLayout": deepcopy(base["document"]),
        "baseRevision": revision,
        "draftLayout": deepcopy(base["document"]),
        "draftRevision": revision,
        "batches": [],
        "cursor": 0,
        "selectedIds": [],
        "generatedDraft": None,
        "recentReceiptIds": [],
        "activeProposal": None,
        "editorGenerationId": "fdl9-editor-generation",
        "commandJournalHash": "7" * 64,
    }


def test_reference_archive_and_review_copy_preserve_all_geometry() -> None:
    fixture = _objective_fixture()
    archive_bytes = REFERENCE_MANUAL_LAYOUT_PATH.read_bytes()
    source = reference_manual_layout()
    review = reviewed_reference_material_travel_layout(site_id="site-local")

    assert layout_revision(source) == fixture["sourceLayoutRevision"]
    assert json.loads(archive_bytes)["layoutId"] == fixture["sourceLayoutId"]
    assert len(source["zones"]) == 45
    assert len(source["placements"]) == fixture["expected"][
        "sourcePlacementCount"
    ]
    assert len(source["routes"]) == fixture["expected"]["sourceRouteCount"]
    assert len(source["floorMarkings"]) == fixture["expected"][
        "sourceMarkingCount"
    ]
    for collection in ("zones", "placements", "routes", "floorMarkings"):
        assert canonical_design_bytes(source[collection]) == canonical_design_bytes(
            review[collection]
        )
    assert review["processBindings"] == fixture["processBindings"]
    assert REFERENCE_MANUAL_LAYOUT_PATH.read_bytes() == archive_bytes


def test_reference_objective_has_a_revision_bound_named_approval() -> None:
    fixture = _objective_fixture()
    receipt = json.loads(APPROVAL_PATH.read_text(encoding="utf-8"))
    unsigned = deepcopy(receipt)
    unsigned.pop("receiptRevision")

    assert hashlib.sha256(
        REVIEWED_REFERENCE_MATERIAL_TRAVEL_FIXTURE_PATH.read_bytes()
    ).hexdigest() == receipt["fixtureFileSha256"]
    assert design_revision(unsigned) == receipt["receiptRevision"]
    assert receipt["approver"]["principalId"] == "shadrack"
    assert receipt["decision"] == "accepted_for_test_gold"
    assert receipt["productionEligible"] is False
    assert fixture["authority"]["approverPrincipalId"] == "shadrack"


def test_reference_source_provider_rejects_any_geometry_drift() -> None:
    layout = reviewed_reference_material_travel_layout(site_id="site-local")
    source = reviewed_material_travel_source_provider(
        None,
        "site-local",
        REVIEWED_REFERENCE_MATERIAL_TRAVEL_LAYOUT_ID,
        {"document": layout},
        {},
    )
    assert source["candidateAuthority"] == "reviewed_reference_test_gold"
    assert source["reviewedCandidateRecipes"] == []

    changed = deepcopy(layout)
    changed["placements"][0]["transform"]["position"]["x"] += 0.001
    with pytest.raises(FacilityDesignServiceError) as caught:
        reviewed_material_travel_source_provider(
            None,
            "site-local",
            REVIEWED_REFERENCE_MATERIAL_TRAVEL_LAYOUT_ID,
            {"document": changed},
            {},
        )
    assert caught.value.code == "facility_design_reviewed_fixture_mismatch"


def test_reference_preview_measures_scale_and_refuses_to_invent_improvement(
    tmp_path: Path,
) -> None:
    fixture = _objective_fixture()
    source_archive_bytes = REFERENCE_MANUAL_LAYOUT_PATH.read_bytes()
    base, brief = _reference_base_and_brief()
    repository = FacilityDesignRepository(tmp_path / "reference-design")
    repository.create_brief(
        tenant_id="local",
        site_id="site-local",
        brief=brief,
    )
    source = reviewed_material_travel_source_provider(
        None,
        "site-local",
        REVIEWED_REFERENCE_MATERIAL_TRAVEL_LAYOUT_ID,
        base,
        brief,
    )
    runtime = FacilityDesignRuntime(repository)
    started = runtime.start_preview(
        tenant_id="local",
        site_id="site-local",
        workspace_id="workspace-local",
        design_base=base,
        design_brief=brief,
        source_bundle=source,
        provider="deterministic",
        model="fdl-reference-proof-v1",
        reasoning_effort=None,
        client_generation_id="reference-proof-generation",
        run_id="fdlr-reference-proof",
    )
    result = runtime.continue_preview(
        tenant_id="local",
        site_id="site-local",
        run_id=started["run"]["runId"],
    )
    run = result["run"]
    assert result["continuationRequired"] is False
    assert run["status"] == "blocked"
    assert run["terminalReason"] == "facility_design_route_endpoint_unavailable"
    summary = runtime.summary(result)
    assert summary["terminalReason"] == "facility_design_route_endpoint_unavailable"
    assert summary["baseline"] is None
    assert "snapshot" in run["stageOutputs"]
    assert "baseline" not in run["stageOutputs"]
    assert run["proposalRefs"] == []
    assert run["candidateResults"] == []
    assert {
        finding["code"] for finding in run["findings"]
    } == {"facility_design_route_endpoint_unavailable"}
    assert route_path_distance_meters(
        base["document"], fixture["transferEvidence"]["routeIds"]
    ) == pytest.approx(
        fixture["expected"]["baselineLoadedRouteDistanceMeters"], abs=1e-12
    )
    assert len(base["document"]["placements"]) == 827
    assert REFERENCE_MANUAL_LAYOUT_PATH.read_bytes() == source_archive_bytes


def test_fdl9_generalization_controls_are_frozen_reviewed_and_label_distinct() -> None:
    suite = json.loads(GENERALIZATION_PATH.read_text(encoding="utf-8"))
    primary = json.loads(PRIMARY_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert design_revision(suite["cases"]) == suite["caseContentSha256"]
    assert suite["classification"] == "held_out_post_contract"
    assert suite["authority"]["approverPrincipalId"] == "shadrack"
    assert suite["authority"]["productionEligible"] is False
    assert sum(case["expectedOutcome"] == "positive" for case in suite["cases"]) == 4
    assert sum(case["expectedOutcome"] == "blocked" for case in suite["cases"]) == 1
    assert {case["topology"] for case in suite["cases"]} >= {
        "straight",
        "obstacle_detour",
        "spine",
        "loop",
    }
    assert any(case["extraPlacementCount"] > 500 for case in suite["cases"])
    assert any(case["extraBufferCount"] > 1 for case in suite["cases"])

    primary_labels = {
        str(item.get("label") or item.get("metadata", {}).get("instanceLabel"))
        for collection in ("zones", "placements", "routes")
        for item in primary["facilityLayout"][collection]
    }
    held_out_prompts = []
    for case in suite["cases"]:
        base, _brief, source, recipes = _generalization_case(case)
        labels = {
            str(item.get("label") or item.get("metadata", {}).get("instanceLabel"))
            for collection in ("zones", "placements", "routes")
            for item in base["document"][collection]
        }
        assert labels.isdisjoint(primary_labels)
        assert source["candidateAuthority"] == "deterministic_geometry_compiler"
        assert "reviewedCandidateRecipes" not in source
        assert recipes == []
        held_out_prompts.extend(case["heldOutPrompts"])
    assert len(held_out_prompts) == 8
    assert len({prompt.casefold() for prompt in held_out_prompts}) == 8
    assert all(
        classify_facility_design_turn(prompt)
        == {"kind": "design", "action": "create_and_preview"}
        for prompt in held_out_prompts
    )


def test_production_sage_and_lab_modes_return_identical_deterministic_artifacts(
    tmp_path: Path,
) -> None:
    suite = json.loads(GENERALIZATION_PATH.read_text(encoding="utf-8"))
    case = next(item for item in suite["cases"] if item["caseId"] == "direct-transfer")
    base, brief, source_bundle, _recipes = _generalization_case(case)
    outcomes = {}
    frozen_clock = lambda: datetime(2026, 9, 6, tzinfo=timezone.utc)
    for mode in ("production_sage", "lab"):
        repository = FacilityDesignRepository(tmp_path / mode, clock=frozen_clock)
        repository.create_brief(
            tenant_id="local",
            site_id="site-local",
            brief=brief,
        )
        runtime = FacilityDesignRuntime(
            repository,
            source_operation_builder=deterministic_design_operation_builder,
            clock=frozen_clock,
        )
        started = runtime.start_preview(
            tenant_id="local",
            site_id="site-local",
            workspace_id="workspace-local",
            design_base=base,
            design_brief=brief,
            source_bundle=source_bundle,
            provider="deterministic",
            model="fdl8-ab-v1",
            reasoning_effort=None,
            client_generation_id="fdl8-ab-generation",
            mode=mode,
            run_id="fdlr-ab-direct-transfer",
        )
        completed = runtime.continue_preview(
            tenant_id="local",
            site_id="site-local",
            run_id=started["run"]["runId"],
        )
        run = completed["run"]
        outcomes[mode] = {
            "candidate": repository.get_artifact(
                "local",
                "site-local",
                **{
                    "artifact_kind": run["candidateResults"][0]["artifactKind"],
                    "artifact_id": run["candidateResults"][0]["artifactId"],
                    "artifact_revision": run["candidateResults"][0]["artifactRevision"],
                },
            )["artifact"],
            "evaluation": repository.get_artifact(
                "local",
                "site-local",
                **{
                    "artifact_kind": run["evaluationResults"][0]["artifactKind"],
                    "artifact_id": run["evaluationResults"][0]["artifactId"],
                    "artifact_revision": run["evaluationResults"][0]["artifactRevision"],
                },
            )["artifact"],
        }
    assert canonical_design_bytes(outcomes["production_sage"]) == (
        canonical_design_bytes(outcomes["lab"])
    )


@pytest.mark.parametrize(
    "case",
    json.loads(GENERALIZATION_PATH.read_text(encoding="utf-8"))["cases"],
    ids=lambda case: case["caseId"],
)
def test_fdl9_generalization_controls_run_apply_and_exact_undo(
    case: dict,
    tmp_path: Path,
) -> None:
    base, brief, source_bundle, _recipes = _generalization_case(case)
    root = tmp_path / case["caseId"]
    repository = FacilityDesignRepository(root)
    leases = FacilityDraftLeaseRepository(root)
    repository.create_brief(
        tenant_id="local",
        site_id="site-local",
        brief=brief,
    )

    runtime = FacilityDesignRuntime(repository)
    started = runtime.start_preview(
        tenant_id="local",
        site_id="site-local",
        workspace_id="workspace-local",
        design_base=base,
        design_brief=brief,
        source_bundle=source_bundle,
        provider="deterministic",
        model="fdl9-held-out-v1",
        reasoning_effort=None,
        client_generation_id=f"generation-{case['caseId']}",
        run_id=f"fdlr-{case['caseId']}",
    )
    completed = runtime.continue_preview(
        tenant_id="local",
        site_id="site-local",
        run_id=started["run"]["runId"],
    )
    run = completed["run"]
    if case["expectedOutcome"] == "blocked":
        assert run["status"] == "blocked"
        assert run["proposalRefs"] == []
        assert case["expectedFindingCode"] in {
            finding["code"] for finding in run["findings"]
        }
        return

    assert run["status"] == "preview_ready"
    assert run["proposalRefs"]
    assert run["candidateResults"]
    for evaluation_ref in run["evaluationResults"]:
        evaluation = repository.get_artifact(
            "local",
            "site-local",
            evaluation_ref["artifactKind"],
            evaluation_ref["artifactId"],
            evaluation_ref["artifactRevision"],
        )["artifact"]
        assert evaluation["feasible"] is True
        assert evaluation["objectiveImproved"] is True

    service = FacilityDesignLoopService(
        repository=repository,
        runtime=runtime,
        lease_repository=leases,
        feature_flags=FacilityLayoutFeatureFlags.all_enabled(),
    )
    proposal_ref = run["proposalRefs"][0]
    proposal = service.inspect_proposal(
        tenant_id="local",
        site_id="site-local",
        proposal_id=proposal_ref["artifactId"],
        proposal_revision=proposal_ref["artifactRevision"],
        include_candidate_layout=True,
    )
    candidate_layout = proposal["candidate"]["candidateLayout"]
    for collection in ("zones", "placements", "processBindings", "floorMarkings"):
        assert canonical_design_bytes(candidate_layout.get(collection, [])) == (
            canonical_design_bytes(base["document"].get(collection, []))
        )
    if case["caseId"] == "dense-spine":
        assert len(candidate_layout["placements"]) > 500
    if case.get("obstacleBounds"):
        from shapely.geometry import LineString, box

        obstacle = box(*case["obstacleBounds"])
        for route in candidate_layout["routes"]:
            line = LineString(
                [(point["x"], point["z"]) for point in route["centerline"]]
            )
            assert not line.intersects(obstacle)

    frame = _editor_frame(base)
    prepared = service.prepare_proposal_apply(
        tenant_id="local",
        site_id="site-local",
        proposal_id=proposal_ref["artifactId"],
        proposal_revision=proposal_ref["artifactRevision"],
        root_undo_frame=frame,
        previous_installation_state=frame,
        expected_result_editor_generation_id="fdl9-applied-generation",
        expected_result_command_journal_hash="8" * 64,
    )
    transaction_id = prepared["transaction"]["transaction"]["transactionId"]
    committed = service.commit_proposal_apply(
        tenant_id="local",
        site_id="site-local",
        transaction_id=transaction_id,
        expected_transaction_revision=prepared["transaction"][
            "transactionRevision"
        ],
        adoption_token=prepared["adoption"]["adoptionToken"],
    )
    active = service.acknowledge_proposal_apply(
        tenant_id="local",
        site_id="site-local",
        transaction_id=transaction_id,
        expected_transaction_revision=committed["transaction"][
            "transactionRevision"
        ],
        adoption_token=prepared["adoption"]["adoptionToken"],
        observed_installation_fingerprint=prepared[
            "expectedInstallationFingerprint"
        ],
    )
    undo = service.prepare_undo(
        tenant_id="local",
        site_id="site-local",
        transaction_id=transaction_id,
        expected_transaction_revision=active["transaction"][
            "transactionRevision"
        ],
    )
    restored = service.acknowledge_undo(
        tenant_id="local",
        site_id="site-local",
        transaction_id=transaction_id,
        expected_transaction_revision=undo["transaction"][
            "transactionRevision"
        ],
        observed_draft_revision=frame["draftRevision"],
        observed_command_journal_hash=frame["commandJournalHash"],
    )
    assert restored["outcome"] == "released"
    assert restored["transaction"]["transaction"]["status"] == "undone"
