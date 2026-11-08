"""Saved-revision validation evidence using real gateways and disposable storage."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from ai_inspector.codex_runtime import packaging_pilot as pilot, packaging_tools as tools
from tests.test_codex_packaging_pilot import execute, setup
from tests.test_codex_packaging_tools import edit_args, env, gateway, invoke, sample_design


def evidence(gw):
    return pilot._evidence(gw, settings=SimpleNamespace(auth_mode="api_key"), effort="medium")


@pytest.mark.parametrize("saved", [True, False])
def test_validation_receipt_records_only_saved_status_and_revision(env, saved):
    gw = gateway(env)
    args = {"expected_revision": 0}
    if not saved:
        args["design"] = sample_design().model_dump(mode="json")
        args["design"]["product"]["mass_evidence"] = "private proposed measurement"
    result = invoke(gw, "validate_packaging", args)
    assert result["ok"]
    receipt = gw.receipts[-1]
    assert receipt["validation"] == {"saved": saved, "revision": 0}
    assert set(receipt) == {"tool", "ok", "argumentHash", "bindingHash", "durationMs", "errorCode", "mutation", "validation"}
    serialized = json.dumps(receipt)
    for private in ("private proposed measurement", "Scale reading", "Foam supplier data", "Pump shipment", str(env[0].root)):
        assert private not in serialized
    assert evidence(gw)["checkedPackaging"] is saved


def test_inspection_assessment_and_legacy_validation_receipts_do_not_claim_saved_validation(env):
    gw = gateway(env)
    assert invoke(gw)["ok"]
    assert "validation" not in gw.receipts[-1]
    assert not evidence(gw)["checkedPackaging"]
    assert invoke(gw, "validate_packaging")["ok"]
    del gw.receipts[-1]["validation"]
    assert not evidence(gw)["checkedPackaging"]


@pytest.mark.parametrize("failure", ["stale_revision", "invalid_result", "oversized_result", "cancelled"])
def test_failed_validation_does_not_record_success_evidence(env, monkeypatch, failure):
    gw = gateway(env)
    args = {"expected_revision": 0}
    if failure == "stale_revision":
        args["expected_revision"] = 1
    elif failure == "invalid_result":
        run = gw._run

        def invalid(*args):
            return {**run(*args), "saved": "true"}

        monkeypatch.setattr(gw, "_run", invalid)
    elif failure == "oversized_result":
        monkeypatch.setattr(tools, "MAX_RESULT_BYTES", 1)
    else:
        async def cancelled(_phase):
            raise asyncio.CancelledError()

        gw.status_sink = cancelled
    if failure == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            invoke(gw, "validate_packaging", args)
    else:
        assert not invoke(gw, "validate_packaging", args)["ok"]
    assert not gw.receipts[-1]["ok"]
    assert "validation" not in gw.receipts[-1]
    assert not evidence(gw)["checkedPackaging"]


def test_only_validation_of_current_saved_revision_counts_across_edit_undo_redo(env):
    gw = gateway(env, editing=True, max_calls=16)
    assert invoke(gw, "validate_packaging")["ok"]
    assert evidence(gw)["checkedPackaging"]
    assert invoke(gw, "edit_packaging", edit_args())["ok"]
    assert not evidence(gw)["checkedPackaging"]
    assert invoke(gw, "validate_packaging", {"expected_revision": 1,
                                           "design": edit_args()["design"]})["ok"]
    assert not evidence(gw)["checkedPackaging"]
    assert invoke(gw, "validate_packaging", {"expected_revision": 1})["ok"]
    assert evidence(gw)["checkedPackaging"]
    for action, revision in (("undo", 1), ("redo", 2)):
        assert invoke(gw, action + "_packaging", {"expected_revision": revision, "request_id": action})["ok"]
        assert not evidence(gw)["checkedPackaging"]
        assert invoke(gw, "validate_packaging", {"expected_revision": revision + 1})["ok"]
        assert evidence(gw)["checkedPackaging"]


def test_unknown_write_cannot_reuse_validation_of_the_last_known_revision(env, monkeypatch):
    gw = gateway(env, editing=True)
    assert invoke(gw, "validate_packaging")["ok"]
    change = env[0].change

    def lost_response(*args, **kwargs):
        change(*args, **kwargs)
        raise RuntimeError("synthetic response lost after commit")

    monkeypatch.setattr(env[0], "change", lost_response)
    assert not invoke(gw, "edit_packaging", edit_args())["ok"]
    result = evidence(gw)
    assert result["mutationOutcome"] == "unknown" and result["revision"] == 0
    assert not result["checkedPackaging"]
    assert env[0].get(env[1], env[2][0].document_id)["revision"] == 1


@pytest.mark.parametrize("validation", ["none", "proposal", "previous", "final"])
def test_final_host_assessment_does_not_overclaim_agent_saved_validation(setup, monkeypatch, validation):
    async def runtime(**kwargs):
        gw = kwargs["gateway"]
        assert (await gw.call("inspect_packaging", {"expected_revision": 0}))["ok"]
        if validation == "previous":
            assert (await gw.call("validate_packaging", {"expected_revision": 0}))["ok"]
        assert (await gw.call("edit_packaging", {"expected_revision": 0, "request_id": "edit-test",
                                                "design": setup.doc["design"]}))["ok"]
        if validation in {"proposal", "final"}:
            args = {"expected_revision": 1}
            if validation == "proposal":
                args["design"] = setup.doc["design"]
            assert (await gw.call("validate_packaging", args))["ok"]
        gw.closed = True
        return "Checked", SimpleNamespace(timeline=[])

    monkeypatch.setattr(pilot, "run_gateway_turn", runtime)
    result = asyncio.run(execute(setup))["codex_packaging"]
    assert result["revision"] == 1 and result["mutationOutcome"] == "committed"
    assert result["validation"] == setup.service.get(setup.scope, setup.doc["id"])["assessment"]
    assert result["checkedPackaging"] is (validation == "final")
