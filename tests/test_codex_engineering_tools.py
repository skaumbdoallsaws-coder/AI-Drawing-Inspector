"""Real saved-repository reads; fault injection only at lifecycle boundaries."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
import itertools
import json
from pathlib import Path
import threading
import time

from jsonschema import Draft202012Validator
import pytest

from ai_inspector.codex_runtime import engineering_tools as engineering
from ai_inspector.codex_runtime.engineering_tools import (
    ENGINEERING_READ_NAMES, EngineeringContext, create_engineering_gateway,
    engineering_tool_specs, read_engineering_facts, tool_specs,
)
from ai_inspector.codex_runtime.facility_tools import (
    FacilityReadGateway, OUTPUT_SCHEMA, tool_specs as facility_tool_specs,
)
from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
from ai_inspector.codex_runtime.policy import PilotError
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, LOCAL_SITE_ID, LOCAL_LAYOUT_ID
from ai_inspector.facility_layout.navigation_intent import navigation_context_summary


FIXTURE = Path(__file__).parent / "fixtures" / "facility_layout" / "two_asset_cell.json"
SEQUENCE = itertools.count()


@pytest.fixture(scope="module")
def host(tmp_path_factory):
    value = LocalFacilityLayoutHost(tmp_path_factory.mktemp("engineering") / "facility", private_assets=False)
    value.ensure_bootstrap()
    yield value
    value.close()


@pytest.fixture
def context(host):
    # Reuse repository geometry. Only identity, actor metadata and authored
    # process references are added; no replacement geometry/solver is supplied.
    document = json.loads(FIXTURE.read_text(encoding="ascii"))
    document["layoutId"] = f"fl-codex-engineering-{next(SEQUENCE)}"
    document["association"]["siteId"] = LOCAL_SITE_ID
    for index, placement in enumerate(document["placements"]):
        placement["metadata"].update(activityActorType="operator", instanceLabel=f"Operator {index}")
    document["processBindings"] = [{
        "processBindingId": f"pb-engineering-{index}", "productId": "product-demo",
        "processMapId": "pm-demo", "processMapRevision": "6" * 64,
        "processNodeIds": ["node-op"], "processEdgeIds": ["edge-flow"],
        "placementIds": [document["placements"][0]["placementId"]],
        "routeIds": [document["routes"][0]["routeId"]], "bindingRole": "material_flow",
        "privateExtension": {"sourcePath": "must-not-be-exposed"},
    } for index in range(3)]
    created = host.service.layout_repository.create_layout(host.principal(), LOCAL_SITE_ID, document)
    current = EngineeringContext(host.principal(), "session-engineering", "conversation-engineering", {
        "active_mode": "facility_layout",
        "facility_layout_ref": {"siteId": LOCAL_SITE_ID, "layoutId": document["layoutId"],
                                "revision": created["revision"]},
        "facility_layout_live_state": {"dirty": False, "conflict": False, "pendingOperations": []},
    })
    return [current]


def gateway(host, context, workflow="facility_navigation", **kwargs):
    return create_engineering_gateway(workflow, host.agent_runtime, current_context=lambda: context[0],
        turn_id=f"turn-engineering-{next(SEQUENCE)}", **kwargs)


def invoke(reader, args=None, name=None):
    return asyncio.run(reader.call(name or reader.specs[0]["name"], {} if args is None else args))


def advance(host, context):
    ref = context[0].normalized["facility_layout_ref"]
    current = host.service.get_layout(context[0].principal, ref["siteId"], ref["layoutId"])
    document = deepcopy(current["layout"])
    document["displayName"] += " updated"
    return host.service.layout_repository.save_layout(context[0].principal,
        ref["siteId"], ref["layoutId"], document, current["revision"])


def hashes(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def test_real_navigation_function_and_repository_are_unchanged(host, context):
    reader = gateway(host, context)
    original = reader.check()
    root = host.service.layout_repository.root
    before = hashes(root)
    fixture_hash = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    result = invoke(reader, {"maximumRecords": 1})
    assert result["ok"], result
    assert result["data"]["facts"] == navigation_context_summary(original["layout"], maximum_records=1)
    assert result["data"]["facts"]["counts"]["actors"] == 2
    assert result["data"]["facts"]["truncated"] is True
    assert result["data"]["facts"]["actors"][0]["missingSemantics"] == ["movement_program"]
    assert hashes(root) == before
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == fixture_hash
    assert reader.check()["revision"] == original["revision"]
    Draft202012Validator(reader.specs[0]["output_schema"]).validate(result)
    assert reader.receipts[0]["ok"] and reader.receipts[0]["bindingHash"] == reader.binding_key
    assert '"centerline"' not in json.dumps(result)


def test_real_saved_process_facts_paging_filtering_no_lazy_resolvers(host, context, monkeypatch):
    reader = gateway(host, context, "facility_process_routes")
    def forbidden(*args, **kwargs):
        pytest.fail("A saved-fact read must not resolve or initialize external Process Maps")
    monkeypatch.setattr(host.agent_runtime, "execute_read_tool", forbidden)
    monkeypatch.setattr(host.service, "process_map_resolver", forbidden)
    root = host.service.layout_repository.root
    before = hashes(root)
    first = invoke(reader, {"pageSize": 1})
    assert first["ok"], first
    facts = first["data"]["facts"]
    assert facts["totalCount"] == 3 and facts["returnedCount"] == 1 and facts["nextOffset"] == 1
    assert facts["records"][0]["routeIds"] == ["rt-material-01"]
    assert facts["records"][0]["processMapRevision"] == "6" * 64
    second = invoke(reader, {"pageSize": 2, "offset": facts["nextOffset"]})
    assert second["ok"] and second["data"]["facts"]["nextOffset"] is None
    assert [row["processBindingId"] for row in second["data"]["facts"]["records"]] == [
        "pb-engineering-1", "pb-engineering-2"]
    selected = invoke(reader, {"ids": ["pb-engineering-2"], "processMapId": "pm-demo"})
    assert selected["data"]["facts"]["totalCount"] == 1
    assert invoke(reader, {"processMapId": "pm-not-bound"})["data"]["facts"]["totalCount"] == 0
    assert invoke(reader, {"offset": 5000})["data"]["facts"]["records"] == []
    assert "privateExtension" not in json.dumps(first) and "must-not-be-exposed" not in json.dumps(first)
    assert hashes(root) == before
    for result in (first, second, selected):
        Draft202012Validator(reader.specs[0]["output_schema"]).validate(result)


def test_specs_are_closed_and_independently_copied():
    def check_objects(value):
        if isinstance(value, dict):
            if value.get("type") == "object" and "oneOf" not in value:
                assert value.get("additionalProperties") is False
            for child in value.values():
                check_objects(child)
        elif isinstance(value, list):
            for child in value:
                check_objects(child)
    specs = tool_specs()
    assert {spec["name"] for spec in specs} == {"observe_navigation_context", "inspect_saved_process_bindings"}
    for spec in specs:
        check_objects(spec)
        Draft202012Validator.check_schema(spec["input_schema"])
        Draft202012Validator.check_schema(spec["output_schema"])
    specs[0]["input_schema"]["properties"].clear()
    assert tool_specs()[0]["input_schema"]["properties"]
    with pytest.raises(ValueError):
        tool_specs("assembly")


@pytest.mark.parametrize("base", [FacilityReadGateway, FacilityEditGateway])
def test_shared_helper_composes_with_existing_gateways_and_one_budget(host, base):
    principal = host.principal()
    original = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    reference = {"siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": original["revision"]}
    # Exercise the actual integrated gateway, including the shared budget.
    reader = base(host.agent_runtime, principal, reference, turn_id=f"shared-{next(SEQUENCE)}", max_calls=3)
    deadline = reader.deadline
    before = hashes(host.service.layout_repository.root)
    names = [spec["name"] for spec in reader.specs]
    assert len(names) == len(set(names)) and ENGINEERING_READ_NAMES <= set(names)
    if base is FacilityEditGateway:
        assert {"preview_facility_operations", "preview_facility_undo"} <= set(names)
    for name in ("inspect_facility_context", "observe_navigation_context", "inspect_saved_process_bindings"):
        result = invoke(reader, name=name)
        assert result["ok"], result
        Draft202012Validator(OUTPUT_SCHEMA).validate(result)
    assert reader.calls == 3 and len(reader.receipts) == 3
    assert reader.deadline == deadline
    result = invoke(reader, name="preview_facility_operations" if base is FacilityEditGateway else "inspect_facility_context")
    assert result["error"]["code"] == "codex_tool_budget_exhausted"
    assert reader.closed and len(reader.receipts) == 4
    assert hashes(host.service.layout_repository.root) == before


@pytest.mark.parametrize("name", sorted(ENGINEERING_READ_NAMES))
def test_shared_helper_real_facts_and_closed_envelope(host, context, name):
    reference = context[0].normalized["facility_layout_ref"]
    before = hashes(host.service.layout_repository.root)
    data = read_engineering_facts(host.agent_runtime, context[0].principal, reference, name, {})
    spec = next(spec for spec in engineering_tool_specs() if spec["name"] == name)
    Draft202012Validator(spec["output_schema"]).validate({"ok": True, "data": data})
    assert data["document"] == reference and data["readOnly"]
    assert "ok" not in data
    if name == "inspect_saved_process_bindings":
        assert data["facts"]["totalCount"] == 3
        assert "privateExtension" not in json.dumps(data)
    else:
        assert data["facts"]["counts"]["actors"] == 2
    assert hashes(host.service.layout_repository.root) == before


@pytest.mark.parametrize("name", sorted(ENGINEERING_READ_NAMES))
def test_shared_helper_reauthorizes_and_rejects_stale_saved_revision(host, context, name):
    reference = context[0].normalized["facility_layout_ref"]
    denied = replace(context[0].principal, roles=("catalog_curator",))
    with pytest.raises(PilotError) as caught:
        read_engineering_facts(host.agent_runtime, denied, reference, name, {})
    assert caught.value.code == "codex_document_unavailable"
    advance(host, context)
    with pytest.raises(PilotError) as caught:
        read_engineering_facts(host.agent_runtime, context[0].principal, reference, name, {})
    assert caught.value.code == "codex_document_unavailable"


@pytest.mark.parametrize("name", sorted(ENGINEERING_READ_NAMES))
def test_shared_helper_rejects_save_during_actual_projection(host, context, monkeypatch, name):
    real = engineering._saved_facts
    def concurrent_save(*args, **kwargs):
        data = real(*args, **kwargs)
        advance(host, context)
        return data
    monkeypatch.setattr(engineering, "_saved_facts", concurrent_save)
    with pytest.raises(PilotError) as caught:
        read_engineering_facts(host.agent_runtime, context[0].principal,
            context[0].normalized["facility_layout_ref"], name, {})
    assert caught.value.code == "codex_document_unavailable"


@pytest.mark.parametrize("name,args,code", [
    ("delete_layout", {}, "codex_tool_denied"),
    ("observe_navigation_context", {"path": "C:/private.json"}, "codex_tool_arguments_invalid"),
    ("observe_navigation_context", {"maximumRecords": 1.0}, "codex_tool_arguments_invalid"),
    ("inspect_saved_process_bindings", {"offset": 1.0}, "codex_tool_arguments_invalid"),
    ("inspect_saved_process_bindings", {"layoutId": "fl-other"}, "codex_tool_arguments_invalid"),
])
def test_shared_helper_validates_without_standalone_gateway(host, context, name, args, code):
    with pytest.raises(PilotError) as caught:
        read_engineering_facts(host.agent_runtime, context[0].principal,
            context[0].normalized["facility_layout_ref"], name, args)
    assert caught.value.code == code


@pytest.mark.parametrize("workflow,args", [
    ("facility_navigation", {"maximumRecords": True}),
    ("facility_navigation", {"maximumRecords": 51}),
    ("facility_navigation", {"actorClass": "unknown"}),
    ("facility_navigation", {"query": "x" * 161}),
    ("facility_navigation", {"path": "C:/private.json"}),
    ("facility_navigation", {"layoutId": "fl-other"}),
    ("facility_navigation", {"principalId": "other-user"}),
    ("facility_navigation", {"revision": "1" * 64}),
    ("facility_process_routes", {"ids": ["../private"]}),
    ("facility_process_routes", {"ids": ["pb-a", "pb-a"]}),
    ("facility_process_routes", {"pageSize": 21}),
    ("facility_process_routes", {"offset": -1}),
    ("facility_process_routes", {"cursor": "forged"}),
])
def test_closed_arguments_cannot_select_authority_or_files(host, context, workflow, args):
    reader = gateway(host, context, workflow)
    result = invoke(reader, args)
    assert result["error"]["code"] == "codex_tool_arguments_invalid"
    assert reader.receipts[0]["argumentHash"] is None


@pytest.mark.parametrize("key,value", [
    ("dirty", True), ("dirty", "false"), ("dirty", None),
    ("conflict", True), ("pendingOperations", [{}]), ("pendingOperations", None),
    ("layoutId", "fl-other"), ("revision", "0" * 64),
    ("baseRevision", "0" * 64), ("draftRevision", "0" * 64),
])
def test_dirty_ambiguous_and_mismatched_live_state_rejected(host, context, key, value):
    context[0].normalized["facility_layout_live_state"][key] = value
    with pytest.raises(PilotError):
        gateway(host, context)


@pytest.mark.parametrize("key", ["facility_generation_ref", "facility_design_ref", "facility_layout_proposal_id"])
def test_preview_rejected_before_reads(host, context, key):
    context[0].normalized[key] = "preview"
    with pytest.raises(PilotError, match="unsaved"):
        gateway(host, context)


@pytest.mark.parametrize("change", ["user", "tenant", "site", "role", "session", "conversation", "workspace", "document"])
def test_current_admission_binding_change_revokes_gateway(host, context, change):
    reader = gateway(host, context)
    if change in {"user", "tenant", "site", "role"}:
        values = {"user": {"principal_id": "other-user"}, "tenant": {"tenant_id": "other-tenant"},
                  "site": {"allowed_site_ids": ("other-site",)}, "role": {"roles": ("viewer",)}}
        context[0] = replace(context[0], principal=replace(context[0].principal, **values[change]))
    elif change in {"session", "conversation"}:
        context[0] = replace(context[0], **{f"{change}_id": "other"})
    elif change == "workspace":
        context[0].normalized["active_mode"] = "assembly"
    else:
        context[0].normalized["facility_layout_ref"]["layoutId"] = "fl-other"
    assert invoke(reader)["ok"] is False
    assert reader.closed
    with pytest.raises(PilotError):
        reader.check()


def test_backend_denies_cross_tenant_site_and_unprivileged_principals(host, context):
    for changes in ({"tenant_id": "tenant-other"}, {"allowed_site_ids": ("site-other",)}, {"roles": ("catalog_curator",)}):
        original = context[0]
        context[0] = replace(original, principal=replace(original.principal, **changes))
        with pytest.raises(PilotError) as caught:
            gateway(host, context)
        assert caught.value.code == "codex_document_unavailable"
        context[0] = original


def test_existing_nav8_fixture_programs_and_anchors_through_real_repository(host, context):
    from tests.test_facility_layout_navigation_nav8 import _layout
    reader = gateway(host, context)
    current = reader.check()
    document = deepcopy(current["layout"])
    document["extensions"] = _layout()["extensions"]
    saved = host.service.layout_repository.save_layout(context[0].principal, LOCAL_SITE_ID,
        document["layoutId"], document, current["revision"])
    context[0].normalized["facility_layout_ref"]["revision"] = saved["revision"]
    result = invoke(gateway(host, context))
    assert result["ok"], result
    facts = result["data"]["facts"]
    assert facts["anchors"][0]["navigationAnchorId"] == "na-machine-home"
    assert facts["movementPrograms"][0]["orderedAnchorIds"] == ["na-machine-home"]
    assert facts["movementPrograms"][0]["manualOverrideCount"] == 1
    assert "authoredPolyline" not in json.dumps(result)


def test_current_context_unavailable_and_missing_clean_state_fail_closed(host, context):
    context[0].normalized.pop("facility_layout_live_state")
    with pytest.raises(PilotError):
        gateway(host, context)
    context[0].normalized["facility_layout_live_state"] = {"dirty": False, "conflict": False}
    reader = gateway(host, context)
    context[0] = None
    result = invoke(reader)
    assert result["error"]["code"] == "codex_engineering_context_invalid"
    assert reader.closed


def test_viewer_principal_can_read_both_workflows(host, context):
    context[0] = replace(context[0], principal=replace(context[0].principal, roles=("viewer",)))
    for workflow in ("facility_navigation", "facility_process_routes"):
        assert invoke(gateway(host, context, workflow))["ok"]


def test_saved_revision_change_before_read(host, context):
    reader = gateway(host, context)
    advance(host, context)
    result = invoke(reader)
    assert result["error"]["code"] == "codex_document_unavailable"
    assert reader.closed and not reader.receipts[0]["ok"]


@pytest.mark.parametrize("change", ["save", "dirty", "document", "principal"])
def test_change_during_real_domain_read_discards_result(host, context, monkeypatch, change):
    reader = gateway(host, context)
    real = engineering.navigation_context_summary
    def concurrent_change(*args, **kwargs):
        result = real(*args, **kwargs)
        if change == "save":
            advance(host, context)
        elif change == "dirty":
            context[0].normalized["facility_layout_live_state"]["dirty"] = True
        elif change == "document":
            context[0].normalized["facility_layout_ref"]["layoutId"] = "fl-other"
        else:
            context[0] = replace(context[0], principal=replace(context[0].principal, principal_id="other"))
        return result
    monkeypatch.setattr(engineering, "navigation_context_summary", concurrent_change)
    result = invoke(reader)
    assert not result["ok"] and "data" not in result
    assert reader.closed and not reader.receipts[0]["ok"]


def test_workflow_isolation_call_budget_and_receipt_bound(host, context):
    reader = gateway(host, context, max_calls=1)
    assert invoke(reader, name="inspect_saved_process_bindings")["error"]["code"] == "codex_tool_denied"
    assert invoke(reader)["error"]["code"] == "codex_tool_budget_exhausted"
    for _ in range(10):
        assert invoke(reader)["error"]["code"] == "codex_run_closed"
    assert len(reader.receipts) == 2
    other = gateway(host, context, "facility_process_routes")
    assert reader.binding_key != other.binding_key
    exposed = other.binding
    exposed["document"]["revision"] = "0" * 64
    assert other.check()["revision"] != "0" * 64


@pytest.mark.parametrize("kwargs", [{"max_calls": 0}, {"max_calls": 9}, {"max_calls": True},
                                     {"timeout": 0}, {"timeout": 121}, {"timeout": float("nan")}])
def test_configured_budget_cannot_widen_hard_caps(host, context, kwargs):
    with pytest.raises(PilotError):
        gateway(host, context, **kwargs)


def test_output_schema_and_byte_caps_fail_closed(host, context, monkeypatch):
    real = engineering.navigation_context_summary
    def malformed(*args, **kwargs):
        result = real(*args, **kwargs)
        result["unreviewedExtra"] = "not allowed"
        return result
    monkeypatch.setattr(engineering, "navigation_context_summary", malformed)
    assert invoke(gateway(host, context))["error"]["code"] == "codex_tool_result_invalid"
    monkeypatch.setattr(engineering, "navigation_context_summary", real)
    monkeypatch.setattr(engineering, "MAX_RESULT_BYTES", 10)
    assert invoke(gateway(host, context))["error"]["code"] == "codex_result_too_large"


def test_exception_text_never_leaks(host, context, monkeypatch):
    reader = gateway(host, context)
    def broken(*args, **kwargs):
        raise RuntimeError("private-path and sensitive diagnostic must not escape")
    monkeypatch.setattr(engineering, "navigation_context_summary", broken)
    result = invoke(reader)
    assert result["error"]["code"] == "codex_tool_failed"
    assert "private-path" not in json.dumps([result, reader.receipts])


def test_context_provider_failure_at_construction_is_sanitized(host):
    def unavailable():
        raise RuntimeError("private principal diagnostic")
    with pytest.raises(PilotError) as caught:
        create_engineering_gateway("facility_navigation", host.agent_runtime,
            current_context=unavailable, turn_id="turn-unavailable")
    assert caught.value.code == "codex_engineering_context_invalid"
    assert "private principal diagnostic" not in str(caught.value)


def test_inventory_mutation_cannot_widen_gateway(host, context):
    reader = gateway(host, context)
    exposed = reader.specs
    exposed[0]["name"] = "delete_layout"
    exposed[0]["input_schema"]["additionalProperties"] = True
    assert invoke(reader, name="delete_layout")["error"]["code"] == "codex_tool_denied"
    assert invoke(reader, {"layoutId": "fl-other"})["error"]["code"] == "codex_tool_arguments_invalid"


@pytest.mark.parametrize("cancel", [False, True])
def test_timeout_and_repeated_cancel_join_real_worker_and_discard(host, context, monkeypatch, cancel):
    reader = gateway(host, context)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    real = engineering.navigation_context_summary
    def delayed(*args, **kwargs):
        result = real(*args, **kwargs)
        entered.set()
        assert release.wait(5)
        finished.set()
        return result
    monkeypatch.setattr(engineering, "navigation_context_summary", delayed)
    async def exercise():
        if not cancel:
            reader.deadline = time.monotonic() + .1
        task = asyncio.create_task(reader.call("observe_navigation_context", {}))
        assert await asyncio.to_thread(entered.wait, 3)
        if cancel:
            task.cancel()
            await asyncio.sleep(.02)
            task.cancel()
        else:
            await asyncio.sleep(.15)
        assert not task.done()
        release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert (await task)["error"]["code"] == "codex_run_closed"
        assert finished.is_set() and reader.closed
        assert not any(receipt["ok"] for receipt in reader.receipts)
    try:
        asyncio.run(exercise())
    finally:
        release.set()
