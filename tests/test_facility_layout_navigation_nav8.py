from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.navigation_intent import (
    BUILD_ACTIVITY_SCENARIO_TOOL,
    PROPOSE_NAVIGATION_INTENT_TOOL,
    classify_navigation_tool_intent,
    is_navigation_semantic_request,
    navigation_action_mode,
    navigation_agent_tool_specs,
    navigation_context_summary,
)
from ai_inspector.facility_layout.operations import (
    FacilityLayoutOperationError,
    apply_facility_layout_operations,
)
from ai_inspector.facility_layout.host import (
    LOCAL_LAYOUT_ID,
    LOCAL_SITE_ID,
    LocalFacilityLayoutHost,
)
import ai_inspector.facility_layout.agent_runtime as agent_runtime_module


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "facility_layout" / "two_asset_cell.json"
DEVELOPMENT_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "navigation"
    / "nav8-development-intent-cases-v1.json"
)
HELD_OUT_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "navigation"
    / "nav8-held-out-intent-cases-v1.json"
)


def _extension() -> dict:
    return {
        "schemaVersion": 1,
        "anchors": [{
            "navigationAnchorId": "na-machine-home",
            "anchorKind": "actor_home",
            "ownerRef": {
                "ownerKind": "placement",
                "ownerId": "pl-machine-01",
            },
            "interactionKind": "none",
            "positionAuthority": "ui_authored",
            "localPosition": {"x": 4.0, "z": 4.0},
            "derivedPositionRef": None,
            "approachDirections": ["any"],
            "actorClasses": ["pedestrian"],
            "evidenceStatus": "authored",
            "evidence": ["evidence:ui-plan-pointer"],
            "reviewStatus": "pending",
        }],
        "movementPrograms": [{
            "movementProgramId": "nmp-machine-cycle",
            "actorPlacementId": "pl-machine-01",
            "actorClass": "pedestrian",
            "actorProfileRef": {
                "profileKind": "pedestrian",
                "profileId": "operator-profile-standard",
                "profileRevision": "1" * 64,
            },
            "orderedStops": [{
                "stopId": "nst-machine-home",
                "navigationAnchorId": "na-machine-home",
                "interactionKind": "none",
                "required": True,
            }],
            "loopMode": "closed_loop",
            "requiredRouteIds": [],
            "requiredAnchorIds": ["na-machine-home"],
            "forbiddenZoneIds": [],
            "forbiddenRouteIds": [],
            "manualPathConstraintIds": ["nmc-machine-guide"],
            "handoffProgramIds": [],
            "sourceRevisions": {"layout": "2" * 64},
            "evidenceStatus": "authored",
            "evidence": ["evidence:ui-plan-pointer"],
            "reviewStatus": "pending",
        }],
        "manualPathConstraints": [{
            "manualPathConstraintId": "nmc-machine-guide",
            "movementProgramId": "nmp-machine-cycle",
            "constraintMode": "guide",
            "authoredPolyline": [
                {"x": 4.0, "z": 4.0},
                {"x": 6.0, "z": 4.0},
            ],
            "snapRefs": [{
                "pointIndex": 0,
                "refKind": "navigation_anchor",
                "refId": "na-machine-home",
            }],
            "lockedSegmentIndexes": [],
            "direction": "bidirectional",
            "positionAuthority": "ui_authored",
            "evidenceStatus": "authored",
            "evidence": ["evidence:ui-plan-pointer"],
            "reviewStatus": "pending",
        }],
        "handoffPrograms": [],
    }


def _layout() -> dict:
    value = json.loads(FIXTURE.read_text(encoding="ascii"))
    value["placements"][0].setdefault("metadata", {})[
        "activityActorType"
    ] = "operator"
    value["placements"][0]["metadata"]["instanceLabel"] = "Operator One"
    value["extensions"] = {"facilityNavigation": _extension()}
    return value


def _semantic_proposal(layout: dict) -> dict:
    proposal = deepcopy(layout["extensions"]["facilityNavigation"])
    program = proposal["movementPrograms"][0]
    program["loopMode"] = "out_and_return"
    program["evidenceStatus"] = "inferred"
    program["evidence"] = ["evidence:sage-semantic-proposal"]
    program["reviewStatus"] = "pending"
    return proposal


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def test_semantic_writer_changes_one_program_and_preserves_geometry() -> None:
    layout = _layout()
    before_manual = _canonical_bytes({
        "anchors": layout["extensions"]["facilityNavigation"]["anchors"],
        "manualPathConstraints": layout["extensions"]["facilityNavigation"][
            "manualPathConstraints"
        ],
    })
    result = apply_facility_layout_operations(layout, [{
        "op": "set_facility_navigation",
        "authoringSource": "sage_semantic",
        "facilityNavigation": _semantic_proposal(layout),
    }])
    navigation = result["document"]["extensions"]["facilityNavigation"]
    after_manual = _canonical_bytes({
        "anchors": navigation["anchors"],
        "manualPathConstraints": navigation["manualPathConstraints"],
    })

    assert before_manual == after_manual
    assert navigation["movementPrograms"][0]["loopMode"] == "out_and_return"
    assert navigation["movementPrograms"][0]["evidenceStatus"] == "inferred"
    assert navigation["movementPrograms"][0]["reviewStatus"] == "pending"


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda proposal: proposal["anchors"][0]["localPosition"].update(
                {"x": 12.0}
            ),
            "facility_navigation_writer_authority_forbidden",
        ),
        (
            lambda proposal: proposal["movementPrograms"][0].update({
                "loopMode": "out_and_return",
                "evidenceStatus": "authored",
                "reviewStatus": "confirmed",
            }),
            "facility_navigation_writer_authority_forbidden",
        ),
    ],
)
def test_semantic_writer_fails_closed(mutate, code: str) -> None:
    layout = _layout()
    proposal = _semantic_proposal(layout)
    mutate(proposal)
    with pytest.raises(FacilityLayoutOperationError) as caught:
        apply_facility_layout_operations(layout, [{
            "op": "set_facility_navigation",
            "authoringSource": "sage_semantic",
            "facilityNavigation": proposal,
        }])
    assert caught.value.code == code


@pytest.mark.parametrize(
    ("prompt", "code"),
    [
        (
            "Route Operator One through na-machine-home at x=40 z=25.",
            "facility_navigation_coordinate_authority_forbidden",
        ),
        (
            "Is movement program nmp-machine-cycle safe?",
            "facility_navigation_engineering_authority_unavailable",
        ),
        (
            "Does actor journey njs-machine-cycle meet OSHA egress requirements?",
            "facility_navigation_engineering_authority_unavailable",
        ),
        (
            "Use whatever clearance is adequate for movement program nmp-forklift.",
            "facility_navigation_engineering_authority_unavailable",
        ),
    ],
)
def test_navigation_claims_refuse_before_provider(prompt: str, code: str) -> None:
    result = classify_navigation_tool_intent(prompt, _layout())
    assert result["kind"] == "refuse"
    assert result["code"] == code


def test_navigation_classifier_resolves_identity_only_tools() -> None:
    layout = _layout()
    propose = classify_navigation_tool_intent(
        "Assign Operator One to na-machine-home and return on the same path.",
        layout,
    )
    assert propose["kind"] == "tool"
    assert propose["tool"] == PROPOSE_NAVIGATION_INTENT_TOOL
    assert propose["arguments"]["actorPlacementId"] == "pl-machine-01"
    assert "x" not in json.dumps(propose["arguments"])

    activity = classify_navigation_tool_intent(
        "Show movement program nmp-machine-cycle in motion.",
        layout,
    )
    assert activity["kind"] == "tool"
    assert activity["tool"] == BUILD_ACTIVITY_SCENARIO_TOOL
    assert activity["arguments"]["movementProgramIds"] == [
        "nmp-machine-cycle"
    ]


def test_selected_plan_authored_path_prompt_starts_read_only_activity() -> None:
    prompt = (
        "Use the selected operator's existing Plan-authored motion path. "
        "Compile its navigation snapshot, plan the journey, and play it in "
        "Plan and 3D. Do not create coordinates and do not save the layout."
    )

    assert is_navigation_semantic_request(prompt) is True
    assert navigation_action_mode(prompt) == "READ_ONLY"
    result = classify_navigation_tool_intent(
        prompt,
        _layout(),
        selected_actor_ids=["pl-machine-01"],
    )

    assert result["kind"] == "tool"
    assert result["tool"] == BUILD_ACTIVITY_SCENARIO_TOOL
    assert result["arguments"]["movementProgramIds"] == [
        "nmp-machine-cycle"
    ]
    assert result["arguments"]["prototypeMode"] is True
    assert "coordinate" not in json.dumps(result["arguments"])


def test_selected_operator_and_destinations_compile_one_automatic_route() -> None:
    prompt = (
        "Route this operator through the selected stops in order, return to "
        "the start, and play it. Do not save."
    )
    result = classify_navigation_tool_intent(
        prompt,
        _layout(),
        selected_actor_ids=["pl-machine-01", "pl-workstation-01"],
    )

    assert result["kind"] == "tool"
    assert result["tool"] == PROPOSE_NAVIGATION_INTENT_TOOL
    assert result["arguments"] == {
        "actorPlacementId": "pl-machine-01",
        "movementProgramId": "nmp-machine-cycle",
        "orderedTargetPlacementIds": ["pl-workstation-01"],
        "loopMode": "task_cycle",
        "requiredRouteIds": [],
        "forbiddenZoneIds": [],
        "forbiddenRouteIds": [],
        "playAfterProposal": True,
    }
    assert "coordinate" not in json.dumps(result["arguments"])


def test_automatic_route_names_a_missing_destination_selection() -> None:
    result = classify_navigation_tool_intent(
        "Route the selected operator through the selected destinations.",
        _layout(),
        selected_actor_ids=["pl-machine-01"],
    )

    assert result["kind"] == "ask"
    assert result["code"] == "facility_navigation_destinations_not_selected"


def test_selected_path_playback_names_missing_prerequisites() -> None:
    prompt = (
        "Use the selected operator's existing Plan-authored motion path. "
        "Compile its navigation snapshot, plan the journey, and play it in "
        "Plan and 3D. Do not create coordinates and do not save the layout."
    )
    no_selection = classify_navigation_tool_intent(
        prompt,
        _layout(),
        selected_actor_ids=[],
    )
    assert no_selection["kind"] == "ask"
    assert no_selection["code"] == "facility_navigation_actor_not_selected"

    no_path_layout = _layout()
    no_path_layout["extensions"]["facilityNavigation"][
        "movementPrograms"
    ][0]["manualPathConstraintIds"] = []
    no_path = classify_navigation_tool_intent(
        prompt,
        no_path_layout,
        selected_actor_ids=["pl-machine-01"],
    )
    assert no_path["kind"] == "ask"
    assert no_path["code"] == "facility_navigation_manual_path_unavailable"


def test_sage_contract_and_context_are_coordinate_free() -> None:
    specs = navigation_agent_tool_specs()
    assert len(specs) == 7
    serialized_specs = json.dumps(specs, sort_keys=True)
    for forbidden_property in (
        '"x"',
        '"y"',
        '"z"',
        '"position"',
        '"coordinates"',
        '"path"',
        '"waypoints"',
    ):
        assert forbidden_property not in serialized_specs

    summary = navigation_context_summary(_layout())
    serialized_summary = json.dumps(summary, sort_keys=True)
    assert '"localPosition"' not in serialized_summary
    assert '"authoredPolyline"' not in serialized_summary
    assert summary["counts"] == {
        "actors": 1,
        "anchors": 1,
        "movementPrograms": 1,
        "handoffPrograms": 0,
    }
    assert summary["canonicalBytes"] <= 8_192


def test_agent_runtime_dispatches_five_bounded_navigation_reads(
    tmp_path: Path,
    monkeypatch,
) -> None:
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    host.ensure_bootstrap()
    try:
        principal = host.principal()
        current = host.service.get_layout(
            principal,
            LOCAL_SITE_ID,
            LOCAL_LAYOUT_ID,
        )
        revision = current["revision"]

        monkeypatch.setattr(
            host.service,
            "compile_navigation_snapshot",
            lambda *_args, **_kwargs: {
                "summary": {
                    "navigationPackageId": "navpkg-runtime-one",
                    "movementProgramId": "nmp-runtime-one",
                    "outcome": "compiled",
                },
                "mutated": False,
            },
        )
        monkeypatch.setattr(
            host.service,
            "plan_actor_journey",
            lambda *_args, **_kwargs: {
                "summary": {
                    "journeySolutionId": "njs-runtime-one",
                    "movementProgramId": "nmp-runtime-one",
                    "outcome": "accepted",
                },
                "mutated": False,
            },
        )

        def journey(journey_id: str) -> dict:
            suffix = "two" if str(journey_id).endswith("two") else "one"
            return {
                "journeySolutionId": f"njs-runtime-{suffix}",
                "movementProgramId": "nmp-runtime-one",
                "actorPlacementId": "pl-runtime-one",
                "outcome": "accepted",
                "distanceMeters": 12.5 if suffix == "one" else 14.0,
                "turnCount": 2 if suffix == "one" else 1,
                "reverseUsed": False,
                "solutionFingerprint": ("a" if suffix == "one" else "b") * 64,
                "generationLayoutRevision": revision,
                "validationContextFingerprint": "c" * 64,
            }

        monkeypatch.setattr(host.service, "get_actor_journey", (
            lambda _principal, _site, _layout, journey_id: journey(journey_id)
        ))
        monkeypatch.setattr(
            agent_runtime_module,
            "journey_solution_summary",
            lambda value: {
                key: value[key]
                for key in (
                    "journeySolutionId",
                    "movementProgramId",
                    "actorPlacementId",
                    "outcome",
                    "distanceMeters",
                    "turnCount",
                    "solutionFingerprint",
                )
            },
        )

        calls = [
            ("observe_navigation_context", {"maximumRecords": 10}),
            (
                "compile_navigation_snapshot",
                {"movementProgramId": "nmp-runtime-one"},
            ),
            (
                "plan_actor_journey",
                {
                    "navigationPackageId": "navpkg-runtime-one",
                    "movementProgramId": "nmp-runtime-one",
                },
            ),
            (
                "validate_actor_journey",
                {"journeySolutionId": "njs-runtime-one"},
            ),
            (
                "compare_journey_alternatives",
                {
                    "journeySolutionIds": [
                        "njs-runtime-one",
                        "njs-runtime-two",
                    ]
                },
            ),
        ]
        results = [
            host.agent_runtime.execute_read_tool(
                principal,
                site_id=LOCAL_SITE_ID,
                layout_id=LOCAL_LAYOUT_ID,
                expected_revision=revision,
                tool_name=name,
                arguments=arguments,
                turn_id="turn-nav8-read-chain",
            )
            for name, arguments in calls
        ]
        assert len(results) == 5
        assert results[1]["summary"]["navigationPackageId"] == (
            "navpkg-runtime-one"
        )
        assert results[2]["summary"]["journeySolutionId"] == "njs-runtime-one"
        assert results[3]["stale"] is False
        assert results[4]["operationalOptimalityClaimed"] is False
        for result in results:
            payload = json.dumps(result, sort_keys=True)
            assert len(payload.encode("ascii")) <= 16_384
            for geometry_field in (
                '"centerline"',
                '"poses"',
                '"coordinates"',
                '"waypoints"',
            ):
                assert geometry_field not in payload
    finally:
        host.close()


def test_development_intent_accuracy_and_refusal_gate() -> None:
    fixture = json.loads(DEVELOPMENT_FIXTURE.read_text(encoding="ascii"))
    assert fixture["usedToAuthorRules"] is True
    cases = fixture["cases"]
    correct = 0
    refusal_total = 0
    refusal_correct = 0
    failures = []
    for case in cases:
        actual = classify_navigation_tool_intent(case["prompt"], _layout())
        matched = actual.get("kind") == case["kind"]
        if case.get("tool") is not None:
            matched = matched and actual.get("tool") == case["tool"]
        if case.get("code") is not None:
            matched = matched and actual.get("code") == case["code"]
        if matched:
            correct += 1
        else:
            failures.append({"caseId": case["caseId"], "actual": actual})
        if case["kind"] == "refuse":
            refusal_total += 1
            if matched:
                refusal_correct += 1

    assert len(cases) == 41
    assert refusal_total == 8
    assert refusal_correct == refusal_total, failures
    assert correct / len(cases) >= 0.95, failures


def test_held_out_intent_gate() -> None:
    fixture_bytes = HELD_OUT_FIXTURE.read_bytes()
    assert hashlib.sha256(fixture_bytes).hexdigest() == (
        "88df25add9f09779bbec594cdcdceb0cb3757d398b3c134f5dbac67388c595cf"
    )
    fixture = json.loads(fixture_bytes.decode("ascii"))
    assert fixture["usedToAuthorRules"] is False
    cases = fixture["cases"]
    results = [
        (case, classify_navigation_tool_intent(case["prompt"], _layout()))
        for case in cases
    ]
    failures = []
    refusal_total = 0
    refusal_correct = 0
    for case, actual in results:
        matched = actual.get("kind") == case["kind"]
        if case.get("tool") is not None:
            matched = matched and actual.get("tool") == case["tool"]
        if case.get("code") is not None:
            matched = matched and actual.get("code") == case["code"]
        if not matched:
            failures.append({"caseId": case["caseId"], "actual": actual})
        if case["kind"] == "refuse":
            refusal_total += 1
            if matched:
                refusal_correct += 1

    correct = len(cases) - len(failures)
    assert len(cases) == 40
    assert refusal_total == 8
    assert refusal_correct == refusal_total, failures
    assert correct / len(cases) >= 0.95, failures
