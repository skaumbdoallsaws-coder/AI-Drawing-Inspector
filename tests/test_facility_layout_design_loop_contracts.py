from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import multiprocessing
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_inspector.facility_layout.canonical import (
    canonical_layout_bytes,
    canonicalize_layout,
    layout_revision,
)
from ai_inspector.facility_layout.chat_intent import (
    facility_layout_tool_authorization,
)
from ai_inspector.facility_layout.design_base import (
    FacilityDesignBaseError,
    capture_facility_design_base,
    facility_design_base_ref,
)
from ai_inspector.facility_layout.design_brief import (
    FACILITY_DESIGN_BRIEF_SCHEMA_VERSION,
    FacilityDesignBriefError,
    apply_facility_design_brief_patch,
    create_facility_design_brief,
    design_revision,
)
from ai_inspector.facility_layout.design_candidates import (
    deterministic_design_operation_builder,
    enumerate_facility_design_candidate_recipes,
    execute_facility_design_candidate,
    fixture_recipe_operation_builder,
)
from ai_inspector.facility_layout.design_evaluator import (
    FACILITY_DESIGN_CONSTRAINT_PREDICATE_VERSION,
    build_facility_design_baseline,
    classify_facility_design_alternatives,
    evaluate_facility_design_candidate,
    evaluate_facility_design_constraints,
    route_path_distance_meters,
)
from ai_inspector.facility_layout.design_fixture import (
    reviewed_material_travel_authority_documents,
)
from ai_inspector.facility_layout.design_repository import (
    FacilityDesignRepository,
    FacilityDesignRepositoryConflictError,
    FacilityDesignRepositoryNotFoundError,
)
from ai_inspector.facility_layout.design_routing import (
    FacilityDesignRoutingError,
    resolve_design_route_endpoint,
    validate_design_transfer_route_path,
)
from ai_inspector.facility_layout.design_runtime import (
    FacilityDesignRuntime,
    reviewed_fixture_recipe_provider,
)
from ai_inspector.facility_layout.design_service import (
    FACILITY_DESIGN_EDITOR_FRAME_VERSION,
    FacilityDesignLoopService,
    FacilityDesignServiceError,
)
from ai_inspector.facility_layout.design_source import (
    build_facility_design_source_bundle,
)
from ai_inspector.facility_layout.errors import FacilityAuthorizationError
from ai_inspector.facility_layout.facility_draft_lease import (
    FacilityDraftLeaseConflictError,
    FacilityDraftLeaseRepository,
)
from ai_inspector.facility_layout.feature_flags import (
    FACILITY_ALL_FEATURE_FLAGS,
    FacilityLayoutFeatureFlags,
)
from ai_inspector.facility_layout.host import (
    LOCAL_ASSET_CATALOG,
    LOCAL_SITE_ID,
    LocalFacilityLayoutHost,
)
from ai_inspector.facility_layout.manufacturing_snapshot import (
    FacilityManufacturingSnapshotError,
    build_facility_manufacturing_snapshot,
    validate_facility_manufacturing_snapshot,
)
from ai_inspector.facility_layout.service import coordinate_frame_fingerprint


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "facility_layout"
    / "design_loop"
    / "fdl-material-travel-v1.json"
)
FIXTURE_DIRECTORY = FIXTURE_PATH.parent
APPROVAL_PATH = FIXTURE_DIRECTORY / "fdl0-approval-receipt-v1.json"
BASE_KINDS_PATH = FIXTURE_DIRECTORY / "fdl0-base-kinds-v1.json"
CURRENT_ROUTING_PATH = FIXTURE_DIRECTORY / "fdl0-current-sage-routing-v1.json"
CREATED_AT = "2026-09-06T00:00:00Z"


class _Clock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 6, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **values: int) -> None:
        self.current += timedelta(**values)


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _ref(kind: str, entity_id: str, revision: str) -> dict:
    return {
        "entityKind": kind,
        "entityId": entity_id,
        "sourceRevision": revision,
    }


def _constraint(
    constraint_id: str,
    kind: str,
    refs: list[dict],
    turn: str = "turn-1",
) -> dict:
    return {
        "constraintId": constraint_id,
        "constraintKind": kind,
        "targetRefs": refs,
        "predicateVersion": FACILITY_DESIGN_CONSTRAINT_PREDICATE_VERSION,
        "authority": "user_authored",
        "evidenceRefs": [f"evidence-{constraint_id}"],
        "status": "active",
        "sourceTurnRef": turn,
        "supersededBy": None,
    }


def _permitted(
    change_id: str,
    refs: list[dict],
    operation_kinds: list[str],
    area_ref: dict | None = None,
) -> dict:
    return {
        "changeId": change_id,
        "targetRefs": refs,
        "operationKinds": operation_kinds,
        "containingAreaRef": area_ref,
        "status": "active",
        "sourceTurnRef": "turn-1",
        "withdrawnBy": None,
    }


def _base_and_brief(fixture: dict | None = None) -> tuple[dict, dict]:
    fixture = fixture or _fixture()
    layout = canonicalize_layout(fixture["facilityLayout"])
    # The immutable FDL0 archive predates candidate corridor validation and
    # places the CNC footprint across the material route. Execution tests use
    # a derived, obstacle-valid arrangement without rewriting approved bytes.
    placements = {item["placementId"]: item for item in layout["placements"]}
    placements["pl-cnc-mill-03"]["transform"]["position"]["x"] = 5.0
    placements["pl-obstacle-west"]["transform"]["position"]["x"] = 25.0
    layout = canonicalize_layout(layout)
    revision = layout_revision(layout)
    base = capture_facility_design_base(
        base_id="fdb-material-travel-v1",
        base_kind="saved_layout",
        tenant_id="tenant-local",
        site_id="site-fdl",
        workspace_id="workspace-local",
        document=layout,
        saved_layout_revision=revision,
        source_ref={
            "repositoryRecordRevision": "8" * 64,
            "savedLayoutRevision": revision,
        },
        captured_at=CREATED_AT,
    )
    machine_ref = _ref("placement", "pl-cnc-mill-03", revision)
    inspection_ref = _ref("placement", "pl-inspection-station-02", revision)
    output_ref = _ref("placement", "pl-output-buffer-a", revision)
    input_ref = _ref("placement", "pl-input-buffer-b", revision)
    material_route_ref = _ref("route", "rt-material-transfer-aisle", revision)
    boulevard_ref = _ref("route", "rt-main-boulevard", revision)
    binding_refs = [
        _ref("process_binding", binding_id, revision)
        for binding_id in fixture["transferEvidence"]["processBindingIds"]
    ]
    body = {
        "status": "active",
        "tenantId": "tenant-local",
        "siteId": "site-fdl",
        "workspaceId": "workspace-local",
        "layoutId": layout["layoutId"],
        "baseStateRef": facility_design_base_ref(base),
        "objective": {
            "objectiveId": "objective-material-travel",
            "objectiveKind": "reduce_loaded_material_travel_v1",
            "targetRefs": [output_ref, input_ref, material_route_ref, boulevard_ref],
            "processBindingIds": fixture["transferEvidence"]["processBindingIds"],
            "requestedMetricIds": sorted(fixture["expected"]["baseline"]),
            "minimumImprovement": None,
            "evidenceRefs": ["evidence-fdl-reviewed-trip-frequency"],
        },
        "scopeRefs": [
            machine_ref,
            inspection_ref,
            output_ref,
            input_ref,
            material_route_ref,
            boulevard_ref,
            *binding_refs,
        ],
        "hardConstraints": [
            _constraint("constraint-lock-cnc", "preserve_entity_geometry", [machine_ref]),
            _constraint(
                "constraint-lock-inspection",
                "preserve_entity_geometry",
                [inspection_ref],
            ),
            _constraint(
                "constraint-preserve-bindings",
                "preserve_process_binding",
                binding_refs,
            ),
        ],
        "preferences": [],
        "permittedChanges": [
            _permitted(
                "change-output-buffer",
                [output_ref],
                ["move_placement_within_area", "move_route_bound_endpoint"],
                _ref("zone", "zn-machining", revision),
            ),
            _permitted(
                "change-input-buffer",
                [input_ref],
                ["move_placement_within_area", "move_route_bound_endpoint"],
                _ref("zone", "zn-inspection", revision),
            ),
            _permitted(
                "change-material-route",
                [material_route_ref],
                ["edit_material_route"],
            ),
            _permitted(
                "change-main-boulevard",
                [boulevard_ref],
                ["edit_material_route"],
            ),
        ],
        "assumptions": [],
        "unknowns": [],
        "referents": [],
        "decisionRefs": ["decision-fdl-fixture-approval"],
        "revisionVector": {
            "layout": revision,
            "processMap": fixture["processMap"]["processMapRevision"],
            "policy": layout["policySetRef"]["policySetRevision"],
        },
    }
    brief = create_facility_design_brief(
        brief_id="fdbf-material-travel-v1",
        semantic_body=body,
        source_turn_refs=["turn-1"],
        principal_id="shadrack",
        created_at=CREATED_AT,
    )
    return base, brief


def _snapshot(fixture: dict, base: dict, brief: dict) -> dict:
    return build_facility_manufacturing_snapshot(
        snapshot_id="fdms-material-travel-v1",
        design_base=base,
        design_brief=brief,
        process_map=fixture["processMap"],
        transfer=fixture["transferEvidence"],
        validation_context_revision=fixture["expected"]["validationContextRevision"],
        created_at=CREATED_AT,
    )


def _candidate_layout(layout: dict, recipe: dict) -> dict:
    result = deepcopy(layout)
    placements = {item["placementId"]: item for item in result["placements"]}
    routes = {item["routeId"]: item for item in result["routes"]}
    for edit in recipe["placementEdits"]:
        placements[edit["placementId"]]["transform"]["position"] = deepcopy(edit["position"])
    for edit in recipe["routeEdits"]:
        routes[edit["routeId"]]["centerline"] = deepcopy(edit["centerline"])
    return canonicalize_layout(result)


def _authoritative_catalog_assets(fixture: dict) -> list[dict]:
    records = []
    for raw in fixture.get("catalogAssets", []):
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
        records.append(
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
    return records


def _runtime_source(fixture: dict) -> dict:
    return {
        "processMap": deepcopy(fixture["processMap"]),
        "transfer": deepcopy(fixture["transferEvidence"]),
        "validationContextRevision": fixture["expected"][
            "validationContextRevision"
        ],
        "candidateUpdatedAt": CREATED_AT,
        "reviewedCandidateRecipes": deepcopy(fixture["candidateRecipes"]),
        "candidateAuthority": "reviewed_test_gold",
        "assetDefinitions": _authoritative_catalog_assets(fixture),
    }


def _persist_brief(repository: FacilityDesignRepository, brief: dict) -> None:
    repository.create_brief(
        tenant_id="tenant-local",
        site_id="site-fdl",
        brief=brief,
    )


def _editor_frame(base: dict, *, generation: str = "editor-generation-1") -> dict:
    document = deepcopy(base["document"])
    revision = layout_revision(document)
    return {
        "schemaVersion": FACILITY_DESIGN_EDITOR_FRAME_VERSION,
        "baseLayout": deepcopy(document),
        "baseRevision": revision,
        "draftLayout": deepcopy(document),
        "draftRevision": revision,
        "batches": [],
        "cursor": 0,
        "selectedIds": [],
        "generatedDraft": None,
        "recentReceiptIds": [],
        "activeProposal": None,
        "editorGenerationId": generation,
        "commandJournalHash": "7" * 64,
    }


def _metric_index(evaluation: dict) -> dict:
    return {item["metricId"]: item for item in evaluation["metrics"]}


def _advance_brief_worker(
    root: str,
    brief: dict,
    expected_revision: str,
    queue: multiprocessing.Queue,
) -> None:
    repository = FacilityDesignRepository(root)
    try:
        repository.advance_brief(
            tenant_id="tenant-local",
            site_id="site-fdl",
            brief=brief,
            expected_brief_revision=expected_revision,
        )
    except FacilityDesignRepositoryConflictError as exc:
        queue.put(exc.code)
    else:
        queue.put("advanced")


def test_fdl0_fixture_is_canonical_and_has_frozen_baseline() -> None:
    fixture = _fixture()
    layout = fixture["facilityLayout"]
    assert canonical_layout_bytes(layout)
    assert layout_revision(layout) == fixture["expected"]["baseLayoutRevision"]
    assert route_path_distance_meters(
        layout, fixture["transferEvidence"]["routeIds"]
    ) == pytest.approx(60.0, abs=1e-12)
    assert fixture["authority"]["approverPrincipalId"] == "shadrack"
    assert fixture["authority"]["productionEligible"] is False


def test_fdl0_approval_receipt_is_revision_bound_and_narrow() -> None:
    receipt = json.loads(APPROVAL_PATH.read_text(encoding="utf-8"))
    fixture_bytes = FIXTURE_PATH.read_bytes()
    assert hashlib.sha256(fixture_bytes).hexdigest() == receipt["fixtureFileSha256"]
    unsigned = deepcopy(receipt)
    unsigned.pop("receiptRevision")
    assert design_revision(unsigned) == receipt["receiptRevision"]
    assert receipt["approver"]["principalId"] == "shadrack"
    assert receipt["decision"] == "accepted_for_test_gold"
    assert {"production", "safety", "compliance"} <= set(
        receipt["excludedAuthority"]
    )


def test_fdl0_frozen_base_kind_cases_execute_as_recorded() -> None:
    fixture = _fixture()
    cases = json.loads(BASE_KINDS_PATH.read_text(encoding="utf-8"))
    layout = fixture["facilityLayout"]
    assert cases["layoutRevision"] == layout_revision(layout)
    for item in cases["cases"]:
        kwargs = {
            "base_id": f"fdb-{item['caseId']}",
            "base_kind": item["baseKind"],
            "tenant_id": "tenant-local",
            "site_id": "site-fdl",
            "workspace_id": "workspace-local",
            "document": layout,
            "saved_layout_revision": item["savedLayoutRevision"],
            "source_ref": item["sourceRef"],
            "captured_at": CREATED_AT,
        }
        if item["expected"] == "accepted":
            assert capture_facility_design_base(**kwargs)["baseKind"] == item["baseKind"]
        else:
            with pytest.raises(FacilityDesignBaseError) as caught:
                capture_facility_design_base(**kwargs)
            assert caught.value.code == item["code"]


def test_fdl0_current_sage_routing_trace_is_replayable() -> None:
    fixture = json.loads(CURRENT_ROUTING_PATH.read_text(encoding="utf-8"))
    for turn in fixture["turns"]:
        result = facility_layout_tool_authorization(
            turn["prompt"],
            read_tool_names=fixture["readToolNames"],
            preview_tool_name=fixture["previewToolName"],
            move_tool_name=fixture["moveToolName"],
        )
        assert result["mode"] == turn["mode"]
        assert result["intent"] == turn["intent"]
        assert result["requestKind"] == turn["requestKind"]
        assert sorted(result["allowedToolNames"]) == turn["allowedToolNames"]


def test_semantic_fingerprint_excludes_audit_ids_and_timestamps() -> None:
    _, first = _base_and_brief()
    body = deepcopy(first["semanticBody"])
    body["objective"]["objectiveId"] = "objective-paraphrase"
    body["baseStateRef"]["baseId"] = "fdb-alias"
    for index, constraint in enumerate(body["hardConstraints"], start=1):
        constraint["constraintId"] = f"constraint-paraphrase-{index}"
        constraint["sourceTurnRef"] = "turn-paraphrase"
    for index, permitted in enumerate(body["permittedChanges"], start=1):
        permitted["changeId"] = f"change-paraphrase-{index}"
        permitted["sourceTurnRef"] = "turn-paraphrase"
    body["decisionRefs"] = ["decision-paraphrase"]
    second = create_facility_design_brief(
        brief_id="fdbf-paraphrase",
        semantic_body=body,
        source_turn_refs=["turn-paraphrase"],
        principal_id="shadrack",
        created_at="2026-09-06T01:00:00Z",
    )
    assert first["briefRevision"] != second["briefRevision"]
    assert first["briefSemanticFingerprint"] == second["briefSemanticFingerprint"]


@pytest.mark.parametrize(
    ("base_kind", "source_ref"),
    [
        (
            "receipt_bound_draft",
            {
                "generationRunId": "fgr-fdl-test",
                "receiptId": "receipt-fdl-stage",
                "receiptRevision": "6" * 64,
                "resultDraftRevision": None,
                "savedBaseRevision": None,
            },
        ),
        (
            "editor_draft",
            {
                "editorSessionId": "session-fdl-test",
                "editorGenerationId": "generation-fdl-1",
                "commandJournalHash": "5" * 64,
                "savedBaseRevision": None,
                "capturedDraftRevision": None,
            },
        ),
    ],
)
def test_all_unsaved_base_kinds_bind_exact_draft_lineage(
    base_kind: str,
    source_ref: dict,
) -> None:
    fixture = _fixture()
    layout = fixture["facilityLayout"]
    revision = layout_revision(layout)
    source_ref = deepcopy(source_ref)
    source_ref["savedBaseRevision"] = "4" * 64
    if base_kind == "receipt_bound_draft":
        source_ref["resultDraftRevision"] = revision
    else:
        source_ref["capturedDraftRevision"] = revision
    base = capture_facility_design_base(
        base_id=f"fdb-{base_kind}",
        base_kind=base_kind,
        tenant_id="tenant-local",
        site_id="site-fdl",
        workspace_id="workspace-local",
        document=layout,
        saved_layout_revision="4" * 64,
        source_ref=source_ref,
        captured_at=CREATED_AT,
    )
    assert base["baseKind"] == base_kind
    assert base["layoutRevision"] == revision
    assert base["savedLayoutRevision"] != base["layoutRevision"]

    stale = deepcopy(source_ref)
    if base_kind == "receipt_bound_draft":
        stale["resultDraftRevision"] = "3" * 64
    else:
        stale["capturedDraftRevision"] = "3" * 64
    with pytest.raises(FacilityDesignBaseError) as caught:
        capture_facility_design_base(
            base_id=f"fdb-{base_kind}-stale",
            base_kind=base_kind,
            tenant_id="tenant-local",
            site_id="site-fdl",
            workspace_id="workspace-local",
            document=layout,
            saved_layout_revision="4" * 64,
            source_ref=stale,
            captured_at=CREATED_AT,
        )
    assert caught.value.code == "facility_design_base_lineage_invalid"


def test_brief_rejects_coordinates_and_deferred_constraints() -> None:
    _, brief = _base_and_brief()
    body = deepcopy(brief["semanticBody"])
    body["unknowns"].append(
        {
            "unknownId": "unknown-coordinate",
            "unknownKind": "geometry",
            "text": "Do not persist this coordinate.",
            "affectedRefIds": [],
            "sourceTurnRef": "turn-2",
            "position": {"x": 1, "z": 2},
        }
    )
    with pytest.raises(FacilityDesignBriefError) as caught:
        create_facility_design_brief(
            brief_id="fdbf-coordinate",
            semantic_body=body,
            source_turn_refs=["turn-2"],
            principal_id="shadrack",
            created_at=CREATED_AT,
        )
    assert caught.value.code == "facility_design_coordinates_forbidden"

    body = deepcopy(brief["semanticBody"])
    body["hardConstraints"].append(
        _constraint(
            "constraint-access",
            "retain_required_access",
            body["objective"]["targetRefs"][:1],
            "turn-2",
        )
    )
    with pytest.raises(FacilityDesignBriefError) as caught:
        create_facility_design_brief(
            brief_id="fdbf-access",
            semantic_body=body,
            source_turn_refs=["turn-2"],
            principal_id="shadrack",
            created_at=CREATED_AT,
        )
    assert caught.value.code == "facility_design_constraint_kind_unsupported"


def test_lock_patch_atomically_withdraws_the_matching_permission() -> None:
    base, brief = _base_and_brief()
    revision = base["layoutRevision"]
    main_lock = _constraint(
        "constraint-lock-main-boulevard",
        "preserve_route_geometry",
        [_ref("route", "rt-main-boulevard", revision)],
        "turn-2",
    )
    patched = apply_facility_design_brief_patch(
        brief,
        {
            "schemaVersion": FACILITY_DESIGN_BRIEF_SCHEMA_VERSION,
            "expectedBriefRevision": brief["briefRevision"],
            "operations": [
                {
                    "action": "add",
                    "collection": "hardConstraints",
                    "recordId": None,
                    "record": main_lock,
                }
            ],
        },
        source_turn_ref="turn-2",
        principal_id="shadrack",
        created_at="2026-09-06T00:01:00Z",
    )
    changes = {
        item["changeId"]: item for item in patched["semanticBody"]["permittedChanges"]
    }
    assert changes["change-main-boulevard"]["status"] == "withdrawn"
    assert changes["change-main-boulevard"]["withdrawnBy"] == main_lock["constraintId"]
    assert changes["change-material-route"]["status"] == "active"


def test_preference_reorder_is_a_closed_revisioned_patch() -> None:
    _, brief = _base_and_brief()
    body = deepcopy(brief["semanticBody"])
    body["preferences"] = [
        {
            "preferenceId": "preference-route",
            "metricId": "loadedRouteDistanceMeters",
            "priority": 1,
            "status": "active",
            "sourceTurnRef": "turn-1",
        },
        {
            "preferenceId": "preference-moves",
            "metricId": "movedPlacementCount",
            "priority": 2,
            "status": "active",
            "sourceTurnRef": "turn-1",
        },
    ]
    current = create_facility_design_brief(
        brief_id=brief["briefId"],
        semantic_body=body,
        source_turn_refs=brief["sourceTurnRefs"],
        principal_id="shadrack",
        created_at=CREATED_AT,
    )
    reordered = apply_facility_design_brief_patch(
        current,
        {
            "schemaVersion": FACILITY_DESIGN_BRIEF_SCHEMA_VERSION,
            "expectedBriefRevision": current["briefRevision"],
            "operations": [
                {
                    "action": "reorder",
                    "collection": "preferences",
                    "recordId": "preference-moves",
                    "record": {"priority": 1},
                },
                {
                    "action": "reorder",
                    "collection": "preferences",
                    "recordId": "preference-route",
                    "record": {"priority": 2},
                },
            ],
        },
        source_turn_ref="turn-3",
        principal_id="shadrack",
        created_at="2026-09-06T00:03:00Z",
    )
    assert {
        item["preferenceId"]: item["priority"]
        for item in reordered["semanticBody"]["preferences"]
    } == {"preference-moves": 1, "preference-route": 2}
    assert reordered["parentBriefRevision"] == current["briefRevision"]


def test_constraint_predicate_version_is_closed() -> None:
    _, brief = _base_and_brief()
    body = deepcopy(brief["semanticBody"])
    body["hardConstraints"][0]["predicateVersion"] = "future-predicate-v2"
    with pytest.raises(FacilityDesignBriefError) as caught:
        create_facility_design_brief(
            brief_id=brief["briefId"],
            semantic_body=body,
            source_turn_refs=brief["sourceTurnRefs"],
            principal_id="shadrack",
            created_at=CREATED_AT,
        )
    assert caught.value.code == (
        "facility_design_constraint_predicate_version_unsupported"
    )


def test_constraint_registry_reports_violation_stale_and_unavailable() -> None:
    fixture = _fixture()
    base, brief = _base_and_brief(fixture)
    revision = base["layoutRevision"]
    candidate = deepcopy(base["document"])
    candidate["placements"][0]["transform"]["position"]["x"] += 1
    results = evaluate_facility_design_constraints(
        baseline_layout=base["document"],
        candidate_layout=candidate,
        brief=brief,
    )
    assert {
        item["constraintId"]: item["status"] for item in results
    }["constraint-lock-cnc"] == "violated"

    stale_body = deepcopy(brief["semanticBody"])
    stale_body["hardConstraints"][0]["targetRefs"][0]["sourceRevision"] = "3" * 64
    stale_brief = create_facility_design_brief(
        brief_id="fdbf-stale-constraint",
        semantic_body=stale_body,
        source_turn_refs=["turn-stale"],
        principal_id="shadrack",
        created_at=CREATED_AT,
    )
    stale_results = evaluate_facility_design_constraints(
        baseline_layout=base["document"],
        candidate_layout=base["document"],
        brief=stale_brief,
    )
    assert {
        item["constraintId"]: item["status"] for item in stale_results
    }["constraint-lock-cnc"] == "stale"

    area_body = deepcopy(brief["semanticBody"])
    area_body["hardConstraints"] = [
        _constraint(
            "constraint-output-area",
            "remain_inside_area",
            [
                _ref("placement", "pl-output-buffer-a", revision),
                _ref("zone", "zn-machining", revision),
            ],
        )
    ]
    area_brief = create_facility_design_brief(
        brief_id="fdbf-area-constraint",
        semantic_body=area_body,
        source_turn_refs=["turn-area"],
        principal_id="shadrack",
        created_at=CREATED_AT,
    )
    unavailable = evaluate_facility_design_constraints(
        baseline_layout=base["document"],
        candidate_layout=base["document"],
        brief=area_brief,
    )
    assert unavailable[0]["status"] == "unavailable"
    satisfied = evaluate_facility_design_constraints(
        baseline_layout=base["document"],
        candidate_layout=base["document"],
        brief=area_brief,
        containment_checker=lambda *_: ("satisfied", {"inside": True}),
    )
    violated = evaluate_facility_design_constraints(
        baseline_layout=base["document"],
        candidate_layout=base["document"],
        brief=area_brief,
        containment_checker=lambda *_: ("violated", {"inside": False}),
    )
    assert satisfied[0]["status"] == "satisfied"
    assert violated[0]["status"] == "violated"
    assert satisfied[0]["details"]["containmentChecks"] == [{"inside": True}]


@pytest.mark.parametrize(
    ("minimum_meters", "expected"),
    [(10.0, True), (25.0, False)],
)
def test_operationally_meaningful_requires_authored_minimum(
    minimum_meters: float,
    expected: bool,
) -> None:
    fixture = _fixture()
    base, brief = _base_and_brief(fixture)
    body = deepcopy(brief["semanticBody"])
    body["objective"]["minimumImprovement"] = {
        "metricId": "loadedRouteDistanceMeters",
        "value": minimum_meters,
        "unit": "m",
    }
    minimum_brief = create_facility_design_brief(
        brief_id=f"fdbf-minimum-{int(minimum_meters)}",
        semantic_body=body,
        source_turn_refs=["turn-minimum"],
        principal_id="shadrack",
        created_at=CREATED_AT,
    )
    snapshot = _snapshot(fixture, base, minimum_brief)
    baseline = build_facility_design_baseline(
        baseline_id="fdlb-minimum",
        layout=base["document"],
        brief=minimum_brief,
        snapshot=snapshot,
        source_bundle=_runtime_source(fixture),
    )
    recipe = next(
        item
        for item in fixture["candidateRecipes"]
        if item["candidateId"] == "fdlc-output-buffer-relocate"
    )
    evaluation = evaluate_facility_design_candidate(
        evaluation_id=f"eval-minimum-{int(minimum_meters)}",
        baseline_layout=base["document"],
        candidate_layout=_candidate_layout(base["document"], recipe),
        brief=minimum_brief,
        snapshot=snapshot,
        baseline=baseline,
        source_bundle=_runtime_source(fixture),
    )
    assert evaluation["minimumImprovementSatisfied"] is expected
    assert evaluation["operationallyMeaningful"] is expected


def test_snapshot_and_all_seven_baseline_metrics_are_exact() -> None:
    fixture = _fixture()
    base, brief = _base_and_brief(fixture)
    snapshot = _snapshot(fixture, base, brief)
    baseline = build_facility_design_baseline(
        baseline_id="fdlb-material-travel-v1",
        layout=base["document"],
        brief=brief,
        snapshot=snapshot,
        source_bundle=_runtime_source(fixture),
    )
    assert baseline["feasible"] is True
    measured = {item["metricId"]: item["value"] for item in baseline["metrics"]}
    assert measured == fixture["expected"]["baseline"]


def test_disconnected_short_route_is_not_a_feasible_improvement() -> None:
    fixture = _fixture()
    base, brief = _base_and_brief(fixture)
    snapshot = _snapshot(fixture, base, brief)
    source = _runtime_source(fixture)
    baseline = build_facility_design_baseline(
        baseline_id="fdlb-disconnected-route",
        layout=base["document"],
        brief=brief,
        snapshot=snapshot,
        source_bundle=source,
    )
    candidate = deepcopy(base["document"])
    route = next(
        item
        for item in candidate["routes"]
        if item["routeId"] == "rt-material-transfer-aisle"
    )
    route["centerline"] = [
        {"x": 30.0, "y": 0.0, "z": 30.0},
        {"x": 31.0, "y": 0.0, "z": 30.0},
    ]
    with pytest.raises(FacilityDesignRoutingError) as caught:
        evaluate_facility_design_candidate(
            evaluation_id="eval-disconnected-route",
            baseline_layout=base["document"],
            candidate_layout=candidate,
            brief=brief,
            snapshot=snapshot,
            baseline=baseline,
            source_bundle=source,
        )
    assert caught.value.code == "facility_design_route_endpoint_geometry_mismatch"


def test_reversed_one_way_candidate_route_is_not_measured() -> None:
    fixture = _fixture()
    base, brief = _base_and_brief(fixture)
    snapshot = _snapshot(fixture, base, brief)
    source = _runtime_source(fixture)
    baseline = build_facility_design_baseline(
        baseline_id="fdlb-reversed-one-way-route",
        layout=base["document"],
        brief=brief,
        snapshot=snapshot,
        source_bundle=source,
    )
    candidate = deepcopy(base["document"])
    route = next(
        item
        for item in candidate["routes"]
        if item["routeId"] == "rt-material-transfer-aisle"
    )
    route["sourceEndpoint"], route["targetEndpoint"] = (
        route["targetEndpoint"],
        route["sourceEndpoint"],
    )
    route["centerline"] = list(reversed(route["centerline"]))
    route["extensions"] = {
        "facilityAisle": {
            "direction": "one_way",
        }
    }
    with pytest.raises(FacilityDesignRoutingError) as caught:
        evaluate_facility_design_candidate(
            evaluation_id="eval-reversed-one-way-route",
            baseline_layout=base["document"],
            candidate_layout=candidate,
            brief=brief,
            snapshot=snapshot,
            baseline=baseline,
            source_bundle=source,
        )
    assert caught.value.code == "facility_design_route_endpoint_unavailable"
    assert caught.value.details["findingCodes"] == [
        "connector_direction_invalid"
    ]


def test_catalog_document_envelope_resolves_exact_offset_connector() -> None:
    fixture = _fixture()
    base, _brief = _base_and_brief(fixture)
    source = _runtime_source(fixture)
    records = []
    for item in source["assetDefinitions"]:
        if item["assetId"] != "asset-fifo-buffer":
            records.append(item)
            continue
        document = deepcopy(item["definition"])
        output = next(
            connector
            for connector in document["connectors"]
            if connector["connectorId"] == "material-output"
        )
        output["position"]["x"] = 2.0
        records.append(
            {
                "revision": item["assetDefinitionRevision"],
                "document": document,
            }
        )
    source["assetDefinitions"] = records

    resolved = resolve_design_route_endpoint(
        base["document"],
        {
            "kind": "placement_connector",
            "placementId": "pl-output-buffer-a",
            "connectorId": "material-output",
        },
        route_kind="material",
        direction="source",
        source_bundle=source,
    )

    assert resolved == (12.0, 8.0)


def test_input_only_source_connector_is_rejected_without_route_fallback() -> None:
    fixture = _fixture()
    base, brief = _base_and_brief(fixture)
    snapshot = _snapshot(fixture, base, brief)
    source = _runtime_source(fixture)
    fifo = next(
        item
        for item in source["assetDefinitions"]
        if item["assetId"] == "asset-fifo-buffer"
    )
    output = next(
        connector
        for connector in fifo["definition"]["connectors"]
        if connector["connectorId"] == "material-output"
    )
    output["role"] = "input"
    source["endpointGeometry"] = {
        "pl-output-buffer-a:material-output": {
            "assetDefinitionRevision": fifo["assetDefinitionRevision"],
            "basePlacementPosition": {"x": 10.0, "y": 0.0, "z": 8.0},
            "baseEndpointPosition": {"x": 10.0, "y": 0.0, "z": 8.0},
        }
    }

    with pytest.raises(FacilityDesignRoutingError) as caught:
        validate_design_transfer_route_path(
            base["document"], snapshot, source_bundle=source
        )

    assert caught.value.code == "facility_design_route_endpoint_unavailable"
    assert caught.value.details["findingCodes"] == [
        "connector_direction_invalid"
    ]


def test_missing_frequency_only_makes_weighted_metric_unavailable() -> None:
    fixture = _fixture()
    fixture["transferEvidence"]["loadedTripsPerShift"] = None
    base, brief = _base_and_brief(fixture)
    snapshot = _snapshot(fixture, base, brief)
    baseline = build_facility_design_baseline(
        baseline_id="fdlb-frequency-missing",
        layout=base["document"],
        brief=brief,
        snapshot=snapshot,
        source_bundle=_runtime_source(fixture),
    )
    metrics = _metric_index(baseline)
    assert metrics["loadedRouteDistanceMeters"]["status"] == "measured"
    assert metrics["loadedTravelMetersPerShift"]["status"] == "unavailable"
    assert metrics["loadedTravelMetersPerShift"]["value"] is None
    assert all(
        item["status"] == "measured"
        for key, item in metrics.items()
        if key != "loadedTravelMetersPerShift"
    )


def test_snapshot_rejects_rehashed_nested_contract_drift() -> None:
    fixture = _fixture()
    base, brief = _base_and_brief(fixture)
    snapshot = _snapshot(fixture, base, brief)
    snapshot["routePath"]["modelAuthoredVerdict"] = "accepted"
    unsigned = deepcopy(snapshot)
    unsigned.pop("snapshotRevision")
    snapshot["snapshotRevision"] = design_revision(unsigned)
    with pytest.raises(FacilityManufacturingSnapshotError) as caught:
        validate_facility_manufacturing_snapshot(snapshot)
    assert caught.value.code == "facility_manufacturing_snapshot_invalid"


def test_frozen_candidates_match_independent_metric_expectations() -> None:
    fixture = _fixture()
    base, brief = _base_and_brief(fixture)
    snapshot = _snapshot(fixture, base, brief)
    baseline = build_facility_design_baseline(
        baseline_id="fdlb-material-travel-v1",
        layout=base["document"],
        brief=brief,
        snapshot=snapshot,
        source_bundle=_runtime_source(fixture),
    )
    evaluations = []
    for recipe in fixture["candidateRecipes"]:
        candidate = _candidate_layout(base["document"], recipe)
        if recipe["candidateId"] == "fdlc-material-aisle-direct":
            with pytest.raises(FacilityDesignRoutingError) as blocked:
                evaluate_facility_design_candidate(
                    evaluation_id=f"eval-{recipe['candidateId']}",
                    baseline_layout=base["document"],
                    candidate_layout=candidate,
                    brief=brief,
                    snapshot=snapshot,
                    baseline=baseline,
                    source_bundle=_runtime_source(fixture),
                )
            assert blocked.value.code == "route_blocked"
            continue
        evaluation = evaluate_facility_design_candidate(
            evaluation_id=f"eval-{recipe['candidateId']}",
            baseline_layout=base["document"],
            candidate_layout=candidate,
            brief=brief,
            snapshot=snapshot,
            baseline=baseline,
            source_bundle=_runtime_source(fixture),
        )
        metrics = _metric_index(evaluation)
        for metric_id, expected in recipe["expected"].items():
            if metric_id == "objectiveImproved":
                assert evaluation[metric_id] is expected
            else:
                assert metrics[metric_id]["value"] == pytest.approx(expected, abs=1e-12)
        evaluations.append(evaluation)

    preferred_body = deepcopy(brief["semanticBody"])
    preferred_body["preferences"] = [
        {
            "preferenceId": "preference-equipment-moves",
            "metricId": "movedPlacementCount",
            "priority": 1,
            "status": "active",
            "sourceTurnRef": "turn-3",
        },
        {
            "preferenceId": "preference-route-distance",
            "metricId": "loadedRouteDistanceMeters",
            "priority": 2,
            "status": "active",
            "sourceTurnRef": "turn-3",
        },
    ]
    preferred_brief = create_facility_design_brief(
        brief_id=brief["briefId"],
        semantic_body=preferred_body,
        source_turn_refs=[*brief["sourceTurnRefs"], "turn-3"],
        principal_id="shadrack",
        created_at="2026-09-06T00:02:00Z",
        parent_brief_revision=brief["briefRevision"],
    )
    classified = classify_facility_design_alternatives(
        evaluations,
        brief=preferred_brief,
    )
    preferred = [item for item in classified if item["preferred"]]
    assert [item["evaluationId"] for item in preferred] == [
        "eval-fdlc-main-boulevard-reflow"
    ]
    assert preferred[0]["preferenceReason"]["wording"] == (
        "preferred among the evaluated bounded alternatives"
    )


def test_fixture_locks_remove_real_candidates_in_frozen_order() -> None:
    fixture = _fixture()
    candidates = {item["candidateId"]: item for item in fixture["candidateRecipes"]}
    assert sorted(candidates) == sorted(fixture["expected"]["turn1CandidateIds"])
    after_main = sorted(
        candidate_id
        for candidate_id, recipe in candidates.items()
        if "constraint-lock-main-boulevard" not in recipe["removedByLocks"]
    )
    assert after_main == sorted(fixture["expected"]["afterMainBoulevardLockCandidateIds"])
    after_output = sorted(
        candidate_id
        for candidate_id in after_main
        if "constraint-lock-output-buffer-a"
        not in candidates[candidate_id]["removedByLocks"]
    )
    assert after_output == fixture["expected"]["afterOutputBufferLockCandidateIds"]


def test_candidate_search_is_canonical_bounded_and_reports_truncation() -> None:
    fixture = _fixture()
    base, brief = _base_and_brief(fixture)
    snapshot = _snapshot(fixture, base, brief)
    first = enumerate_facility_design_candidate_recipes(
        brief=brief,
        snapshot=snapshot,
    )
    second = enumerate_facility_design_candidate_recipes(
        brief=deepcopy(brief),
        snapshot=deepcopy(snapshot),
    )
    assert first == second
    assert first["searchStatus"] == "truncated"
    assert first["frontierCount"] == 5
    assert first["unexpandedFrontierCount"] == 1
    assert len(first["recipes"]) == 4
    assert [
        item["leverKind"] for item in first["recipes"][:2]
    ] == ["source_buffer_fit", "destination_buffer_fit"]


def test_fixture_candidate_operations_use_atomic_kernel_and_match_frozen_hashes() -> None:
    fixture = _fixture()
    base, brief = _base_and_brief(fixture)
    snapshot = _snapshot(fixture, base, brief)
    for recipe in fixture["candidateRecipes"]:
        operations = fixture_recipe_operation_builder(
            recipe, base["document"], snapshot
        )
        assert design_revision(operations) == recipe["operationPlanHash"]
        candidate = execute_facility_design_candidate(
            candidate_id=recipe["candidateId"],
            recipe=recipe,
            design_base=base,
            brief=brief,
            snapshot=snapshot,
            operation_builder=fixture_recipe_operation_builder,
        )
        assert candidate["operationPlanHash"] == recipe["operationPlanHash"]
        assert candidate["previewPure"] is True
        assert layout_revision(base["document"]) == base["layoutRevision"]
        assert route_path_distance_meters(
            candidate["candidateLayout"],
            fixture["transferEvidence"]["routeIds"],
        ) == pytest.approx(
            recipe["expected"]["loadedRouteDistanceMeters"], abs=1e-12
        )


def test_repository_retains_pinned_unsaved_base_across_instances(tmp_path: Path) -> None:
    base, brief = _base_and_brief()
    repository = FacilityDesignRepository(tmp_path / "design-store")
    repository.store_artifact(
        tenant_id="tenant-local",
        site_id="site-fdl",
        artifact_kind="design_base",
        artifact_id=base["baseId"],
        artifact_revision=base["baseRevision"],
        artifact=base,
    )
    artifact_ref = {
        "artifactKind": "design_base",
        "artifactId": base["baseId"],
        "artifactRevision": base["baseRevision"],
    }
    repository.create_brief(
        tenant_id="tenant-local",
        site_id="site-fdl",
        brief=brief,
        artifact_refs=[artifact_ref],
    )
    assert repository.artifact_pin_count(
        "tenant-local", "site-fdl", base["baseRevision"]
    ) == 1

    reopened = FacilityDesignRepository(tmp_path / "design-store")
    assert reopened.get_brief(
        "tenant-local", "site-fdl", brief["briefId"]
    )["brief"]["briefRevision"] == brief["briefRevision"]
    assert reopened.get_artifact(
        "tenant-local",
        "site-fdl",
        "design_base",
        base["baseId"],
        base["baseRevision"],
    )["artifact"] == base


def test_repository_pin_discovery_survives_a_long_storage_root(tmp_path: Path) -> None:
    base, brief = _base_and_brief()
    repository = FacilityDesignRepository(
        tmp_path
        / ("repository-" + "x" * 96)
        / ("nested-" + "y" * 96)
    )
    repository.store_artifact(
        tenant_id="tenant-local",
        site_id="site-fdl",
        artifact_kind="design_base",
        artifact_id=base["baseId"],
        artifact_revision=base["baseRevision"],
        artifact=base,
    )
    repository.create_brief(
        tenant_id="tenant-local",
        site_id="site-fdl",
        brief=brief,
        artifact_refs=[
            {
                "artifactKind": "design_base",
                "artifactId": base["baseId"],
                "artifactRevision": base["baseRevision"],
            }
        ],
    )

    assert repository.artifact_pin_count(
        "tenant-local", "site-fdl", base["baseRevision"]
    ) == 1
    assert repository.list_brief_heads(
        "tenant-local",
        "site-fdl",
        layout_id=base["layoutId"],
        active_only=True,
    )[0]["briefId"] == brief["briefId"]


def test_repository_collects_only_released_unpinned_artifacts(tmp_path: Path) -> None:
    base, brief = _base_and_brief()
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    repository = FacilityDesignRepository(
        tmp_path / "design-store",
        clock=lambda: now,
    )
    stored = repository.store_artifact(
        tenant_id="tenant-local",
        site_id="site-fdl",
        artifact_kind="design_base",
        artifact_id=base["baseId"],
        artifact_revision=base["baseRevision"],
        artifact=base,
    )
    assert repository.store_artifact(
        tenant_id="tenant-local",
        site_id="site-fdl",
        artifact_kind="design_base",
        artifact_id=base["baseId"],
        artifact_revision=base["baseRevision"],
        artifact=deepcopy(base),
    ) == stored
    artifact_ref = {
        "artifactKind": "design_base",
        "artifactId": base["baseId"],
        "artifactRevision": base["baseRevision"],
    }
    repository.create_brief(
        tenant_id="tenant-local",
        site_id="site-fdl",
        brief=brief,
        artifact_refs=[artifact_ref],
    )
    cutoff = now + timedelta(days=1)
    assert repository.collect_unpinned_artifacts(
        "tenant-local", "site-fdl", older_than=cutoff
    ) == []
    assert repository.list_brief_heads(
        "tenant-local",
        "site-fdl",
        layout_id=base["layoutId"],
        active_only=True,
    )[0]["briefId"] == brief["briefId"]
    assert repository.release_brief_pins(
        "tenant-local", "site-fdl", brief["briefId"]
    ) == 1
    removed = repository.collect_unpinned_artifacts(
        "tenant-local", "site-fdl", older_than=cutoff
    )
    assert [item["artifactRevision"] for item in removed] == [
        base["baseRevision"]
    ]
    with pytest.raises(FacilityDesignRepositoryNotFoundError):
        repository.get_artifact(
            "tenant-local",
            "site-fdl",
            "design_base",
            base["baseId"],
            base["baseRevision"],
        )


def test_repository_cross_process_cas_allows_one_head_advance(tmp_path: Path) -> None:
    _, brief = _base_and_brief()
    root = tmp_path / "design-store"
    repository = FacilityDesignRepository(root)
    repository.create_brief(
        tenant_id="tenant-local",
        site_id="site-fdl",
        brief=brief,
    )
    candidates = []
    for index in (1, 2):
        candidates.append(
            apply_facility_design_brief_patch(
                brief,
                {
                    "schemaVersion": FACILITY_DESIGN_BRIEF_SCHEMA_VERSION,
                    "expectedBriefRevision": brief["briefRevision"],
                    "operations": [
                        {
                            "action": "add",
                            "collection": "assumptions",
                            "recordId": None,
                            "record": {
                                "assumptionId": f"assumption-race-{index}",
                                "text": f"Race candidate {index}",
                                "reviewStatus": "proposed",
                                "evidenceRefs": [],
                                "sourceTurnRef": f"turn-race-{index}",
                            },
                        }
                    ],
                },
                source_turn_ref=f"turn-race-{index}",
                principal_id="shadrack",
                created_at=f"2026-09-06T00:0{index}:00Z",
            )
        )
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    processes = [
        context.Process(
            target=_advance_brief_worker,
            args=(str(root), candidate, brief["briefRevision"], queue),
        )
        for candidate in candidates
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    outcomes = sorted(queue.get(timeout=2) for _ in processes)
    assert outcomes == ["advanced", "facility_design_brief_revision_conflict"]


def test_durable_runtime_reaches_two_bounded_unsaved_proposals_in_ten_calls(
    tmp_path: Path,
) -> None:
    fixture = _fixture()
    base, brief = _base_and_brief(fixture)
    repository = FacilityDesignRepository(tmp_path / "design-runtime")
    _persist_brief(repository, brief)
    runtime = FacilityDesignRuntime(
        repository,
        candidate_recipe_provider=reviewed_fixture_recipe_provider,
        operation_builder=fixture_recipe_operation_builder,
    )
    started = runtime.start_preview(
        tenant_id="tenant-local",
        site_id="site-fdl",
        workspace_id="workspace-local",
        design_base=base,
        design_brief=brief,
        source_bundle=_runtime_source(fixture),
        provider="anthropic",
        model="claude-sonnet-4-5-20250929",
        reasoning_effort=None,
        client_generation_id="client-generation-1",
        run_id="fdlr-material-travel",
    )
    result = runtime.continue_preview(
        tenant_id="tenant-local",
        site_id="site-fdl",
        run_id=started["run"]["runId"],
    )
    while result["continuationRequired"]:
        result = runtime.continue_preview(
            tenant_id="tenant-local",
            site_id="site-fdl",
            run_id=started["run"]["runId"],
        )
    assert result["run"]["status"] == "preview_ready", json.dumps(
        {
            "status": result["run"]["status"],
            "findings": result["run"]["findings"],
            "candidateQueue": result["run"]["candidateQueue"],
            "terminalReason": result["run"]["terminalReason"],
        },
        sort_keys=True,
    )
    assert result["turnToolCalls"] == 10
    assert result["run"]["counters"]["workflowToolCalls"] == 10
    assert len(result["run"]["proposalRefs"]) == 2
    assert result["run"]["searchStatus"] == "complete"
    summary = runtime.summary(result)
    assert summary["baseline"]["layoutRevision"] == base["layoutRevision"]
    assert summary["baseline"]["feasible"] is True
    assert summary["objectiveEndpoints"] == {
        "source": {
            "entityKind": "placement",
            "entityId": fixture["transferEvidence"]["sourcePlacementId"],
            "connectorId": fixture["transferEvidence"]["sourceConnectorId"],
        },
        "target": {
            "entityKind": "placement",
            "entityId": fixture["transferEvidence"]["targetPlacementId"],
            "connectorId": fixture["transferEvidence"]["targetConnectorId"],
        },
    }
    assert summary["terminalReason"] is None
    proposals = [
        repository.get_artifact(
            "tenant-local",
            "site-fdl",
            ref["artifactKind"],
            ref["artifactId"],
            ref["artifactRevision"],
        )["artifact"]
        for ref in result["run"]["proposalRefs"]
    ]
    assert all(item["saveEligibility"] == "unsaved_draft_only" for item in proposals)
    assert {
        item["operationPlanRevision"] for item in proposals
    } <= {
        recipe["operationPlanHash"] for recipe in fixture["candidateRecipes"]
    }


def test_design_source_rejects_missing_authoritative_process_map() -> None:
    fixture = _fixture()
    base, brief = _base_and_brief(fixture)

    with pytest.raises(FacilityDesignServiceError) as caught:
        build_facility_design_source_bundle(
            design_base=base,
            design_brief=brief,
            asset_definitions=_authoritative_catalog_assets(fixture),
            process_map_resolver=lambda *_: None,
        )

    assert caught.value.code == "facility_design_process_map_unavailable"


def test_design_source_rejects_stale_authoritative_process_map() -> None:
    fixture = _fixture()
    base, brief = _base_and_brief(fixture)

    with pytest.raises(FacilityDesignServiceError) as caught:
        build_facility_design_source_bundle(
            design_base=base,
            design_brief=brief,
            asset_definitions=_authoritative_catalog_assets(fixture),
            process_map_resolver=lambda *_: {
                "revision": "f" * 64,
                "document": fixture["processMap"],
            },
        )

    assert (
        caught.value.code
        == "facility_design_process_map_revision_mismatch"
    )
    assert caught.value.details["requestedRevision"] == fixture[
        "processMap"
    ]["processMapRevision"]
    assert caught.value.details["reportedRevisions"] == sorted(
        ["f" * 64, fixture["processMap"]["processMapRevision"]]
    )


def test_default_runtime_compiles_coordinate_free_recipes_for_new_layout(
    tmp_path: Path,
) -> None:
    fixture = deepcopy(_fixture())
    asset_revisions = {}
    for asset in fixture["catalogAssets"]:
        asset["geometry"]["obb"]["halfExtents"]["y"] = 0.5
        revision = design_revision(
            {"assetId": asset["assetId"], "geometry": asset["geometry"]}
        )
        asset["assetDefinitionRevision"] = revision
        asset_revisions[asset["assetId"]] = revision
    for placement in fixture["facilityLayout"]["placements"]:
        placement["assetDefinitionRevision"] = asset_revisions[
            placement["assetId"]
        ]
    base, brief = _base_and_brief(fixture)
    source = build_facility_design_source_bundle(
        design_base=base,
        design_brief=brief,
        asset_definitions=_authoritative_catalog_assets(fixture),
        process_map_resolver=lambda *_: {
            "revision": fixture["processMap"]["processMapRevision"],
            "document": fixture["processMap"],
        },
    )
    assert "reviewedCandidateRecipes" not in source
    assert "placementEdits" not in json.dumps(source, sort_keys=True)
    assert "routeEdits" not in json.dumps(source, sort_keys=True)
    assert "endpointGeometry" not in source

    generic_snapshot = _snapshot(fixture, base, brief)
    try:
        validate_design_transfer_route_path(
            base["document"], generic_snapshot, source_bundle=source
        )
    except FacilityDesignRoutingError as error:
        pytest.fail(f"{error.code}: {error.details}")
    generic_search = enumerate_facility_design_candidate_recipes(
        brief=brief, snapshot=generic_snapshot
    )
    for recipe in generic_search["recipes"]:
        if recipe["leverKind"] == "route_only_reflow":
            continue
        try:
            operations = deterministic_design_operation_builder(
                recipe, base["document"], generic_snapshot, source
            )
        except Exception as error:
            pytest.fail(
                f"{getattr(error, 'code', type(error).__name__)}: "
                f"{getattr(error, 'details', str(error))}"
            )
        edited_routes = [
            operation["routeId"]
            for operation in operations
            if operation["op"] == "edit_route"
        ]
        if recipe["leverKind"] == "source_buffer_fit":
            assert edited_routes == ["rt-material-transfer-aisle"]
        elif recipe["leverKind"] == "destination_buffer_fit":
            assert edited_routes == ["rt-main-boulevard"]

    repository = FacilityDesignRepository(tmp_path / "generic-design-runtime")
    _persist_brief(repository, brief)
    runtime = FacilityDesignRuntime(repository)
    started = runtime.start_preview(
        tenant_id="tenant-local",
        site_id="site-fdl",
        workspace_id="workspace-local",
        design_base=base,
        design_brief=brief,
        source_bundle=source,
        provider="anthropic",
        model="claude-sonnet-4-5-20250929",
        reasoning_effort=None,
        client_generation_id="client-generation-generic",
        run_id="fdlr-generic-layout",
    )
    result = runtime.continue_preview(
        tenant_id="tenant-local",
        site_id="site-fdl",
        run_id=started["run"]["runId"],
    )
    while result["continuationRequired"]:
        result = runtime.continue_preview(
            tenant_id="tenant-local",
            site_id="site-fdl",
            run_id=started["run"]["runId"],
        )
    assert result["run"]["status"] == "preview_ready", json.dumps(
        result["run"]["findings"], sort_keys=True
    )
    assert result["run"]["candidateResults"]
    assert result["run"]["proposalRefs"]
    candidate_operations = []
    for candidate_ref in result["run"]["candidateResults"]:
        candidate = repository.get_artifact(
            "tenant-local",
            "site-fdl",
            candidate_ref["artifactKind"],
            candidate_ref["artifactId"],
            candidate_ref["artifactRevision"],
        )["artifact"]
        assert candidate["operations"]
        assert all(
            operation["op"] in {"move_placement", "edit_route"}
            for operation in candidate["operations"]
        )
        candidate_operations.extend(candidate["operations"])
    assert any(
        operation["op"] == "move_placement"
        for operation in candidate_operations
    )


def test_runtime_restart_resumes_after_receipt_without_replaying_completed_stages(
    tmp_path: Path,
) -> None:
    fixture = _fixture()
    base, brief = _base_and_brief(fixture)
    root = tmp_path / "design-runtime"
    repository = FacilityDesignRepository(root)
    _persist_brief(repository, brief)
    calls = {"recipes": 0}

    def recipes(current_brief, snapshot, source):
        calls["recipes"] += 1
        return reviewed_fixture_recipe_provider(current_brief, snapshot, source)

    first_runtime = FacilityDesignRuntime(
        repository,
        candidate_recipe_provider=recipes,
        operation_builder=fixture_recipe_operation_builder,
    )
    started = first_runtime.start_preview(
        tenant_id="tenant-local",
        site_id="site-fdl",
        workspace_id="workspace-local",
        design_base=base,
        design_brief=brief,
        source_bundle=_runtime_source(fixture),
        provider="anthropic",
        model="claude-sonnet-4-5-20250929",
        reasoning_effort=None,
        client_generation_id="client-generation-restart",
        run_id="fdlr-restart",
    )
    partial = first_runtime.continue_preview(
        tenant_id="tenant-local",
        site_id="site-fdl",
        run_id=started["run"]["runId"],
        maximum_tool_calls=4,
    )
    assert partial["continuationRequired"] is True
    assert partial["run"]["nextStageId"] == "execute_candidates"
    frozen_receipts = deepcopy(partial["run"]["stageReceipts"])
    assert calls["recipes"] == 1

    reopened_repository = FacilityDesignRepository(root)
    reopened = FacilityDesignRuntime(
        reopened_repository,
        candidate_recipe_provider=recipes,
        operation_builder=fixture_recipe_operation_builder,
    )
    completed = reopened.continue_preview(
        tenant_id="tenant-local",
        site_id="site-fdl",
        run_id="fdlr-restart",
    )
    assert completed["run"]["status"] == "preview_ready"
    assert completed["run"]["stageReceipts"][:4] == frozen_receipts
    assert calls["recipes"] == 1


def test_runtime_brief_lock_removes_consequential_reviewed_recipes(
    tmp_path: Path,
) -> None:
    fixture = _fixture()
    base, brief = _base_and_brief(fixture)
    original_brief = deepcopy(brief)
    main_lock = _constraint(
        "constraint-lock-main-boulevard",
        "preserve_route_geometry",
        [_ref("route", "rt-main-boulevard", base["layoutRevision"])],
        "turn-2",
    )
    brief = apply_facility_design_brief_patch(
        brief,
        {
            "schemaVersion": FACILITY_DESIGN_BRIEF_SCHEMA_VERSION,
            "expectedBriefRevision": brief["briefRevision"],
            "operations": [
                {
                    "action": "add",
                    "collection": "hardConstraints",
                    "recordId": None,
                    "record": main_lock,
                }
            ],
        },
        source_turn_ref="turn-2",
        principal_id="shadrack",
        created_at="2026-09-06T00:01:00Z",
    )
    repository = FacilityDesignRepository(tmp_path / "design-runtime")
    _persist_brief(repository, original_brief)
    repository.advance_brief(
        tenant_id="tenant-local",
        site_id="site-fdl",
        brief=brief,
        expected_brief_revision=original_brief["briefRevision"],
    )
    runtime = FacilityDesignRuntime(
        repository,
        candidate_recipe_provider=reviewed_fixture_recipe_provider,
        operation_builder=fixture_recipe_operation_builder,
    )
    started = runtime.start_preview(
        tenant_id="tenant-local",
        site_id="site-fdl",
        workspace_id="workspace-local",
        design_base=base,
        design_brief=brief,
        source_bundle=_runtime_source(fixture),
        provider="anthropic",
        model="claude-sonnet-4-5-20250929",
        reasoning_effort=None,
        client_generation_id="client-generation-lock",
        run_id="fdlr-lock",
    )
    result = runtime.continue_preview(
        tenant_id="tenant-local", site_id="site-fdl", run_id=started["run"]["runId"]
    )
    candidate_ids = {
        ref["artifactId"] for ref in result["run"]["candidateResults"]
    }
    assert "fdlc-main-boulevard-reflow" not in candidate_ids
    assert candidate_ids == {"fdlc-output-buffer-relocate"}
    assert any(
        item["sourceCode"] == "route_blocked"
        for item in result["run"]["findings"]
    )


def test_runtime_uses_only_structured_recovery_and_stays_within_two_repairs(
    tmp_path: Path,
) -> None:
    fixture = _fixture()
    base, brief = _base_and_brief(fixture)
    repository = FacilityDesignRepository(tmp_path / "design-runtime")
    _persist_brief(repository, brief)
    good = deepcopy(fixture["candidateRecipes"][2])
    bad = {
        "candidateId": "fdlc-blocked",
        "strategyId": "blocked-route-v1",
        "targetIds": ["rt-material-transfer-aisle"],
        "placementEdits": [],
        "routeEdits": [],
    }

    def one_bad(_brief, _snapshot, _source):
        return {
            "recipes": [bad],
            "searchStatus": "complete",
            "unexpandedFrontierCount": 0,
        }

    def builder(recipe, layout, snapshot):
        if recipe["candidateId"] == "fdlc-blocked":
            from ai_inspector.facility_layout.design_candidates import (
                FacilityDesignCandidateError,
            )

            raise FacilityDesignCandidateError(
                "route_blocked",
                "The authored-width route is blocked.",
                details={"affectedIds": ["rt-material-transfer-aisle"]},
            )
        return fixture_recipe_operation_builder(recipe, layout, snapshot)

    def repair(action, _recipe, attempt):
        assert action["actionKind"] == "reflow_same_route"
        assert attempt == 1
        return good

    runtime = FacilityDesignRuntime(
        repository,
        candidate_recipe_provider=one_bad,
        operation_builder=builder,
        repair_provider=repair,
    )
    started = runtime.start_preview(
        tenant_id="tenant-local",
        site_id="site-fdl",
        workspace_id="workspace-local",
        design_base=base,
        design_brief=brief,
        source_bundle=_runtime_source(fixture),
        provider="anthropic",
        model="claude-sonnet-4-5-20250929",
        reasoning_effort=None,
        client_generation_id="client-generation-repair",
        run_id="fdlr-repair",
    )
    result = runtime.continue_preview(
        tenant_id="tenant-local", site_id="site-fdl", run_id=started["run"]["runId"]
    )
    assert result["run"]["status"] == "preview_ready"
    assert result["run"]["counters"]["repairAttempts"] == 1
    assert result["run"]["counters"]["candidateExecutionAttempts"] == 2
    assert result["run"]["recoveryActions"][0]["actionKind"] == "reflow_same_route"


def test_runtime_elapsed_budget_fails_before_first_tool_call(tmp_path: Path) -> None:
    fixture = _fixture()
    base, brief = _base_and_brief(fixture)
    clock = _Clock()
    repository = FacilityDesignRepository(tmp_path / "design-runtime", clock=clock)
    _persist_brief(repository, brief)
    runtime = FacilityDesignRuntime(
        repository,
        candidate_recipe_provider=reviewed_fixture_recipe_provider,
        operation_builder=fixture_recipe_operation_builder,
        clock=clock,
    )
    started = runtime.start_preview(
        tenant_id="tenant-local",
        site_id="site-fdl",
        workspace_id="workspace-local",
        design_base=base,
        design_brief=brief,
        source_bundle=_runtime_source(fixture),
        provider="anthropic",
        model="claude-sonnet-4-5-20250929",
        reasoning_effort=None,
        client_generation_id="client-generation-budget",
        run_id="fdlr-budget",
    )
    clock.advance(seconds=301)
    result = runtime.continue_preview(
        tenant_id="tenant-local", site_id="site-fdl", run_id=started["run"]["runId"]
    )
    assert result["run"]["status"] == "budget_exhausted"
    assert result["run"]["counters"]["workflowToolCalls"] == 0
    assert result["run"]["terminalReason"] == (
        "facility_design_elapsed_budget_exceeded"
    )


def test_run_expiry_releases_run_pins_but_retains_active_unsaved_base(
    tmp_path: Path,
) -> None:
    fixture = _fixture()
    saved_base, saved_brief = _base_and_brief(fixture)
    draft_revision = saved_base["layoutRevision"]
    base = capture_facility_design_base(
        base_id="fdb-retained-editor-draft",
        base_kind="editor_draft",
        tenant_id="tenant-local",
        site_id="site-fdl",
        workspace_id="workspace-local",
        document=saved_base["document"],
        saved_layout_revision=draft_revision,
        source_ref={
            "editorSessionId": "editor-retention",
            "editorGenerationId": "editor-generation-retention",
            "commandJournalHash": "9" * 64,
            "savedBaseRevision": draft_revision,
            "capturedDraftRevision": draft_revision,
        },
        captured_at=CREATED_AT,
    )
    body = deepcopy(saved_brief["semanticBody"])
    body["baseStateRef"] = facility_design_base_ref(base)
    brief = create_facility_design_brief(
        brief_id="fdbf-retained-editor-draft",
        semantic_body=body,
        source_turn_refs=["turn-retention"],
        principal_id="shadrack",
        created_at=CREATED_AT,
    )
    clock = _Clock()
    repository = FacilityDesignRepository(tmp_path / "design", clock=clock)
    _persist_brief(repository, brief)
    runtime = FacilityDesignRuntime(
        repository,
        candidate_recipe_provider=reviewed_fixture_recipe_provider,
        operation_builder=fixture_recipe_operation_builder,
        clock=clock,
    )
    started = runtime.start_preview(
        tenant_id="tenant-local",
        site_id="site-fdl",
        workspace_id="workspace-local",
        design_base=base,
        design_brief=brief,
        source_bundle=_runtime_source(fixture),
        provider="anthropic",
        model="claude-sonnet-4-5-20250929",
        reasoning_effort=None,
        client_generation_id="client-generation-retention",
        run_id="fdlr-retention",
    )
    completed = runtime.continue_preview(
        tenant_id="tenant-local",
        site_id="site-fdl",
        run_id=started["run"]["runId"],
    )
    assert repository.artifact_pin_count(
        "tenant-local", "site-fdl", base["baseRevision"]
    ) == 2

    clock.advance(days=1, seconds=1)
    tombstone = repository.expire_run(
        tenant_id="tenant-local",
        site_id="site-fdl",
        run_id="fdlr-retention",
        expected_run_revision=completed["runRevision"],
    )
    assert tombstone["priorStatus"] == "preview_ready"
    assert repository.artifact_pin_count(
        "tenant-local", "site-fdl", base["baseRevision"]
    ) == 1
    assert repository.get_brief(
        "tenant-local", "site-fdl", brief["briefId"]
    )["brief"]["semanticBody"]["baseStateRef"]["baseRevision"] == base[
        "baseRevision"
    ]
    with pytest.raises(FacilityDesignRepositoryNotFoundError) as caught:
        repository.get_run("tenant-local", "site-fdl", "fdlr-retention")
    assert caught.value.code == "facility_design_run_expired"

    removed = repository.collect_unpinned_artifacts(
        "tenant-local",
        "site-fdl",
        older_than=clock.current + timedelta(seconds=1),
    )
    assert base["baseRevision"] not in {
        item["artifactRevision"] for item in removed
    }
    clock.advance(days=30, seconds=1)
    assert repository.collect_expired_run_tombstones(
        "tenant-local", "site-fdl"
    ) == ["fdlr-retention"]
    assert repository.get_artifact(
        "tenant-local",
        "site-fdl",
        "design_base",
        base["baseId"],
        base["baseRevision"],
    )["artifact"] == base


def test_design_service_apply_is_gated_before_any_lease_access(
    tmp_path: Path,
) -> None:
    enabled = set(FACILITY_ALL_FEATURE_FLAGS)
    enabled.remove("INSPECTORPRO_FACILITY_LAYOUT_AGENT_WRITE")
    flags = FacilityLayoutFeatureFlags.from_environment({
        item: "1" if item in enabled else "0"
        for item in FACILITY_ALL_FEATURE_FLAGS
    })
    repository = FacilityDesignRepository(tmp_path / "design")
    leases = FacilityDraftLeaseRepository(tmp_path / "design")
    runtime = FacilityDesignRuntime(repository)
    service = FacilityDesignLoopService(
        repository=repository,
        runtime=runtime,
        lease_repository=leases,
        feature_flags=flags,
    )

    with pytest.raises(FacilityAuthorizationError) as caught:
        service.prepare_proposal_apply(
            tenant_id="tenant-local",
            site_id="site-fdl",
            proposal_id="proposal-missing",
            proposal_revision="1" * 64,
            root_undo_frame={},
            previous_installation_state={},
            expected_result_editor_generation_id="editor-generation-2",
            expected_result_command_journal_hash="2" * 64,
        )
    assert caught.value.details["capability"] == "agent_write"
    assert not leases.lease_path(
        "tenant-local", "site-fdl", "fl-fdl-material-travel-v1"
    ).exists()


def test_design_service_keeps_complete_brief_records_for_editor_state(
    tmp_path: Path,
) -> None:
    base, brief = _base_and_brief()
    repository = FacilityDesignRepository(tmp_path / "design")
    repository.store_artifact(
        tenant_id="tenant-local",
        site_id="site-fdl",
        artifact_kind="design_base",
        artifact_id=base["baseId"],
        artifact_revision=base["baseRevision"],
        artifact=base,
    )
    _persist_brief(repository, brief)
    service = FacilityDesignLoopService(
        repository=repository,
        runtime=FacilityDesignRuntime(repository),
        lease_repository=FacilityDraftLeaseRepository(tmp_path / "design"),
        feature_flags=FacilityLayoutFeatureFlags.all_enabled(),
    )

    inspected = service.inspect_brief(
        tenant_id="tenant-local",
        site_id="site-fdl",
        brief_id=brief["briefId"],
    )["brief"]
    assert inspected["semanticBody"]["hardConstraints"][0]["status"] == "active"
    assert inspected["semanticBody"]["hardConstraints"][0]["constraintId"]

    constraint = _constraint(
        "constraint-editor-visible-main-boulevard",
        "preserve_route_geometry",
        [_ref("route", "rt-main-boulevard", base["layoutRevision"])],
        "turn-editor-visible",
    )
    updated = service.update_brief(
        tenant_id="tenant-local",
        site_id="site-fdl",
        principal_id="shadrack",
        brief_id=brief["briefId"],
        patch={
            "schemaVersion": FACILITY_DESIGN_BRIEF_SCHEMA_VERSION,
            "expectedBriefRevision": brief["briefRevision"],
            "operations": [{
                "action": "add",
                "collection": "hardConstraints",
                "recordId": None,
                "record": constraint,
            }],
        },
        source_turn_ref="turn-editor-visible",
    )["brief"]
    visible = {
        item["constraintId"]: item["status"]
        for item in updated["semanticBody"]["hardConstraints"]
    }
    assert visible["constraint-editor-visible-main-boulevard"] == "active"


def test_design_service_applies_and_undoes_one_exact_unsaved_proposal(
    tmp_path: Path,
) -> None:
    fixture = _fixture()
    base, brief = _base_and_brief(fixture)
    clock = _Clock()
    root = tmp_path / "design"
    repository = FacilityDesignRepository(root, clock=clock)
    leases = FacilityDraftLeaseRepository(root, clock=clock)
    _persist_brief(repository, brief)
    runtime = FacilityDesignRuntime(
        repository,
        candidate_recipe_provider=reviewed_fixture_recipe_provider,
        operation_builder=fixture_recipe_operation_builder,
        clock=clock,
    )
    service = FacilityDesignLoopService(
        repository=repository,
        runtime=runtime,
        lease_repository=leases,
        feature_flags=FacilityLayoutFeatureFlags.all_enabled(),
        clock=clock,
    )
    started = runtime.start_preview(
        tenant_id="tenant-local",
        site_id="site-fdl",
        workspace_id="workspace-local",
        design_base=base,
        design_brief=brief,
        source_bundle=_runtime_source(fixture),
        provider="anthropic",
        model="claude-sonnet-4-5-20250929",
        reasoning_effort=None,
        client_generation_id="client-generation-apply",
        run_id="fdlr-apply",
    )
    completed = runtime.continue_preview(
        tenant_id="tenant-local",
        site_id="site-fdl",
        run_id=started["run"]["runId"],
    )
    proposal_ref = completed["run"]["proposalRefs"][0]
    frame = _editor_frame(base)
    prepared = service.prepare_proposal_apply(
        tenant_id="tenant-local",
        site_id="site-fdl",
        proposal_id=proposal_ref["artifactId"],
        proposal_revision=proposal_ref["artifactRevision"],
        root_undo_frame=frame,
        previous_installation_state=frame,
        expected_result_editor_generation_id="editor-generation-2",
        expected_result_command_journal_hash="8" * 64,
    )
    prepared_transaction = prepared["transaction"]
    committed = service.commit_proposal_apply(
        tenant_id="tenant-local",
        site_id="site-fdl",
        transaction_id=prepared_transaction["transaction"]["transactionId"],
        expected_transaction_revision=prepared_transaction[
            "transactionRevision"
        ],
        adoption_token=prepared["adoption"]["adoptionToken"],
    )
    assert committed["lease"]["status"] == "review_required"
    acknowledged = service.acknowledge_proposal_apply(
        tenant_id="tenant-local",
        site_id="site-fdl",
        transaction_id=committed["transaction"]["transaction"][
            "transactionId"
        ],
        expected_transaction_revision=committed["transaction"][
            "transactionRevision"
        ],
        adoption_token=prepared["adoption"]["adoptionToken"],
        observed_installation_fingerprint=prepared[
            "expectedInstallationFingerprint"
        ],
    )
    assert acknowledged["lease"]["status"] == "active"
    assert acknowledged["transaction"]["transaction"]["status"] == "active"

    undo_prepared = service.prepare_undo(
        tenant_id="tenant-local",
        site_id="site-fdl",
        transaction_id=acknowledged["transaction"]["transaction"][
            "transactionId"
        ],
        expected_transaction_revision=acknowledged["transaction"][
            "transactionRevision"
        ],
    )
    assert undo_prepared["mode"] == "coordinated"
    assert undo_prepared["readiness"] == "undo_acknowledgment_pending"
    assert undo_prepared["lease"]["status"] == "review_required"
    assert undo_prepared["lease"]["reviewReason"] == "undo_unacknowledged"
    retried_prepare = service.prepare_undo(
        tenant_id="tenant-local",
        site_id="site-fdl",
        transaction_id=acknowledged["transaction"]["transaction"][
            "transactionId"
        ],
        expected_transaction_revision=acknowledged["transaction"][
            "transactionRevision"
        ],
    )
    assert retried_prepare["transaction"] == undo_prepared["transaction"]
    assert retried_prepare["rootUndoFrame"] == frame
    undone = service.acknowledge_undo(
        tenant_id="tenant-local",
        site_id="site-fdl",
        transaction_id=undo_prepared["transaction"]["transaction"][
            "transactionId"
        ],
        expected_transaction_revision=undo_prepared["transaction"][
            "transactionRevision"
        ],
        observed_draft_revision=frame["draftRevision"],
        observed_command_journal_hash=frame["commandJournalHash"],
    )
    assert undone["outcome"] == "released"
    assert undone["transaction"]["transaction"]["status"] == "undone"
    retried_acknowledgment = service.acknowledge_undo(
        tenant_id="tenant-local",
        site_id="site-fdl",
        transaction_id=undo_prepared["transaction"]["transaction"][
            "transactionId"
        ],
        expected_transaction_revision=undo_prepared["transaction"][
            "transactionRevision"
        ],
        observed_draft_revision=frame["draftRevision"],
        observed_command_journal_hash=frame["commandJournalHash"],
    )
    assert retried_acknowledgment["outcome"] == "already_undone"
    assert retried_acknowledgment["transaction"] == undone["transaction"]

    reconciled_prepare = service.prepare_undo(
        tenant_id="tenant-local",
        site_id="site-fdl",
        transaction_id=undo_prepared["transaction"]["transaction"]["transactionId"],
        expected_transaction_revision=undo_prepared["transaction"][
            "transactionRevision"
        ],
    )
    assert reconciled_prepare["mode"] == "already_undone"
    assert reconciled_prepare["readiness"] == "ready"
    assert reconciled_prepare["rootUndoFrame"] == frame


def test_failed_replacement_restores_a_not_root_o(tmp_path: Path) -> None:
    fixture = _fixture()
    base, brief = _base_and_brief(fixture)
    clock = _Clock()
    root = tmp_path / "design"
    repository = FacilityDesignRepository(root, clock=clock)
    leases = FacilityDraftLeaseRepository(root, clock=clock)
    _persist_brief(repository, brief)
    runtime = FacilityDesignRuntime(
        repository,
        candidate_recipe_provider=reviewed_fixture_recipe_provider,
        operation_builder=fixture_recipe_operation_builder,
        clock=clock,
    )
    service = FacilityDesignLoopService(
        repository=repository,
        runtime=runtime,
        lease_repository=leases,
        feature_flags=FacilityLayoutFeatureFlags.all_enabled(),
        clock=clock,
    )
    started = runtime.start_preview(
        tenant_id="tenant-local",
        site_id="site-fdl",
        workspace_id="workspace-local",
        design_base=base,
        design_brief=brief,
        source_bundle=_runtime_source(fixture),
        provider="anthropic",
        model="claude-sonnet-4-5-20250929",
        reasoning_effort=None,
        client_generation_id="client-generation-replacement",
        run_id="fdlr-replacement",
    )
    completed = runtime.continue_preview(
        tenant_id="tenant-local",
        site_id="site-fdl",
        run_id=started["run"]["runId"],
    )
    proposal_a, proposal_b = completed["run"]["proposalRefs"][:2]
    frame_o = _editor_frame(base)

    prepared_a = service.prepare_proposal_apply(
        tenant_id="tenant-local",
        site_id="site-fdl",
        proposal_id=proposal_a["artifactId"],
        proposal_revision=proposal_a["artifactRevision"],
        root_undo_frame=frame_o,
        previous_installation_state=frame_o,
        expected_result_editor_generation_id="editor-generation-a",
        expected_result_command_journal_hash="a" * 64,
    )
    committed_a = service.commit_proposal_apply(
        tenant_id="tenant-local",
        site_id="site-fdl",
        transaction_id=prepared_a["transaction"]["transaction"]["transactionId"],
        expected_transaction_revision=prepared_a["transaction"][
            "transactionRevision"
        ],
        adoption_token=prepared_a["adoption"]["adoptionToken"],
    )
    active_a = service.acknowledge_proposal_apply(
        tenant_id="tenant-local",
        site_id="site-fdl",
        transaction_id=committed_a["transaction"]["transaction"]["transactionId"],
        expected_transaction_revision=committed_a["transaction"][
            "transactionRevision"
        ],
        adoption_token=prepared_a["adoption"]["adoptionToken"],
        observed_installation_fingerprint=prepared_a[
            "expectedInstallationFingerprint"
        ],
    )
    transaction_a = deepcopy(active_a["transaction"])
    lease_a = deepcopy(active_a["lease"])
    frame_a = {
        **_editor_frame(base, generation="editor-generation-a"),
        "draftLayout": deepcopy(prepared_a["candidateLayout"]),
        "draftRevision": active_a["transaction"]["transaction"][
            "proposalBinding"
        ]["resultLayoutRevision"],
        "generatedDraft": {
            "kind": "facility_design_proposal",
            "proposalId": proposal_a["artifactId"],
        },
        "activeProposal": {
            "proposalId": proposal_a["artifactId"],
            "proposalRevision": proposal_a["artifactRevision"],
            "transactionBindingRevision": prepared_a[
                "transactionBindingRevision"
            ],
        },
        "commandJournalHash": "a" * 64,
    }
    expected_source_owner = {
        field: lease_a[field]
        for field in ("ownerKind", "ownerRunId", "ownerToken", "leaseRevision")
    }
    prepared_b = service.prepare_proposal_apply(
        tenant_id="tenant-local",
        site_id="site-fdl",
        proposal_id=proposal_b["artifactId"],
        proposal_revision=proposal_b["artifactRevision"],
        root_undo_frame=frame_o,
        previous_installation_state=frame_a,
        expected_result_editor_generation_id="editor-generation-b",
        expected_result_command_journal_hash="b" * 64,
        expected_source_owner=expected_source_owner,
        transaction_id=transaction_a["transaction"]["transactionId"],
        expected_transaction_revision=transaction_a["transactionRevision"],
    )
    committed_b = service.commit_proposal_apply(
        tenant_id="tenant-local",
        site_id="site-fdl",
        transaction_id=prepared_b["transaction"]["transaction"]["transactionId"],
        expected_transaction_revision=prepared_b["transaction"][
            "transactionRevision"
        ],
        adoption_token=prepared_b["adoption"]["adoptionToken"],
    )

    with pytest.raises(FacilityDraftLeaseConflictError) as caught:
        service.recover_proposal_apply(
            tenant_id="tenant-local",
            site_id="site-fdl",
            transaction_id=committed_b["transaction"]["transaction"][
                "transactionId"
            ],
            expected_transaction_revision=committed_b["transaction"][
                "transactionRevision"
            ],
            observed_installation_fingerprint=prepared_a["adoption"]["adoption"][
                "rootInstallationFingerprint"
            ],
        )
    assert caught.value.code == "facility_draft_replacement_root_observed"

    recovered = service.recover_proposal_apply(
        tenant_id="tenant-local",
        site_id="site-fdl",
        transaction_id=committed_b["transaction"]["transaction"]["transactionId"],
        expected_transaction_revision=committed_b["transaction"][
            "transactionRevision"
        ],
        observed_installation_fingerprint=prepared_b["adoption"]["adoption"][
            "previousInstallationFingerprint"
        ],
    )
    assert recovered["outcome"] == "previous_proposal_restored"
    assert recovered["transaction"] == transaction_a
    assert recovered["lease"] == lease_a


def test_authority_lost_undo_restores_local_frame_without_touching_new_lease(
    tmp_path: Path,
) -> None:
    fixture = _fixture()
    base, brief = _base_and_brief(fixture)
    clock = _Clock()
    root = tmp_path / "design"
    repository = FacilityDesignRepository(root, clock=clock)
    leases = FacilityDraftLeaseRepository(root, clock=clock)
    _persist_brief(repository, brief)
    runtime = FacilityDesignRuntime(
        repository,
        candidate_recipe_provider=reviewed_fixture_recipe_provider,
        operation_builder=fixture_recipe_operation_builder,
        clock=clock,
    )
    service = FacilityDesignLoopService(
        repository=repository,
        runtime=runtime,
        lease_repository=leases,
        feature_flags=FacilityLayoutFeatureFlags.all_enabled(),
        clock=clock,
    )
    started = runtime.start_preview(
        tenant_id="tenant-local",
        site_id="site-fdl",
        workspace_id="workspace-local",
        design_base=base,
        design_brief=brief,
        source_bundle=_runtime_source(fixture),
        provider="anthropic",
        model="claude-sonnet-4-5-20250929",
        reasoning_effort=None,
        client_generation_id="client-generation-local-undo",
        run_id="fdlr-local-undo",
    )
    completed = runtime.continue_preview(
        tenant_id="tenant-local",
        site_id="site-fdl",
        run_id=started["run"]["runId"],
    )
    proposal = completed["run"]["proposalRefs"][0]
    frame_o = _editor_frame(base)
    prepared = service.prepare_proposal_apply(
        tenant_id="tenant-local",
        site_id="site-fdl",
        proposal_id=proposal["artifactId"],
        proposal_revision=proposal["artifactRevision"],
        root_undo_frame=frame_o,
        previous_installation_state=frame_o,
        expected_result_editor_generation_id="editor-generation-local-undo",
        expected_result_command_journal_hash="d" * 64,
    )
    transaction_id = prepared["transaction"]["transaction"]["transactionId"]
    committed = service.commit_proposal_apply(
        tenant_id="tenant-local",
        site_id="site-fdl",
        transaction_id=transaction_id,
        expected_transaction_revision=prepared["transaction"][
            "transactionRevision"
        ],
        adoption_token=prepared["adoption"]["adoptionToken"],
    )
    active = service.acknowledge_proposal_apply(
        tenant_id="tenant-local",
        site_id="site-fdl",
        transaction_id=transaction_id,
        expected_transaction_revision=committed["transaction"][
            "transactionRevision"
        ],
        adoption_token=prepared["adoption"]["adoptionToken"],
        observed_installation_fingerprint=prepared[
            "expectedInstallationFingerprint"
        ],
    )

    clock.advance(days=1, seconds=1)
    newer = leases.acquire(
        tenant_id="tenant-local",
        site_id="site-fdl",
        layout_id=base["layoutId"],
        owner_kind="generation_run",
        owner_run_id="fgr-new-writer",
        owner_token="lease-new-writer",
        base_saved_layout_revision=base["savedLayoutRevision"],
        current_draft_revision=base["layoutRevision"],
    )
    transaction_before = repository.get_transaction(
        "tenant-local", "site-fdl", transaction_id
    )
    local = service.prepare_undo(
        tenant_id="tenant-local",
        site_id="site-fdl",
        transaction_id=transaction_id,
        expected_transaction_revision=active["transaction"][
            "transactionRevision"
        ],
    )
    assert local["mode"] == "local_only"
    assert local["readiness"] == "stale_local_restore"
    assert local["rootUndoFrame"] == frame_o
    assert leases.inspect(
        "tenant-local", "site-fdl", base["layoutId"]
    )["lease"] == newer
    assert repository.get_transaction(
        "tenant-local", "site-fdl", transaction_id
    ) == transaction_before


def test_design_host_runs_preview_apply_undo_and_explicit_save(
    tmp_path: Path,
) -> None:
    fixture = _fixture()
    host = LocalFacilityLayoutHost(tmp_path / "host")
    host._resolve_process_map = (
        lambda _principal, _site_id, _product_id, _map_id, revision: {
            "revision": revision,
            "document": deepcopy(fixture["processMap"]),
        }
    )
    host.service.process_map_resolver = (
        lambda _principal, _site_id, _product_id, _map_id, revision: {
            "revision": revision,
            "document": deepcopy(fixture["processMap"]),
        }
    )
    app = FastAPI()
    app.include_router(host.create_router())
    client = TestClient(app)
    principal = host.principal()
    host.ensure_bootstrap()
    authorities = reviewed_material_travel_authority_documents(
        site_id=LOCAL_SITE_ID
    )
    shell_document = deepcopy(authorities["facilityShell"])
    shell_document["status"] = "draft"
    shell_created = host.shell_repository.create(
        principal, site_id=LOCAL_SITE_ID, document=shell_document
    )
    shell_reviewed = host.shell_repository.review(
        principal,
        site_id=LOCAL_SITE_ID,
        authority_id=shell_document["shellId"],
        expected_revision=shell_created.envelope.revision,
    )
    shell_published = host.shell_repository.publish(
        principal,
        site_id=LOCAL_SITE_ID,
        authority_id=shell_document["shellId"],
        expected_revision=shell_reviewed.envelope.revision,
    ).envelope
    policy_document = deepcopy(authorities["policySet"])
    policy_document["status"] = "draft"
    policy_created = host.policy_repository.create(
        principal, site_id=LOCAL_SITE_ID, document=policy_document
    )
    policy_reviewed = host.policy_repository.review(
        principal,
        site_id=LOCAL_SITE_ID,
        authority_id=policy_document["policySetId"],
        expected_revision=policy_created.envelope.revision,
    )
    policy_published = host.policy_repository.publish(
        principal,
        site_id=LOCAL_SITE_ID,
        authority_id=policy_document["policySetId"],
        expected_revision=policy_reviewed.envelope.revision,
    ).envelope
    layout = deepcopy(fixture["facilityLayout"])
    layout["layoutId"] = "fl-fdl-host"
    layout["association"]["siteId"] = LOCAL_SITE_ID
    layout["sourceShellRef"] = {
        "shellId": shell_published.document["shellId"],
        "shellRevision": shell_published.revision,
        "coordinateFrameFingerprint": coordinate_frame_fingerprint(
            shell_published.document["coordinateFrame"]
        ),
    }
    layout["policySetRef"] = {
        "policySetId": policy_published.document["policySetId"],
        "policySetRevision": policy_published.revision,
    }
    asset_substitutions = {
        "asset-cnc-mill": "asset-cnc-mill",
        "asset-inspection-station": "asset-workbench",
        "asset-fifo-buffer": "asset-material-transfer-buffer",
        "asset-fixed-obstacle": "asset-pallet-rack",
    }
    local_catalog = {
        item["assetId"]: item
        for item in LOCAL_ASSET_CATALOG
    }
    for placement in layout["placements"]:
        asset_id = asset_substitutions[placement["assetId"]]
        definition = local_catalog[asset_id]
        placement["assetId"] = asset_id
        placement["assetDefinitionRevision"] = definition[
            "assetDefinitionRevision"
        ]
    placement_index = {
        item["placementId"]: item for item in layout["placements"]
    }
    placement_index["pl-cnc-mill-03"]["transform"]["position"]["x"] = 5.0
    placement_index["pl-obstacle-west"]["transform"]["position"]["x"] = 25.0
    created = host.layout_repository.create_layout(
        principal, LOCAL_SITE_ID, layout
    )
    saved_revision = created["revision"]
    base = capture_facility_design_base(
        base_id="fdb-host-material-travel",
        base_kind="saved_layout",
        tenant_id=principal.tenant_id,
        site_id=LOCAL_SITE_ID,
        workspace_id="workspace-local",
        document=created["layout"],
        saved_layout_revision=saved_revision,
        source_ref={
            "repositoryRecordRevision": saved_revision,
            "savedLayoutRevision": saved_revision,
        },
        captured_at=CREATED_AT,
    )
    _, template = _base_and_brief(fixture)
    semantic_body = deepcopy(template["semanticBody"])
    semantic_body.update(
        {
            "tenantId": principal.tenant_id,
            "siteId": LOCAL_SITE_ID,
            "layoutId": layout["layoutId"],
            "baseStateRef": facility_design_base_ref(base),
        }
    )

    def rebind_layout_revision(value):
        if isinstance(value, dict):
            for key, nested in value.items():
                if key == "sourceRevision":
                    value[key] = saved_revision
                else:
                    rebind_layout_revision(nested)
        elif isinstance(value, list):
            for nested in value:
                rebind_layout_revision(nested)

    rebind_layout_revision(semantic_body)
    semantic_body["revisionVector"]["layout"] = saved_revision
    headers = {"X-InspectorPro-Session": "fdl-host-session"}
    created_brief = client.post(
        f"/api/facility-layout-design/{LOCAL_SITE_ID}/{layout['layoutId']}/briefs",
        headers=headers,
        json={
            "briefId": "fdbf-host-material-travel",
            "designBase": base,
            "semanticBody": semantic_body,
            "sourceTurnRef": "turn-1",
        },
    )
    assert created_brief.status_code == 200, created_brief.text
    brief = created_brief.json()["brief"]
    started = client.post(
        f"/api/facility-layout-design/{LOCAL_SITE_ID}/{layout['layoutId']}"
        f"/briefs/{brief['briefId']}/preview",
        headers=headers,
        json={"clientGenerationId": "fdl-host-generation-1"},
    )
    assert started.status_code == 200, started.text
    run_id = started.json()["runId"]
    continued = client.post(
        f"/api/facility-layout-design/{LOCAL_SITE_ID}/{layout['layoutId']}"
        f"/runs/{run_id}/continue",
        headers=headers,
        json={"maximumToolCalls": 10},
    )
    assert continued.status_code == 200, continued.text
    summary = continued.json()
    while summary.get("continuationRequired"):
        continued = client.post(
            f"/api/facility-layout-design/{LOCAL_SITE_ID}/{layout['layoutId']}"
            f"/runs/{run_id}/continue",
            headers=headers,
            json={"maximumToolCalls": 10},
        )
        assert continued.status_code == 200, continued.text
        summary = continued.json()
    assert summary["status"] == "preview_ready"
    assert summary["proposalRefs"]
    proposal_ref = summary["proposalRefs"][0]
    inspected = client.get(
        f"/api/facility-layout-design/{LOCAL_SITE_ID}/{layout['layoutId']}"
        f"/proposals/{proposal_ref['artifactId']}",
        params={
            "proposalRevision": proposal_ref["artifactRevision"],
            "includeCandidateLayout": "true",
        },
    )
    assert inspected.status_code == 200, inspected.text
    assert inspected.json()["candidate"]["candidateLayout"] != base["document"]

    frame = _editor_frame(base)
    prepared = client.post(
        f"/api/facility-layout-design/{LOCAL_SITE_ID}/{layout['layoutId']}"
        f"/proposals/{proposal_ref['artifactId']}/apply/prepare",
        json={
            "proposalRevision": proposal_ref["artifactRevision"],
            "rootUndoFrame": frame,
            "previousInstallationState": frame,
            "expectedResultEditorGenerationId": "editor-generation-host-a",
            "expectedResultCommandJournalHash": "e" * 64,
        },
    )
    assert prepared.status_code == 200, prepared.text
    prepared_body = prepared.json()
    transaction = prepared_body["transaction"]
    transaction_id = transaction["transaction"]["transactionId"]
    committed = client.post(
        f"/api/facility-layout-design/{LOCAL_SITE_ID}/{layout['layoutId']}"
        f"/transactions/{transaction_id}/apply/commit",
        json={
            "expectedTransactionRevision": transaction[
                "transactionRevision"
            ],
            "adoptionToken": prepared_body["adoption"]["adoptionToken"],
        },
    )
    assert committed.status_code == 200, committed.text
    committed_body = committed.json()
    acknowledged = client.post(
        f"/api/facility-layout-design/{LOCAL_SITE_ID}/{layout['layoutId']}"
        f"/transactions/{transaction_id}/apply/acknowledge",
        json={
            "expectedTransactionRevision": committed_body["transaction"][
                "transactionRevision"
            ],
            "adoptionToken": prepared_body["adoption"]["adoptionToken"],
            "observedInstallationFingerprint": prepared_body[
                "expectedInstallationFingerprint"
            ],
        },
    )
    assert acknowledged.status_code == 200, acknowledged.text
    active_transaction = acknowledged.json()["transaction"]

    def browser_number_round_trip(value):
        if isinstance(value, dict):
            return {
                key: browser_number_round_trip(nested)
                for key, nested in value.items()
            }
        if isinstance(value, list):
            return [browser_number_round_trip(item) for item in value]
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return deepcopy(value)

    applied_frame = deepcopy(frame)
    applied_frame.update(
        {
            "baseLayout": browser_number_round_trip(frame["baseLayout"]),
            "draftLayout": browser_number_round_trip(
                prepared_body["candidateLayout"]
            ),
            "draftRevision": prepared_body["transaction"]["transaction"]
            ["proposalBinding"]["resultLayoutRevision"],
            "batches": [
                {
                    "label": "Apply Facility design proposal",
                    "operations": deepcopy(
                        prepared_body["candidateOperations"]
                    ),
                }
            ],
            "cursor": 1,
            "activeProposal": {
                "proposalId": proposal_ref["artifactId"],
                "proposalRevision": proposal_ref["artifactRevision"],
                "transactionId": transaction_id,
                "transactionRevision": active_transaction[
                    "transactionRevision"
                ],
                "transactionBindingRevision": prepared_body[
                    "transactionBindingRevision"
                ],
                "status": "active",
            },
            "editorGenerationId": "editor-generation-host-a",
            "commandJournalHash": "e" * 64,
        }
    )
    continued_from_applied = client.post(
        f"/api/facility-layout-design/{LOCAL_SITE_ID}/{layout['layoutId']}"
        "/briefs",
        headers=headers,
        json={
            "editorFrame": applied_frame,
            "semanticIntent": {
                "schema_version": "facility-design-intent-v1",
                "operation": "create_material_travel_brief",
                "source_label": "Output Buffer A",
                "target_label": "Input Buffer B",
                "loaded_trips_per_shift": 24,
                "shift_name": "Day Shift",
                "locked_entity_labels": [
                    "CNC Mill 03",
                    "Inspection Station 02",
                ],
                "movable_placement_labels": [
                    "Output Buffer A",
                    "Input Buffer B",
                ],
                "mutable_route_labels": [
                    "Material Transfer Aisle",
                    "Main Boulevard",
                ],
            },
            "sourceTurnRef": "turn-applied-editor-draft",
        },
    )
    assert continued_from_applied.status_code == 200, (
        continued_from_applied.text
    )
    applied_brief = continued_from_applied.json()["brief"]
    assert (
        applied_brief["semanticBody"]["baseStateRef"]["baseKind"]
        == "editor_draft"
    )
    applied_base_ref = applied_brief["semanticBody"]["baseStateRef"]
    applied_base = host.design_repository.get_artifact(
        principal.tenant_id,
        LOCAL_SITE_ID,
        "design_base",
        applied_base_ref["baseId"],
        applied_base_ref["baseRevision"],
    )["artifact"]
    assert applied_base["layoutRevision"] == applied_frame["draftRevision"]
    assert applied_base["document"] == prepared_body["candidateLayout"]

    undo = client.post(
        f"/api/facility-layout-design/{LOCAL_SITE_ID}/{layout['layoutId']}"
        f"/transactions/{transaction_id}/undo/prepare",
        json={
            "expectedTransactionRevision": active_transaction[
                "transactionRevision"
            ]
        },
    )
    assert undo.status_code == 200, undo.text
    undo_body = undo.json()
    assert undo_body["rootUndoFrame"] == frame
    undone = client.post(
        f"/api/facility-layout-design/{LOCAL_SITE_ID}/{layout['layoutId']}"
        f"/transactions/{transaction_id}/undo/acknowledge",
        json={
            "expectedTransactionRevision": undo_body["transaction"][
                "transactionRevision"
            ],
            "observedDraftRevision": frame["draftRevision"],
            "observedCommandJournalHash": frame["commandJournalHash"],
        },
    )
    assert undone.status_code == 200, undone.text
    assert undone.json()["transaction"]["transaction"]["status"] == "undone"
    assert host.layout_repository.get_layout(
        principal, LOCAL_SITE_ID, layout["layoutId"]
    )["revision"] == saved_revision

    save_prepared = client.post(
        f"/api/facility-layout-design/{LOCAL_SITE_ID}/{layout['layoutId']}"
        f"/proposals/{proposal_ref['artifactId']}/apply/prepare",
        json={
            "proposalRevision": proposal_ref["artifactRevision"],
            "rootUndoFrame": frame,
            "previousInstallationState": frame,
            "expectedResultEditorGenerationId": "editor-generation-host-save",
            "expectedResultCommandJournalHash": "f" * 64,
        },
    )
    assert save_prepared.status_code == 200, save_prepared.text
    save_prepared_body = save_prepared.json()
    save_transaction = save_prepared_body["transaction"]
    save_transaction_id = save_transaction["transaction"]["transactionId"]
    save_committed = client.post(
        f"/api/facility-layout-design/{LOCAL_SITE_ID}/{layout['layoutId']}"
        f"/transactions/{save_transaction_id}/apply/commit",
        json={
            "expectedTransactionRevision": save_transaction[
                "transactionRevision"
            ],
            "adoptionToken": save_prepared_body["adoption"][
                "adoptionToken"
            ],
        },
    )
    assert save_committed.status_code == 200, save_committed.text
    save_acknowledged = client.post(
        f"/api/facility-layout-design/{LOCAL_SITE_ID}/{layout['layoutId']}"
        f"/transactions/{save_transaction_id}/apply/acknowledge",
        json={
            "expectedTransactionRevision": save_committed.json()[
                "transaction"
            ]["transactionRevision"],
            "adoptionToken": save_prepared_body["adoption"][
                "adoptionToken"
            ],
            "observedInstallationFingerprint": save_prepared_body[
                "expectedInstallationFingerprint"
            ],
        },
    )
    assert save_acknowledged.status_code == 200, save_acknowledged.text
    active_save_transaction = save_acknowledged.json()["transaction"]
    explicit_save = client.post(
        f"/api/facility-layout-design/{LOCAL_SITE_ID}/{layout['layoutId']}"
        f"/transactions/{save_transaction_id}/save",
        json={
            "expectedTransactionRevision": active_save_transaction[
                "transactionRevision"
            ],
            "observedDraftRevision": inspected.json()["proposal"][
                "resultLayoutRevision"
            ],
            "observedCommandJournalHash": "f" * 64,
            "explicitApproval": True,
        },
    )
    assert explicit_save.status_code == 200, explicit_save.text
    saved_body = explicit_save.json()
    assert saved_body["transaction"]["transaction"]["status"] == "saved"
    assert saved_body["lease"]["status"] == "released"
    assert saved_body["saveReceipt"]["proposalId"] == proposal_ref[
        "artifactId"
    ]
    reopened = host.layout_repository.get_layout(
        principal, LOCAL_SITE_ID, layout["layoutId"]
    )
    assert reopened["revision"] == saved_body["savedLayout"]["revision"]
    reopened_geometry = deepcopy(reopened["layout"])
    candidate_geometry = deepcopy(inspected.json()["candidate"]["candidateLayout"])
    candidate_geometry["createdAt"] = reopened_geometry["createdAt"]
    candidate_geometry["updatedAt"] = reopened_geometry["updatedAt"]
    assert canonical_layout_bytes(reopened_geometry) == canonical_layout_bytes(
        candidate_geometry
    )

    duplicate_save = client.post(
        f"/api/facility-layout-design/{LOCAL_SITE_ID}/{layout['layoutId']}"
        f"/transactions/{save_transaction_id}/save",
        json={
            "expectedTransactionRevision": saved_body["transaction"][
                "transactionRevision"
            ],
            "observedDraftRevision": inspected.json()["proposal"][
                "resultLayoutRevision"
            ],
            "observedCommandJournalHash": "f" * 64,
            "explicitApproval": True,
        },
    )
    assert duplicate_save.status_code == 422
    assert duplicate_save.json()["detail"]["error"]["code"] == (
        "facility_design_transaction_not_save_eligible"
    )
    assert host.layout_repository.get_layout(
        principal, LOCAL_SITE_ID, layout["layoutId"]
    )["revision"] == reopened["revision"]
