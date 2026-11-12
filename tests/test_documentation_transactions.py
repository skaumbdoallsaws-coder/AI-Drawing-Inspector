"""In-place P1a transactions; every write is below pytest's temporary root."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import uuid

import pytest

from ai_inspector.documentation import commands as contract
from ai_inspector.documentation.commands import DocumentEditError, binding, canonical_bytes, content_hash, document_id
from ai_inspector.documentation.targets import ReadBindings, hash_values, read_targets, text_targets, target_id
from ai_inspector.parts_manual.documentation import (
    DocumentationSceneRepository, DocumentationSceneError, DocumentationSceneBindingError,
    documentation_scene_revision, validate_documentation_scene,
)
from ai_inspector.specification_sheet.slots import SlotStore, SpecificationSlotError

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/documentation_editor/scene-v2-mmle-excerpt.json"
NUMBER, SOURCE, PLAN = "MMLE-50D", "source-1", "plan-1"
PAGE = "page-text"


class SceneHarness:
    def __init__(self, root):
        self.root = root
        self.repo = DocumentationSceneRepository(root, "work_instructions")
        self.path = root / "mmle-50d" / "documentation-scene.json"
        self.lock = self.repo.transaction_lock
        self.document = {"pages": [{"pageId": PAGE, "layoutBlocks": [
            {"blockId": key, "blockType": "paragraph", "text": value}
            for key, value in (("title", "one"), ("caption", "two"))]}]}
        self.page_targets = {PAGE: {"page_element": ["title", "caption"]}}

    def snapshot(self):
        loaded = self.repo.read(NUMBER, SOURCE, PLAN)
        scene = loaded["scene"]
        state = {**scene, "scene": scene, "documentId": document_id("work_instructions", NUMBER),
                 "revision": scene["editRevision"], "sceneRevision": loaded["revision"]}
        targets = text_targets(state, self.document)
        hashes = {target["alias"]: content_hash(state, key, hash_values(targets)[key]) for key, target in targets.items()}
        return state, hashes

    def commit(self, request, invalid=False):
        with self.lock:  # exactly the host contract: compile/hash and apply under one lock
            state, hashes = self.snapshot()
            native = [{"operation": "update_text", "pageId": PAGE, "targetType": "page_element",
                       "targetId": key, "text": value} for key, value in request["values"].items()]
            if invalid:
                native[-1]["targetId"] = "absent"
            return self.repo.apply_batch(NUMBER, SOURCE, PLAN,
                base_revision=request["sceneRevision"], expected_revision=request["expectedRevision"],
                request_id=request["requestId"], commands=native, page_targets=self.page_targets,
                expected_hashes=request["hashes"], current_hashes=hashes,
                hashes_revision=state["sceneRevision"], payload=request)["receipt"]

    def values(self):
        state, _ = self.snapshot()
        return {target["alias"]: target["text"] for target in text_targets(state, self.document).values()}

    def undo(self):
        state, _ = self.snapshot()
        self.repo.move_history(NUMBER, SOURCE, PLAN, base_revision=state["sceneRevision"], direction="undo")


class SlotHarness:
    def __init__(self, root):
        self.root = root
        self.repo = SlotStore(root, NUMBER)
        self.path, self.lock = self.repo.path, self.repo.transaction_lock

    def snapshot(self):
        state = self.repo.read()
        state.update(revision=state["editRevision"], sceneRevision=None,
                     documentId=document_id("product_specification_sheet", NUMBER),
                     sourceRevision=SOURCE, manualPlanRevision=PLAN)
        hashes = {key: content_hash(state, "slot:" + key, {"versionKey": "slot:" + key,
            "entry": state["values"].get(key, {"value": value})}) for key, value in (("title", "one"), ("caption", "two"))}
        return state, hashes

    def commit(self, request, invalid=False):
        with self.lock:
            _state, hashes = self.snapshot()
            items = [{"slot": key, "value": value} for key, value in request["values"].items()]
            if invalid:
                items[-1]["slot"] = "absent"
            # Test invalid payload via transaction so domain validation, rather
            # than a differing hash-key set, is responsible for the rejection.
            self.repo.transaction(lambda store: store.set_values(items, "chat"),
                expected_revision=request["expectedRevision"], request_id=request["requestId"],
                expected_hashes={"slot:" + k: v for k, v in request["hashes"].items()},
                current_hashes={"slot:" + k: v for k, v in hashes.items()}, payload=request)
            return self.repo.last_receipt

    def values(self):
        state, _ = self.snapshot()
        return {key: state["values"].get(key, {"value": value})["value"] for key, value in (("title", "one"), ("caption", "two"))}


@pytest.fixture(params=[SceneHarness, SlotHarness], ids=["scene", "slots"])
def store(request, tmp_path):
    return request.param(tmp_path)


def request_for(store, values, request_id=None):
    state, hashes = store.snapshot()
    return {"requestId": request_id or uuid.uuid4().hex, "expectedRevision": state["revision"],
            "sceneRevision": state["sceneRevision"], "hashes": {key: hashes[key] for key in values},
            "values": values}


def disk(store):
    return {p.relative_to(store.root).as_posix(): p.read_bytes() for p in store.root.rglob("*") if p.is_file()}


def test_legacy_scene_read_and_first_write_preserve_original(tmp_path):
    store = SceneHarness(tmp_path)
    store.path.parent.mkdir()
    original = b"  " + FIXTURE.read_bytes() + b"\r\n"
    store.path.write_bytes(original)
    before = disk(store)
    loaded = store.repo.read(NUMBER, "sanitized-source-1", "sanitized-plan-1")
    old = json.loads(original)
    assert loaded["scene"]["schemaVersion"] == 8
    assert loaded["scene"]["pages"] == old["pages"]
    assert loaded["scene"]["commands"] == old["commands"]
    # Claude measured this with the pre-P1a repository.read() on the same
    # excerpt (HEAD and new code side by side). The old reader also normalized
    # the excerpt; hashing raw JSON instead is not the saved-read contract.
    expected_revision = "e3fc2f7708123a6db577db01cbbe71c57fcba94241cde4af3978ebf8cf7d9ab1"
    assert loaded["revision"] == documentation_scene_revision(loaded["scene"]) == expected_revision
    assert disk(store) == before
    result = store.repo.apply_command(NUMBER, "sanitized-source-1", "sanitized-plan-1",
        base_revision=loaded["revision"], page_targets=store.page_targets,
        command={"operation": "update_text", "targetType": "page_element", "pageId": PAGE,
                 "targetId": "title", "text": "new"})
    assert result["scene"]["schemaVersion"] == 8
    assert store.path.with_name("documentation-scene.v2.json").read_bytes() == original
    reopened = DocumentationSceneRepository(tmp_path).read(NUMBER, "sanitized-source-1", "sanitized-plan-1")
    assert reopened["scene"] == result["scene"]
    assert reopened["scene"]["commands"][:5] == old["commands"]


def test_legacy_slots_read_and_first_write_preserve_original(tmp_path):
    store = SlotHarness(tmp_path)
    store.path.parent.mkdir()
    original = b' {"schemaVersion":1,"values":{"title":{"value":"old","source":"workspace"}}}\r\n'
    store.path.write_bytes(original)
    before = disk(store)
    assert store.repo.read()["values"]["title"]["value"] == "old"
    assert store.repo.read()["schemaVersion"] == 3
    assert disk(store) == before
    store.commit(request_for(store, {"title": "new"}))
    assert store.path.with_name("slots.v1.json").read_bytes() == original
    assert SlotStore(tmp_path, NUMBER).read()["editRevision"] == 1


def test_stale_matching_preimages_are_accepted(store):
    old = request_for(store, {"title": "Sage"})
    store.commit(request_for(store, {"caption": "human"}))
    receipt = store.commit(old)
    assert (receipt["expectedRevision"], receipt["beforeRevision"], receipt["revision"]) == (0, 1, 2)
    assert store.values() == {"title": "Sage", "caption": "human"}


def test_stale_changed_target_rejected(store):
    old = request_for(store, {"title": "Sage", "caption": "Sage too"})
    store.commit(request_for(store, {"title": "human"}))
    before = disk(store)
    with pytest.raises(DocumentEditError) as error:
        store.commit(old)
    assert error.value.code == "content_hash_mismatch"
    assert disk(store) == before


def test_older_revision_open_conflict_is_rejected(store):
    old = request_for(store, {"title": "Sage"})
    store.commit(request_for(store, {"caption": "human"}))
    state = json.loads(store.path.read_bytes())
    state["conflicts"] = [{"targetId": "slot:title" if isinstance(store, SlotHarness) else "title", "status": "open"}]
    store.path.write_bytes(canonical_bytes(state))
    before = disk(store)
    with pytest.raises(DocumentEditError) as error:
        store.commit(old)
    assert error.value.code == "manual_edit_conflict"
    assert disk(store) == before


def test_invalid_second_operation_commits_nothing(store):
    before = disk(store)
    with pytest.raises((DocumentEditError, SpecificationSlotError)):
        store.commit(request_for(store, {"title": "valid", "caption": "invalid"}), invalid=True)
    assert disk(store) == before


def test_future_revision_rejected(store):
    request = request_for(store, {"title": "future"})
    request["expectedRevision"] = 100
    with pytest.raises(DocumentEditError) as error:
        store.commit(request)
    assert error.value.code == "stale_revision"
    assert not store.path.exists()


def test_retry_after_restart_returns_original_receipt(store):
    request = request_for(store, {"title": "first"})
    receipt = store.commit(request)
    store.commit(request_for(store, {"caption": "later"}))
    before = disk(store)
    assert type(store)(store.root).commit(request) == receipt
    assert disk(store) == before


def test_reused_request_id_rejected(store):
    request = request_for(store, {"title": "first"}, "reused")
    store.commit(request)
    request["values"]["title"] = "second"
    before = disk(store)
    with pytest.raises(DocumentEditError) as error:
        store.commit(request)
    assert error.value.code == "request_id_reused"
    assert disk(store) == before


@pytest.mark.parametrize("revert", [False, True])
def test_evicted_retry_fails_safely_even_after_value_reverted(store, monkeypatch, revert):
    monkeypatch.setattr(contract, "RECEIPT_LIMIT", 2)
    if isinstance(store, SlotHarness):
        monkeypatch.setattr("ai_inspector.specification_sheet.slots.now", lambda: "2026-01-01T00:00:00Z")
        store.repo.set_values([{"slot": "title", "value": "one"}], "chat")
    request = request_for(store, {"title": "first"})
    store.commit(request)
    if revert:
        if isinstance(store, SceneHarness):
            store.undo()
        else:
            store.commit(request_for(store, {"title": "one"}))
    for value in ("third", "fourth"):
        store.commit(request_for(store, {"caption": value}))
    state, _ = store.snapshot()
    assert len(state["receipts"]) == 2
    assert request["requestId"] not in state["receipts"]
    before = disk(store)
    with pytest.raises(DocumentEditError) as error:
        type(store)(store.root).commit(request)
    assert error.value.code == "content_hash_mismatch"
    assert disk(store) == before


def test_two_threads_cannot_overwrite_one_read(store):
    first = request_for(store, {"title": "first"})
    second = request_for(store, {"title": "second"})
    def commit(request):
        try:
            return type(store)(store.root).commit(request)["revision"]
        except DocumentEditError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(commit, [first, second]))
    assert sorted(map(str, result)) == ["1", "content_hash_mismatch"]
    assert store.snapshot()[0]["revision"] == 1


def test_replace_failure_keeps_last_committed_state(store, monkeypatch):
    store.commit(request_for(store, {"title": "committed"}))
    before = disk(store)
    def denied(*_args):
        raise PermissionError("simulated denied replace")
    monkeypatch.setattr("os.replace", denied)
    with pytest.raises((PermissionError, DocumentationSceneError)):
        store.commit(request_for(store, {"title": "not committed"}))
    assert disk(store) == before


def test_scene_batch_undo_redo_is_one_cursor_step(tmp_path):
    store = SceneHarness(tmp_path)
    receipt = store.commit(request_for(store, {"title": "first", "caption": "second"}))
    state, _ = store.snapshot()
    assert receipt["undoable"]
    assert state["historyCursor"] == len(state["commands"]) == 1
    assert state["commands"][0]["operation"] == "batch"
    assert len(state["commands"][0]["commands"]) == 2
    validate_documentation_scene(state["scene"])
    store.undo()
    assert store.values() == {"title": "one", "caption": "two"}
    state, _ = store.snapshot()
    store.repo.move_history(NUMBER, SOURCE, PLAN, base_revision=state["sceneRevision"], direction="redo")
    assert store.values() == {"title": "first", "caption": "second"}
    assert store.snapshot()[0]["revision"] == 3


def test_scene_binding_changed_refuses_batch(tmp_path):
    store = SceneHarness(tmp_path)
    store.commit(request_for(store, {"title": "first"}))
    loaded = store.repo.read(NUMBER, SOURCE, PLAN)
    before = disk(store)
    with pytest.raises(DocumentationSceneBindingError):
        store.repo.apply_batch(NUMBER, "other-source", PLAN, base_revision=loaded["revision"],
            expected_revision=1, request_id="wrong-binding", commands=[{}], page_targets={},
            expected_hashes={"title": "hash"}, current_hashes={"title": "hash"}, hashes_revision=loaded["revision"])
    assert disk(store) == before


def test_slot_compound_failure_and_success_are_one_write(tmp_path, monkeypatch):
    from ai_inspector.specification_sheet import slots
    store = SlotStore(tmp_path, NUMBER)
    real_write, writes = slots._write_json, []
    def record(path, payload):
        writes.append(path)
        real_write(path, payload)
    monkeypatch.setattr(slots, "_write_json", record)
    def change(candidate, invalid=False):
        candidate.set_units("metric")
        candidate.set_values([{"slot": "title", "value": "new"}], "workspace")
        if invalid:
            raise ValueError("after two staged changes")
    with pytest.raises(ValueError):
        store.transaction(lambda candidate: change(candidate, True))
    assert writes == [] and not store.path.exists()
    store.transaction(change)
    assert writes == [store.path]
    assert store.read()["editRevision"] == 1
    assert store.read()["units"] == "metric"


def test_mixed_batch_refused():
    with pytest.raises(DocumentEditError) as error:
        contract.operation_store([{"operation": "replace_text", "targetId": "a"},
                                  {"operation": "set_slot_value", "targetId": "b"}])
    assert error.value.code == "invalid_document_operation"
    assert str(error.value) == "send text and value edits as separate requests"


def test_unknown_schema_never_overwritten(store):
    store.path.parent.mkdir()
    store.path.write_bytes(b'{"schemaVersion":999,"future":"preserve"}')
    before = disk(store)
    with pytest.raises((DocumentEditError, DocumentationSceneError)):
        store.snapshot()
    assert disk(store) == before


def _text_read(tmp_path, text="  exact\n\tspacing  "):
    state, _ = SceneHarness(tmp_path).snapshot()
    document = {"pages": [{"pageId": "page-text", "layoutBlocks": [
        {"blockId": "note", "blockType": "paragraph", "text": text}]}]}
    targets = text_targets(state, document)
    return state, targets, read_targets(state, targets, [{"targetId": "note", "pageId": "page-text"}])


def test_full_read_preserves_whitespace(tmp_path):
    _state, _targets, result = _text_read(tmp_path)
    target = result["targets"][0]
    assert target["text"] == "  exact\n\tspacing  "
    assert not target["isExcerpt"] and target["fullLength"] == len(target["text"])
    assert target["hashVersion"] == 1


def test_old_tool_inputs_use_read_snapshot(tmp_path):
    state, targets, read = _text_read(tmp_path)
    cache = ReadBindings("turn-1")
    arguments = {"edits": [{"pageId": "page-text", "targetId": "note", "text": "replacement"}]}
    with pytest.raises(DocumentEditError) as error:
        cache.bind("work_instructions", arguments)
    assert error.value.code == "document_read_required"
    cache.record("work_instructions", read)
    bound = cache.bind("work_instructions", arguments)
    state["revision"] = 10  # no last-minute host read can update the captured snapshot
    assert bound["expectedRevision"] == 0
    assert bound["operations"][0]["expectedContentHash"] == read["targets"][0]["contentHash"]
    assert bound == cache.bind("work_instructions", arguments)


def test_excerpt_cannot_replace_full_field(tmp_path):
    _state, _targets, read = _text_read(tmp_path)
    read["targets"][0]["isExcerpt"] = True
    cache = ReadBindings("turn-1")
    cache.record("work_instructions", read)
    with pytest.raises(DocumentEditError) as error:
        cache.bind("work_instructions", {"edits": [{"pageId": "page-text", "targetId": "note", "text": "short"}]})
    assert error.value.code == "full_read_required"


def test_oversized_target_reports_size(tmp_path):
    with pytest.raises(DocumentEditError) as error:
        _text_read(tmp_path, "x" * 70000)
    assert error.value.code == "read_result_too_large"
    assert error.value.details["targets"][0]["bytes"] > 65536




def test_target_identity_is_scoped_to_source_and_document(tmp_path):
    state, _, _ = _text_read(tmp_path)
    before = target_id(state, PAGE, "table.r0.c0")
    assert before != target_id({**state, "sourceRevision": "changed"}, PAGE, "table.r0.c0")
    assert before != target_id({**state, "documentId": document_id("operations_maintenance_manual", NUMBER)}, PAGE, "table.r0.c0")
    assert target_id(state, PAGE, "part.fixture.description") == "part.fixture.description"


def test_ui_binding_guard_and_stale_message():
    source = r'''
const assert = require('node:assert/strict');
require('./static/documentation_commands.js');
const api = globalThis.DocumentationCommands;
const old = {revision:'rev-1', scene:{assemblyNumber:'MMLE-50D',sourceRevision:'s',manualPlanRevision:'p'}};
const bound = api.capture(old, {pageId:'p1'}, '/old');
old.revision = 'rev-2';
assert.equal(bound.payload.revision, 'rev-1');
assert.equal(bound.apiBase, '/old');
assert.equal(api.isCurrent(bound, old, '/old'), false);
assert.equal(api.isCurrent(bound, {...old,revision:'rev-1'}, '/new'), false);
assert.equal(api.isCurrent(bound, {...old,revision:'rev-1'}, '/old'), true);
assert.match(api.message(new Error('content_hash_mismatch')), /draft is still visible/);
'''
    result = subprocess.run(["node", "-e", source], cwd=ROOT, capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_evicted_structural_retry_rejected_after_collection_revert(tmp_path, monkeypatch):
    monkeypatch.setattr(contract, "RECEIPT_LIMIT", 2)
    store = SlotStore(tmp_path, NUMBER)
    def collection_hash(state):
        return content_hash(state, "@sheet", {"rows": state["rows"]})
    store.set_rows([])
    initial = store.read()
    payload = {"rows": [{"key": "speed", "label": "Speed"}]}
    expected = {"@sheet": collection_hash(initial)}
    def apply(request_id, rows, observed, hashes):
        return store.transaction(lambda candidate: candidate.set_rows(rows), expected_revision=observed,
            request_id=request_id, expected_hashes=hashes, current_hashes={"@sheet": collection_hash(store.read())},
            payload={"rows": rows})
    apply("first", payload["rows"], initial["editRevision"], expected)
    for index, rows in enumerate(([{"key": "weight", "label": "Weight"}], payload["rows"], [])):
        state = store.read()
        apply(str(index), rows, state["editRevision"], {"@sheet": collection_hash(state)})
    before = store.path.read_bytes()
    with pytest.raises(DocumentEditError) as error:
        apply("first", payload["rows"], initial["editRevision"], expected)
    assert error.value.code == "content_hash_mismatch"
    assert store.path.read_bytes() == before


def test_crash_after_commit_before_response_keeps_receipt(tmp_path):
    store = SceneHarness(tmp_path)
    request = request_for(store, {"title": "committed before response"})
    args = {"base_revision": request["sceneRevision"], "expected_revision": 0,
            "request_id": request["requestId"], "commands": [{"operation": "update_text", "targetType": "page_element",
            "pageId": PAGE, "targetId": "title", "text": request["values"]["title"]}],
            "page_targets": store.page_targets, "expected_hashes": request["hashes"], "current_hashes": request["hashes"],
            "hashes_revision": request["sceneRevision"], "payload": request}
    request_file = tmp_path / "request.json"
    request_file.write_bytes(canonical_bytes(args))
    script = '''import json, os, sys
from pathlib import Path
from ai_inspector.parts_manual.documentation import DocumentationSceneRepository
repo = DocumentationSceneRepository(sys.argv[1], "work_instructions")
repo.apply_batch("MMLE-50D", "source-1", "plan-1", **json.loads(Path(sys.argv[2]).read_bytes()))
os._exit(19)
'''
    import sys
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(request_file)], cwd=ROOT,
        capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=30)
    assert result.returncode == 19, result.stderr.decode(errors="replace")
    before = disk(store)
    receipt = SceneHarness(tmp_path).commit(request)
    assert receipt == store.snapshot()[0]["receipts"][request["requestId"]]["receipt"]
    assert disk(store) == before


@pytest.mark.parametrize("count", [2, 12])
def test_full_size_batch_is_one_history_entry(tmp_path, count):
    store = SceneHarness(tmp_path)
    keys = [f"field-{index}" for index in range(count)]
    store.document["pages"][0]["layoutBlocks"] = [
        {"blockId": key, "blockType": "paragraph", "text": "before"} for key in keys]
    store.page_targets[PAGE]["page_element"] = keys
    result = store.commit(request_for(store, {key: "after" for key in keys}))
    scene = store.snapshot()[0]["scene"]
    assert scene["historyCursor"] == len(scene["commands"]) == 1
    assert len(scene["commands"][0]["commands"]) == count
    assert result["revision"] == 1 and len(result["changedIds"]) == count
    store.undo()
    assert store.snapshot()[0]["scene"]["pages"] == {}


def test_noop_receipt_has_no_content_revision_or_history_change(tmp_path):
    store = SceneHarness(tmp_path)
    state, hashes = store.snapshot()
    args = dict(base_revision=state["sceneRevision"], expected_revision=0, request_id="noop",
        commands=[{"operation": "update_text", "pageId": PAGE, "targetType": "page_element",
                   "targetId": "title", "text": "one", "_noChange": True}],
        page_targets=store.page_targets, expected_hashes={"title": hashes["title"]},
        current_hashes=hashes, hashes_revision=state["sceneRevision"])
    result = store.repo.apply_batch(NUMBER, SOURCE, PLAN, **args)
    assert result["scene"]["editRevision"] == 0 and result["scene"]["commands"] == []
    assert not result["receipt"]["undoable"] and result["receipt"]["changedIds"] == []
    before = disk(store)
    assert store.repo.apply_batch(NUMBER, SOURCE, PLAN, **args)["receipt"] == result["receipt"]
    assert disk(store) == before
    args["commands"][0]["text"] = "different"
    with pytest.raises(DocumentEditError) as error:
        store.repo.apply_batch(NUMBER, SOURCE, PLAN, **args)
    assert error.value.code == "request_id_reused"


def test_a_later_excerpt_supersedes_an_earlier_full_read(tmp_path):
    state, targets, read = _text_read(tmp_path)
    cache = ReadBindings("turn")
    cache.record("work_instructions", read)
    latest = deepcopy(read)
    latest["targets"][0]["isExcerpt"] = True
    cache.record("work_instructions", latest)
    with pytest.raises(DocumentEditError) as error:
        cache.bind("work_instructions", {"edits": [{"pageId": PAGE, "targetId": "note", "text": "new"}]})
    assert error.value.code == "full_read_required"


def test_slot_apply_batch_api_returns_persisted_receipt(tmp_path):
    harness = SlotHarness(tmp_path)
    state, hashes = harness.snapshot()
    arguments = dict(expected_revision=state["revision"], request_id="slot-batch",
        expected_hashes={"slot:" + key: value for key, value in hashes.items()},
        current_hashes={"slot:" + key: value for key, value in hashes.items()})
    items = [{"slot": "title", "value": "first"}, {"slot": "caption", "value": "second"}]
    result = harness.repo.apply_batch(items, "chat", **arguments)
    # P1b-3's slot undo journal makes a slot batch one undoable change (P1a had no slot undo).
    assert result["receipt"]["revision"] == 1 and result["receipt"]["undoable"]
    assert result["changed"] == ["slot:caption", "slot:title"]
    before = disk(harness)
    assert SlotStore(tmp_path, NUMBER).apply_batch(items, "chat", **arguments) == result
    assert disk(harness) == before


def test_locked_authored_text_is_readable_without_edit_capability(tmp_path):
    state, _, _ = _text_read(tmp_path)
    targets = text_targets(state, {"pages": [{"pageId": PAGE, "documentationObjects": {
        "object-note": {"type": "text", "locked": True, "content": "  Keep exact\ntext  "}}}]})
    full = read_targets(state, targets, [{"targetId": "object-note", "pageId": PAGE}])["targets"][0]
    assert full["text"] == "  Keep exact\ntext  " and full["capabilities"] == []
    assert targets[full["targetId"]]["operation"] == "read_only"
