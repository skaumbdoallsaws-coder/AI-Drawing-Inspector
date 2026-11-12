"""P2a-1 server contract. All persistence uses temporary stores; no browser needed."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import uuid

import pytest

from ai_inspector.documentation import rich_text as rich
from ai_inspector.documentation.commands import DocumentEditError, canonical_bytes, content_hash, document_id, operation_store
from ai_inspector.documentation.identity import compile_identities
from ai_inspector.documentation.provenance import project_document, prepare_text_command, check_export
from ai_inspector.documentation.targets import ReadBindings, hash_values, owner_state, read_targets, text_targets
from ai_inspector.parts_manual.documentation import DocumentationSceneRepository, documentation_scene_revision
from tests.test_documentation_refresh import mmle_client, MMLE_ROUTES

KIND, NUMBER, PAGE, OBJECT = "operations_and_maintenance_manual", "RICH", "page-note", "document-object-note"
ROOT = Path(__file__).resolve().parents[1]


def envelope(text="A note", *, start=1, marks=None):
    counter = iter(range(start, start + rich.MAX_NODES + 10))
    value = rich.from_plain(text, id_factory=lambda: "rt-" + str(uuid.UUID(int=next(counter))))
    if marks:
        value["doc"]["content"][0]["content"][0]["marks"] = marks
    return value


def object_value(key=OBJECT, text="Original\r\n  note\t"):
    return {"objectId": key, "type": "text", "name": "Authored note", "source": "user",
            "content": text, "frame": {"x": 0.1, "y": 0.1, "width": 0.4, "height": 0.2}}


class RichScene:
    def __init__(self, root):
        self.repo = DocumentationSceneRepository(root, KIND)
        self.path = root / NUMBER.lower() / "documentation-scene.json"
        self.base = compile_identities({"schemaVersion": 3, "documentType": KIND,
            "product": {"assemblyNumber": NUMBER}, "sourceRevision": "source-a", "manualPlanRevision": "plan-a",
            "pages": [{"pageId": PAGE, "pageNumber": 1, "title": "Note", "layoutBlocks": [
                {"blockId": "generated-note", "blockType": "paragraph", "text": "Generated plain text"}]}]})
        self.add()

    def load(self):
        return self.repo.read(NUMBER, self.base["sourceRevision"], self.base["manualPlanRevision"], identity_document=self.base)

    def snapshot(self):
        loaded = self.load()
        scene = loaded["scene"]
        document = deepcopy(self.base)
        for page in document["pages"]:
            composition = deepcopy(scene["pages"].get(page["pageId"], {}))
            page["documentationComposition"] = composition
            page["documentationObjects"] = deepcopy(composition.get("documentObjects", {}))
        document = project_document(document, scene)
        state = {**scene, "scene": scene, "documentId": document_id(KIND, NUMBER),
                 "revision": scene["editRevision"], "sceneRevision": loaded["revision"], "aliasRevision": self.base["aliasRevision"]}
        targets = text_targets(state, document)
        return state, document, targets

    def field(self, key=OBJECT):
        state, _, targets = self.snapshot()
        return read_targets(state, targets, [{"targetId": key}])["targets"][0]

    def value(self, key=OBJECT):
        return self.load()["scene"]["pages"][PAGE]["documentObjects"][key]["content"]

    def command(self, command):
        state, document, _ = self.snapshot()
        objects = list(state["scene"]["pages"].get(PAGE, {}).get("documentObjects", {}))
        return self.repo.apply_command(NUMBER, self.base["sourceRevision"], self.base["manualPlanRevision"],
            base_revision=state["sceneRevision"], identity_document=self.base,
            page_targets={PAGE: {"document_object": objects, "page_element": ["generated-note"]}},
            command=prepare_text_command(document, {"pageId": PAGE, "targetType": "document_object", "targetId": OBJECT, **command}))

    def add(self, key=OBJECT):
        return self.command({"operation": "add_object", "targetId": key, "documentObject": object_value(key)})

    def edit(self, value=None, key=OBJECT):
        return self.command({"operation": "replace_rich_text", "targetId": key, "richText": value or envelope()})

    def batch(self, value, *, field=None, request_id="rich-batch", plain=False, whole=False):
        field = field or self.field()
        state, document, targets = self.snapshot()
        values = hash_values(targets)
        command = {"operation": "update_text" if plain else "replace_rich_text", "pageId": PAGE,
                   "targetType": "document_object", "targetId": OBJECT, "text" if plain else "richText": value,
                   "wholeFieldReplacement": whole}
        return self.repo.apply_batch(NUMBER, self.base["sourceRevision"], self.base["manualPlanRevision"],
            base_revision=state["sceneRevision"], expected_revision=field["binding"]["revision"], request_id=request_id,
            commands=[prepare_text_command(document, command)], page_targets={PAGE: {"document_object": [OBJECT]}},
            expected_hashes={OBJECT: field["contentHash"]}, current_hashes={key: content_hash(owner_state(state, targets[key]), key, value)
                for key, value in values.items()}, hashes_revision=state["sceneRevision"], identity_document=self.base)


@pytest.fixture
def scene(tmp_path, monkeypatch):
    monkeypatch.setenv(rich.FEATURE_FLAG, "on")
    return RichScene(tmp_path)


@pytest.mark.parametrize("text", ["", "\n", "\n\n", "a\nb\n", "\r\n", "a\r\nb\r\n", "\r", "\t a\t",
    " leading", "trailing ", " a   b  ", "\U0001f642\U0001f680", "e\u0301 \u212b\u0308"])
def test_plain_text_lossless_migration(text):
    value = rich.from_plain(text)
    assert rich.plain_text(value) == text
    assert rich.validate(value) == value


@pytest.mark.parametrize("node", [
    {"type": "image", "attrs": {"src": "https://example.com/a.png"}},
    {"type": "codeBlock"}, {"type": "blockquote"}, {"type": "table"},
    {"type": "paragraph", "attrs": {"id": "rt-" + str(uuid.UUID(int=1)), "onclick": "alert(1)"}},
    {"type": "paragraph", "content": []}, {"type": []},
])
def test_unsupported_nodes_rejected(node):
    value = envelope()
    value["doc"]["content"] = [node]
    with pytest.raises(DocumentEditError):
        rich.validate(value)


@pytest.mark.parametrize("url,allowed", [("https://example.com/path?q=1#part", True), ("http://example.com", True),
    ("javascript:alert(1)", False), ("data:text/html,x", False), ("file:///C:/secret", False),
    ("/relative", False), ("../relative", False), ("//example.com", False), ("C:/secret", False),
    ("\\\\host\\share", False), ("mailto:person@example.com", False), ("https://example.com\\x", False),
    ("https://example.com/\nfile", False), ("https://name:pass@example.com", False)])
def test_link_scheme_allowlist(url, allowed):
    value = envelope(marks=[{"type": "link", "attrs": {"href": url, "target": "caller", "rel": "opener", "class": "caller"}}])
    if allowed:
        attrs = rich.validate(value)["doc"]["content"][0]["content"][0]["marks"][0]["attrs"]
        assert attrs == {"href": url, **rich.LINK_ATTRIBUTES}
    else:
        with pytest.raises(DocumentEditError) as caught:
            rich.validate(value)
        assert caught.value.code == "unsafe_rich_text_link"


@pytest.mark.parametrize("mark", [{"type": "strike"}, {"type": "textStyle", "attrs": {"color": "red"}},
    {"type": "textStyle", "attrs": {"color": "#123456", "backgroundColor": "#ffffff"}},
    {"type": "link", "attrs": {"href": "https://example.com", "onclick": "bad"}}, {"type": []}])
def test_unsupported_marks_and_attributes(mark):
    with pytest.raises(DocumentEditError):
        rich.validate(envelope(marks=[mark]))


def test_node_id_format_duplicates_and_document_ownership(scene):
    value = envelope()
    value["doc"]["content"][0]["attrs"]["id"] = "gen-paragraph-compiler-owned"
    with pytest.raises(DocumentEditError) as caught:
        scene.edit(value)
    assert caught.value.code == "invalid_rich_text_node_id"
    value = envelope()
    value["doc"]["content"].append(deepcopy(value["doc"]["content"][0]))
    with pytest.raises(DocumentEditError) as caught:
        scene.edit(value)
    assert caught.value.code == "rich_text_node_id_collision"
    scene.edit()
    scene.add("document-object-other")
    before = scene.path.read_bytes()
    with pytest.raises(DocumentEditError) as caught:
        scene.edit(envelope(), "document-object-other")
    assert caught.value.code == "rich_text_node_id_collision" and scene.path.read_bytes() == before
    scene.edit(envelope(start=100), "document-object-other")


def test_size_and_depth_bounds():
    with pytest.raises(DocumentEditError) as caught:
        rich.from_plain("x" * rich.MAX_BYTES)
    assert caught.value.code == "rich_text_too_large"
    with pytest.raises(DocumentEditError):
        rich.from_plain("\n" * rich.MAX_NODES)
    value = envelope()
    counter = iter(range(100, 1000))
    def node(kind, children, **attrs):
        return {"type": kind, "attrs": {"id": "rt-" + str(uuid.UUID(int=next(counter))), **attrs}, "content": children}
    nested = node("bulletList", [node("listItem", [node("paragraph", [])])])
    value["schemaVersion"] = 2
    for _ in range(rich.MAX_LIST_DEPTH):
        nested = node("bulletList", [node("listItem", [node("paragraph", []), nested])])
    value["doc"]["content"] = [nested]
    with pytest.raises(DocumentEditError) as caught:
        rich.validate(value)
    assert caught.value.code == "rich_text_too_large"
    for level in (0, 4, True):
        value["doc"]["content"] = [node("heading", [], level=level)]
        with pytest.raises(DocumentEditError):
            rich.validate(value)
    for start in (0, 10000, True):
        value["doc"]["content"] = [node("orderedList", [node("listItem", [node("paragraph", [])])], start=start)]
        with pytest.raises(DocumentEditError):
            rich.validate(value)


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5])
def test_old_scene_no_rewrite(tmp_path, version):
    scene = RichScene(tmp_path)
    original = json.loads(scene.path.read_bytes())
    original["schemaVersion"] = version
    raw = ("  " + json.dumps(original, indent=2) + "\n").encode("ascii")
    scene.path.write_bytes(raw)
    loaded = scene.load()
    assert loaded["scene"]["schemaVersion"] == 8
    assert isinstance(scene.value(), str) and scene.path.read_bytes() == raw
    assert not scene.path.with_name("documentation-scene.v4.json").exists()
    scene.command({"operation": "update_text", "text": "A plain edit"})
    assert scene.path.with_name(f"documentation-scene.v{max(2, version)}.json").read_bytes() == raw


def test_rich_hash_and_plain_projection(scene):
    before = scene.field()
    assert before["richText"] is None and not before["isRichText"]
    scene.edit(envelope("Same words", marks=[{"type": "bold"}]))
    state, document, targets = scene.snapshot()
    first = scene.field()
    assert first["text"] == "Same words" and first["richText"] == scene.value() and first["isRichText"]
    assert first["wholeFieldReplacementRequired"] and first["plainEditConsequence"]
    assert document["pages"][0]["documentationObjects"][OBJECT]["content"] == "Same words"
    assert first["contentHash"] != before["contentHash"]
    # Hold all version counters fixed to prove that marks themselves are hashed.
    changed = deepcopy(targets)
    changed[OBJECT]["attributes"]["content"]["doc"]["content"][0]["content"][0]["marks"] = [{"type": "italic"}]
    assert content_hash(state, OBJECT, hash_values(targets)[OBJECT]) != content_hash(state, OBJECT, hash_values(changed)[OBJECT])
    assert len(canonical_bytes(read_targets(state, targets, [{"targetId": OBJECT}]))) < 65536


def test_largest_field_read_has_headroom(scene):
    value = envelope("x" * (rich.MAX_BYTES - 256))
    scene.edit(value)
    state, _, targets = scene.snapshot()
    result = read_targets(state, targets, [{"targetId": OBJECT}])
    assert len(canonical_bytes({"ok": True, "data": result})) < 56 * 1024
    assert result["targets"][0]["text"] == rich.plain_text(value)


def test_plain_hash_input_unchanged_and_flag_independent(scene, monkeypatch):
    state, _, targets = scene.snapshot()
    before = hash_values(targets)
    legacy = deepcopy(targets)
    for value in legacy.values():
        value.pop("richField", None)
    assert hash_values(legacy) == before
    monkeypatch.setenv(rich.FEATURE_FLAG, "off")
    assert scene.field()["contentHash"] == content_hash(state, OBJECT, before[OBJECT])


def test_generated_headings_and_locked_objects_never_accept_rich(scene):
    scene.base["pages"][0]["layoutBlocks"][0]["blockType"] = "heading"
    with pytest.raises(DocumentEditError) as caught:
        scene.command({"operation": "replace_rich_text", "targetType": "page_element",
                       "targetId": "generated-note", "richText": envelope()})
    assert caught.value.code == "read_only_derived_field"
    key = "document-object-locked"
    scene.command({"operation": "add_object", "targetId": key,
                   "documentObject": {**object_value(key), "locked": True}})
    assert scene.field(key)["capabilities"] == []
    with pytest.raises(DocumentEditError) as caught:
        scene.edit(envelope(start=100), key)
    assert caught.value.code == "read_only_derived_field"


@pytest.mark.parametrize("setting", [None, "", "0", "false", "off", "unknown"])
def test_flag_fail_closed(scene, monkeypatch, setting):
    if setting is None:
        monkeypatch.delenv(rich.FEATURE_FLAG)
    else:
        monkeypatch.setenv(rich.FEATURE_FLAG, setting)
    assert not rich.enabled() and "replace_rich_text" not in scene.field()["capabilities"]
    original = scene.path.read_bytes()
    with pytest.raises(DocumentEditError) as caught:
        scene.edit()
    assert caught.value.code == "documentation_rich_text_disabled" and scene.path.read_bytes() == original
    scene.command({"operation": "update_text", "text": "Plain stays supported"})
    assert scene.value() == "Plain stays supported"


def test_flag_on_and_disabled_reopen_undo(scene, monkeypatch):
    assert "replace_rich_text" in scene.field()["capabilities"]
    before = scene.value()
    scene.edit()
    monkeypatch.setenv(rich.FEATURE_FLAG, "off")
    raw = scene.path.read_bytes()
    assert scene.field()["isRichText"] and scene.path.read_bytes() == raw
    scene.repo.move_history(NUMBER, "source-a", "plan-a", base_revision=scene.load()["revision"], direction="undo", identity_document=scene.base)
    assert scene.value() == before


def test_plain_write_requires_explicit_whole_field_replacement(scene):
    stored = envelope(marks=[{"type": "bold"}])
    scene.edit(stored)
    original = scene.path.read_bytes()
    for callback in (lambda: scene.command({"operation": "update_text", "text": "replacement"}),
                     lambda: scene.batch("replacement", plain=True)):
        with pytest.raises(DocumentEditError) as caught:
            callback()
        assert caught.value.code == "rich_text_replacement_required" and scene.path.read_bytes() == original
    result = scene.batch("replacement\n with spaces ", plain=True, whole=True)
    assert scene.value() == "replacement\n with spaces " and isinstance(scene.value(), str)
    assert result["receipt"]["validation"] == [{"code": "rich_text_replaced_with_plain", "targetIds": [OBJECT]}]
    scene.repo.undo_change(NUMBER, "source-a", "plan-a", change_id=result["receipt"]["changeId"],
        expected_revision=result["scene"]["editRevision"], request_id="undo-plain", identity_document=scene.base)
    assert scene.value() == stored


def test_named_and_document_undo_redo_round_trip(scene):
    plain = scene.value()
    value = envelope(marks=[{"type": "underline"}])
    committed = scene.batch(value)
    assert committed["receipt"]["undoable"]
    scene.repo.move_history(NUMBER, "source-a", "plan-a", base_revision=scene.load()["revision"], direction="undo", identity_document=scene.base)
    assert scene.value() == plain
    scene.repo.move_history(NUMBER, "source-a", "plan-a", base_revision=scene.load()["revision"], direction="redo", identity_document=scene.base)
    assert scene.value() == value
    latest = scene.load()
    change = latest["changes"][-1]["changeId"]
    undone = scene.repo.undo_change(NUMBER, "source-a", "plan-a", change_id=change,
        expected_revision=latest["scene"]["editRevision"], request_id="named-undo", identity_document=scene.base)
    assert scene.value() == plain
    scene.repo.undo_change(NUMBER, "source-a", "plan-a", change_id=undone["receipt"]["changeId"],
        expected_revision=undone["scene"]["editRevision"], request_id="named-redo", identity_document=scene.base)
    assert scene.value() == value


def test_read_bound_stale_hash_and_batch_atomicity(scene):
    observed = scene.field()
    scene.edit(envelope("Concurrent human"))
    raw = scene.path.read_bytes()
    with pytest.raises(DocumentEditError) as caught:
        scene.batch(envelope("Agent draft"), field=observed)
    assert caught.value.code == "content_hash_mismatch" and scene.path.read_bytes() == raw


def test_batch_validates_every_rich_field_before_writing(scene):
    scene.add("document-object-other")
    state, document, targets = scene.snapshot()
    keys = [OBJECT, "document-object-other"]
    hashes = {key: read_targets(state, targets, [{"targetId": key}])["targets"][0]["contentHash"] for key in keys}
    # The second field tries to paste IDs that the first command just staged.
    commands = [prepare_text_command(document, {"operation": "replace_rich_text", "pageId": PAGE,
        "targetType": "document_object", "targetId": key, "richText": envelope()}) for key in keys]
    raw = scene.path.read_bytes()
    with pytest.raises(DocumentEditError) as caught:
        scene.repo.apply_batch(NUMBER, "source-a", "plan-a", base_revision=state["sceneRevision"],
            expected_revision=state["revision"], request_id="atomic-rich", commands=commands,
            page_targets={PAGE: {"document_object": keys}}, expected_hashes=hashes, current_hashes=hashes,
            hashes_revision=state["sceneRevision"], identity_document=scene.base)
    assert caught.value.code == "rich_text_node_id_collision" and scene.path.read_bytes() == raw


def test_undo_cannot_reintroduce_another_fields_node_ids(scene):
    scene.edit()
    cleared = scene.command({"operation": "update_text", "text": "plain", "wholeFieldReplacement": True})
    scene.add("document-object-other")
    scene.edit(envelope(), "document-object-other")
    raw = scene.path.read_bytes()
    with pytest.raises(DocumentEditError) as caught:
        scene.repo.undo_change(NUMBER, "source-a", "plan-a", change_id=cleared["command"]["commandId"],
            expected_revision=scene.load()["scene"]["editRevision"], request_id="collision-undo", identity_document=scene.base)
    assert caught.value.code == "rich_text_node_id_collision" and scene.path.read_bytes() == raw


def test_invalid_stored_envelope_is_field_read_only(scene):
    scene.edit()
    stored = json.loads(scene.path.read_bytes())
    stored["commands"][-1]["richText"]["doc"]["content"][0]["type"] = "image"
    raw = json.dumps(stored, ensure_ascii=True).encode("ascii")
    scene.path.write_bytes(raw)
    field = scene.field()
    assert field["richTextError"] == "invalid_rich_text" and field["capabilities"] == []
    assert field["text"] == "" and field["richText"] is None and scene.path.read_bytes() == raw
    with pytest.raises(DocumentEditError):
        scene.edit()
    scene.add("document-object-unrelated")  # Corruption of one field does not disable the document.


def test_corrupt_unicode_envelope_does_not_break_document_read(scene):
    scene.edit()
    stored = json.loads(scene.path.read_bytes())
    stored["commands"][-1]["richText"]["doc"]["content"][0]["content"][0]["text"] = "\ud800"
    raw = json.dumps(stored, ensure_ascii=True).encode("ascii")
    scene.path.write_bytes(raw)
    assert scene.field()["richTextError"] == "invalid_rich_text"
    assert scene.path.read_bytes() == raw


def test_rich_refresh_reset_copy_and_orphan_payload(scene):
    value = envelope("Retain exactly", marks=[{"type": "italic"}])
    scene.edit(value)
    newer = deepcopy(scene.base)
    newer["sourceRevision"] = "source-b"
    newer = compile_identities(newer)
    scene.base = newer
    refreshed = scene.repo.refresh(NUMBER, "source-b", "plan-a", base_revision=scene.load()["revision"], identity_document=newer)
    scene.base = newer
    assert scene.value() == value and OBJECT not in refreshed["scene"].get("generatedBaseline", {})
    preview = scene.repo.reset_preview(NUMBER, "source-b", "plan-a", identity_document=newer)
    raw = scene.path.read_bytes()
    reset = scene.repo.rebaseline(NUMBER, "source-b", "plan-a", base_revision=preview["expectedRevision"],
        preview_hash=preview["previewHash"], user_authorized=True, identity_document=newer)
    assert scene.path.with_name("sr-" + reset["recoveryId"] + ".json").read_bytes() == raw
    scene.path.write_bytes(raw)
    deleted = deepcopy(newer)
    deleted.update(sourceRevision="source-c", pages=[])
    deleted = compile_identities(deleted)
    scene.base = deleted
    orphaned = scene.repo.refresh(NUMBER, "source-c", "plan-a", base_revision=scene.load()["revision"], identity_document=deleted)
    orphan = next(item for item in orphaned["orphans"] if item["targetId"] == OBJECT)
    assert orphan["C"]["payload"]["content"] == value and not orphaned["scene"]["pages"]


def test_open_conflict_refuses_rich_write(scene):
    scene.repo.conflict_reader = lambda number: {"conflicts": [{"conflictId": "conflict-test", "targetId": OBJECT, "status": "open"}]}
    raw = scene.path.read_bytes()
    with pytest.raises(DocumentEditError) as caught:
        scene.edit()
    assert caught.value.code == "manual_edit_conflict" and scene.path.read_bytes() == raw


def test_spec_scene_targets_use_scene_owner_revision(scene):
    state, document, _ = scene.snapshot()
    document.update(documentType="product_specification_sheet", slots={"title": {"value": "Sheet title"}})
    state.update(revision=91, editEpoch=12, fieldVersions={"slot:title": 9})
    targets = text_targets(state, document)
    assert set(targets) == {OBJECT, "slot:title"}  # Generated page prose stays excluded.
    result = read_targets(state, targets, [{"targetId": OBJECT}, {"targetId": "slot:title"}])
    authored, slot = result["targets"]
    assert authored["owner"] == "scene" and authored["binding"]["revision"] == state["scene"]["editRevision"]
    assert slot["owner"] == "slots" and slot["binding"]["revision"] == 91
    assert "replace_rich_text" in authored["capabilities"] and slot["capabilities"] == ["set_slot_value"]
    bindings = ReadBindings("spec-turn")
    bindings.record("product_specification_sheet", result)
    observed = bindings.bind("product_specification_sheet", {"edits": [{"pageId": PAGE, "targetId": OBJECT, "text": "new"}]})
    assert observed["expectedRevision"] == authored["revision"] and observed["owner"] == "scene"
    with pytest.raises(DocumentEditError):
        operation_store([{"operation": "replace_rich_text", "targetId": OBJECT}, {"operation": "set_slot_value", "targetId": "slot:title"}])


@pytest.mark.parametrize("kind,route", MMLE_ROUTES)
def test_ui_route_and_sage_share_storage_and_read_contract(mmle_client, monkeypatch, kind, route):
    import server
    monkeypatch.setenv(rich.FEATURE_FLAG, "on")
    base = f"/api/{route}/MMLE-50D/documentation-scene"
    response = mmle_client.get(base)
    assert response.status_code == 200, response.text
    initial = response.json()
    page = initial["document"]["pages"][0]["pageId"]

    def command(payload, **operation):
        document = payload["document"]
        return mmle_client.post(base + "/commands", json={"baseRevision": payload["revision"],
            "sourceRevision": document["sourceRevision"], "manualPlanRevision": document["manualPlanRevision"],
            "pageId": page, "targetType": "document_object", "targetId": OBJECT, **operation})

    created = command(initial, operation="add_object", documentObject=object_value())
    assert created.status_code == 200, created.text
    opened = mmle_client.get(base).json()
    field = next(item for item in opened["richTextFields"] if item["targetId"] == OBJECT)
    assert opened["documentationRichText"] and field["owner"] == "scene"
    assert field["binding"]["revision"] == opened["scene"]["editRevision"]
    if kind == "product_specification_sheet":
        assert field["binding"]["revision"] != opened["slotBinding"]["revision"]
        assert OBJECT not in opened["slotBinding"]["hashes"]
    value = envelope("UI and Sage agree", marks=[{"type": "bold"}, {"type": "textStyle", "attrs": {"color": "#aAbBcC"}}])
    edited = command(opened, operation="replace_rich_text", richText=value, expectedContentHash=field["contentHash"])
    assert edited.status_code == 200, edited.text
    ui_value = edited.json()["scene"]["pages"][page]["documentObjects"][OBJECT]["content"]
    assert ui_value == rich.validate(value)
    plain_refused = command(edited.json(), operation="update_text", text="would flatten")
    assert plain_refused.json()["error"] == "rich_text_replacement_required", plain_refused.text
    # A current scene revision cannot authorize an old rich field hash.
    stale = command(edited.json(), operation="replace_rich_text", richText=value, expectedContentHash=field["contentHash"])
    assert stale.json()["error"] == "content_hash_mismatch", stale.text
    payload = edited.json()
    history = {"baseRevision": payload["revision"], "sourceRevision": payload["document"]["sourceRevision"],
               "manualPlanRevision": payload["document"]["manualPlanRevision"]}
    undone = mmle_client.post(base + "/undo", json=history)
    assert undone.status_code == 200, undone.text
    assert undone.json()["scene"]["pages"][page]["documentObjects"][OBJECT]["content"] == object_value()["content"]
    host = server._DocumentationAgentHost()
    snapshot = host.document_snapshot("MMLE-50D", kind)
    full = read_targets(snapshot["state"], snapshot["targets"], [{"targetId": OBJECT}])
    bindings = ReadBindings("same-rich-write")
    bindings.record(kind, full)
    observed = bindings.bind_operations(kind, {"documentId": full["documentId"],
        "expectedRevision": full["targets"][0]["binding"]["revision"], "requestId": "sage-rich",
        "operations": [{"operation": "replace_rich_text", "targetId": OBJECT,
                        "expectedContentHash": full["targets"][0]["contentHash"], "richText": value}]})
    result = host.apply_document_edits("MMLE-50D", kind, observed)
    reopened = mmle_client.get(base).json()
    assert reopened["scene"]["pages"][page]["documentObjects"][OBJECT]["content"] == ui_value
    assert host.apply_document_edits("MMLE-50D", kind, observed)["receipt"] == result["receipt"]
    current = next(item for item in reopened["richTextFields"] if item["targetId"] == OBJECT)
    assert current["text"] == "UI and Sage agree" and current["provenance"]["origin"] == "manual"
    assert current["provenance"]["evidenceStatus"] == "unbound" and not current["provenance"]["activeClaimIds"]
    monkeypatch.setenv(rich.FEATURE_FLAG, "off")
    disabled = command(reopened, operation="replace_rich_text", richText=value, expectedContentHash=current["contentHash"])
    assert disabled.json()["error"] == "documentation_rich_text_disabled", disabled.text
    with pytest.raises(DocumentEditError) as caught:
        bindings.bind_operations(kind, {"documentId": full["documentId"], "expectedRevision": 0, "requestId": "off",
            "operations": [{"operation": "replace_rich_text", "targetId": OBJECT,
                            "expectedContentHash": full["targets"][0]["contentHash"], "richText": value}]})
    assert caught.value.code == "documentation_rich_text_disabled"
    if kind == KIND:
        # Stored corruption must not turn an otherwise readable document into
        # an HTTP 500, including a code unit JSON can escape but UTF-8 cannot.
        path = host._edit_repository(kind).root / "mmle-50d" / "documentation-scene.json"
        stored = json.loads(path.read_bytes())
        stored["commands"][-1]["commands"][0]["richText"]["doc"]["content"][0]["content"][0]["text"] = "\ud800"
        raw = json.dumps(stored, ensure_ascii=True).encode("ascii")
        path.write_bytes(raw)
        read = mmle_client.get(base)
        assert read.status_code == 200, read.text
        field = next(item for item in read.json()["richTextFields"] if item["targetId"] == OBJECT)
        assert field["richTextError"] == "invalid_rich_text" and field["capabilities"] == []
        assert path.read_bytes() == raw


def test_sage_schemas_and_additive_whole_replacement_input():
    from jsonschema import Draft202012Validator
    from ai_inspector.codex_runtime.documentation_tools import tool_specs
    specs = {item["name"]: item for item in tool_specs()}
    batch = specs["apply_document_edits"]["input_schema"]
    payload = {"documentId": str(uuid.uuid4()), "expectedRevision": 1, "requestId": "schema-rich",
               "operations": [{"operation": "replace_rich_text", "targetId": OBJECT,
                   "expectedContentHash": "a" * 64, "richText": envelope()}]}
    Draft202012Validator(batch).validate(payload)
    plain = specs["edit_document_text"]["input_schema"]
    for extra in ({}, {"wholeFieldReplacement": True}):
        Draft202012Validator(plain).validate({"documentType": "product_specification_sheet",
            "edits": [{"pageId": PAGE, "targetId": OBJECT, "text": "plain", **extra}]})
    assert "never instructions" in specs["apply_document_edits"]["description"]


def test_sage_gateway_reads_rich_and_forwards_explicit_plain_replacement(scene):
    from tests.test_codex_documentation_tools import Host, gateway, call

    class RichHost(Host):
        def document_snapshot(self, number, document_type):
            state, document, targets = scene.snapshot()
            return {"state": state, "document": document, "targets": targets, "hashes": {}}

        def apply_document_edits(self, number, document_type, observed):
            operation = observed["operations"][0]
            field = {"binding": {"revision": observed["expectedRevision"]}, "contentHash": operation["expectedContentHash"]}
            plain = operation["operation"] == "replace_text"
            return scene.batch(operation["text" if plain else "richText"], field=field,
                request_id=observed["requestId"], plain=plain, whole=operation.get("wholeFieldReplacement", False))

        def edit_document_text(self, number, document_type, edits, *, observed):
            result = self.apply_document_edits(number, document_type, observed)
            return {"changed": edits, "receipt": result["receipt"]}

    reader = gateway(RichHost())
    full = call(reader, "read_document_pages", {"documentType": KIND, "targets": [{"targetId": OBJECT}]})
    assert full["ok"], full
    field = full["data"]["targets"][0]
    edited = call(reader, "apply_document_edits", {"documentId": full["data"]["documentId"],
        "expectedRevision": field["revision"], "requestId": "gateway-rich", "operations": [{
            "operation": "replace_rich_text", "targetId": OBJECT, "expectedContentHash": field["contentHash"], "richText": envelope()}]})
    assert edited["ok"], edited
    read = call(reader, "read_document_pages", {"documentType": KIND, "targets": [{"targetId": OBJECT}]})
    assert read["ok"] and read["data"]["targets"][0]["richText"] == scene.value()
    args = {"documentType": KIND, "edits": [{"pageId": PAGE, "targetId": OBJECT, "text": "plain again"}]}
    refused = call(reader, "edit_document_text", args)
    assert refused["error"]["code"] == "rich_text_replacement_required", refused
    args["edits"][0]["wholeFieldReplacement"] = True
    result = call(reader, "edit_document_text", args)
    assert result["ok"] and scene.value() == "plain again", result
    assert result["data"]["receipt"]["validation"][0]["code"] == "rich_text_replaced_with_plain"


@pytest.mark.parametrize("mode", ["review", "draft", "customer", "controlled"])
@pytest.mark.parametrize("kind", [KIND, "illustrated_parts_manual", "work_instructions", "product_specification_sheet"])
def test_rich_feature_guard_allows_supported_export_formats(scene, kind, mode):
    scene.edit()
    document = scene.snapshot()[1]
    document["documentType"] = kind
    for format in ("pdf", "docx"):
        check_export(document, mode, format=format)
    with pytest.raises(DocumentEditError) as caught:
        rich.refuse_export(document, format="unknown")
    assert caught.value.code == "unsupported_export_feature"
    assert caught.value.details["targets"] == [{"pageId": PAGE, "targetId": OBJECT}]


def test_vendored_bundle_checksum_and_exports():
    directory = ROOT / "static/vendor/tiptap"
    manifest = (directory / "VERSIONS.md").read_text(encoding="utf-8")
    bundle = (directory / "tiptap.bundle.js").read_bytes()
    expected = re.search(r"SHA-256 `([0-9a-f]{64})`", manifest).group(1)
    assert hashlib.sha256(bundle).hexdigest() == expected == "c36fd989775f6ed6f6884333bd05d8e4f097b25e256e1e14a42c226f7b83b301"
    section = manifest.split("## Exports", 1)[1].split("##", 1)[0]
    exports = set(re.findall(r"`(\w+)`", section))
    export_blocks = re.findall(r"export\s*\{([^}]+)\}", bundle.decode("ascii"))
    names = {part.strip().split(" as ")[-1] for block in export_blocks for part in block.split(",") if part.strip()}
    assert names == exports
    assert "BackgroundColor" in names  # Vendored but deliberately unused by P2a.
    assert "**3.32.0**" in manifest
