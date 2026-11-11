"""P3a-3 generated narrative fields, using temporary stores and the real exporters."""
from copy import deepcopy
import io
import json
import zipfile

import pytest

from ai_inspector.documentation.commands import DocumentEditError, content_hash, document_id
from ai_inspector.documentation.identity import compile_identities, editable_targets, project_scene, sync_identity_overrides
from ai_inspector.documentation.provenance import project_document, prepare_text_command
from ai_inspector.documentation.rich_text import FEATURES, plain_text, guard_restored_fields
from ai_inspector.documentation.rich_blocks import base_style, prepare_pdf_blocks
from ai_inspector.documentation.targets import text_targets, read_targets, hash_values, ReadBindings, rich_block_capabilities
from tests.test_documentation_rich_text import RichScene, envelope, KIND, NUMBER, PAGE, OBJECT
from tests.test_documentation_refresh import mmle_client

BLOCK_TYPES = ("paragraph", "note", "status_panel", "cad_figure", "heading", "continuation_heading", "cover_kicker",
               "cover_title", "draft_banner", "contents_list", "table", "key_value_table", "list", "figure_legend",
               "bom", "spec_feature", "spec_title", "formula")


class NarrativeScene(RichScene):
    def snapshot(self):
        loaded = self.load()
        scene = loaded["scene"]
        document = deepcopy(self.base)
        view = project_scene(document, scene)
        for page in document["pages"]:
            page["documentationComposition"] = deepcopy(view.get("pages", {}).get(page["pageId"], {}))
            page["documentationObjects"] = deepcopy(page["documentationComposition"].get("documentObjects", {}))
        sync_identity_overrides(document)
        document = project_document(document, scene)
        state = {**scene, "scene": scene, "documentId": document_id(KIND, NUMBER),
                 "revision": scene["editRevision"], "sceneRevision": loaded["revision"], "aliasRevision": document["aliasRevision"]}
        return state, document, text_targets(state, document)

    def command(self, command):
        state, document, _ = self.snapshot()
        targets = editable_targets(document, {PAGE: {"document_object": list(state["pages"].get(PAGE, {}).get("documentObjects", {})),
            "page_element": [b["blockId"] for b in document["pages"][0]["layoutBlocks"]]}})
        return self.repo.apply_command(NUMBER, self.base["sourceRevision"], self.base["manualPlanRevision"],
            base_revision=state["sceneRevision"], identity_document=self.base, page_targets=targets,
            command=prepare_text_command(document, {"pageId": PAGE, "targetType": "document_object", "targetId": OBJECT, **command}))

    def generated(self, alias="generated-note", value=None, **extra):
        return self.command({"operation": "replace_rich_text", "targetType": "page_element", "targetId": alias,
                             "richText": value or envelope(), **extra})

    def override(self, alias="generated-note"):
        key = self.base["aliasMap"][PAGE][alias]["targetId"]
        return self.load()["scene"]["pages"][PAGE].get("pageElementOverrides", {}).get(key)


@pytest.fixture
def narrative(tmp_path, monkeypatch):
    monkeypatch.setenv("INSPECTORPRO_DOCUMENTATION_RICH_TEXT", "on")
    scene = NarrativeScene(tmp_path)
    for kind in BLOCK_TYPES[1:]:
        scene.base["pages"][0]["layoutBlocks"].append({"blockId": kind, "blockType": kind, "text": "Generated " + kind,
            "caption": "Generated caption", "frame": {"x": 40, "y": 100, "width": 400, "height": 100}})
    scene.base = compile_identities(scene.base)
    return scene


@pytest.mark.parametrize("document_type", [KIND, "work_instructions", "illustrated_parts_manual", "product_specification_sheet"])
@pytest.mark.parametrize("kind", BLOCK_TYPES)
def test_eligibility_and_capability_table(document_type, kind):
    caps = rich_block_capabilities(document_type, kind)
    eligible = document_type in {KIND, "work_instructions"} and kind in {"paragraph", "note", "status_panel", "cad_figure"}
    assert bool(caps) == eligible
    if caps:
        assert caps["schemaVersions"] == [1, 2]
        expected = set(FEATURES) - {"heading", "namedStyle"} if kind == "paragraph" else {
            "bold", "italic", "underline", "strike", "subscript", "superscript", "highlight", "color", "link"}
        assert set(caps["features"]) == expected
        assert caps["listDepth"] == (6 if kind == "paragraph" else 0)


@pytest.mark.parametrize("kind", [k for k in BLOCK_TYPES if k not in {"paragraph", "note", "status_panel", "cad_figure"}])
def test_ineligible_generated_writes_refused(narrative, kind):
    before = narrative.path.read_bytes()
    with pytest.raises(DocumentEditError) as error:
        narrative.generated(kind)
    assert error.value.code == "read_only_derived_field"
    assert narrative.path.read_bytes() == before


@pytest.mark.parametrize("kind", ["note", "status_panel", "cad_figure"])
@pytest.mark.parametrize("feature", ["fontSize", "bulletList"])
def test_notice_caption_refuse_size_and_list(narrative, kind, feature):
    value = envelope()
    if feature == "fontSize":
        value["schemaVersion"] = 2
        value["doc"]["content"][0]["content"][0]["marks"] = [{"type": "textStyle", "attrs": {"fontSize": 12}}]
    else:
        from ai_inspector.documentation.rich_text import from_plain
        p = value["doc"]["content"][0]
        ids = [from_plain("")["doc"]["content"][0]["attrs"] for _ in range(2)]
        value["doc"]["content"] = [{"type": "bulletList", "attrs": ids[0], "content": [{"type": "listItem", "attrs": ids[1], "content": [p]}]}]
    with pytest.raises(DocumentEditError) as error:
        narrative.generated(kind, value)
    assert error.value.code == "unsupported_rich_text_feature"
    assert feature in error.value.details["features"]


def test_generated_storage_projection_whole_replacement_and_undo(narrative):
    source = "A  note\r\nwith\ttabs  "
    value = envelope(source, marks=[{"type": "bold"}])
    result = narrative.generated(value=value)
    stored = {"richText": value, "text": source}
    assert narrative.override() == stored
    field = narrative.field("generated-note")
    assert field["richText"] == value and field["text"] == source and field["richTextEligible"]
    assert field["wholeFieldReplacementRequired"] and field["provenance"]["origin"] == "manual"
    with pytest.raises(DocumentEditError) as error:
        narrative.command({"operation": "update_text", "targetType": "page_element", "targetId": "generated-note", "text": source})
    assert error.value.code == "rich_text_replacement_required"
    loaded = narrative.load()
    undone = narrative.repo.undo_change(NUMBER, "source-a", "plan-a", change_id=result["command"]["commandId"],
        expected_revision=loaded["scene"]["editRevision"], request_id="undo-rich", actor="user", identity_document=narrative.base)
    assert narrative.override() is None
    narrative.repo.undo_change(NUMBER, "source-a", "plan-a", change_id=undone["receipt"]["changeId"],
        expected_revision=undone["scene"]["editRevision"], request_id="redo-rich", actor="user", identity_document=narrative.base)
    assert narrative.override() == stored
    narrative.command({"operation": "update_text", "targetType": "page_element", "targetId": "generated-note",
                       "text": "Plain", "wholeFieldReplacement": True})
    assert narrative.override() == {"text": "Plain"}
    narrative.generated(value=value)
    narrative.command({"operation": "reset", "targetType": "page_element", "targetId": "generated-note"})
    assert narrative.override() is None


def test_ids_across_generated_and_authored_and_restore_guard(narrative):
    value = envelope()
    narrative.generated(value=value)
    with pytest.raises(DocumentEditError) as error:
        narrative.edit(value)
    assert error.value.code == "rich_text_node_id_collision"
    before = narrative.load()["scene"]
    after = deepcopy(before)
    after["pages"][PAGE]["pageElementOverrides"]["other"] = {"richText": value, "text": plain_text(value)}
    with pytest.raises(DocumentEditError) as error:
        guard_restored_fields(before, after)
    assert error.value.code == "rich_text_node_id_collision"
    narrative.edit(envelope(start=100))


@pytest.mark.parametrize("choice", ["keep_manual", "use_generated"])
def test_format_only_override_conflicts_on_new_generated_text(narrative, choice):
    from ai_inspector.documentation.refresh import exposure
    value = envelope("Generated plain text", marks=[{"type": "bold"}])
    narrative.generated(value=value)
    newer = deepcopy(narrative.base)
    newer["sourceRevision"] = "source-b"
    newer["pages"][0]["layoutBlocks"][0]["text"] = "New generated text"
    result = narrative.repo.refresh(NUMBER, "source-b", "plan-a", base_revision=narrative.load()["revision"], identity_document=newer)
    narrative.base = compile_identities(newer)
    conflict = exposure(result["scene"])["conflicts"][0]
    assert conflict["C"]["override"]["richText"] == value
    with pytest.raises(DocumentEditError) as error:
        narrative.generated(value=envelope(start=100))
    assert error.value.code == "manual_edit_conflict"
    state, _, targets = narrative.snapshot()
    hashes = {key: content_hash(state, key, row) for key, row in hash_values(targets).items()}
    args = {"documentId": state["documentId"], "expectedRevision": state["editRevision"], "requestId": "resolve-rich",
            "resolutions": [{"conflictId": conflict["conflictId"], "expectedConflictHash": conflict["conflictHash"], "choice": choice}]}
    narrative.repo.resolve_conflicts(NUMBER, "source-b", "plan-a", arguments=args, targets=targets, hashes=hashes, identity_document=newer)
    assert narrative.override() == ({"richText": value, "text": plain_text(value)} if choice == "keep_manual" else None)


def test_generated_corruption_is_read_only_without_rewrite(narrative):
    narrative.generated()
    stored = json.loads(narrative.path.read_bytes())
    stored["commands"][-1]["richText"]["doc"]["content"][0]["content"][0]["text"] = "\ud800"
    raw = json.dumps(stored, ensure_ascii=True).encode("ascii")
    narrative.path.write_bytes(raw)
    field = narrative.field("generated-note")
    assert field["richTextError"] and field["richText"] is None and field["text"] == "A note"
    assert field["capabilities"] == [] and narrative.path.read_bytes() == raw


@pytest.mark.parametrize("kind,route", [(KIND, "operations-manual"), ("work_instructions", "work-instructions")])
@pytest.mark.parametrize("block_kind", ["paragraph", "cad_figure"])
def test_generated_ui_and_sage_batch_receipt_retry(mmle_client, monkeypatch, kind, route, block_kind):
    import server
    monkeypatch.setenv("INSPECTORPRO_DOCUMENTATION_RICH_TEXT", "on")
    url = f"/api/{route}/MMLE-50D/documentation-scene"
    calls = []
    reader = server.documentation_read_targets
    def batched(*args, **kwargs):
        calls.append(len(args[2]))
        return reader(*args, **kwargs)
    monkeypatch.setattr(server, "documentation_read_targets", batched)
    opened = mmle_client.get(url).json()
    assert calls == [len(opened["richTextFields"])]
    eligible = {(p["pageId"], b["blockId"]) for p in opened["document"]["pages"]
                for b in p.get("layoutBlocks", []) if b.get("blockType") == block_kind}
    field = next(f for f in opened["richTextFields"] if (f["pageId"], f["legacyTargetId"]) in eligible)
    value = envelope("Generated narrative proof", marks=[{"type": "bold"}])
    response = mmle_client.post(url + "/commands", json={"baseRevision": opened["revision"],
        "sourceRevision": opened["document"]["sourceRevision"], "manualPlanRevision": opened["document"]["manualPlanRevision"],
        "operation": "replace_rich_text", "pageId": field["pageId"], "targetType": "page_element",
        "targetId": field["legacyTargetId"], "richText": value, "expectedContentHash": field["contentHash"]})
    assert response.status_code == 200, response.text
    host = server._DocumentationAgentHost()
    snapshot = host.document_snapshot("MMLE-50D", kind)
    full = read_targets(snapshot["state"], snapshot["targets"], [{"targetId": field["targetId"]}])
    bindings = ReadBindings("generated-rich")
    bindings.record(kind, full)
    value = deepcopy(value)
    value["doc"]["content"][0]["content"][0]["text"] = "Sage narrative proof"
    observed = bindings.bind_operations(kind, {"documentId": full["documentId"], "expectedRevision": full["revision"],
        "requestId": "generated-rich-batch", "operations": [{"operation": "replace_rich_text", "targetId": field["targetId"],
        "expectedContentHash": full["targets"][0]["contentHash"], "richText": value}]})
    result = host.apply_document_edits("MMLE-50D", kind, observed)
    assert host.apply_document_edits("MMLE-50D", kind, observed)["receipt"] == result["receipt"]
    current = mmle_client.get(url).json()
    after = next(f for f in current["richTextFields"] if f["targetId"] == field["targetId"])
    assert after["richText"] == value and after["text"] == "Sage narrative proof"
    if kind == "work_instructions":
        assert [p.get("figureRevision") for p in current["document"]["pages"]] == [p.get("figureRevision") for p in opened["document"]["pages"]]


@pytest.mark.parametrize("builder", ["operations", "wi"])
@pytest.mark.parametrize("kind", ["paragraph", "note", "status_panel", "cad_figure"])
def test_rich_generated_pdf_docx_geometry(tmp_path, monkeypatch, builder, kind):
    import fitz
    from PIL import Image
    from ai_inspector.operations_manual import exports as ops
    from ai_inspector.documentation.rich_layout import content_model
    from ai_inspector.documentation.rich_fonts import line_box
    from tests.test_documentation_rich_exports import fixture_document, docx_parts, xp
    from tests.documentation_rich_export_support import compare_pdf, compare_docx
    document = fixture_document(builder)
    page = document["pages"][0]
    block = {"blockId": "narrative", "blockType": kind, "text": "Legacy plain", "caption": "Legacy caption",
             "signalWord": "NOTICE", "style": {"fontSize": 9, "lineHeight": 12, "color": "#123456", "fontWeight": 700},
             "frame": {"x": 40, "y": 100, "width": 400, "height": 160}}
    page["layoutBlocks"] = [block]
    value = envelope("Proof", marks=[{"type": "italic"}, {"type": "highlight", "attrs": {"color": "#aabbcc"}}])
    value["schemaVersion"] = 2
    page["documentationComposition"] = {"pageElementOverrides": {"narrative": {"richText": value, "text": "STALE PROJECTION"}}}
    image = tmp_path / "capture.png"
    Image.new("RGB", (80, 80), "white").save(image)
    monkeypatch.setattr(ops, "document_draft_render_path", lambda *a: image)
    plan = prepare_pdf_blocks(fitz, document)[page["pageId"]]["narrative"]
    style = base_style(block)
    size = 9 if kind == "paragraph" else 7.5 if kind == "cad_figure" else 10
    pitch = 12 if kind in {"paragraph", "cad_figure"} else 14
    assert plan.layout.measured_height == pytest.approx(pitch)
    assert plan.layout.lines[0].baseline - plan.layout.frame[1] == pytest.approx(line_box(size, "Arial", pitch / size)[0])
    runs = plan.layout.lines[0].runs
    assert all(r.font_size == size for r in runs)
    if kind in {"note", "status_panel"}:
        assert runs[0].text == "NOTICE" and runs[0].bold
        assert runs[1].x - runs[0].x - runs[0].width == pytest.approx(3)
        assert plan.frame[0] == 108
        assert plan.frame[1] == pytest.approx(100 + (160 - 14) / 2)
    if kind == "cad_figure":
        assert plan.frame[1] == 244
        assert runs[0].x - 40 == pytest.approx(440 - runs[-1].x - runs[-1].width)
    pdf = ops.build_prototype_pdf_bytes(tmp_path, "PROOF", document)
    compare_pdf(pdf, document, page["pageId"], "narrative", tmp_path / "proof.png")
    docx = ops.build_prototype_docx_bytes(tmp_path, "PROOF", document)
    compare_docx(docx, "narrative", content_model(value, style))
    xml = docx_parts(docx)["word/document.xml"]
    assert "STALE PROJECTION" not in "".join(xp(xml, '//w:t/text()'))
    if kind in {"note", "status_panel"}:
        signal = next(p for p in xp(xml, '//w:p') if xp(p, './w:bookmarkStart'))
        assert xp(signal, './w:r/w:t/text()')[:2] == ["NOTICE", " "]
        assert xp(signal, './w:r[2]/w:rPr/w:fitText/@w:val') == ["60"]


def test_base_line_height_and_paragraph_override():
    from ai_inspector.documentation.rich_layout import content_model
    block = {"blockType": "paragraph", "style": {"fontSize": 7.4, "lineHeight": 10, "color": "#596a76"}}
    style = base_style(block)
    value = envelope()
    assert content_model(value, style).paragraphs[0].line_height == pytest.approx(10 / 7.4)
    assert base_style({"blockType": "paragraph"})["baseLineHeight"] == 1.35
    value["schemaVersion"] = 2
    value["doc"]["content"][0]["attrs"]["lineHeight"] = 2
    assert content_model(value, style).paragraphs[0].line_height == 2
    assert content_model(envelope(), {}).paragraphs[0].line_height == 1.2


def test_generated_overflow_names_target():
    import fitz
    from tests.test_documentation_rich_exports import fixture_document
    document = fixture_document("operations")
    page = document["pages"][0]
    page["layoutBlocks"] = [{"blockId": "caption", "blockType": "cad_figure",
        "frame": {"x": 40, "y": 50, "width": 80, "height": 100}}]
    value = envelope("Too much caption " * 40)
    page["documentationComposition"] = {"pageElementOverrides": {"caption": {"richText": value, "text": plain_text(value)}}}
    with pytest.raises(DocumentEditError) as error:
        prepare_pdf_blocks(fitz, document)
    assert error.value.code == "layout_overflow"
    assert error.value.details["targets"][0]["targetId"] == "caption"


@pytest.mark.parametrize("builder", ["operations", "wi"])
def test_plain_generated_export_bytes_unchanged_since_p3a2(tmp_path, monkeypatch, builder):
    import fitz
    from PIL import Image
    from ai_inspector.operations_manual import exports as ops
    from tests.test_documentation_rich_exports import fixture_document, legacy_module
    document = fixture_document(builder)
    document["pages"][0]["layoutBlocks"] = [
        {"blockId": kind, "blockType": kind, "text": "Unchanged plain text", "caption": "Unchanged caption",
         "frame": {"x": 40, "y": 60 + i * 130, "width": 400, "height": 110}}
        for i, kind in enumerate(["paragraph", "note", "cad_figure"])]
    image = tmp_path / "capture.png"
    Image.new("RGB", (80, 80), "white").save(image)
    old = legacy_module(ops, monkeypatch, commit="de5e171")
    monkeypatch.setattr(ops, "document_draft_render_path", lambda *a: image)
    monkeypatch.setattr(old, "document_draft_render_path", lambda *a: image)
    save = fitz.Document.tobytes
    monkeypatch.setattr(fitz.Document, "tobytes", lambda self, *a, **kw: save(self, *a, **{**kw, "no_new_id": True}))
    assert ops.build_prototype_pdf_bytes(tmp_path, "PROOF", document) == old.build_prototype_pdf_bytes(tmp_path, "PROOF", document)
    # ZIP timestamps are transport entropy; compare every native package member byte for byte.
    def parts(payload):
        with zipfile.ZipFile(io.BytesIO(payload)) as package:
            return {name: package.read(name) for name in package.namelist()}
    assert parts(ops.build_prototype_docx_bytes(tmp_path, "PROOF", document)) == parts(old.build_prototype_docx_bytes(tmp_path, "PROOF", document))


def test_scene_v5_backup_and_future_refusal(narrative):
    old = json.loads(narrative.path.read_bytes())
    old["schemaVersion"] = 5
    raw = (json.dumps(old, indent=2) + "\n").encode("utf-8")
    narrative.path.write_bytes(raw)
    assert narrative.load()["scene"]["schemaVersion"] == 6
    assert narrative.path.read_bytes() == raw
    narrative.generated()
    assert narrative.path.with_name("documentation-scene.v5.json").read_bytes() == raw
    future = json.loads(narrative.path.read_bytes())
    future["schemaVersion"] = 7
    raw = json.dumps(future).encode("utf-8")
    narrative.path.write_bytes(raw)
    # A read refuses an unknown schema as every earlier scene version did (supervisor P3a-3).
    from ai_inspector.parts_manual.documentation import DocumentationSceneError
    with pytest.raises(DocumentationSceneError, match="unsupported documentation scene schema"):
        narrative.load()
    assert narrative.path.read_bytes() == raw


def test_generated_orphan_restore_preserves_envelope(narrative):
    from ai_inspector.documentation.refresh import exposure
    value = envelope("Restore rich", marks=[{"type": "bold"}])
    narrative.generated(value=value)
    newer = deepcopy(narrative.base)
    newer["sourceRevision"] = "source-b"
    newer["pages"][0]["layoutBlocks"] = newer["pages"][0]["layoutBlocks"][1:]
    result = narrative.repo.refresh(NUMBER, "source-b", "plan-a", base_revision=narrative.load()["revision"], identity_document=newer)
    narrative.base = compile_identities(newer)
    orphan = exposure(result["scene"])["orphans"][0]
    state, _, targets = narrative.snapshot()
    destination = narrative.base["aliasMap"][PAGE]["note"]["targetId"]
    args = {"documentId": state["documentId"], "expectedRevision": state["editRevision"], "requestId": "restore-rich",
        "resolutions": [{"conflictId": orphan["orphanId"], "expectedConflictHash": orphan["conflictHash"], "choice": "restore",
                         "targetId": destination, "expectedContentHash": "observed"}]}
    narrative.repo.resolve_conflicts(NUMBER, "source-b", "plan-a", arguments=args, targets=targets,
                                    hashes={destination: "observed"}, identity_document=newer)
    assert narrative.override("note") == {"text": plain_text(value), "richText": value}
