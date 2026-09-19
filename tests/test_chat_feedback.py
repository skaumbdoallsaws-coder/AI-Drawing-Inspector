from __future__ import annotations

import json

import pytest

from ai_inspector.chat_feedback import ChatFeedbackError, ChatFeedbackStore


def _payload(**overrides):
    value = {
        "messageId": "turn_42",
        "rating": "down",
        "reasons": ["missing_context", "incorrect_calculation"],
        "correction": "Use the approved 25 mm bore.",
        "responseText": "The bore is 24 mm.",
        "conversationId": "conversation_1",
        "agentSessionId": "session_sage",
        "clientTurnId": "client_turn_42",
        "turnId": "turn_42",
        "runId": "run_42",
        "responseId": "response_42",
        "agentType": "deviation-analyst",
        "model": "test-model",
        "promptVersion": "prompt-v1",
        "trace": {"sourceIds": ["source_skf"], "toolIds": ["inspect_part"]},
    }
    value.update(overrides)
    return value


def test_feedback_is_durable_trace_linked_and_idempotently_updated(tmp_path) -> None:
    store = ChatFeedbackStore(tmp_path / "feedback.sqlite3")

    first = store.record(tenant_id="tenant_1", user_id="user_1", payload=_payload())
    second = store.record(
        tenant_id="tenant_1",
        user_id="user_1",
        payload=_payload(rating="up", reasons=["bad_source"], correction=""),
    )

    assert second.feedback_id == first.feedback_id
    row = store.get(tenant_id="tenant_1", user_id="user_1", message_id="turn_42")
    assert row is not None
    assert row["rating"] == "up"
    assert json.loads(row["reasons_json"]) == []
    assert row["turn_id"] == "turn_42"
    assert row["run_id"] == "run_42"
    assert len(row["response_sha256"]) == 64


def test_feedback_is_tenant_and_user_scoped(tmp_path) -> None:
    store = ChatFeedbackStore(tmp_path / "feedback.sqlite3")
    store.record(tenant_id="tenant_a", user_id="user_a", payload=_payload())

    assert store.get(tenant_id="tenant_b", user_id="user_a", message_id="turn_42") is None
    assert store.get(tenant_id="tenant_a", user_id="user_b", message_id="turn_42") is None


def test_feedback_rejects_unknown_reasons(tmp_path) -> None:
    store = ChatFeedbackStore(tmp_path / "feedback.sqlite3")

    with pytest.raises(ChatFeedbackError, match="unsupported feedback reason"):
        store.record(
            tenant_id="tenant_1",
            user_id="user_1",
            payload=_payload(reasons=["execute_arbitrary_action"]),
        )


def test_feedback_redacts_secrets_before_persistence(tmp_path) -> None:
    store = ChatFeedbackStore(tmp_path / "feedback.sqlite3")
    secret = "sk-ant-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    store.record(
        tenant_id="tenant_1",
        user_id="user_1",
        payload=_payload(
            responseText="Provider key " + secret,
            correction="Remove " + secret,
            trace={"providerNote": secret},
        ),
    )

    row = store.get(tenant_id="tenant_1", user_id="user_1", message_id="turn_42")
    assert row is not None
    persisted = row["response_text"] + row["correction_text"] + row["trace_json"]
    assert secret not in persisted
    assert "sk-ant-" not in persisted
