from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import server
from ai_inspector.telemetry import get_default_store, reset_default_store_for_tests


@pytest.fixture
def feedback_client(tmp_path: Path, monkeypatch):
    database_path = tmp_path / "chat-feedback.sqlite3"
    metrics_path = tmp_path / "chat-feedback-telemetry.sqlite3"
    monkeypatch.setenv("INSPECTORPRO_CHAT_FEEDBACK_DB_PATH", str(database_path))
    monkeypatch.setenv("INSPECTORPRO_METRICS_DB", str(metrics_path))
    server._reset_chat_feedback_store_for_tests()
    reset_default_store_for_tests()
    with TestClient(server.app) as client:
        yield client, database_path, metrics_path
    server._reset_chat_feedback_store_for_tests()
    reset_default_store_for_tests()


def _payload(**overrides):
    payload = {
        "messageId": "message-42",
        "rating": "down",
        "reasons": ["invalid_clearance"],
        "correction": "Maintain 1.2 m operator clearance.",
        "responseText": "The proposed machine row is valid.",
        "conversationId": "conversation-7",
        "agentSessionId": "session-7",
        "clientTurnId": "client-turn-7",
        "turnId": "turn-7",
        "runId": "run-7",
        "responseId": "response-7",
        "agentType": "deviation-analyst",
        "model": "test-model",
        "promptVersion": "facility-layout-v1",
        "trace": {
            "contextManifestId": "manifest-7",
            "toolIds": ["facility.layout.validate"],
        },
    }
    payload.update(overrides)
    return payload


def test_feedback_endpoint_persists_trace_and_updates_one_message(feedback_client):
    client, database_path, metrics_path = feedback_client

    first = client.post("/api/agent/chat/feedback", json=_payload())
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["status"] == "recorded"
    assert first_body["rating"] == "down"

    second = client.post(
        "/api/agent/chat/feedback",
        json=_payload(rating="up", reasons=[], correction=""),
    )
    assert second.status_code == 200, second.text
    assert second.json()["feedbackId"] == first_body["feedbackId"]
    assert second.json()["rating"] == "up"

    record = server._chat_feedback_store().get(
        tenant_id="local",
        user_id="local-user",
        message_id="message-42",
    )
    assert record is not None
    assert record["turn_id"] == "turn-7"
    assert record["run_id"] == "run-7"
    assert record["rating"] == "up"
    assert database_path.exists()
    telemetry = [
        event
        for event in get_default_store().query_recent(20)
        if event.workflow == "agent_chat_feedback"
    ]
    assert telemetry
    assert telemetry[0].feedbackRating == "up"
    assert telemetry[0].feedbackReasonCount == 0
    assert telemetry[0].feedbackHasCorrection is False
    assert telemetry[0].feedbackLinkedTurn is True
    assert telemetry[0].feedbackLinkedRun is True
    assert metrics_path.exists()


def test_feedback_endpoint_rejects_unknown_reason(feedback_client):
    client, _database_path, _metrics_path = feedback_client
    response = client.post(
        "/api/agent/chat/feedback",
        json=_payload(reasons=["looks_unusual"]),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"]["code"] == "invalid_chat_feedback"
