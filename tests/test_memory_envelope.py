from __future__ import annotations

import copy

import pytest

from ai_inspector.memory import (
    ContinuityProjection,
    MemoryEnvelopeError,
    build_memory_envelope,
    canonical_sha256,
    finalize_context_manifest,
)


def _continuity(*, summary: bool = True) -> ContinuityProjection:
    value = None
    if summary:
        value = {
            "schemaVersion": "sage-continuity-summary-1.0",
            "summaryRevision": 1,
            "throughTurnSequence": 4,
            "objective": {
                "text": "Review the current map.",
                "sourceTurnIds": ["turn-source-001"],
            },
            "userClaims": [],
            "continuityDecisions": [],
            "assumptions": [],
            "corrections": [],
            "openQuestions": [],
            "referencedEntities": [],
            "sourceEvidenceRefs": [],
            "warnings": [],
        }
    return ContinuityProjection(
        status="healthy",
        staleness="fresh",
        summary=value,
        summary_revision=1 if value else 0,
        through_turn_sequence=4 if value else 0,
        recent_history=(
            {"role": "user", "content": "Show the current map."},
            {"role": "assistant", "content": "The saved map is loaded."},
        ),
        recent_turn_ids=("turn-source-004",),
        omitted_turn_count=3,
        unsummarized_turn_count=0 if value else 1,
        unsummarized_token_estimate=0,
        oldest_unsummarized_turn_sequence=None if value else 1,
        all_unsummarized_turns_included=True,
        warnings=(),
        applied_to_prompt=True,
    )


def _arguments() -> dict:
    return {
        "context_manifest_id": "context-test-001",
        "identity": {
            "conversationId": "conv-test-001",
            "agentSessionId": "agent-session-test-001",
            "turnId": "turn-test-005",
            "agentType": "deviation-analyst",
        },
        "scope": {
            "kind": "process_map",
            "ids": {"productId": "tricycle", "mapId": "default"},
            "scopeFingerprint": "scope-v1:" + "1" * 64,
            "revisionVector": {
                "processMapRevision": "a" * 64,
                "productStructureRevision": "b" * 64,
            },
        },
        "workflow_state": {
            "workflow_id": "process-map-generation",
            "version": "1.0.0",
            "status": "active",
            "stage": "draft_plan",
            "objective": "Build a reviewable map preview.",
            "entities": {},
            "referents": {},
            "pending_clarification": None,
        },
        "providers": [
            {
                "contextKey": "assembly.parts",
                "origin": "browser",
                "requestedBy": ["generate-process-map"],
                "required": False,
                "sourceIds": ["browser-selection"],
                "sourceRevisions": [],
                "included": True,
                "payload": {"selected_parts": ["untrusted-browser-part"]},
            },
            {
                "contextKey": "process_map.state",
                "origin": "server",
                "requestedBy": ["generate-process-map"],
                "required": True,
                "sourceIds": ["tricycle/default"],
                "sourceRevisions": ["a" * 64],
                "included": True,
                "payload": {"dirty": False, "selection": []},
            },
            {
                "contextKey": "process_map.evidence",
                "origin": "server",
                "requestedBy": ["generate-process-map"],
                "required": False,
                "sourceIds": ["tricycle/default"],
                "sourceRevisions": ["a" * 64],
                "included": False,
                "omissionReason": "optional_context_unavailable",
            },
        ],
        "approved_source_decisions": [],
        "continuity": _continuity(),
        "receipts": [],
        "selected_skills": ["generate-process-map"],
        "allowed_tools": ["build_process_map_preview"],
        "restrictions": ["no_commit_without_approval"],
        "classification": "preview",
        "current_user_request": "Build a preview but do not commit it.",
    }


def test_envelope_is_canonical_deterministic_and_authority_separated() -> None:
    args = _arguments()
    first = build_memory_envelope(**args)
    second_args = copy.deepcopy(args)
    second_args["providers"] = list(reversed(second_args["providers"]))
    second = build_memory_envelope(**second_args)

    assert first.envelope == second.envelope
    assert first.manifest == second.manifest
    assert first.memory_envelope_sha256 == second.memory_envelope_sha256
    assert canonical_sha256(first.envelope) == first.memory_envelope_sha256
    trusted = first.envelope["observations"]["trustedContext"]
    assert trusted == {
        "process_map.state": {"dirty": False, "selection": []}
    }
    assert "assembly.parts" not in trusted
    assert first.envelope["continuity"]["authority"] == (
        "untrusted_continuity"
    )
    assert first.envelope["budget"]["omissions"] == [
        "process_map.evidence:optional_context_unavailable"
    ]
    provider = {
        row["contextKey"]: row for row in first.manifest["providers"]
    }
    for key in ("assembly.parts", "process_map.state"):
        assert provider[key]["included"] is True
        assert provider[key]["origin"] in {"server", "browser"}
        assert provider[key]["requestedBy"]
        assert provider[key]["estimatedTokens"] > 0
        assert len(provider[key]["payloadSha256"]) == 64
    assert "untrusted-browser-part" not in str(first.manifest)
    for tag in (
        "trusted_current_state",
        "trusted_source_decisions",
        "workflow_continuity",
        "untrusted_conversation_summary",
        "untrusted_recent_turns",
    ):
        assert f"<{tag}>" in first.prompt_sections


def test_initial_turn_supports_no_summary_without_inventing_provenance() -> None:
    args = _arguments()
    args["continuity"] = _continuity(summary=False)
    built = build_memory_envelope(**args)

    assert built.envelope["continuity"]["summary"] is None
    assert built.manifest["continuity"]["summaryRevision"] == 0
    assert "turn-source-001" not in built.prompt_sections


def test_required_section_budget_fails_closed_with_provider_details() -> None:
    args = _arguments()
    args["providers"][1]["payload"] = {"state": "x" * 26000}

    with pytest.raises(MemoryEnvelopeError) as caught:
        build_memory_envelope(**args)

    assert caught.value.code == "required_context_budget_exceeded"
    assert caught.value.details["section"] == "trustedContext"
    assert caught.value.details["providers"] == ["process_map.state"]


def test_manifest_never_contains_raw_images_or_secrets() -> None:
    for payload in (
        {"preview": "data:image/png;base64,AAAA"},
        {"apiKey": "must-not-persist"},
    ):
        args = _arguments()
        args["providers"][1]["payload"] = payload
        with pytest.raises(MemoryEnvelopeError) as caught:
            build_memory_envelope(**args)
        assert caught.value.code == "unsafe_memory_payload"


def test_terminal_barrier_finalization_preserves_envelope_hash() -> None:
    built = build_memory_envelope(**_arguments())
    finalized = finalize_context_manifest(
        built.manifest,
        {
            "classification": "preview",
            "sourceRevisionVectorSha256": "c" * 64,
            "preEffectRevisionVectorSha256": "c" * 64,
            "outcome": "effect_committed",
            "resultingRevisionVector": {"processMapRevision": "d" * 64},
            "postEffectRevisionDrift": True,
        },
    )

    assert finalized["memoryEnvelopeSha256"] == (
        built.memory_envelope_sha256
    )
    assert finalized["revisionBarrier"]["outcome"] == "effect_committed"
    assert finalized["revisionBarrier"]["resultingRevisionVectorSha256"]
    assert finalized["revisionBarrier"]["postEffectRevisionDrift"] is True

    lifecycle_shape = finalize_context_manifest(
        built.manifest,
        {
            "classification": "action_write",
            "sourceRevisionVector": {"processMapRevision": "a" * 64},
            "preEffectRevisionVector": {"processMapRevision": "a" * 64},
            "resultingRevisionVector": {"processMapRevision": "b" * 64},
            "casOutcome": "applied",
            "effectCount": 1,
            "postEffectRevisionDrift": False,
        },
    )
    assert lifecycle_shape["revisionBarrier"]["outcome"] == (
        "effect_committed"
    )
