"""Assisted material proofs on a saved gym and copied, real catalog GLB bytes."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
import struct
from urllib.parse import unquote

import pytest

from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.operation_proposals import create
from tools.check_codex_facility_authoring import ROOT, case_operations
from tests.test_codex_facility_authoring import gym


@pytest.fixture
def copied_visual(gym, tmp_path, monkeypatch):
    entry = gym.host._catalog["asset-chair-black"]
    source = ROOT / unquote(entry["overview"]["path"]).lstrip("/")
    source_bytes = source.read_bytes()
    target = tmp_path / "generated/copied-chair.glb"
    target.parent.mkdir()
    shutil.copyfile(source, target)
    monkeypatch.setattr(gym.host, "_component_visual_root", tmp_path)
    monkeypatch.setitem(entry, "overview", {**entry["overview"], "path": "/generated/copied-chair.glb"})
    try:
        yield target
    finally:
        assert source.read_bytes() == source_bytes
        gym.assert_source()


def change_visual(path):
    """Change metadata in the disposable GLB while retaining all real geometry."""
    data = path.read_bytes()
    json_size, kind = struct.unpack_from("<II", data, 12)
    assert kind == 0x4E4F534A
    document = json.loads(data[20:20 + json_size])
    document["asset"]["generator"] = "component-proof-regression"
    payload = json.dumps(document, separators=(",", ":")).encode()
    payload += b" " * (-len(payload) % 4)
    tail = data[20 + json_size:]
    changed = struct.pack("<4sIIII", b"glTF", 2, 20 + len(payload) + len(tail), len(payload), kind) + payload + tail
    assert sha256(changed).digest() != sha256(data).digest()
    path.write_bytes(changed)


def operation(gym, request):
    result = case_operations(gym, "component_materials")[0]
    result["materials"]["overrides"][0]["color"] = "#" + sha256(request.node.name.encode()).hexdigest()[:6]
    return result


def propose(gym, op):
    return create(gym.host.service, gym.principal, gym.site_id, gym.layout_id,
                  gym.current()["revision"], operations=[op])


@pytest.mark.parametrize("proof", [None, "", "A" * 64, "0" * 63, 42])
def test_nonnull_assisted_materials_require_exact_hash(gym, copied_visual, request, proof):
    before = gym.current()
    op = operation(gym, request)
    if proof is None:
        del op["visualSha256"]
    else:
        op["visualSha256"] = proof
    with pytest.raises(FacilityLayoutError) as error:
        propose(gym, op)
    assert error.value.code == "component_visual_proof_required"
    assert gym.current() == before


def test_unknown_component_key_is_rejected_for_matching_visual(gym, copied_visual, request):
    before = gym.current()
    op = operation(gym, request)
    op["materials"]["overrides"][0]["key"] = "m999999-s0"
    with pytest.raises(FacilityLayoutError) as error:
        propose(gym, op)
    assert error.value.code == "component_material_key_unavailable"
    assert gym.current() == before


@pytest.mark.parametrize("empty", [False, True])
def test_place_asset_cannot_bypass_proof_with_inline_materials(gym, copied_visual, request, empty):
    before = gym.current()
    material_edit = operation(gym, request)
    placement = deepcopy(next(p for p in before["layout"]["placements"]
                              if p["placementId"] == material_edit["placementId"]))
    placement.pop("placementId")
    placement["componentMaterials"] = {} if empty else material_edit["materials"]
    with pytest.raises(FacilityLayoutError) as error:
        propose(gym, {"op": "place_asset", "placement": placement,
                      "visualSha256": material_edit["visualSha256"]})
    assert error.value.code == "component_target_requires_saved_visual"
    assert "set_component_materials" in str(error.value)
    assert gym.current() == before


@pytest.mark.parametrize("phase", ["create", "preview", "apply", "commit_recheck"])
def test_changed_real_visual_rejected_before_saved_mutation(gym, copied_visual, request, monkeypatch, phase):
    before = gym.current()
    op = operation(gym, request)
    if phase != "create":
        proposal = propose(gym, op)
    if phase in {"apply", "commit_recheck"}:
        approval = gym.approval(proposal, "changed-visual-" + phase)
        assert approval.status_code == 200
    if phase == "commit_recheck":
        # The visual changes after the apply's rebuild has passed its checks, just before the commit: the commit
        # checks the components again itself (it no longer replays the operations) and must refuse.
        regenerate = gym.host.service._regenerate_proposal
        calls = []
        def change_after_regenerate(*args, **kwargs):
            result = regenerate(*args, **kwargs)
            calls.append(True)
            change_visual(copied_visual)
            return result
        monkeypatch.setattr(gym.host.service, "_regenerate_proposal", change_after_regenerate)
    else:
        change_visual(copied_visual)
    with pytest.raises(FacilityLayoutError) as error:
        if phase == "create":
            propose(gym, op)
        elif phase == "preview":
            gym.host.service.get_layout_proposal_preview(gym.principal, gym.site_id, gym.layout_id,
                                                       proposal["proposalId"])
        else:
            gym.host.service.apply_layout_proposal(gym.principal, gym.site_id, gym.layout_id,
                approval.json()["approvalToken"], proposal["alternative"]["transactionBinding"],
                session_id="authoring-test-approver", idempotency_key="changed-visual-" + phase)
    assert error.value.code == "component_visual_revision_conflict"
    if phase == "commit_recheck":
        assert len(calls) == 1
    assert gym.current() == before


def test_material_edit_cannot_reuse_proof_for_replacement_in_same_batch(gym, copied_visual, request):
    before = gym.current()
    op = operation(gym, request)
    replacement = case_operations(gym, "replace_asset")[0]
    with pytest.raises(FacilityLayoutError) as error:
        create(gym.host.service, gym.principal, gym.site_id, gym.layout_id, before["revision"],
               operations=[replacement, op])
    assert error.value.code == "component_target_requires_saved_visual"
    assert gym.current() == before


def test_manual_component_operations_and_null_assisted_reset_remain_proof_free(gym, copied_visual, request, monkeypatch):
    before = gym.current()
    op = operation(gym, request)
    del op["visualSha256"]
    reset = {"op": "set_component_materials", "placementId": op["placementId"], "materials": None}
    monkeypatch.setattr(gym.host.service, "component_inventory_resolver", None)
    saved = gym.host.service.apply_operations(gym.principal, gym.site_id, gym.layout_id,
                                             before["revision"], [op])
    try:
        placement = next(p for p in saved["layout"]["placements"] if p["placementId"] == op["placementId"])
        assert placement["componentMaterials"] == op["materials"]
        proposal = propose(gym, reset)
        restored = gym.approve_commit(proposal, "proof-free-null-reset")
        expected = deepcopy(before["layout"])
        expected["updatedAt"] = restored["layout"]["updatedAt"]
        assert restored["layout"] == expected
    finally:
        current = gym.current()
        if any(p["placementId"] == op["placementId"] and "componentMaterials" in p for p in current["layout"]["placements"]):
            gym.host.service.apply_operations(gym.principal, gym.site_id, gym.layout_id, current["revision"], [reset])


def test_assisted_materials_fail_closed_without_authoritative_resolver(gym, copied_visual, request, monkeypatch):
    before = gym.current()
    op = operation(gym, request)
    monkeypatch.setattr(gym.host.service, "component_inventory_resolver", None)
    with pytest.raises(FacilityLayoutError) as error:
        propose(gym, op)
    assert error.value.code == "component_inventory_unavailable"
    assert gym.current() == before
