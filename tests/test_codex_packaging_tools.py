"""Offline adapter tests over real PackagingService and disposable SQLite storage."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import json
import socket
import threading
import time

from pydantic import TypeAdapter
import pytest

from ai_inspector.codex_runtime import packaging_tools as tools
from ai_inspector.codex_runtime.policy import PilotError
from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.packaging_shipping.geometry import digest
from ai_inspector.packaging_shipping.models import Design, Edit
from ai_inspector.packaging_shipping.service import PackagingService
from ai_inspector.packaging_shipping.sources import import_glb


def sample_design():
    return Design.model_validate({
        "name": "Pump shipment", "quantity": 1,
        "product": {"name": "Pump", "dimensions_m": [0.1, 0.2, 0.15],
                    "mass_kg": 2, "mass_basis": "user_measured", "mass_evidence": "Scale reading"},
        "constraints": {"allowed_orientations": list(range(6)), "contents": "ordinary_nonhazardous"},
        "packages": [{"id": "box_1", "carton": {
            "name": "Carton", "inner_m": [0.5, 0.5, 0.5], "outer_m": [0.52, 0.52, 0.52],
            "tare_kg": 0.3, "tare_evidence": "Scale reading", "max_payload_kg": 20, "cost_usd": 3},
            "placements": [{"id": "item_1", "position_m": [0.02, 0.02, 0.02], "orientation": 0}],
            "inserts": [{"id": "pad_1", "name": "End pad", "dimensions_m": [0.01, 0.5, 0.5],
                         "position_m": [0, 0, 0], "density_kg_m3": 30,
                         "material_evidence": "Foam supplier data", "cost_usd": 1}],
            "allowance_kg": 0, "allowance_evidence": "No additional packing"}],
    })


@pytest.fixture
def env(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Packaging tools must not use network or billing")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    service = PackagingService(tmp_path / "packaging")
    monkeypatch.setattr(service, "save_quotes", forbidden)
    principal = FacilityPrincipal("engineer", "tenant-a", ("site-b", "site-a"), ("editor",))
    scope = tools.packaging_scope(principal)
    saved = service.create(scope, sample_design())
    context = [tools.PackagingContext(principal, "session-1", "conversation-1", "selection-1",
        saved["id"], saved["revision"], "packaging_shipping", False, False)]
    lease = threading.RLock()
    return service, scope, context, lease


def gateway(env, *, editing=False, **kwargs):
    service, _, context, lease = env
    context[0] = replace(context[0], direct_edit_authorized=editing)
    return tools.create_packaging_gateway(service, current_context=lambda: context[0], turn_id="turn-1",
        mutation_guard=(lambda: lease) if editing else None, **kwargs)


def invoke(gw, name="inspect_packaging", args=None):
    result = asyncio.run(gw.call(name, {"expected_revision": 0} if args is None else args))
    success = tools._TOOLS[name][1] if isinstance(name, str) and name in tools._TOOLS else tools._InspectSuccess
    TypeAdapter(success | tools.Failure).validate_python(result)
    return result


def edit_args(name="New shipment", revision=0, request_id="edit-1"):
    design = sample_design().model_dump(mode="json")
    design["name"] = name
    return {"expected_revision": revision, "request_id": request_id, "design": design}


def assert_error(result, code):
    assert result["ok"] is False, result
    assert result["error"]["code"] == code, result


def snapshot(env):
    service, scope, context, _ = env
    with service.db() as db:
        tables = {name: [tuple(row) for row in db.execute("SELECT * FROM " + name)]
                  for name in ("documents", "receipts", "sources", "quotes")}
    return tables


def test_specs_closed_typed_independent_and_scope_matches_api(env):
    principal = env[2][0].principal
    assert env[1] == digest({"tenant": principal.tenant_id, "sites": ["site-a", "site-b"],
                             "workflow": "packaging_shipping"})
    assert len(tools.tool_specs()) == 5
    specs = tools.tool_specs(direct_edit=True)
    assert len(specs) == 8

    def closed(value):
        if isinstance(value, dict):
            if value.get("type") == "object" and "anyOf" not in value:
                assert value.get("additionalProperties") is False
            for child in value.values():
                closed(child)
        elif isinstance(value, list):
            for child in value:
                closed(child)
    closed(specs)
    assert all(s["output_schema"]["type"] == "object" for s in specs)
    assert {s["name"] for s in specs if not s["read_only"]} == tools._WRITES
    specs[0]["input_schema"]["properties"].clear()
    assert tools.tool_specs()[0]["input_schema"]["properties"]
    gw = gateway(env)
    binding = gw.binding
    binding["document_id"] = "other"
    gw.specs.clear()
    assert gw.binding["document_id"] == env[2][0].document_id and len(gw.specs) == 5


def test_inspect_validate_propose_real_solver_do_not_write(env):
    gw = gateway(env)
    before = snapshot(env)
    read = invoke(gw)
    assert read["ok"] and read["data"]["source_refs"] == []
    assert read["data"]["packages"][0]["inserts"][0]["id"] == "pad_1"
    assert read["data"]["assessment"]["rate_ready"] is True
    assert read["data"]["assessment"]["status"] == "needs_review"
    assert read["data"]["assessment"]["total_gross_kg"] == pytest.approx(2.375)
    validated = invoke(gw, "validate_packaging")
    assert validated["data"]["saved"] is True
    proposed = invoke(gw, "propose_packaging", {"expected_revision": 0,
        "cartons": [sample_design().packages[0].carton.model_dump(mode="json")], "max_packages": 1})
    # The saved end pad has no cushion requirement to rebuild from, so the proposal refuses
    # rather than returning lighter candidates without it.
    assert_error(proposed, "protection_requirement_needed")
    assert snapshot(env) == before
    assert gw.check()["revision"] == 0
    assert [r["ok"] for r in gw.receipts] == [True, True, False]
    assert all(r["bindingHash"] == gw.binding_key for r in gw.receipts)
    assert str(env[0].root) not in json.dumps(read)


def test_propose_rebuilds_the_cushion_requirement_and_carries_the_allowance(env):
    service, scope, context, _ = env
    data = sample_design().model_dump(mode="json")
    data["constraints"]["cushion"] = {"floor_m": 0.0, "top_m": 0.0, "sides_m": 0.01, "material": {
        "name": "Foam", "density_kg_m3": 30.0, "evidence": "Foam supplier data"}, "evidence": "End protection"}
    saved = service.create(scope, Design.model_validate(data))
    context[0] = replace(context[0], document_id=saved["id"], revision=saved["revision"])
    gw = gateway(env)
    before = snapshot(env)
    proposed = invoke(gw, "propose_packaging", {"expected_revision": 0,
        "cartons": [sample_design().packages[0].carton.model_dump(mode="json")], "max_packages": 1})
    assert proposed["ok"], proposed
    assert proposed["data"]["saved"] is False and proposed["data"]["replaces_existing_packages"] is True
    assert proposed["data"]["preservation"] == {"cushion": "rebuilt_from_requirement", "allowance": "carried_forward",
                                                "carton_graphics": "none", "insert_graphics_dropped": 0}
    candidate, = proposed["data"]["candidates"]
    package = candidate["design"]["packages"][0]
    assert len(package["placements"]) == 1
    assert sorted(i["id"] for i in package["inserts"]) == ["cushion-x-max", "cushion-x-min", "cushion-z-max", "cushion-z-min"]
    assert package["allowance_kg"] == 0 and package["allowance_evidence"] == "No additional packing"
    assert candidate["assessment"]["status"] == "needs_review" and candidate["assessment"]["rate_ready"] is True
    assert snapshot(env) == before
    assert all(r["ok"] for r in gw.receipts)


@pytest.mark.parametrize("orientation", range(6))
def test_all_six_orientations_are_real_domain_values(env, orientation):
    args = edit_args()
    args["design"]["packages"][0]["placements"][0]["orientation"] = orientation
    result = invoke(gateway(env, editing=True), "edit_packaging", args)
    assert result["ok"], result
    assert env[0].get(env[1], env[2][0].document_id)["design"]["packages"][0]["placements"][0]["orientation"] == orientation


def test_48_items_and_solid_pads_are_supported_but_49_is_rejected(env):
    args = edit_args()
    args["design"]["quantity"] = 48
    args["design"]["packages"][0]["placements"] = [
        {"id": f"item_{i}", "position_m": [0.02, 0.02, 0.02], "orientation": i % 6} for i in range(48)]
    gw = gateway(env, editing=True)
    assert invoke(gw, "edit_packaging", args)["ok"]
    validation = invoke(gw, "validate_packaging", {"expected_revision": 1, "findings_limit": 2})
    assert validation["data"]["assessment"]["placed_quantity"] == 48
    assert validation["data"]["assessment"]["next_findings_offset"] == 2
    args.update(expected_revision=1, request_id="too-many")
    args["design"]["quantity"] = 49
    assert_error(invoke(gw, "edit_packaging", args), "codex_tool_arguments_invalid")
    args["design"]["quantity"] = 48
    extra = deepcopy(args["design"]["packages"][0])
    extra.update(id="box_2", placements=[{"id": "item_extra", "position_m": [0, 0, 0]}])
    args["design"]["packages"].append(extra)
    assert_error(invoke(gw, "edit_packaging", args), "codex_tool_arguments_invalid")
    assert env[0].get(env[1], env[2][0].document_id)["revision"] == 1


def test_edits_undo_redo_receipts_and_retries_use_real_transactions(env):
    gw = gateway(env, editing=True, max_calls=12)
    first = invoke(gw, "edit_packaging", edit_args())
    assert first["ok"] and first["data"]["can_undo"]
    assert first["data"]["receipt"] == {"request_id": "edit-1", "action": "edit",
        "before_revision": 0, "after_revision": 1, "outcome": "committed"}
    replay = invoke(gw, "edit_packaging", edit_args())
    assert replay["ok"] and replay["data"]["replayed"]
    assert_error(invoke(gw, "edit_packaging", edit_args("Different")), "request_id_reused")
    assert_error(invoke(gw, "validate_packaging"), "revision_conflict")
    undo = invoke(gw, "undo_packaging", {"expected_revision": 1, "request_id": "undo-1"})
    assert undo["ok"] and undo["data"]["document"]["revision"] == 2
    assert env[0].get(env[1], env[2][0].document_id)["design"]["name"] == "Pump shipment"
    redo = invoke(gw, "redo_packaging", {"expected_revision": 2, "request_id": "redo-1"})
    assert redo["ok"] and redo["data"]["document"]["revision"] == 3
    assert_error(invoke(gw, "edit_packaging", edit_args()), "revision_conflict")
    assert env[0].get(env[1], env[2][0].document_id)["design"]["name"] == "New shipment"
    with env[0].db() as db:
        assert db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 3
    env[2][0] = replace(env[2][0], revision=3)
    assert gw.check()["revision"] == 3
    env[2][0] = replace(env[2][0], revision=0)
    assert_error(invoke(gw, args={"expected_revision": 3}), "revision_conflict")
    assert gw.closed


@pytest.mark.parametrize("action", ["undo", "redo"])
def test_empty_history_is_structured_without_mutation(env, action):
    result = invoke(gateway(env, editing=True), action + "_packaging",
                    {"expected_revision": 0, "request_id": "history-1"})
    assert_error(result, "nothing_to_" + action)
    assert result["mutation"]["outcome"] == "not_started"


@pytest.mark.parametrize("field,value", [
    ("expected_revision", True), ("expected_revision", 0.0), ("expected_revision", "0"),
    ("expected_revision", -1), ("expected_revision", 10**40),
    ("scope", "other"), ("document_id", "other"),
    ("principal", {"roles": ["admin"]}), ("source_path", "C:/private/model.glb"),
    ("shell", "echo unsafe"), ("request_id", "../path"),
])
def test_strict_top_level_schema(env, field, value):
    args = edit_args()
    args[field] = value
    before = snapshot(env)
    assert_error(invoke(gateway(env, editing=True), "edit_packaging", args), "codex_tool_arguments_invalid")
    assert snapshot(env) == before


@pytest.mark.parametrize("change", [
    lambda d: d.update(quantity=True),
    lambda d: d.update(quantity=1.0),
    lambda d: d["product"].update(dimensions_m=["0.1", 0.2, 0.3]),
    lambda d: d["product"].update(dimensions_m=[float("nan"), 0.2, 0.3]),
    lambda d: d["product"].update(dimensions_m=[float("inf"), 0.2, 0.3]),
    lambda d: d["product"].update(dimensions_m=(0.1, 0.2, 0.3)),
    lambda d: d["product"].update(mass_evidence=""),
    lambda d: d["product"].update(path="C:/private/model.glb"),
    lambda d: d["packages"][0]["placements"][0].update(orientation=True),
    lambda d: d["packages"][0]["placements"][0].update(orientation=6),
    lambda d: d["packages"][0]["placements"][0].update(orientation=0.0),
    lambda d: d["packages"][0]["inserts"][0].update(density_kg_m3=-1),
    lambda d: d["packages"][0]["inserts"][0].update(id="item_1"),
    lambda d: d["packages"][0]["carton"].update(outer_m=[0.4, 0.4, 0.4]),
])
def test_strict_nested_domain_schema(env, change):
    args = edit_args()
    change(args["design"])
    before = snapshot(env)
    assert_error(invoke(gateway(env, editing=True), "edit_packaging", args), "codex_tool_arguments_invalid")
    assert snapshot(env) == before


def test_untrusted_payload_limits_and_denied_tools(env):
    gw = gateway(env, max_calls=8)
    assert_error(invoke(gw, "edit_packaging", edit_args()), "codex_tool_denied")
    assert_error(invoke(gw, "shell", {}), "codex_tool_denied")
    assert_error(invoke(gw, ["inspect_packaging"], {}), "codex_tool_denied")
    assert_error(invoke(gw, args=[]), "codex_tool_arguments_invalid")
    assert_error(invoke(gw, args={"expected_revision": 0, "x": "x" * 25000}), "codex_tool_arguments_invalid")
    recursive = {"expected_revision": 0}
    recursive["x"] = recursive
    assert_error(invoke(gw, args=recursive), "codex_tool_arguments_invalid")


def test_imported_glb_is_scoped_immutable_and_returns_only_reference(env):
    import trimesh
    service, scope, context, _ = env
    glb = trimesh.creation.box(extents=[0.1, 0.2, 0.15]).export(file_type="glb")
    metadata, normalized = import_glb(glb, "Pump GLB", 1.0)
    metadata["private_path"] = "C:/private/do-not-disclose.glb"
    metadata = service.store_source(scope, metadata, normalized)
    args = edit_args()
    args["design"]["product"].update(source_id=metadata["id"], source_revision=metadata["source_revision"],
                                     dimensions_m=metadata["dimensions_m"])
    gw = gateway(env, editing=True, max_calls=12)
    result = invoke(gw, "edit_packaging", args)
    assert result["ok"], result
    read = invoke(gw, args={"expected_revision": 1})
    assert read["data"]["source_refs"] == [{"kind": "imported_glb", "source_id": metadata["id"],
                                             "source_revision": metadata["source_revision"]}]
    assert "private_path" not in json.dumps(read) and "do-not-disclose" not in json.dumps(read)
    for field, value, code in [
        ("dimensions_m", [0.01, 0.01, 0.01], "source_changed"),
        ("source_revision", "f" * 64, "source_changed"),
        ("source_id", "src_not_authorized", "source_not_found"),
        ("mass_basis", "cad", "cad_mass_unavailable"),
    ]:
        proposed = deepcopy(args["design"])
        proposed["product"][field] = value
        assert_error(invoke(gw, "validate_packaging", {"expected_revision": 1, "design": proposed}), code)
    foreign = tools.packaging_scope(replace(context[0].principal, tenant_id="tenant-b"))
    metadata2, normalized2 = import_glb(glb, "Other", 0.001)
    source2 = service.store_source(foreign, metadata2, normalized2)
    proposed = deepcopy(args["design"])
    proposed["product"].update(source_id=source2["id"], source_revision=source2["source_revision"],
                               dimensions_m=source2["dimensions_m"])
    assert_error(invoke(gw, "validate_packaging", {"expected_revision": 1, "design": proposed}), "source_not_found")


@pytest.mark.parametrize("value,code", [("cad", "cad_evidence_required"), ("revision", "source_changed")])
def test_manual_sources_cannot_claim_cad_or_a_source_revision(env, value, code):
    args = edit_args()
    args["design"]["product"].update({"mass_basis": "cad"} if value == "cad" else {"source_revision": "x"})
    assert_error(invoke(gateway(env, editing=True), "edit_packaging", args), code)


@pytest.mark.parametrize("field,value", [
    ("session_id", "session-2"), ("conversation_id", "conversation-2"),
    ("selection_id", "selection-2"), ("document_id", "pkg_other"),
    ("active_mode", "facility_layout"), ("direct_edit_authorized", False),
    ("dirty", True), ("conflict", True), ("pending_operations", 1),
])
def test_refreshed_context_fails_closed_before_write(env, field, value):
    gw = gateway(env, editing=True)
    before = snapshot(env)
    env[2][0] = replace(env[2][0], **{field: value})
    result = invoke(gw, "edit_packaging", edit_args())
    assert result["ok"] is False and gw.closed
    assert snapshot(env) == before


@pytest.mark.parametrize("change", [
    {"principal_id": "other"}, {"tenant_id": "other"}, {"roles": ("viewer",)},
    {"allowed_site_ids": ("site-a",)},
])
def test_principal_and_scope_are_immutable(env, change):
    gw = gateway(env, editing=True)
    env[2][0] = replace(env[2][0], principal=replace(env[2][0].principal, **change))
    assert_error(invoke(gw, "edit_packaging", edit_args()), "codex_packaging_context_changed")
    assert env[0].get(env[1], gw.binding["document_id"])["revision"] == 0


def test_direct_edit_requires_both_role_and_explicit_authority_and_lease(env):
    assert len(gateway(env).specs) == 5
    env[2][0] = replace(env[2][0], principal=replace(env[2][0].principal, roles=("viewer",)))
    gw = gateway(env, editing=True)
    assert len(gw.specs) == 5
    assert_error(invoke(gw, "edit_packaging", edit_args()), "codex_tool_denied")
    env[2][0] = replace(env[2][0], principal=replace(env[2][0].principal, roles=("editor",)))
    with pytest.raises(PilotError, match="admitted"):
        tools.create_packaging_gateway(env[0], current_context=lambda: env[2][0], turn_id="turn-no-lease")


def test_facility_context_and_cross_tenant_document_never_admit(env):
    context = env[2]
    context[0] = replace(context[0], active_mode="facility_layout")
    with pytest.raises(PilotError) as error:
        gateway(env)
    assert error.value.code == "codex_packaging_context_invalid"
    context[0] = replace(context[0], active_mode="packaging_shipping",
                         principal=replace(context[0].principal, tenant_id="foreign"))
    with pytest.raises(PilotError) as error:
        gateway(env)
    assert error.value.code == "codex_document_unavailable"


def test_external_revision_changes_close_turn_and_prevent_stale_write(env):
    gw = gateway(env, editing=True)
    env[0].change(env[1], env[2][0].document_id, Edit.model_validate(edit_args("Human edit", request_id="human")))
    assert_error(invoke(gw, "edit_packaging", edit_args()), "revision_conflict")
    assert gw.closed and env[0].get(env[1], env[2][0].document_id)["design"]["name"] == "Human edit"


def test_cas_race_between_precheck_and_transaction_does_not_overwrite(env, monkeypatch):
    gw = gateway(env, editing=True)
    original = env[0].change
    def racing(scope, doc_id, command, action):
        original(scope, doc_id, Edit.model_validate(edit_args("Raced", request_id="race")))
        return original(scope, doc_id, command, action)
    monkeypatch.setattr(env[0], "change", racing)
    result = invoke(gw, "edit_packaging", edit_args())
    assert_error(result, "revision_conflict")
    assert result["mutation"]["outcome"] == "not_started"
    assert env[0].get(env[1], env[2][0].document_id)["design"]["name"] == "Raced"


def test_budget_timeout_closed_and_bounded_receipts(env):
    gw = gateway(env, max_calls=1)
    assert invoke(gw)["ok"]
    assert_error(invoke(gw), "codex_tool_budget_exhausted")
    assert_error(invoke(gw), "codex_run_closed")
    assert len(gw.receipts) == 2 and gw.calls == 1
    gw = gateway(env)
    gw.deadline = time.monotonic() - 1
    assert_error(invoke(gw), "codex_run_closed")


@pytest.mark.parametrize("kwargs", [{"max_calls": True}, {"max_calls": 25}, {"timeout": float("inf")},
                                    {"timeout": 0}, {"timeout": True}])
def test_invalid_limits_never_admit(env, kwargs):
    with pytest.raises(PilotError):
        gateway(env, **kwargs)


def test_errors_are_sanitized_and_large_results_are_bounded(env, monkeypatch):
    gw = gateway(env)
    def fail(*args, **kwargs):
        raise RuntimeError("C:/private/database.sqlite token=secret")
    monkeypatch.setattr(tools, "propose", fail)
    result = invoke(gw, "propose_packaging", {"expected_revision": 0,
        "cartons": [sample_design().packages[0].carton.model_dump(mode="json")]})
    assert_error(result, "codex_tool_failed")
    assert "private" not in json.dumps(result) and "secret" not in json.dumps(gw.receipts)
    monkeypatch.setattr(tools, "MAX_RESULT_BYTES", 100)
    assert_error(invoke(gw), "codex_result_too_large")


async def wait_event(event):
    async with asyncio.timeout(5):
        while not event.is_set():
            await asyncio.sleep(0.002)


def test_context_switch_during_read_discards_result(env, monkeypatch):
    gw = gateway(env)
    original = tools._assessment
    def switched(*args, **kwargs):
        result = original(*args, **kwargs)
        env[2][0] = replace(env[2][0], selection_id="selection-away-and-back")
        return result
    monkeypatch.setattr(tools, "_assessment", switched)
    assert_error(invoke(gw), "codex_packaging_context_changed")
    assert gw.closed


def test_cancellation_before_commit_drains_worker_and_does_not_write(env, monkeypatch):
    gw = gateway(env, editing=True)
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    original = env[0].get
    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        try:
            return original(*args, **kwargs)
        finally:
            done.set()
    monkeypatch.setattr(env[0], "get", delayed)
    async def run():
        task = asyncio.create_task(gw.call("edit_packaging", edit_args()))
        try:
            await wait_event(entered)
            task.cancel()
            await asyncio.sleep(0.02)
            task.cancel()
            await asyncio.sleep(0.01)
            assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(run())
    assert done.is_set() and gw.closed
    assert original(env[1], env[2][0].document_id)["revision"] == 0
    assert gw.receipts[-1]["mutation"]["outcome"] == "not_started"


@pytest.mark.parametrize("cancel", [True, False])
def test_cancel_or_timeout_after_transaction_entry_retains_committed_receipt(env, monkeypatch, cancel):
    gw = gateway(env, editing=True)
    entered, release = threading.Event(), threading.Event()
    original = env[0].change
    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(env[0], "change", delayed)
    async def run():
        if not cancel:
            gw.deadline = time.monotonic() + 0.25
        task = asyncio.create_task(gw.call("edit_packaging", edit_args()))
        try:
            await wait_event(entered)
            if cancel:
                task.cancel()
            await asyncio.sleep(0.35 if not cancel else 0.03)
            assert not task.done()
        finally:
            release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await task
            assert_error(result, "codex_run_closed")
            assert result["mutation"]["outcome"] == "committed"
    asyncio.run(run())
    assert gw.closed and gw.receipts[-1]["mutation"]["outcome"] == "committed"
    assert gw.receipts[-1]["mutation"]["after_revision"] == 1
    assert env[0].get(env[1], env[2][0].document_id)["revision"] == 1


def test_context_switch_waits_for_host_mutation_lease(env, monkeypatch):
    gw = gateway(env, editing=True)
    entered, release, switched = threading.Event(), threading.Event(), threading.Event()
    original = env[0].change
    old_id = env[2][0].document_id
    other = env[0].create(env[1], sample_design())
    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    def switch():
        with env[3]:
            env[2][0] = replace(env[2][0], document_id=other["id"], selection_id="next")
            switched.set()
    monkeypatch.setattr(env[0], "change", delayed)
    async def run():
        task = asyncio.create_task(gw.call("edit_packaging", edit_args()))
        await wait_event(entered)
        switcher = threading.Thread(target=switch)
        switcher.start()
        try:
            await asyncio.sleep(0.03)
            assert not switched.is_set()
        finally:
            release.set()
        await task
        await asyncio.to_thread(switcher.join, 5)
        assert switched.is_set()
    asyncio.run(run())
    assert env[0].get(env[1], old_id)["revision"] == 1
    assert env[0].get(env[1], other["id"])["revision"] == 0
    assert gw.receipts[-1]["mutation"]["outcome"] == "committed"


def test_revocation_while_waiting_for_write_lease_prevents_commit(env):
    entered, release = threading.Event(), threading.Event()
    @contextmanager
    def guard():
        entered.set()
        assert release.wait(5)
        with env[3]:
            yield
    env[2][0] = replace(env[2][0], direct_edit_authorized=True)
    gw = tools.create_packaging_gateway(env[0], current_context=lambda: env[2][0],
                                        turn_id="turn-1", mutation_guard=guard)
    async def run():
        task = asyncio.create_task(gw.call("edit_packaging", edit_args()))
        try:
            await wait_event(entered)
            with env[3]:
                env[2][0] = replace(env[2][0], selection_id="new-selection")
        finally:
            release.set()
        return await task
    assert_error(asyncio.run(run()), "codex_packaging_context_changed")
    assert env[0].get(env[1], env[2][0].document_id)["revision"] == 0


def test_concurrent_calls_are_serialized_and_stale_second_write_is_rejected(env):
    gw = gateway(env, editing=True)
    async def run():
        return await asyncio.gather(gw.call("edit_packaging", edit_args()),
                                   gw.call("edit_packaging", edit_args("Second", request_id="edit-2")))
    first, second = asyncio.run(run())
    assert first["ok"]
    assert_error(second, "revision_conflict")
    assert env[0].get(env[1], env[2][0].document_id)["revision"] == 1


def test_status_cancellation_prevents_worker_start(env):
    async def stopped(_phase):
        raise asyncio.CancelledError()
    gw = gateway(env, editing=True, status_sink=stopped)
    before = snapshot(env)
    with pytest.raises(asyncio.CancelledError):
        invoke(gw, "edit_packaging", edit_args())
    assert gw.closed and snapshot(env) == before
    assert gw.receipts[-1]["mutation"]["outcome"] == "not_started"


def test_anyio_level_cancellation_drains_inflight_commit(env, monkeypatch):
    import anyio
    gw = gateway(env, editing=True)
    entered, release = threading.Event(), threading.Event()
    original = env[0].change
    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(env[0], "change", delayed)
    async def run():
        with anyio.CancelScope() as scope:
            async with anyio.create_task_group() as group:
                group.start_soon(gw.call, "edit_packaging", edit_args())
                await wait_event(entered)
                scope.cancel()
                release.set()
        assert gw.receipts[-1]["mutation"]["outcome"] == "committed"
    asyncio.run(run())
    assert gw.closed and env[0].get(env[1], env[2][0].document_id)["revision"] == 1


def test_lost_service_response_reports_unknown_not_rollback(env, monkeypatch):
    gw = gateway(env, editing=True)
    original = env[0].change
    def lost(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("C:/private/response-lost")
    monkeypatch.setattr(env[0], "change", lost)
    result = invoke(gw, "edit_packaging", edit_args())
    assert_error(result, "codex_tool_failed")
    assert result["mutation"]["outcome"] == "unknown" and gw.closed
    assert env[0].get(env[1], env[2][0].document_id)["revision"] == 1
    assert "private" not in json.dumps(result)


def test_inspect_package_and_validation_findings_pagination(env):
    args = edit_args()
    first = args["design"]["packages"][0]
    second = deepcopy(first)
    second.update(id="box_2", placements=[{"id": "item_2", "position_m": [0.02, 0.02, 0.02]}])
    args["design"].update(quantity=2, packages=[first, second])
    gw = gateway(env, editing=True)
    assert invoke(gw, "edit_packaging", args)["ok"]
    page1 = invoke(gw, args={"expected_revision": 1})["data"]
    assert page1["package_count"] == 2 and page1["next_package_offset"] == 1
    page2 = invoke(gw, args={"expected_revision": 1, "package_offset": 1})["data"]
    assert page2["packages"][0]["id"] == "box_2" and page2["next_package_offset"] is None
    proposed = deepcopy(args["design"])
    proposed["product"].update(mass_kg=None, mass_basis="unknown", mass_evidence="")
    before = snapshot(env)
    result = invoke(gw, "validate_packaging", {"expected_revision": 1, "design": proposed,
                                               "findings_limit": 1})
    assert result["data"]["saved"] is False and result["data"]["assessment"]["next_findings_offset"] == 1
    assert snapshot(env) == before


def test_context_callback_failure_is_revocation_not_an_error_leak(env):
    gw = gateway(env, editing=True)
    def revoked():
        raise RuntimeError("C:/private/revoked-session")
    gw.current_context = revoked
    result = invoke(gw, "edit_packaging", edit_args())
    assert_error(result, "codex_packaging_context_changed")
    assert gw.closed and "private" not in json.dumps(result)
    assert env[0].get(env[1], env[2][0].document_id)["revision"] == 0


def test_existing_runtime_credential_hook_is_rechecked_before_writes(env):
    gw = gateway(env, editing=True)
    def expired():
        raise RuntimeError("private credential diagnostic")
    gw.credential_check = expired
    result = invoke(gw, "edit_packaging", edit_args())
    assert_error(result, "codex_packaging_context_changed")
    assert gw.closed and "private" not in json.dumps(result)
    assert env[0].get(env[1], env[2][0].document_id)["revision"] == 0
