from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.canonical import canonicalize_layout, layout_revision
from ai_inspector.facility_layout.design_base import capture_facility_design_base
from ai_inspector.facility_layout.design_brief import (
    apply_facility_design_brief_patch,
    create_facility_design_brief,
)
from ai_inspector.facility_layout.design_intent import (
    APPLY_FACILITY_DESIGN_PROPOSAL_DRAFT_TOOL,
    FACILITY_DESIGN_INTENT_SCHEMA_VERSION,
    FacilityDesignIntentError,
    canonicalize_facility_design_intent,
    classify_facility_design_turn,
    compile_facility_design_brief_body,
    compile_facility_design_brief_patch,
    facility_design_agent_tool_specs,
    facility_design_allowed_tools,
    recover_facility_design_create_intent,
    recover_facility_design_update_intent,
)
from ai_inspector.facility_layout.design_fixture import (
    REVIEWED_MATERIAL_TRAVEL_LAYOUT_ID,
    reviewed_material_travel_authority_documents,
    reviewed_material_travel_layout,
    reviewed_material_travel_source_provider,
)
from ai_inspector.facility_layout.design_service import FacilityDesignServiceError


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "design_loop"
    / "fdl-material-travel-v1.json"
)
CREATED_AT = "2026-09-05T12:00:00.000000Z"


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _base() -> dict:
    layout = canonicalize_layout(_fixture()["facilityLayout"])
    revision = layout_revision(layout)
    return capture_facility_design_base(
        base_id="fdb-design-intent",
        base_kind="saved_layout",
        tenant_id="tenant-local",
        site_id="site-fdl",
        workspace_id="workspace-local",
        document=layout,
        saved_layout_revision=revision,
        source_ref={
            "repositoryRecordRevision": revision,
            "savedLayoutRevision": revision,
        },
        captured_at=CREATED_AT,
    )


def _initial_intent() -> dict:
    return {
        "schema_version": FACILITY_DESIGN_INTENT_SCHEMA_VERSION,
        "operation": "create_material_travel_brief",
        "source_label": "Output Buffer A",
        "target_label": "Inspection Input FIFO",
        "loaded_trips_per_shift": 24,
        "shift_name": "Day Shift",
        "locked_entity_labels": ["CNC Mill 03", "Inspection Station 02"],
        "movable_placement_labels": ["Output Buffer A", "Input Buffer B"],
        "mutable_route_labels": ["Material Transfer Aisle", "Main Boulevard"],
    }


def _initial_brief() -> tuple[dict, dict]:
    base = _base()
    intent = _initial_intent()
    intent["target_label"] = "Input Buffer B"
    body = compile_facility_design_brief_body(
        intent=intent,
        design_base=base,
        source_turn_ref="turn-1",
    )
    brief = create_facility_design_brief(
        brief_id="fdbf-intent",
        semantic_body=body,
        source_turn_refs=["turn-1"],
        principal_id="shadrack",
        created_at=CREATED_AT,
    )
    return base, brief


@pytest.mark.parametrize(
    "message",
    [
        "Reduce loaded material travel between machining and inspection.",
        "Cut the material handling distance from the machining FIFO to inspection.",
        "Please shorten loaded travel for the Machining to Inspection transfer.",
        "Lower material movement between these two departments.",
        "Improve the material route distance from Output Buffer A to Input Buffer B.",
        "Minimize loaded material handling between Machining and Inspection.",
        "Reduce material travel for the current transfer.",
        "Cut loaded route distance from Output Buffer A to Input Buffer B.",
        "Shorten the material movement between the two buffers.",
        "Lower loaded travel for this material flow.",
        "Improve material handling from the source buffer to inspection.",
        "Minimise loaded material route distance across this facility.",
    ],
)
def test_material_travel_paraphrases_enter_the_same_design_action(message: str) -> None:
    assert classify_facility_design_turn(message) == {
        "kind": "design",
        "action": "create_and_preview",
    }


@pytest.mark.parametrize(
    "message",
    [
        "Can material travel from Inbound to Dispatch?",
        (
            "What if we added a direct material route from Receiving to "
            "Shipping? Would it reduce travel by 20 percent?"
        ),
        "What would happen if we reduced loaded material travel?",
        "Show material travel from Machining to Inspection.",
    ],
)
def test_read_only_material_travel_questions_do_not_enter_design_mode(
    message: str,
) -> None:
    assert classify_facility_design_turn(message) == {
        "kind": "not_applicable"
    }


@pytest.mark.parametrize(
    ("message", "action"),
    [
        ("Keep the current Main Boulevard fixed too.", "update_and_preview"),
        ("Do not move Output Buffer A; rebuild the proposal.", "update_and_preview"),
        ("Prefer fewer equipment moves over the shortest route.", "update_and_preview"),
        ("Show me the best remaining options.", "preview"),
        ("Apply the corrected proposal you just showed me.", "apply"),
        ("Undo that.", "undo"),
        ("Show the active design brief constraints.", "inspect"),
        ("Hold Input Buffer B in place and rebuild the options.", "update_and_preview"),
        ("Compare the remaining trade-offs.", "preview"),
        ("Install that alternative.", "apply"),
    ],
)
def test_follow_ups_require_and_use_an_exact_active_design(
    message: str,
    action: str,
) -> None:
    active = {"briefId": "fdbf-intent", "briefRevision": "a" * 64}
    assert classify_facility_design_turn(message, active_design=active) == {
        "kind": "design",
        "action": action,
    }
    assert classify_facility_design_turn(message)["kind"] == "not_applicable"


def test_six_turn_acceptance_conversation_has_exact_action_boundaries() -> None:
    active = {"briefId": "fdbf-intent", "briefRevision": "a" * 64}
    turns = [
        (
            "Reduce loaded material travel from Machining Output FIFO to "
            "Inspection Input FIFO. Keep CNC Mill 03 and Inspection Station "
            "02 fixed. You may move Output Buffer A and Input Buffer B, and "
            "you may reroute Material Transfer Aisle and Main Boulevard. Use "
            "the reviewed 24 loaded trips per Day Shift.",
            "create_and_preview",
        ),
        ("Keep the current Main Boulevard fixed too.", "update_and_preview"),
        (
            "Show me the best remaining options. Prefer fewer equipment moves "
            "over the shortest route.",
            "update_and_preview",
        ),
        (
            "Keep Output Buffer A exactly where it is. Rebuild the lower-"
            "disruption option under that lock and show me the corrected "
            "proposal. Do not apply it yet.",
            "update_and_preview",
        ),
        (
            "Apply the corrected lower-disruption proposal you just showed me. "
            "Do not save it.",
            "apply",
        ),
        ("Undo that.", "undo"),
    ]
    for index, (message, action) in enumerate(turns):
        result = classify_facility_design_turn(
            message,
            active_design=None if index == 0 else active,
        )
        assert result == {"kind": "design", "action": action}


def test_explicit_lock_recovery_uses_only_active_exact_referents() -> None:
    active = {
        "briefId": "fdbf-intent",
        "briefRevision": "a" * 64,
        "referents": [
            {"phrase": "Main Boulevard", "status": "active"},
            {"phrase": "Output Buffer A", "status": "active"},
            {"phrase": "Old Buffer", "status": "superseded"},
        ],
    }

    recovered = recover_facility_design_update_intent(
        "Keep Main Boulevard fixed and keep Output Buffer A where it is.",
        active_design=active,
    )

    assert recovered == {
        "schema_version": FACILITY_DESIGN_INTENT_SCHEMA_VERSION,
        "operation": "add_geometry_locks",
        "target_labels": ["Main Boulevard", "Output Buffer A"],
    }
    assert recover_facility_design_update_intent(
        "Keep an unreviewed shortcut fixed.",
        active_design=active,
    ) is None


def test_explicit_preference_recovery_preserves_user_order() -> None:
    active = {"briefId": "fdbf-intent", "briefRevision": "a" * 64}

    fewer_moves = recover_facility_design_update_intent(
        "Prefer fewer equipment moves over the shortest route.",
        active_design=active,
    )
    shortest_route = recover_facility_design_update_intent(
        "Prefer the shortest route over fewer equipment moves.",
        active_design=active,
    )

    assert fewer_moves["preference_metric_ids"] == [
        "movedPlacementCount",
        "loadedRouteDistanceMeters",
    ]
    assert shortest_route["preference_metric_ids"] == [
        "loadedRouteDistanceMeters",
        "movedPlacementCount",
    ]


def test_exact_create_recovery_rejects_unconsumed_constraints() -> None:
    layout = reviewed_material_travel_layout(site_id="site-fdl")
    prefix = (
        "Reduce loaded material travel from Output Buffer A to Input Buffer B. "
        "Keep CNC Mill 03 and Inspection Station 02 fixed. "
    )
    suffix = (
        " You may reroute Material Transfer Aisle and Main Boulevard. "
        "Use the reviewed 24 loaded trips per Day Shift."
    )

    assert recover_facility_design_create_intent(
        prefix
        + "You may move Output Buffer A and Input Buffer B."
        + suffix,
        layout=layout,
    ) is not None
    for constrained_move in (
        "You may move Output Buffer A or Input Buffer B, but not both.",
        "You may move Output Buffer A by at most 1 meter.",
    ):
        assert recover_facility_design_create_intent(
            prefix + constrained_move + suffix,
            layout=layout,
        ) is None
    assert recover_facility_design_create_intent(
        (
            "Reduce loaded material travel from Output Buffer A to Input "
            "Buffer B. Keep CNC Mill 03 and Unknown Press fixed. You may "
            "move Output Buffer A and Input Buffer B. You may reroute "
            "Material Transfer Aisle and Main Boulevard. Use the reviewed "
            "24 loaded trips per Day Shift."
        ),
        layout=layout,
    ) is None


def test_exact_update_recovery_rejects_mixed_lock_and_move_permission() -> None:
    active = {
        "briefId": "fdbf-intent",
        "briefRevision": "a" * 64,
        "referents": [
            {"phrase": "Output Buffer A", "status": "active"},
            {"phrase": "Input Buffer B", "status": "active"},
        ],
    }

    assert recover_facility_design_update_intent(
        "Keep Output Buffer A fixed, but Input Buffer B can move.",
        active_design=active,
    ) is None


def test_rather_than_preference_prioritizes_the_explicit_preference() -> None:
    active = {"briefId": "fdbf-intent", "briefRevision": "a" * 64}

    recovered = recover_facility_design_update_intent(
        "Rather than the shortest route, prefer fewer equipment moves.",
        active_design=active,
    )

    assert recovered["preference_metric_ids"] == [
        "movedPlacementCount",
        "loadedRouteDistanceMeters",
    ]


def test_unsupported_material_travel_claim_refuses_deterministically() -> None:
    result = classify_facility_design_turn(
        "Optimize material travel and certify this layout meets OSHA capacity requirements."
    )
    assert result["kind"] == "refuse"
    assert result["code"] == "facility_design_claim_unsupported"


def test_initial_intent_resolves_exact_ids_and_builds_coordinate_free_brief() -> None:
    base, brief = _initial_brief()
    body = brief["semanticBody"]
    assert body["baseStateRef"]["baseRevision"] == base["baseRevision"]
    assert body["objective"]["processBindingIds"] == [
        "pb-inspection-resource",
        "pb-machining-inspection-transfer",
        "pb-machining-resource",
    ]
    assert {item["entityId"] for item in body["objective"]["targetRefs"]} == {
        "pl-output-buffer-a",
        "pl-input-buffer-b",
        "rt-material-transfer-aisle",
        "rt-main-boulevard",
    }
    assert {item["entityId"] for item in body["hardConstraints"][0]["targetRefs"]}
    encoded = json.dumps(body, sort_keys=True)
    for forbidden in ('"coordinates"', '"centerline"', '"transform"', '"position"'):
        assert forbidden not in encoded


def test_reviewed_process_endpoint_aliases_resolve_without_guessing() -> None:
    base = _base()
    intent = _initial_intent()
    intent["source_label"] = "Machining Output FIFO"

    body = compile_facility_design_brief_body(
        intent=intent,
        design_base=base,
        source_turn_ref="turn-aliases",
    )

    assert {item["entityId"] for item in body["objective"]["targetRefs"]} >= {
        "pl-output-buffer-a",
        "pl-input-buffer-b",
    }


def test_lock_patch_withdraws_the_matching_permission_atomically() -> None:
    base, brief = _initial_brief()
    patch = compile_facility_design_brief_patch(
        intent={
            "schema_version": FACILITY_DESIGN_INTENT_SCHEMA_VERSION,
            "operation": "add_geometry_locks",
            "brief_id": brief["briefId"],
            "expected_brief_revision": brief["briefRevision"],
            "target_labels": ["Main Boulevard"],
        },
        current_brief=brief,
        design_base=base,
        source_turn_ref="turn-2",
    )
    revised = apply_facility_design_brief_patch(
        brief,
        patch,
        source_turn_ref="turn-2",
        principal_id="shadrack",
        created_at="2026-09-05T12:01:00.000000Z",
    )
    route_permissions = [
        item
        for item in revised["semanticBody"]["permittedChanges"]
        if any(ref["entityId"] == "rt-main-boulevard" for ref in item["targetRefs"])
    ]
    assert len(route_permissions) == 1
    assert route_permissions[0]["status"] == "withdrawn"
    assert any(
        constraint["status"] == "active"
        and any(
            ref["entityId"] == "rt-main-boulevard"
            for ref in constraint["targetRefs"]
        )
        for constraint in revised["semanticBody"]["hardConstraints"]
    )


def test_preference_patch_separates_disruption_from_travel() -> None:
    base, brief = _initial_brief()
    patch = compile_facility_design_brief_patch(
        intent={
            "schema_version": FACILITY_DESIGN_INTENT_SCHEMA_VERSION,
            "operation": "set_preference_order",
            "expected_brief_revision": brief["briefRevision"],
            "preference_metric_ids": [
                "movedPlacementCount",
                "loadedTravelMetersPerShift",
            ],
        },
        current_brief=brief,
        design_base=base,
        source_turn_ref="turn-3",
    )
    revised = apply_facility_design_brief_patch(
        brief,
        patch,
        source_turn_ref="turn-3",
        principal_id="shadrack",
        created_at="2026-09-05T12:02:00.000000Z",
    )
    assert [
        (item["metricId"], item["priority"])
        for item in revised["semanticBody"]["preferences"]
        if item["status"] == "active"
    ] == [
        ("movedPlacementCount", 1),
        ("loadedTravelMetersPerShift", 2),
    ]


def test_tool_surface_is_closed_and_apply_is_capability_conditional() -> None:
    preview_specs = facility_design_agent_tool_specs(apply_enabled=False)
    write_specs = facility_design_agent_tool_specs(apply_enabled=True)
    assert APPLY_FACILITY_DESIGN_PROPOSAL_DRAFT_TOOL not in {
        item["name"] for item in preview_specs
    }
    assert APPLY_FACILITY_DESIGN_PROPOSAL_DRAFT_TOOL in {
        item["name"] for item in write_specs
    }
    schema_text = json.dumps(write_specs, sort_keys=True)
    for forbidden in ('"x"', '"y"', '"z"', '"coordinates"', '"centerline"'):
        assert forbidden not in schema_text
    assert APPLY_FACILITY_DESIGN_PROPOSAL_DRAFT_TOOL not in facility_design_allowed_tools(
        "apply", apply_enabled=False
    )
    assert APPLY_FACILITY_DESIGN_PROPOSAL_DRAFT_TOOL in facility_design_allowed_tools(
        "apply", apply_enabled=True
    )


def test_intent_contract_rejects_geometry_fields() -> None:
    value = _initial_intent()
    value["position"] = {"x": 1, "z": 2}
    with pytest.raises(FacilityDesignIntentError) as caught:
        canonicalize_facility_design_intent(value)
    assert caught.value.code == "facility_design_coordinate_ownership"


@pytest.mark.parametrize(
    ("case_id", "mutate_layout", "mutate_intent", "expected_code"),
    [
        (
            "ambiguous-source",
            lambda layout: [
                placement.setdefault("metadata", {}).update(
                    {"semanticAliases": ["Shared Transfer Point"]}
                )
                for placement in layout["placements"][2:4]
            ],
            lambda intent: intent.update({"source_label": "Shared Transfer Point"}),
            "facility_design_referent_ambiguous",
        ),
        (
            "ambiguous-route",
            lambda layout: [
                route.update({"label": "Shared Material Path"})
                for route in layout["routes"]
            ],
            lambda intent: intent.update(
                {"mutable_route_labels": ["Shared Material Path"]}
            ),
            "facility_design_referent_ambiguous",
        ),
        (
            "missing-source",
            lambda _layout: None,
            lambda intent: intent.update({"source_label": "Unknown Output"}),
            "facility_design_referent_missing",
        ),
        (
            "missing-lock",
            lambda _layout: None,
            lambda intent: intent.update(
                {"locked_entity_labels": ["Unknown Fixed Machine"]}
            ),
            "facility_design_referent_missing",
        ),
    ],
)
def test_ambiguous_or_missing_referents_fail_before_brief_mutation(
    case_id,
    mutate_layout,
    mutate_intent,
    expected_code,
) -> None:
    layout = deepcopy(_fixture()["facilityLayout"])
    mutate_layout(layout)
    layout = canonicalize_layout(layout)
    revision = layout_revision(layout)
    base = capture_facility_design_base(
        base_id=f"fdb-{case_id}",
        base_kind="saved_layout",
        tenant_id="tenant-local",
        site_id="site-fdl",
        workspace_id="workspace-local",
        document=layout,
        saved_layout_revision=revision,
        source_ref={
            "repositoryRecordRevision": revision,
            "savedLayoutRevision": revision,
        },
        captured_at=CREATED_AT,
    )
    intent = _initial_intent()
    mutate_intent(intent)
    with pytest.raises(FacilityDesignIntentError) as caught:
        compile_facility_design_brief_body(
            intent=intent,
            design_base=base,
            source_turn_ref=f"turn-{case_id}",
        )
    assert caught.value.code == expected_code
    assert base["document"] == layout


def test_duplicate_referents_are_rejected_instead_of_silently_collapsed() -> None:
    intent = _initial_intent()
    intent["locked_entity_labels"] = ["CNC Mill 03", "CNC Mill 03"]
    with pytest.raises(FacilityDesignIntentError) as caught:
        canonicalize_facility_design_intent(intent)
    assert caught.value.code == "facility_design_intent_invalid"


def test_stale_correction_revision_is_rejected_before_patch_creation() -> None:
    base, brief = _initial_brief()
    with pytest.raises(FacilityDesignIntentError) as caught:
        compile_facility_design_brief_patch(
            intent={
                "schema_version": FACILITY_DESIGN_INTENT_SCHEMA_VERSION,
                "operation": "add_geometry_locks",
                "expected_brief_revision": "f" * 64,
                "target_labels": ["Main Boulevard"],
            },
            current_brief=brief,
            design_base=base,
            source_turn_ref="turn-stale",
        )
    assert caught.value.code == "facility_design_brief_revision_conflict"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (lambda intent: intent.pop("loaded_trips_per_shift"), "facility_design_intent_invalid"),
        (lambda intent: intent.update({"loaded_trips_per_shift": 0}), "facility_design_intent_invalid"),
        (lambda intent: intent.update({"operation": "increase_throughput"}), "facility_design_intent_invalid"),
    ],
)
def test_unavailable_or_unsupported_objective_inputs_fail_closed(
    mutation,
    expected_code,
) -> None:
    intent = _initial_intent()
    mutation(intent)
    with pytest.raises(FacilityDesignIntentError) as caught:
        canonicalize_facility_design_intent(intent)
    assert caught.value.code == expected_code


def test_missing_process_binding_blocks_objective_compilation() -> None:
    layout = deepcopy(_fixture()["facilityLayout"])
    layout["processBindings"] = []
    layout = canonicalize_layout(layout)
    revision = layout_revision(layout)
    base = capture_facility_design_base(
        base_id="fdb-no-bindings",
        base_kind="saved_layout",
        tenant_id="tenant-local",
        site_id="site-fdl",
        workspace_id="workspace-local",
        document=layout,
        saved_layout_revision=revision,
        source_ref={
            "repositoryRecordRevision": revision,
            "savedLayoutRevision": revision,
        },
        captured_at=CREATED_AT,
    )
    with pytest.raises(FacilityDesignIntentError) as caught:
        compile_facility_design_brief_body(
            intent=_initial_intent(),
            design_base=base,
            source_turn_ref="turn-no-bindings",
        )
    assert caught.value.code == "facility_design_process_binding_unavailable"


def test_inconsistent_process_binding_revision_blocks_objective_compilation() -> None:
    layout = deepcopy(_fixture()["facilityLayout"])
    layout["processBindings"][0]["processMapRevision"] = "e" * 64
    layout = canonicalize_layout(layout)
    revision = layout_revision(layout)
    base = capture_facility_design_base(
        base_id="fdb-stale-bindings",
        base_kind="saved_layout",
        tenant_id="tenant-local",
        site_id="site-fdl",
        workspace_id="workspace-local",
        document=layout,
        saved_layout_revision=revision,
        source_ref={
            "repositoryRecordRevision": revision,
            "savedLayoutRevision": revision,
        },
        captured_at=CREATED_AT,
    )
    with pytest.raises(FacilityDesignIntentError) as caught:
        compile_facility_design_brief_body(
            intent=_initial_intent(),
            design_base=base,
            source_turn_ref="turn-stale-bindings",
        )
    assert caught.value.code == "facility_design_process_binding_stale"


def test_reviewed_source_provider_accepts_only_the_exact_fixture_geometry() -> None:
    layout = reviewed_material_travel_layout(site_id="site-local")
    authorities = reviewed_material_travel_authority_documents(
        site_id="site-local"
    )
    assert layout["sourceShellRef"]["shellRevision"] == authorities[
        "facilityShellRevision"
    ]
    assert layout["policySetRef"]["policySetRevision"] == authorities[
        "policySetRevision"
    ]
    source = reviewed_material_travel_source_provider(
        None,
        "site-local",
        REVIEWED_MATERIAL_TRAVEL_LAYOUT_ID,
        {"document": layout},
        {},
    )
    assert source["candidateAuthority"] == "reviewed_test_gold"
    assert len(source["reviewedCandidateRecipes"]) >= 2

    changed = deepcopy(layout)
    changed["placements"][0]["transform"]["position"]["x"] += 1
    with pytest.raises(FacilityDesignServiceError) as caught:
        reviewed_material_travel_source_provider(
            None,
            "site-local",
            REVIEWED_MATERIAL_TRAVEL_LAYOUT_ID,
            {"document": changed},
            {},
        )
    assert caught.value.code == "facility_design_reviewed_fixture_mismatch"
