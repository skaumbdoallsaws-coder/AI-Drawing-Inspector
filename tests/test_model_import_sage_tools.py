"""MI3b tool contracts with fake scoped hooks, no server bootstrap or workers.

The separate host integration suite exercises real store/worker publication. These
unit tests pin dispatch, schema sharing, MCP limits, pictures and cancellation.
"""
from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
import json
import threading
from types import SimpleNamespace

import anyio
import httpx
from jsonschema import Draft202012Validator
import pytest

from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway, edit_tool_specs
from ai_inspector.codex_runtime.facility_tools import FacilityReadGateway, tool_specs
from ai_inspector.codex_runtime import model_import_tools as tools
from ai_inspector.codex_runtime.mcp_bridge import make_application
from ai_inspector.codex_runtime.pilot import EDIT_INSTRUCTIONS, INSTRUCTIONS
from ai_inspector.codex_runtime.policy import runtime_config
from ai_inspector.codex_runtime.progress import describe
from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.industrial_assets.model_import.recipe import RECIPE_SCHEMA
from tests.test_codex_mcp_pictures import posted

IMPORT = "mi-" + "a" * 24
DRAFT = "md-" + "b" * 24
REF = {"siteId": "site-a", "layoutId": "layout-a", "revision": "c" * 64}
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jV9sAAAAASUVORK5CYII=")
RECIPE = {"importId": IMPORT, "name": "Fixture bowl", "category": "Decor"}


class Runtime:
    def __init__(self):
        self.calls = []
        self.revision = REF["revision"]
        self.service = SimpleNamespace(get_layout=lambda *_: {"revision": self.revision, "layout": {}})
        self.summary = {"draftId": DRAFT, "dimensions": {"width": 1, "height": 1, "depth": 1},
                        "partsTotal": 36000, "parts": [{"key": "p0", "name": "bowl", "triangles": 12}],
                        "nextPartsOffset": 1, "attribution": {"licenseClass": "cc0"}}
        self.picture = PNG

    def authorize(self, principal, reference, write=False):
        if write and "editor" not in principal.roles:
            raise FacilityLayoutError("role_not_authorized", "Editing is not allowed.", status_code=403)
        if principal.tenant_id != "tenant-a" or reference["siteId"] != REF["siteId"]:
            raise FacilityLayoutError("model_import_missing", "That model was not found.", status_code=404)

    def model_import_inspect(self, principal, reference, *, import_id=None, draft_id=None, offset=0, limit=64):
        self.calls.append((tools.INSPECT, principal, reference, import_id, draft_id, offset, limit))
        self.authorize(principal, reference)
        if import_id is None and draft_id is None:
            return {"imports": [{"id": IMPORT, "name": "bowl.glb", "state": "ready", "created": 1}]}, None
        return deepcopy(self.summary), self.picture

    def model_import_prepare(self, principal, reference, recipe, cancel):
        self.calls.append((tools.PREPARE, principal, reference, recipe, cancel))
        self.authorize(principal, reference, True)
        assert isinstance(cancel, threading.Event) and not cancel.is_set()
        return deepcopy(self.summary), self.picture

    def model_import_register(self, principal, reference, draft_id):
        self.calls.append((tools.REGISTER, principal, reference, draft_id))
        self.authorize(principal, reference, True)
        return {"assetId": "asset-import-bowl-" + "d" * 24, "assetDefinitionRevision": "e" * 64,
                "displayName": "Fixture bowl", "category": "Decor", "dimensions": self.summary["dimensions"],
                "attribution": self.summary["attribution"], "added": True}


def gateway(kind=FacilityEditGateway, **principal_fields):
    principal = SimpleNamespace(**{**dict(tenant_id="tenant-a", principal_id="user-a", roles=("editor",)),
                                   **principal_fields})
    runtime = Runtime()
    gate = kind(runtime, principal, REF, turn_id="models", max_calls=30)
    return gate, runtime


def call(gate, name, args):
    return asyncio.run(gate.call(name, args))


def test_shared_recipe_and_exact_inventory_and_progress():
    reads = {spec["name"]: spec for spec in tool_specs()}
    edits = {spec["name"]: spec for spec in edit_tool_specs()}
    assert tools.INSPECT in reads and not {tools.PREPARE, tools.REGISTER} & reads.keys()
    assert {tools.PREPARE, tools.REGISTER} <= edits.keys()
    assert reads[tools.INSPECT]["pictures"] and edits[tools.PREPARE]["pictures"]
    assert edits[tools.PREPARE]["input_schema"] == RECIPE_SCHEMA
    assert edits[tools.PREPARE]["input_schema"] is not RECIPE_SCHEMA
    assert edits[tools.REGISTER]["read_only"] is False
    for spec in [reads[tools.INSPECT], edits[tools.PREPARE], edits[tools.REGISTER]]:
        Draft202012Validator.check_schema(spec["input_schema"])
    assert set(runtime_config("http://unused/mcp", "test", offline=True)["mcp_servers"]["inspectorpro"]["enabled_tools"]) == reads.keys()
    for name, label in [(tools.INSPECT, "Reading the imported 3D model"),
                        (tools.PREPARE, "Preparing the 3D model draft"),
                        (tools.REGISTER, "Recording the model in the shared library")]:
        assert describe(name, {})["running"] == label


@pytest.mark.parametrize("kind", [FacilityReadGateway, FacilityEditGateway])
@pytest.mark.parametrize("args", [{}, {"importId": IMPORT}, {"draftId": DRAFT, "partsOffset": 64, "partsLimit": 12}])
def test_inspection_delegates_scope_ids_and_paging(kind, args):
    gate, runtime = gateway(kind)
    result = call(gate, tools.INSPECT, args)
    assert result["ok"]
    invoked = runtime.calls[0]
    assert invoked[1] is gate.principal and invoked[2] is gate.reference
    assert invoked[3:] == (args.get("importId"), args.get("draftId"), args.get("partsOffset", 0), args.get("partsLimit", 64))
    image = gate.take_image()
    if args:
        assert image == {"mimeType": "image/png", "data": base64.b64encode(PNG).decode("ascii")}
    else:
        assert result["data"]["imports"][0]["id"] == IMPORT and image is None
    assert gate.take_image() is None
    assert len(json.dumps(result).encode()) < 65536


@pytest.mark.parametrize("name,args", [
    (tools.INSPECT, {"importId": IMPORT, "draftId": DRAFT}), (tools.INSPECT, {"importId": "wrong"}),
    (tools.INSPECT, {"draftId": DRAFT + "\n"}), (tools.INSPECT, {"partsOffset": -1}),
    (tools.INSPECT, {"partsLimit": 65}), (tools.INSPECT, {"partsLimit": 0}),
    (tools.INSPECT, {"siteId": "other"}), (tools.INSPECT, {"path": "file.glb"}),
    (tools.PREPARE, {**RECIPE, "size": {"dimension": "height", "meters": 0}}),
    (tools.PREPARE, {**RECIPE, "attribution": {"statedBy": "file"}}),
    (tools.PREPARE, {**RECIPE, "unknown": True}), (tools.REGISTER, {}),
    (tools.REGISTER, {"draftId": DRAFT, "approved": True}), (tools.REGISTER, {"draftId": IMPORT}),
])
def test_invalid_arguments_never_reach_host(name, args):
    gate, runtime = gateway()
    result = call(gate, name, args)
    assert result["error"]["code"] == "codex_tool_arguments_invalid"
    assert result["error"]["details"]["findings"] and runtime.calls == []
    assert gate.take_image() is None


def test_prepare_and_register_only_in_edit_gateway_keep_proposal_separate():
    reader, _ = gateway(FacilityReadGateway)
    assert call(reader, tools.PREPARE, RECIPE)["error"]["code"] == "codex_tool_denied"
    assert call(reader, tools.REGISTER, {"draftId": DRAFT})["error"]["code"] == "codex_tool_denied"
    gate, runtime = gateway()
    gate.proposal = {"proposalId": "existing-layout-preview"}
    assert call(gate, tools.PREPARE, RECIPE)["ok"]
    first_event = runtime.calls[-1][-1]
    assert runtime.calls[-1][3] == RECIPE
    registered = call(gate, tools.REGISTER, {"draftId": DRAFT})
    assert registered["ok"] and registered["data"]["added"]
    assert set(registered["data"]) == {"assetId", "assetDefinitionRevision", "displayName", "category", "dimensions", "attribution", "added"}
    assert runtime.calls[-1][1] is gate.principal and runtime.calls[-1][2] is gate.reference
    assert gate.take_image() is None and gate.proposal == {"proposalId": "existing-layout-preview"}
    assert call(gate, tools.PREPARE, RECIPE)["ok"]
    assert runtime.calls[-1][-1] is not first_event and gate.model_import_cancel is None


@pytest.mark.parametrize("name,args", [(tools.PREPARE, RECIPE), (tools.REGISTER, {"draftId": DRAFT})])
def test_viewer_cannot_bypass_the_host(name, args):
    gate, runtime = gateway(roles=("viewer",))
    assert call(gate, tools.INSPECT, {"importId": IMPORT})["ok"]
    assert call(gate, name, args)["error"]["code"] == "role_not_authorized"
    assert len(runtime.calls) == 2 and gate.take_image() is None


@pytest.mark.parametrize("foreign", ["tenant", "site"])
def test_foreign_scope_is_passed_to_authoritative_hook(foreign):
    gate, _ = gateway()
    if foreign == "tenant":
        gate.principal.tenant_id = "other"
    else:
        gate.reference["siteId"] = "other"
    assert call(gate, tools.INSPECT, {"importId": IMPORT})["error"]["code"] == "model_import_missing"


def test_stale_binding_fails_before_hook_and_late_staleness_clears_picture():
    gate, runtime = gateway()
    runtime.revision = "changed"
    assert call(gate, tools.INSPECT, {"importId": IMPORT})["error"]["code"] == "codex_document_unavailable"
    assert not runtime.calls
    runtime.revision = REF["revision"]
    original = runtime.model_import_prepare
    def late(*args):
        result = original(*args)
        runtime.revision = "changed"
        return result
    runtime.model_import_prepare = late
    assert call(gate, tools.PREPARE, RECIPE)["error"]["code"] == "codex_document_unavailable"
    assert gate.take_image() is None


def test_host_errors_keep_recipe_paths_and_clear_prior_images():
    gate, runtime = gateway()
    assert call(gate, tools.INSPECT, {"importId": IMPORT})["ok"]
    details = {"problems": [{"path": "parts[0].select", "problem": "No matching material"}],
               "closest": [{"key": "p0", "name": "paint"}]}
    def fail(*_):
        raise FacilityLayoutError("selector_empty", "No matching parts.", details=details)
    runtime.model_import_prepare = fail
    result = call(gate, tools.PREPARE, RECIPE)
    assert result["error"] == {"code": "selector_empty", "message": "No matching parts.", "details": details}
    assert gate.take_image() is None
    runtime.model_import_prepare = lambda *_: (_ for _ in ()).throw(RuntimeError("private file path"))
    result = call(gate, tools.PREPARE, RECIPE)
    assert "private file path" not in json.dumps(result) and gate.take_image() is None


@pytest.mark.parametrize("failure", ["summary", "envelope", "picture", "mime"])
def test_result_byte_limits_and_invalid_images_clear_picture(failure):
    gate, runtime = gateway()
    if failure == "summary":
        runtime.summary = {"large": "x" * (48 * 1024)}
    elif failure == "envelope":
        runtime.summary = {"rows": [[0] * 30 for _ in range(750)]}
        assert len(json.dumps(runtime.summary, separators=(",", ":")).encode()) < tools.SUMMARY_BYTES
        assert len(json.dumps({"ok": True, "data": runtime.summary}).encode()) > 65536
    elif failure == "picture":
        runtime.picture = PNG + bytes(tools.PICTURE_BYTES)
    else:
        runtime.picture = b"not a PNG"
    result = call(gate, tools.PREPARE, RECIPE)
    assert result["error"]["code"] == ("model_import_picture_invalid" if failure == "mime" else "codex_result_too_large")
    assert gate.take_image() is None


def test_valid_but_oversized_recipe_is_refused_before_host():
    gate, runtime = gateway()
    patch = {"color": "#112233", "roughness": 1, "metalness": 1, "texture": "drop", "emissive": "off",
             "alpha": "mask", "alphaCutoff": .95, "doubleSided": True}
    args = {**RECIPE, "pivot": {"parts": [{"mesh": "z" * 80}] * 64},
            "parts": [{"select": {"material": "x" * 80}, "name": "y" * 80, "material": patch,
                       "scale": 20, "turnDegrees": 360, "move": [100, 100, 100]}] * 64}
    assert Draft202012Validator(RECIPE_SCHEMA).is_valid(args)
    assert len(json.dumps(args).encode()) > tools.REQUEST_BYTES
    assert call(gate, tools.PREPARE, args)["error"]["code"] == "codex_tool_arguments_too_large"
    assert runtime.calls == []


def test_mcp_picture_results_have_json_text_and_png_but_no_structured_content():
    gate, _ = gateway()
    answers = posted(gate, ("tools/call", {"name": tools.INSPECT, "arguments": {"importId": IMPORT}}),
                     ("tools/call", {"name": tools.PREPARE, "arguments": RECIPE}),
                     ("tools/call", {"name": tools.REGISTER, "arguments": {"draftId": DRAFT}}))
    for answer in answers[:2]:
        assert answer.get("structuredContent") is None
        text, image = answer["content"]
        assert json.loads(text["text"])["ok"]
        assert image["mimeType"] == "image/png" and base64.b64decode(image["data"]) == PNG
    assert answers[-1]["structuredContent"]["data"]["added"]
    assert len(answers[-1]["content"]) == 1


def test_mcp_request_limit_includes_json_rpc_envelope():
    pytest.importorskip("mcp")
    gate, runtime = gateway()
    app, manager = make_application(gate, "synthetic", "127.0.0.1:7654")
    async def exercise():
        async with manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 123)),
                                         base_url="http://127.0.0.1:7654") as client:
                response = await client.post("/mcp", headers={"Authorization": "Bearer synthetic",
                    "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"},
                    json={"jsonrpc": "2.0", "id": "x" * 32768, "method": "tools/call",
                          "params": {"name": tools.PREPARE, "arguments": RECIPE}})
                assert response.status_code == 413
    asyncio.run(exercise())
    assert runtime.calls == []


@pytest.mark.parametrize("level_cancel", [False, True])
def test_cancel_sets_worker_event_then_joins_despite_repeated_cancellation(level_cancel):
    gate, runtime = gateway()
    entered, signalled, release, finished = (threading.Event() for _ in range(4))
    def prepare(principal, reference, recipe, cancel):
        entered.set()
        try:
            assert cancel.wait(3)
            signalled.set()
            assert release.wait(3)
            # Even a late host result must not expose a picture after cancellation.
            return deepcopy(runtime.summary), PNG
        finally:
            finished.set()
    runtime.model_import_prepare = prepare

    async def exercise():
        task = None
        async def work():
            nonlocal task
            task = asyncio.current_task()
            await gate.call(tools.PREPARE, RECIPE)
            pytest.fail("A cancelled prepare must not publish a result")
        async with anyio.create_task_group() as group:
            group.start_soon(work)
            try:
                async with asyncio.timeout(2):
                    while not entered.is_set():
                        await asyncio.sleep(.001)
                    if level_cancel:
                        group.cancel_scope.cancel()
                    else:
                        task.cancel()
                    with anyio.CancelScope(shield=True):
                        while not signalled.is_set():
                            await asyncio.sleep(.001)
                        assert gate.closed and gate.lock.locked()
                        for _ in range(2):
                            task.cancel()
                            await asyncio.sleep(.01)
                            assert not task.done() and not finished.is_set()
            finally:
                release.set()
        assert task.cancelled() and finished.is_set() and not gate.lock.locked()
        assert gate.take_image() is None and gate.model_import_cancel is None and gate.receipts == []
    anyio.run(exercise, backend="asyncio")


def test_playbook_keeps_credit_and_distinguishes_library_from_placement():
    assert "inspect_model_import" in INSTRUCTIONS and "cannot prepare or register" in INSTRUCTIONS
    for text in ("inspect_model_import", "prepare_model_asset", "register_model_asset", "CC BY-SA",
                 "non-commercial use only", "ND licence", "ask before preparing", "before registering",
                 'statedBy "user"', "two more prepare rounds", "Place only when asked", "every site"):
        assert text in EDIT_INSTRUCTIONS


@pytest.mark.parametrize("name,hook,args", [
    (tools.INSPECT, "model_import_inspect", {"importId": IMPORT}),
    (tools.PREPARE, "model_import_prepare", RECIPE),
    (tools.REGISTER, "model_import_register", {"draftId": DRAFT}),
])
def test_absent_host_hook_fails_closed(name, hook, args):
    gate, runtime = gateway()
    setattr(runtime, hook, None)
    result = call(gate, name, args)
    assert result["error"]["code"] == "model_import_unavailable"
    assert gate.take_image() is None and runtime.calls == []
