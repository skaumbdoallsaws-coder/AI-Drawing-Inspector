"""MI3b real-host gates for Claude after the concurrent host hooks land.

Only temporary facility/catalog roots and generated models are used. Upload and
prepare use the real resource-limited workers; no server bootstrap or provider.
The cancellation case substitutes a sleeping worker script to observe kill/join.
"""
from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import numpy as np
import pytest

from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
from ai_inspector.codex_runtime.facility_tools import FacilityReadGateway
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, LOCAL_SITE_ID, LOCAL_LAYOUT_ID
from ai_inspector.facility_layout.model_import_store import ModelImportScope, get_model_import_store
from ai_inspector.facility_layout.model_imports import create_model_import_router
from ai_inspector.industrial_assets.model_import import runner
from tests.model_import_test_support import Fixture, textured_box
from tests.test_authored_assets_live import project

DEPENDENCIES = Path(np.__file__).resolve().parent.parent
CREDIT = {"title": "Synthetic bowl", "author": "Test artist", "license": "CC BY 4.0",
          "licenseClass": "cc-by", "statedBy": "user"}
BASE = f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/model-imports"


def saved(host, principal=None, site=LOCAL_SITE_ID, layout=LOCAL_LAYOUT_ID):
    return host.service.get_layout(principal or host.principal(), site, layout)


def reference(host, principal=None, site=LOCAL_SITE_ID):
    return {"siteId": site, "layoutId": LOCAL_LAYOUT_ID,
            "revision": saved(host, principal, site)["revision"]}


def gateway(env, kind=FacilityEditGateway, principal=None, site=LOCAL_SITE_ID):
    principal = principal or env.host.principal()
    return kind(env.host.agent_runtime, principal, reference(env.host, principal, site),
                turn_id="model-integration", max_calls=30, timeout=300)


def call(gate, tool, args):
    return asyncio.run(gate.call(tool, args))


def recipe(import_id, **fields):
    return {"importId": import_id, "name": "Synthetic bowl", "category": "Decor", "attribution": CREDIT, **fields}


def image(gate):
    picture = gate.take_image()
    assert picture["mimeType"] == "image/png"
    payload = base64.b64decode(picture["data"])
    assert payload.startswith(b"\x89PNG\r\n\x1a\n") and len(payload) <= 1536 * 1024
    assert gate.take_image() is None


@pytest.fixture
def env(tmp_path):
    root = project(tmp_path)
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=True, private_asset_root=root)
    host.ensure_bootstrap()
    for name in ("model_import_inspect", "model_import_prepare", "model_import_register"):
        assert callable(getattr(host.agent_runtime, name, None)), f"MI3b shared host hook missing: {name}"
    store = get_model_import_store(host.service)
    store.runtime = lambda: SimpleNamespace(dependency_root=DEPENDENCIES)
    app = FastAPI()
    app.include_router(create_model_import_router(service=host.service,
                        principal_resolver=lambda _: host.principal(), store=store))
    try:
        with TestClient(app) as client:
            yield SimpleNamespace(host=host, store=store, client=client, root=root, facility=tmp_path / "facility")
    finally:
        store.close()
        host.close()


def upload(env, payload=None):
    response = env.client.post(BASE, content=textured_box().bytes() if payload is None else payload,
                               headers={"X-Model-Name": "synthetic.glb"})
    assert response.status_code == 202, response.text
    import_id = response.json()["id"]
    deadline = time.monotonic() + 85
    while time.monotonic() < deadline:
        response = env.client.get(BASE + "/" + import_id)
        assert response.status_code == 200, response.text
        record = response.json()
        if record["state"] not in {"queued", "checking"} and not env.store._active():
            assert record["state"] == "ready", record
            return import_id
        time.sleep(.02)
    pytest.fail("Real model worker did not finish within its wall-clock budget")


def prepared(env):
    import_id = upload(env)
    gate = gateway(env)
    result = call(gate, "prepare_model_asset", recipe(import_id, size={"dimension": "height", "meters": .4}))
    assert result["ok"], result
    return import_id, result["data"]["draftId"], gate


def test_upload_inspect_prepare_register_place_and_restart(env):
    import_id = upload(env)
    gate = gateway(env)
    before = saved(env.host)
    version = env.host.list_assets()["catalogVersion"]
    inspected = call(gate, "inspect_model_import", {"importId": import_id})
    assert inspected["ok"] and inspected["data"]["state"] == "ready", inspected
    image(gate)
    prepared_result = call(gate, "prepare_model_asset", recipe(import_id, size={"dimension": "height", "meters": .4}))
    assert prepared_result["ok"], prepared_result
    draft = prepared_result["data"]
    image(gate)
    assert len(json.dumps(prepared_result).encode()) < 65536
    assert saved(env.host) == before and env.host.list_assets()["catalogVersion"] == version
    registered = call(gate, "register_model_asset", {"draftId": draft["draftId"]})
    assert registered["ok"], registered
    asset = registered["data"]
    assert asset["added"] and asset["dimensions"] == draft["dimensions"]
    assert asset["attribution"]["author"] == CREDIT["author"]
    assert saved(env.host) == before and env.host.list_assets()["catalogVersion"] != version
    inspected_asset = call(gate, "inspect_facility_asset", {"assetId": asset["assetId"]})
    assert inspected_asset["ok"], inspected_asset
    assert inspected_asset["data"]["assetDefinitionRevision"] == asset["assetDefinitionRevision"]
    assert inspected_asset["data"]["definition"]["attribution"] == asset["attribution"]
    again = call(gate, "register_model_asset", {"draftId": draft["draftId"]})
    assert again["ok"] and again["data"] == {**asset, "added": False}
    placement = {"assetId": asset["assetId"], "assetDefinitionRevision": asset["assetDefinitionRevision"],
        "transform": {"position": {"x": 4, "y": 0, "z": 4}, "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1},
                      "scale": 1}, "positionMode": "locked", "snapRelationship": None, "metadata": {}}
    staged = call(gate, "preview_facility_operations", {"operations": [{"op": "place_asset", "placement": placement}]})
    assert staged["ok"] and staged["data"]["proposalId"], staged
    assert staged["data"]["validation"]["introduced"]["spatial"]["errorCount"] == 0
    assert saved(env.host) == before  # library publication and the preview never save the layout
    env.store.close()
    env.host.close()
    restarted = LocalFacilityLayoutHost(env.facility, private_assets=True, private_asset_root=env.root)
    try:
        restarted.ensure_bootstrap()
        reader = FacilityReadGateway(restarted.agent_runtime, restarted.principal(), reference(restarted), turn_id="restart")
        found = call(reader, "inspect_facility_asset", {"assetId": asset["assetId"]})
        assert found["ok"] and found["data"] == inspected_asset["data"]
        kept = call(reader, "inspect_model_import", {"draftId": draft["draftId"], "partsLimit": 1})
        assert kept["ok"] and kept["data"]["draftId"] == draft["draftId"], kept
        image(reader)
    finally:
        get_model_import_store(restarted.service).close()
        restarted.close()


def test_viewer_read_allowed_but_prepare_and_register_denied(env):
    import_id, draft_id, _ = prepared(env)
    viewer = replace(env.host.principal(), roles=("viewer",))
    gate = gateway(env, principal=viewer)
    assert call(gate, "inspect_model_import", {"importId": import_id})["ok"]
    for tool, arguments in (("prepare_model_asset", recipe(import_id)),
                            ("register_model_asset", {"draftId": draft_id})):
        result = call(gate, tool, arguments)
        assert not result["ok"] and result["error"]["code"] == "role_not_authorized"
        assert gate.take_image() is None


def test_stale_binding_cannot_prepare_or_register(env):
    import_id, draft_id, gate = prepared(env)
    current = saved(env.host)
    env.host.service.apply_operations(env.host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID, current["revision"],
                                     [{"op": "rename_layout", "displayName": "Changed after binding"}])
    for tool, arguments in (("inspect_model_import", {"importId": import_id}),
                            ("prepare_model_asset", recipe(import_id)),
                            ("register_model_asset", {"draftId": draft_id})):
        result = call(gate, tool, arguments)
        assert result["error"]["code"] == "codex_document_unavailable" and gate.take_image() is None


@pytest.mark.parametrize("scope", ["tenant", "site"])
def test_foreign_imports_and_drafts_match_missing_ids(env, scope):
    import_id, draft_id, _ = prepared(env)
    principal = env.host.principal()
    site = LOCAL_SITE_ID
    if scope == "tenant":
        principal = replace(principal, tenant_id="other-tenant")
    else:
        site = "other-site"
        principal = replace(principal, allowed_site_ids=(site,))
    # Persist an authorized empty layout for that scope, so the test reaches import lookup.
    document = deepcopy(saved(env.host)["layout"])
    document["association"]["siteId"] = site
    env.host.layout_repository.create_layout(principal, site, document)
    gate = gateway(env, principal=principal, site=site)
    for tool, arguments, missing in (
        ("inspect_model_import", {"importId": import_id}, {"importId": "mi-" + "f" * 24}),
        ("inspect_model_import", {"draftId": draft_id}, {"draftId": "md-" + "f" * 24}),
        ("prepare_model_asset", recipe(import_id), recipe("mi-" + "f" * 24)),
        ("register_model_asset", {"draftId": draft_id}, {"draftId": "md-" + "f" * 24}),
    ):
        foreign_result, missing_result = call(gate, tool, arguments), call(gate, tool, missing)
        assert not foreign_result["ok"] and foreign_result["error"] == missing_result["error"]
        assert set(foreign_result) == set(missing_result)
        assert gate.take_image() is None


def test_real_many_parts_prepare_is_bounded_and_can_be_paged(env):
    fixture = Fixture()
    primitive = fixture.triangle([[0, 0, 0], [.001, 0, 0], [0, .001, .001]])
    fixture.document["meshes"][0]["primitives"] = [deepcopy(primitive) for _ in range(3000)]
    import_id = upload(env, fixture.bytes())
    gate = gateway(env)
    result = call(gate, "prepare_model_asset", recipe(import_id, copies=[{"x": i * .002} for i in range(12)]))
    assert result["ok"], result
    data = result["data"]
    assert data["partsTotal"] == 36000 and len(data["parts"]) <= 64
    assert len(json.dumps(data, separators=(",", ":")).encode()) <= 48 * 1024
    assert len(json.dumps(result).encode()) < 65536
    image(gate)
    page = call(gate, "inspect_model_import", {"draftId": data["draftId"], "partsOffset": 64, "partsLimit": 12})
    assert page["ok"] and len(page["data"]["parts"]) == 12, page
    assert page["data"]["parts"][0]["key"] != data["parts"][0]["key"]
    image(gate)


def test_real_gateway_cancel_kills_joins_releases_and_does_not_publish(env, tmp_path, monkeypatch):
    import_id = upload(env)
    gate = gateway(env)
    stub = tmp_path / "sleeping_model_worker.py"
    stub.write_bytes(b"import time\nfrom pathlib import Path\nPath('worker-started').touch()\ntime.sleep(30)\n")
    monkeypatch.setattr(runner, "_WORKER", stub)
    processes, original = [], runner.subprocess.Popen
    def capture(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(runner.subprocess, "Popen", capture)

    async def exercise():
        task = asyncio.create_task(gate.call("prepare_model_asset", recipe(import_id)))
        try:
            async with asyncio.timeout(10):
                while not list(env.store.root.rglob("worker-started")):
                    if task.done():
                        pytest.fail(f"Prepare ended before the worker started: {task.result()}")
                    await asyncio.sleep(.01)
                assert processes and processes[0].poll() is None
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    asyncio.run(exercise())
    assert processes and all(process.poll() is not None for process in processes)
    assert gate.closed and not gate.lock.locked() and gate.take_image() is None
    bound = ModelImportScope(env.host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    record = env.store.get(bound, import_id)
    assert record["state"] == "ready" and record["drafts"] == []
    assert env.store._active() == []
    assert not list((env.store.root / bound.key / "locks").glob("*.json"))
    assert not list((env.store.root / bound.key / "drafts").glob("md-*"))
    assert not list(env.store.root.rglob("worker-started"))
    # Admission is usable immediately after the gateway's joined cancellation.
    incoming = env.store.begin_upload(bound, "next.glb", 1)
    incoming.abort()
