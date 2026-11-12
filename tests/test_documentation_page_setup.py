"""P4b-1: fixed paper, pure migration, atomic acceptance and real export geometry.

All stores and captures used by these tests are temporary. Run under pytest in the
supervisor environment; the builder performs syntax checks only.
"""
from copy import deepcopy
import io
import json
from pathlib import Path

import fitz
import pytest
from docx import Document
from docx.enum.section import WD_ORIENT

from ai_inspector.documentation import layout, fit
from ai_inspector.documentation.commands import DocumentEditError
from ai_inspector.documentation.registry import document_type_summaries
from ai_inspector.parts_manual.documentation import (
    DocumentationSceneRepository, DocumentationSceneError, documentation_scene_revision,
    _upgrade_documentation_scene, apply_documentation_command_candidate,
)
from ai_inspector.parts_manual import layout as parts_layout, pdf as parts_pdf
from ai_inspector.operations_manual import flow, exports as operations_pdf
from ai_inspector.specification_sheet import document as spec_document, exports as spec_pdf
from ai_inspector.work_instructions import exports as work_pdf
from tests.test_documentation_refresh import mmle_client, MMLE_ROUTES
from tests.test_documentation_rich_text import scene, PAGE, OBJECT, NUMBER
from tests.test_documentation_objects import history
from tests.test_documentation_rich_exports import (
    BUILDERS, fixture_document, attach, build, build_docx, image_path, legacy_module,
    mixed, docx_parts, TARGET,
)

PARTS = "illustrated_parts_manual"
OPS = "operations_and_maintenance_manual"
SPEC = "product_specification_sheet"
WI = "work_instructions"
COMMIT = "8ac3838"  # P4a-2 supervisor gate, before page setup.


def setup(kind, paper="A4"):
    return layout.normalize_page_setup(kind, {"paper": paper, "orientation": layout.DESIGN[kind][2]})


def refused(fn, code="unsupported_page_setup"):
    with pytest.raises(DocumentEditError) as caught:
        fn()
    assert caught.value.code == code
    return caught.value


@pytest.mark.parametrize("kind", layout.DESIGN)
def test_presets_and_registry(kind):
    presets = layout.page_setups(kind)
    assert [p["paper"] for p in presets] == ["Letter", "A4"]
    dw, dh, orientation = layout.DESIGN[kind]
    design = {PARTS: parts_layout.publication_layout(), OPS: flow.publication_layout(),
              WI: flow.publication_layout(), SPEC: spec_document.specification_sheet_layout()}[kind]
    content = design["shared"]["safeArea" if kind == PARTS else "content"]
    for p in presets:
        pw, ph = layout.PAPERS[p["paper"]]
        if orientation == "landscape":
            pw, ph = ph, pw
        assert p["id"] == p["paper"].lower() + "-" + orientation
        assert p["page"] == {"width": pw, "height": ph}
        assert p["layoutMode"] == "fixed"
        assert p["margins"] == {"top": round(content["y"] * ph / dh, 2),
            "left": round(content["x"] * pw / dw, 2),
            "right": round((dw-content["x"]-content["width"]) * pw / dw, 2),
            "bottom": round((dh-content["y"]-content["height"]) * ph / dh, 2)}
        assert setup(kind, p["paper"]) == {k: p[k] for k in ("paper", "orientation", "margins", "layoutMode")}
    entry = next(r for r in document_type_summaries() if r["documentType"] == kind)
    assert entry["pageSetups"] == [p["id"] for p in presets]
    assert entry["pageOrientation"] == orientation
    assert layout.page_setups("inspection_sheet") == layout.page_setups("unknown") == []
    assert next(r for r in document_type_summaries() if r["documentType"] == "inspection_sheet")["pageSetups"] == []


@pytest.mark.parametrize("kind", layout.DESIGN)
def test_normalization_refuses_every_unsupported_value(kind):
    canonical = setup(kind)
    for value in (None, [], {}, {**canonical, "paper": "Legal"},
                  {**canonical, "orientation": "portrait" if canonical["orientation"] == "landscape" else "landscape"},
                  {**canonical, "layoutMode": "flow"}, {**canonical, "extra": 1},
                  {**canonical, "margins": None}, {**canonical, "margins": {"top": 0}}):
        refused(lambda: layout.normalize_page_setup(kind, value))
    for key in canonical["margins"]:
        for value in (True, "10", float("inf"), float("nan"), canonical["margins"][key] + .011):
            refused(lambda: layout.normalize_page_setup(kind, {**canonical, "margins": {**canonical["margins"], key: value}}))
        for delta in (-.01, 0, .01):
            assert layout.normalize_page_setup(kind, {**canonical,
                "margins": {**canonical["margins"], key: canonical["margins"][key]+delta}}) == canonical
    refused(lambda: layout.normalize_page_setup("inspection_sheet", canonical))
    assert layout.page_setup_options(kind, {})["current"] is None
    assert not any(p["selected"] for p in layout.page_setup_options(kind, {})["presets"])


@pytest.mark.parametrize("kind", layout.DESIGN)
def test_identity_helpers_keep_objects_and_numbers(kind):
    frame = {"x": 12.3456789, "y": 25, "width": 300.1234567, "height": 40}
    values = [12.3456789, 25, 300.1234567, 40]
    for value in ([None, setup(kind, "Letter")] if kind in (PARTS, SPEC) else [None]):
        g = layout.geometry(kind, value)
        assert g.identity and g.sx == g.sy == 1
        assert g.rect(frame) is frame and g.rect(values) is values
        assert g.x(values[0]) is values[0]
        assert g.y(values[1]) is values[1]
        assert g.w(values[2]) is values[2] and g.h(values[3]) is values[3]
        contract = {"page": {"width": 1}, "shared": {"content": frame}}
        assert g.layout(contract) is contract


@pytest.mark.parametrize("kind,paper,expected", [
    (OPS, "Letter", (46.2, 83.8667, 699.6, 489.6)),
    (OPS, "A4", (49.1103, 81.5754, 743.6695, 476.224)),
    (WI, "Letter", (46.2, 83.8667, 699.6, 489.6)),
    (WI, "A4", (49.1103, 81.5754, 743.6695, 476.224)),
    (PARTS, "Letter", (56, 74, 848, 432)),
    (PARTS, "A4", (59.5276, 71.9783, 901.4176, 420.1976)),
    (SPEC, "Letter", (56, 74, 848, 432)),
    (SPEC, "A4", (54.4701, 78.6614, 824.8324, 459.2127)),
])
def test_stretch_vectors(kind, paper, expected):
    g = layout.geometry(kind, setup(kind, paper))
    assert g.rect((56, 74, 848, 432)) == pytest.approx(expected, abs=1e-4)
    for frame in ((0, 0, 1, 1), (36, 82, 540, 654), (28, 62, 736, 502)):
        actual = g.rect(frame)
        assert actual == tuple(round(v * (g.sx if i % 2 == 0 else g.sy), 4) for i, v in enumerate(frame))
    assert g.fitz_rect(28, 62, 764, 564) == (g.x(28), g.y(62), g.x(764), g.y(564))


def test_schema_seven_read_revision_backup_and_future_refusal(scene, monkeypatch):
    raw_scene = scene.load()["scene"]
    raw_scene["schemaVersion"] = 7
    before_revision = documentation_scene_revision(raw_scene)
    old = legacy_module(__import__("ai_inspector.parts_manual.documentation", fromlist=["x"]), monkeypatch, COMMIT)
    assert before_revision == old.documentation_scene_revision(raw_scene)
    raw = ("  " + json.dumps(raw_scene, indent=2) + "\n").encode("ascii")
    scene.path.write_bytes(raw)
    loaded = scene.load()
    assert loaded["scene"]["schemaVersion"] == 8 and "pageSetup" not in loaded["scene"]
    assert loaded["revision"] == before_revision and scene.path.read_bytes() == raw
    scene.command({"operation": "set_object_frame", "frame": {
        **loaded["scene"]["pages"][PAGE]["documentObjects"][OBJECT]["frame"], "x": .21}})
    assert scene.path.with_name("documentation-scene.v7.json").read_bytes() == raw
    future = deepcopy(loaded["scene"]); future["schemaVersion"] = 9
    with pytest.raises(DocumentationSceneError, match="unsupported documentation scene schema"):
        _upgrade_documentation_scene(deepcopy(future))
    scene.path.write_text(json.dumps(future), encoding="ascii")
    refused(lambda: scene.repo._save(NUMBER, loaded["scene"]), "unsupported_document_schema")
    invalid = deepcopy(raw_scene); invalid["pageSetup"] = {"paper": "Legal", "orientation": "landscape"}
    scene.path.write_text(json.dumps(invalid), encoding="ascii")
    refused(scene.load)


def test_backup_mismatch_does_not_overwrite(scene):
    original = scene.load()["scene"]; original["schemaVersion"] = 7
    raw = json.dumps(original).encode("ascii"); scene.path.write_bytes(raw)
    scene.path.with_name("documentation-scene.v7.json").write_bytes(b"different")
    refused(lambda: scene.command({"operation": "set_object_frame", "frame": {
        **original["pages"][PAGE]["documentObjects"][OBJECT]["frame"], "x": .22}}), "legacy_store_changed")
    assert scene.path.read_bytes() == raw


def _real(client, route):
    if route == "parts-manual":
        import server
        if not (server.PARTS_MANUAL_ROOT / "mmle-50d" / "manual-plan.json").is_file():
            pytest.skip("needs the isolated approved MMLE manual plan")
    response = client.get(f"/api/{route}/MMLE-50D/documentation-scene")
    assert response.status_code == 200, response.text
    return response.json()


def command(client, route, payload, value, **extra):
    document = payload["document"]
    return client.post(f"/api/{route}/MMLE-50D/documentation-scene/commands", json={
        "baseRevision": payload["revision"], "sourceRevision": document["sourceRevision"],
        "manualPlanRevision": document["manualPlanRevision"], "operation": "set_page_setup",
        "pageId": document["pages"][0]["pageId"], "targetType": "document_page_setup",
        "targetId": "page-setup", "pageSetup": value, **extra})


def move_history(client, route, payload, direction):
    document = payload["document"]
    result = client.post(f"/api/{route}/MMLE-50D/documentation-scene/{direction}", json={
        "baseRevision": payload["revision"], "sourceRevision": document["sourceRevision"],
        "manualPlanRevision": document["manualPlanRevision"]})
    assert result.status_code == 200, result.text
    return result.json()


def frames(value):
    if isinstance(value, dict):
        if {"x", "y", "width", "height"} <= value.keys():
            yield value
        else:
            for child in value.values():
                yield from frames(child)
    elif isinstance(value, list):
        for child in value:
            yield from frames(child)


def generated_frames(document):
    return {p["pageId"]: [deepcopy(b["frame"]) for b in p.get("layoutBlocks", [])]
            for p in document["pages"]}


def capture_document(root, document, route, number="MMLE-50D"):
    """Use the real artifact stores and revisions, without bypassing readiness or capture QA."""
    from ai_inspector.operations_manual.artifacts import store_draft_render_artifact, attach_draft_render_artifacts
    from tests.test_operations_manual_workspace import _png
    if route == "parts-manual":
        from ai_inspector.parts_manual.artifacts import store_render_artifact, attach_render_artifacts
        from tests.test_parts_manual import _png as parts_png, _valid_balloon
        from tests.test_documentation_refresh import _spread_balloons
        for page in document["pages"]:
            if page.get("renderRequest"):
                store_render_artifact(root, number, document, page["pageId"], parts_png(),
                    balloons=_spread_balloons(_valid_balloon, page["renderRequest"].get("calloutItems", [])))
        result = attach_render_artifacts(root, number, document)
    elif route == "specification-sheet":
        from tools.documentation_baseline import specification_capture
        result = specification_capture(root, number, document, _png(1200, 900))
    else:
        for page in document["pages"]:
            if page.get("renderRequest"):
                store_draft_render_artifact(root, number, document, page["pageId"], _png(1200, 900),
                    source_revision=document["sourceRevision"], manual_plan_revision=document["manualPlanRevision"],
                    api_route=route, figure_revision=page.get("figureRevision"))
        result = attach_draft_render_artifacts(root, number, document)
    assert all(p["renderRequest"]["image"]["status"] == "ready" for p in result["pages"] if p.get("renderRequest"))
    return result


def report_for(root, document):
    kind = document["documentType"]
    if kind == PARTS:
        return parts_pdf.fit_report(root, "MMLE-50D", document)
    if kind == SPEC:
        return spec_pdf.fit_report(document, render_root=root, assembly_number="MMLE-50D")
    return (work_pdf if kind == WI else operations_pdf).fit_report(root, "MMLE-50D", document)


def figure_revisions(document):
    if document["documentType"] == SPEC:
        return {p["pageId"]: document["figureRevision"] for p in document["pages"] if p.get("renderRequest")}
    from ai_inspector.work_instructions.document import page_figure_revision
    return {p["pageId"]: (p["renderRequest"]["figureRevision"] if document["documentType"] == PARTS
                         else page_figure_revision(document, p))
            for p in document["pages"] if p.get("renderRequest")}


def assert_restored(before, undone):
    # Undo appends an inverse to the immutable journal. Publication values are restored exactly;
    # journal-derived revision strings necessarily identify the new history entry.
    for key in ("pages", "fieldMeta", "theme", "pageMasters", "pageSetup"):
        assert (key in undone["scene"], undone["scene"].get(key)) == (key in before["scene"], before["scene"].get(key))
    ignored = {"documentRevision", "documentationSceneRevision"}
    assert {k: v for k, v in undone["document"].items() if k not in ignored} == {
        k: v for k, v in before["document"].items() if k not in ignored}


@pytest.mark.parametrize("paper", ["Letter", "A4"])
@pytest.mark.parametrize("kind,route", MMLE_ROUTES)
def test_four_routes_set_read_undo_redo_clear_and_identity(mmle_client, kind, route, paper):
    before = _real(mmle_client, route)
    design = deepcopy(before["document"])
    assert "pageSetup" not in design and "pageSetup" not in before["scene"]
    assert before["pageSetupOptions"]["current"] is None
    expected_design = {PARTS: parts_layout.publication_layout(), OPS: flow.publication_layout(),
                       WI: flow.publication_layout(), SPEC: spec_document.specification_sheet_layout()}[kind]
    assert design["publicationLayout"] == expected_design
    value = setup(kind, paper)
    response = command(mmle_client, route, before, value)
    assert response.status_code == 200, response.text
    after = response.json(); current = after["document"]
    assert after["scene"]["pageSetup"] == current["pageSetup"] == value
    assert after["pageSetupOptions"] == _real(mmle_client, route)["pageSetupOptions"]
    assert after["pageSetupOptions"]["current"] == value
    assert [p["id"] for p in after["pageSetupOptions"]["presets"] if p["selected"]] == [paper.lower()+"-"+layout.DESIGN[kind][2]]
    size = layout.geometry(kind, value).page
    assert current["publicationLayout"]["page"]["width"] == size["width"]
    assert current["publicationLayout"]["page"]["height"] == size["height"]
    for f in list(frames(current["publicationLayout"])) + [f for page in current["pages"] for f in frames(page.get("layoutBlocks", []))]:
        assert min(f["x"], f["y"]) >= -1e-4
        assert f["x"] + f["width"] <= size["width"] + 1e-4
        assert f["y"] + f["height"] <= size["height"] + 1e-4
    if paper == "Letter" and kind in (PARTS, SPEC):
        assert current["publicationLayout"] == design["publicationLayout"]
        assert generated_frames(current) == generated_frames(design)
        assert figure_revisions(current) == figure_revisions(design)
        assert all("pageSize" not in p["renderRequest"] for p in current["pages"] if p.get("renderRequest"))
    undone = move_history(mmle_client, route, after, "undo")
    assert_restored(before, undone)
    redone = move_history(mmle_client, route, undone, "redo")
    assert redone["document"]["publicationLayout"] == current["publicationLayout"]
    assert redone["scene"]["pageSetup"] == value
    unchanged = command(mmle_client, route, redone, value)
    assert unchanged.status_code == 409 and unchanged.json()["error"] == "unsupported_page_setup"
    assert "already uses" in unchanged.json()["message"]
    stale = command(mmle_client, route, before, None)
    assert stale.status_code == 409 and stale.json()["error"] == "documentation_scene_revision_conflict"
    cleared = command(mmle_client, route, redone, None)
    assert cleared.status_code == 200, cleared.text
    assert_restored(before, cleared.json())

@pytest.mark.parametrize("kind,route", MMLE_ROUTES)
def test_route_refusals_write_nothing(mmle_client, kind, route):
    before = _real(mmle_client, route)
    good = setup(kind)
    for invalid in ({**good, "paper": "Tabloid"}, {**good, "orientation": "portrait" if good["orientation"] == "landscape" else "landscape"},
                    {**good, "margins": {**good["margins"], "top": 0}}, {**good, "layoutMode": "flow"}, {**good, "custom": 1}):
        response = command(mmle_client, route, before, invalid)
        assert response.status_code == 409, response.text
        assert response.json()["error"] == "unsupported_page_setup"
        after = _real(mmle_client, route)
        assert after["scene"] == before["scene"] and after["revision"] == before["revision"]
        assert after["document"] == before["document"]


def _fit_document(builder, content, *, frame, style=None):
    document = attach(fixture_document(builder), content, frame=frame, style=style)
    kind = document["documentType"]
    contract = {PARTS: parts_layout.publication_layout(), OPS: flow.publication_layout(),
                WI: flow.publication_layout(), SPEC: spec_document.specification_sheet_layout()}[kind]
    document["publicationLayout"] = contract
    return document


def _paper(document, paper="A4"):
    result = deepcopy(document)
    result["pageSetup"] = setup(result["documentType"], paper)
    g = layout.geometry(result["documentType"], result["pageSetup"])
    result["publicationLayout"] = g.layout(result["publicationLayout"])
    g.blocks(result["pages"])
    return result


def test_fit_collects_every_failure_and_export_keeps_its_legacy_refusal(tmp_path):
    from ai_inspector.documentation.rich_text import from_plain
    text = "A measured line with room"
    width = fitz.get_text_length(text, fontname="helv", fontsize=12) + 6.1
    original = _fit_document("operations", from_plain(text),
        frame={"x": .1, "y": .2, "width": width/960, "height": 20.5/540}, style={"fontSize": 12})
    assert operations_pdf.fit_report(tmp_path, "PROOF", original) == []
    candidate = _paper(original)
    first = candidate["pages"][0]
    second = deepcopy(first); second["pageId"] = "page-second"; second["pageNumber"] = 2
    candidate["pages"].append(second); candidate["pageCount"] = 2
    report = operations_pdf.fit_report(tmp_path, "PROOF", candidate)
    assert [(r["pageId"], r["targetId"], r["reason"]) for r in report] == [
        (first["pageId"], TARGET, "text_does_not_fit"), ("page-second", TARGET, "text_does_not_fit")]
    error = refused(lambda: operations_pdf.build_prototype_pdf_bytes(tmp_path, "PROOF", candidate), "layout_overflow")
    assert str(error) == ("Authored text must fit inside its text box, and the box must be on the "
                          "page; enlarge or move the box, or shorten the text.")
    assert error.details["targets"] == report and "count" not in error.details
    assert not list(tmp_path.rglob("*.pdf"))

def test_plain_parts_text_is_reported_but_export_stays_legacy(tmp_path, monkeypatch):
    document = _fit_document("parts", "Plain text that cannot fit\n" * 12,
        frame={"x": .1, "y": .2, "width": .4, "height": .01}, style={"fontSize": 12})
    report = parts_pdf.fit_report(tmp_path, "PROOF", document)
    assert any(r["targetId"] == TARGET and r["reason"] == "text_does_not_fit" for r in report)
    previous = legacy_module(parts_pdf, monkeypatch, COMMIT)
    save = fitz.Document.tobytes
    monkeypatch.setattr(fitz.Document, "tobytes", lambda self,*a,**kw: save(self,*a,**{**kw,"no_new_id":True}))
    assert parts_pdf.build_manual_pdf_bytes(tmp_path, "PROOF", document) == previous.build_manual_pdf_bytes(tmp_path, "PROOF", document)

def test_fit_candidate_is_checked_before_history_or_write(scene):
    loaded = scene.load(); original = scene.path.read_bytes()
    failures = [{"targetId": OBJECT, "pageId": PAGE, "reason": "text_does_not_fit"}] * 55
    def check(current, candidate):
        assert "pageSetup" not in current
        assert candidate["pageSetup"] == setup(OPS)
        fit.refuse(failures, limit=50)
    error = refused(lambda: scene.repo.apply_command(NUMBER, scene.base["sourceRevision"], scene.base["manualPlanRevision"],
        base_revision=loaded["revision"], identity_document=scene.base, page_targets={PAGE: {}},
        command={"operation": "set_page_setup", "pageId": PAGE, "targetType": "document_page_setup",
                 "targetId": "page-setup", "pageSetup": setup(OPS)}, check_candidate=check), "layout_overflow")
    assert error.details["count"] == 55 and len(error.details["targets"]) == 50
    assert scene.path.read_bytes() == original and scene.load()["scene"] == loaded["scene"]


@pytest.mark.parametrize("builder", BUILDERS)
def test_no_setup_pdf_bytes_equal_committed_caller(builder, tmp_path, image_path, monkeypatch):
    document = attach(fixture_document(builder), mixed())
    save = fitz.Document.tobytes
    monkeypatch.setattr(fitz.Document, "tobytes", lambda self,*a,**kw: save(self,*a,**{**kw,"no_new_id":True}))
    previous = legacy_module(parts_pdf if builder == "parts" else spec_pdf if builder in {"specification", "fillable"} else operations_pdf,
                             monkeypatch, COMMIT)
    if builder in {"specification", "fillable"}:
        previous.draft_render_path = lambda *a: image_path
    modules = (previous if builder == "parts" else parts_pdf, previous if builder in {"specification", "fillable"} else spec_pdf,
               previous if builder in {"operations", "wi"} else operations_pdf)
    assert build(builder, document, tmp_path) == build(builder, document, tmp_path, modules=modules)


@pytest.mark.parametrize("builder", ["operations", "wi", "specification"])
def test_no_setup_docx_parts_equal_committed_caller(builder, tmp_path, image_path, monkeypatch):
    from lxml import etree
    document = attach(fixture_document(builder), mixed())
    previous = legacy_module(spec_pdf if builder == "specification" else operations_pdf, monkeypatch, COMMIT)
    if builder == "specification":
        previous.draft_render_path = lambda *a: image_path
    now = docx_parts(build_docx(builder, document, tmp_path))
    old = docx_parts(build_docx(builder, document, tmp_path, previous))
    assert now.keys() == old.keys()
    assert all(etree.tostring(now[k]) == etree.tostring(old[k]) for k in now)


@pytest.mark.parametrize("builder", BUILDERS)
def test_a4_export_page_and_docx_section_geometry(builder, tmp_path, image_path):
    document = _paper(_fit_document(builder, "Paper geometry proof", frame={"x": .1, "y": .3, "width": .6, "height": .2}))
    size = layout.geometry(document["documentType"], document["pageSetup"]).page
    with fitz.open(stream=build(builder, document, tmp_path), filetype="pdf") as pdf:
        assert len(pdf) == document["pageCount"]
        for page in pdf:
            assert (page.rect.width, page.rect.height) == pytest.approx((size["width"], size["height"]), abs=.01)
            assert all(word[0] >= -.01 and word[1] >= -.01 and word[2] <= page.rect.width+.01 and word[3] <= page.rect.height+.01
                       for word in page.get_text("words"))
    if builder in {"operations", "wi", "specification"}:
        section = Document(io.BytesIO(build_docx(builder, document, tmp_path))).sections[0]
        assert (section.page_width.pt, section.page_height.pt) == pytest.approx((size["width"], size["height"]), abs=.03)
        assert section.orientation == (WD_ORIENT.PORTRAIT if builder == "specification" else WD_ORIENT.LANDSCAPE)


@pytest.mark.parametrize("kind,route", MMLE_ROUTES)
def test_real_compiler_pagination_and_capture_binding(mmle_client, kind, route):
    before = _real(mmle_client, route)
    response = command(mmle_client, route, before, setup(kind))
    assert response.status_code == 200, response.text
    after = response.json()["document"]
    assert after["pageCount"] == len(after["pages"])
    assert [p["pageNumber"] for p in after["pages"]] == list(range(1, after["pageCount"] + 1))
    for page in after["pages"]:
        if kind == PARTS:
            assert len(page.get("bom", [])) <= 20 and len(page.get("entries", [])) <= 20
        if page.get("renderRequest"):
            assert page["renderRequest"]["pageSize"] == [after["publicationLayout"]["page"][k] for k in ("width", "height")]
    if kind == OPS:
        contents = next(p for p in after["pages"] if p["pageType"] == "operations_contents")
        for entry in contents["entries"]:
            if entry["sourceKey"] not in {"document-control", "contents"}:
                first = next(p for p in after["pages"] if p.get("sectionId") == entry["sourceKey"])
                assert entry["pageNumber"] == first["pageNumber"]
    if kind == SPEC:
        assert after["figureRevision"] != before["document"]["figureRevision"]
    else:
        old = {p["pageId"]: p for p in before["document"]["pages"]}
        from ai_inspector.parts_manual.document import figure_revision
        from ai_inspector.work_instructions.document import page_figure_revision
        for p in after["pages"]:
            if p.get("renderRequest") and p["pageId"] in old and old[p["pageId"]].get("renderRequest"):
                if kind == PARTS:
                    assert p["renderRequest"]["figureRevision"] != old[p["pageId"]]["renderRequest"]["figureRevision"]
                else:
                    assert page_figure_revision(after, p) != page_figure_revision(before["document"], old[p["pageId"]])
    # No captures exist in this isolated store. New paper must not make any of the previous capture statuses ready.
    assert not any((p.get("renderRequest", {}).get("image", {})).get("status") == "ready" for p in after["pages"])


def test_real_relative_fit_in_both_directions_and_clear(mmle_client):
    route = "operations-manual"
    before = _real(mmle_client, route)
    document = before["document"]
    page_id = next(p["pageId"] for p in document["pages"] if p.get("pageType") == "operations_content")
    text = "A measured line with room"
    width = fitz.get_text_length(text, fontname="helv", fontsize=12) + 6.1
    key = "document-object-paper-fit"
    frame = {"x": .1, "y": .2, "width": width/960, "height": 20.5/540}
    def object_command(payload, operation, **values):
        doc = payload["document"]
        result = mmle_client.post(f"/api/{route}/MMLE-50D/documentation-scene/commands", json={
            "baseRevision": payload["revision"], "sourceRevision": doc["sourceRevision"],
            "manualPlanRevision": doc["manualPlanRevision"], "operation": operation,
            "pageId": page_id, "targetType": "document_object", "targetId": key, **values})
        assert result.status_code == 200, result.text
        return result.json()
    def rejected(payload, value):
        response = command(mmle_client, route, payload, value)
        assert response.status_code == 409, response.text
        body = response.json()
        assert body["error"] == "layout_overflow"
        assert [t["targetId"] for t in body["details"]["targets"]] == [key]
        assert body["details"]["targets"][0]["reason"] == "text_does_not_fit"
        assert _real(mmle_client, route)["scene"] == payload["scene"]
    def accepted(payload, value):
        response = command(mmle_client, route, payload, value)
        assert response.status_code == 200, response.text
        return response.json()
    before = object_command(before, "add_object", documentObject={"objectId": key, "type": "text",
        "name": "Paper fit", "source": "user", "content": text, "frame": frame,
        "styleOverrides": {"fontSize": 12}})
    rejected(before, setup(OPS))  # It fits now, but wrapping on A4 is a new failure.
    larger = object_command(before, "set_object_frame", frame={**frame, "height": .2})
    paper = accepted(larger, setup(OPS))
    # Two lines fit in a 35 pt A4 frame, but not its 31.75 pt design-page counterpart.
    paper = object_command(paper, "update_text", text="First line\nSecond line")
    paper = object_command(paper, "set_object_frame", frame={**frame, "width": .5, "height": 35/595.28})
    rejected(paper, None)
    # Now both fail. The old failure is less than four points worse on clearing and is accepted.
    paper = object_command(paper, "set_object_frame", frame={**frame, "width": .5, "height": .01})
    design = accepted(paper, None)
    assert "pageSetup" not in design["scene"]
    paper = accepted(design, setup(OPS))  # The same existing failure improves in the other direction.
    paper = object_command(paper, "set_object_frame", frame={**frame, "width": .5, "height": .2})
    assert "pageSetup" not in accepted(paper, None)["document"]

@pytest.mark.parametrize("kind,route", MMLE_ROUTES)
def test_fit_report_skips_capture_file_access(mmle_client, kind, route, tmp_path, monkeypatch):
    document = _real(mmle_client, route)["document"]
    root = tmp_path / "captures"
    def forbidden(*args, **kwargs):
        raise AssertionError("Fit must not look for or open a capture")
    def checked_report():
        with monkeypatch.context() as guarded:
            guarded.setattr(parts_pdf, "_required_render_paths", forbidden)
            guarded.setattr(parts_pdf, "_image_fit_rect", forbidden)
            guarded.setattr(operations_pdf, "document_draft_render_path", forbidden)
            guarded.setattr(operations_pdf, "_fit_image_rect", forbidden)
            guarded.setattr(spec_pdf, "draft_render_path", forbidden)
            guarded.setattr(spec_pdf, "_fit_image_rect", forbidden)
            return report_for(root, document)
    before = checked_report()
    capture_document(root, document, route)
    assert list(root.rglob("*.png"))
    assert checked_report() == before  # Existing generator findings are not required to be empty.

def test_parts_row_minimum_and_outside_objects_are_reported(tmp_path):
    document = fixture_document("parts")  # Keep the required contents page.
    document["publicationLayout"] = parts_layout.publication_layout()
    document["publicationLayout"]["pageTypes"]["manual_section_parts_list"]["bom"]["height"] = 200
    document["pages"].append({"pageId": "page-bom", "pageNumber": 2, "title": "Parts list",
        "pageType": "manual_section_parts_list", "bom": [
            {"item": i+1, "description": "Part", "displayPartNumber": "PN", "quantity": 1} for i in range(20)]})
    document["pageCount"] = 2
    attach(document, "outside", frame={"x": 1.01, "y": .3, "width": .2, "height": .2})
    report = parts_pdf.fit_report(tmp_path, "PROOF", document)
    assert any(r["pageId"] == "page-bom" and r["targetId"] == "bom" and r["reason"] == "row_too_small" for r in report)
    assert any(r["targetId"] == TARGET and r["reason"] == "outside_page" for r in report)
    assert any(r["targetId"] == "contents_heading" for r in report)
    assert not any(r["targetId"] == "header_title" for r in report)

def test_generated_plain_failures_are_collected_in_page_order(tmp_path):
    document = fixture_document("operations")
    # The builder keeps authored soft-wrap lines and clamps every frame to at least 24 pt.
    document["pages"][0]["layoutBlocks"] = [{"blockId": key, "blockType": "paragraph",
        "text": "First line Second line Third line", "lines": ["First line", "Second line", "Third line"],
        "style": {"fontSize": 10, "lineHeight": 14},
        "frame": {"x": 56, "y": 100+i*30, "width": 200, "height": 24}}
        for i, key in enumerate(("first", "second", "third"))]
    report = operations_pdf.fit_report(tmp_path, "PROOF", document)
    assert [v["targetId"] for v in report] == ["first", "second", "third"]
    assert all(v["reason"] == "text_does_not_fit" and v["measuredHeight"] == 38 for v in report)

def test_work_capture_taken_on_design_page_is_stale_on_paper(tmp_path):
    from ai_inspector.operations_manual.artifacts import (
        store_draft_render_artifact, attach_draft_render_artifacts, document_draft_render_path,
        OperationsManualArtifactError,
    )
    from ai_inspector.work_instructions.document import with_figure_revisions
    document = fixture_document("wi")
    document["publicationLayout"] = flow.publication_layout()
    document["pages"][0]["renderRequest"] = {"occurrenceIds": ["part"], "showItemCallouts": False,
        "image": {"status": "pending", "targetAspectRatio": 2}}
    document = with_figure_revisions(document)
    page = document["pages"][0]
    with fitz.open() as pdf:
        image = pdf.new_page(width=1200, height=900).get_pixmap().tobytes("png")
    from tests.test_documentation_rich_exports import NUMBER as export_number
    store_draft_render_artifact(tmp_path, export_number, document, page["pageId"], image,
        source_revision=document["sourceRevision"], manual_plan_revision=document["manualPlanRevision"],
        api_route="work-instructions", figure_revision=page["figureRevision"])
    ready = attach_draft_render_artifacts(tmp_path, export_number, document)
    assert ready["pages"][0]["renderRequest"]["image"]["status"] == "ready"
    paper = _paper(document)
    g = paper["publicationLayout"]["page"]
    paper["pages"][0]["renderRequest"]["pageSize"] = [g["width"], g["height"]]
    paper = with_figure_revisions(paper)
    assert paper["pages"][0]["figureRevision"] != page["figureRevision"]
    stale = attach_draft_render_artifacts(tmp_path, export_number, paper)
    assert stale["pages"][0]["renderRequest"]["image"]["status"] != "ready"
    with pytest.raises(OperationsManualArtifactError, match="stale"):
        document_draft_render_path(tmp_path, export_number, stale, stale["pages"][0])


@pytest.mark.parametrize("paper", ["Letter", "A4"])
@pytest.mark.parametrize("kind,route", MMLE_ROUTES)
def test_real_preset_pdf_and_docx_sizes_with_fresh_captures(mmle_client, kind, route, paper, tmp_path):
    before = _real(mmle_client, route)
    changed = command(mmle_client, route, before, setup(kind, paper))
    assert changed.status_code == 200, changed.text
    document = changed.json()["document"]
    root = tmp_path / "captures"
    document = capture_document(root, document, route)
    size = layout.geometry(kind, setup(kind, paper)).page
    if kind == PARTS:
        payload = parts_pdf.build_manual_pdf_bytes(root, "MMLE-50D", document)
        word = None
    elif kind == SPEC:
        payload = spec_pdf.build_specification_pdf_bytes(document, render_root=root, assembly_number="MMLE-50D")
        word = spec_pdf.build_specification_docx_bytes(document, render_root=root, assembly_number="MMLE-50D")
        fillable, _ = spec_pdf.build_specification_fillable_pdf_bytes(document, render_root=root, assembly_number="MMLE-50D")
        with fitz.open(stream=fillable, filetype="pdf") as pdf:
            assert (pdf[0].rect.width, pdf[0].rect.height) == pytest.approx((size["width"], size["height"]), abs=.01)
    else:
        payload = operations_pdf.build_prototype_pdf_bytes(root, "MMLE-50D", document)
        word = operations_pdf.build_prototype_docx_bytes(root, "MMLE-50D", document)
    with fitz.open(stream=payload, filetype="pdf") as pdf:
        assert len(pdf) == document["pageCount"]
        for page in pdf:
            assert (page.rect.width, page.rect.height) == pytest.approx((size["width"], size["height"]), abs=.01)
        if kind == OPS:
            contents = next(p for p in document["pages"] if p["pageType"] == "operations_contents")
            for entry in contents["entries"]:
                if entry["sourceKey"] not in {"document-control", "contents"}:
                    heading_page = next(p for p in document["pages"] if p.get("sectionId") == entry["sourceKey"])
                    assert heading_page["pageNumber"] == entry["pageNumber"]
                    normalize = lambda text: " ".join(text.split())
                    assert normalize(entry["title"]) in normalize(pdf[entry["pageNumber"]-1].get_text())
        if kind == PARTS:
            assert all(len(p.get("bom", [])) <= 20 for p in document["pages"])
            assert {p["pageId"]: len(p.get("bom", [])) for p in document["pages"]} == {
                p["pageId"]: len(p.get("bom", [])) for p in before["document"]["pages"]}
    if word is not None:
        for section in Document(io.BytesIO(word)).sections:
            assert (section.page_width.pt, section.page_height.pt) == pytest.approx((size["width"], size["height"]), abs=.03)
            assert section.orientation == (WD_ORIENT.PORTRAIT if kind == SPEC else WD_ORIENT.LANDSCAPE)

@pytest.mark.parametrize("module,name,kind", [(parts_layout, "publication_layout", PARTS),
    (flow, "publication_layout", OPS), (spec_document, "specification_sheet_layout", SPEC)])
def test_identity_layout_contract_bytes_equal_p4a2(module, name, kind, monkeypatch):
    previous = legacy_module(module, monkeypatch, COMMIT)
    expected = getattr(previous, name)()
    actual = getattr(module, name)(layout.geometry(kind))
    assert json.dumps(actual, ensure_ascii=True) == json.dumps(expected, ensure_ascii=True)


def test_scene_setting_replay_and_restore_absence(scene):
    before = scene.load()
    command_value = {"operation": "set_page_setup", "pageId": PAGE, "targetType": "document_page_setup",
                     "targetId": "page-setup", "pageSetup": setup(OPS)}
    changed = scene.repo.apply_command(NUMBER, scene.base["sourceRevision"], scene.base["manualPlanRevision"],
        base_revision=before["revision"], identity_document=scene.base, page_targets={PAGE: {}}, command=command_value)
    record = changed["command"]["change"]
    assert record["changes"] == [{"path": ["pageSetup"], "before": {"present": False},
                                 "after": {"present": True, "value": setup(OPS)}}]
    assert documentation_scene_revision(changed["scene"]) != before["revision"]
    after = history(scene, "undo")
    assert "pageSetup" not in after["scene"]
    assert history(scene, "redo")["scene"]["pageSetup"] == setup(OPS)
    # A pre-journal cursor before the setting must not preserve the last replayed value.
    old_cursor = deepcopy(changed["scene"])
    old_cursor["historyCursor"] -= 1
    assert "pageSetup" not in _upgrade_documentation_scene(old_cursor)


@pytest.mark.parametrize("delta,kept", [(0, False), (-2, False), (3.9, False), (4.0, False), (4.1, True)])
def test_new_failures_compares_excess_not_page_or_absolute_height(delta, kept):
    current = [{"targetId": "body", "pageId": "old-page", "reason": "text_does_not_fit",
                "measuredHeight": 50, "frame": [10, 20, 110, 60]}]
    candidate = [{"targetId": "body", "pageId": "new-page", "reason": "text_does_not_fit",
                  "measuredHeight": 90 + delta, "frame": [10, 30, 110, 110]}]
    assert fit.new_failures(current, candidate) == (candidate if kept else [])


def test_new_failures_uses_largest_excess_and_requires_measurements():
    def item(page, height=None, reason="text_does_not_fit", target="body"):
        return {"pageId": page, "targetId": target, "reason": reason,
                **({"frame": [0, 10, 100, 50], "measuredHeight": height} if height is not None else {})}
    current = [item("p1", 45), item("p2", 65), item("p3"), item("p4", target="unknown-size")]
    candidates = [item("p5", 68.9), item("p6", 69.1), item("p7"), item("p8", 100, target="unknown-size"),
                  item("p9", reason="outside_page"), item("p10", target="new")]
    before = deepcopy((current, candidates))
    assert fit.new_failures(current, candidates) == [candidates[1], candidates[4], candidates[5]]
    assert (current, candidates) == before
    assert fit.new_failures([], candidates) == candidates
    assert fit.new_failures(current, []) == []


@pytest.mark.parametrize("kind,route", MMLE_ROUTES)
@pytest.mark.parametrize("own_error", [False, True])
def test_candidate_compiler_error_is_layout_refusal_without_writing(mmle_client, monkeypatch, kind, route, own_error):
    import server
    from ai_inspector.parts_manual.schema import PartsManualValidationError
    from ai_inspector.operations_manual.evidence import OperationsManualEvidenceError
    from ai_inspector.work_instructions.document import WorkInstructionError
    from ai_inspector.specification_sheet.document import SpecificationSheetError
    before = _real(mmle_client, route)
    name = {PARTS: "build_manual_document", OPS: "build_operations_manual_document",
            WI: "_work_instruction_document_for_scene", SPEC: "_specification_sheet_compile"}[kind]
    original = getattr(server, name)
    error_type = {PARTS: PartsManualValidationError, OPS: OperationsManualEvidenceError,
                  WI: WorkInstructionError, SPEC: SpecificationSheetError}[kind] if own_error else ValueError
    def compile_document(*args, **kwargs):
        scene = kwargs.get("scene") if kind == WI else kwargs.get("documentation_scene")
        if scene and scene.get("pageSetup"):
            raise error_type("candidate frame cannot be placed")
        return original(*args, **kwargs)
    monkeypatch.setattr(server, name, compile_document)
    response = command(mmle_client, route, before, setup(kind))
    assert response.status_code == 409, response.text
    payload = response.json()
    assert payload["error"] == "layout_overflow"
    assert payload["message"] == "This publication cannot be laid out on this page setup: candidate frame cannot be placed"
    assert not payload.get("targets") and not payload.get("details", {}).get("targets")
    after = _real(mmle_client, route)
    assert after["scene"] == before["scene"] and after["document"] == before["document"]


@pytest.mark.parametrize("kind", layout.DESIGN)
@pytest.mark.parametrize("result", [{}, {"scene": None}, {"receipt": {"changeId": "receipt-only"}}])
def test_page_setup_options_for_answers_without_a_scene(kind, result):
    import server
    assert server._documentation_page_setup_options({"documentType": kind}, result) == layout.page_setup_options(kind, {})


@pytest.mark.parametrize("builder", BUILDERS)
def test_export_never_calls_fit_report(builder, tmp_path, image_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("An export must not run the diagnostic fit pass")
    for module in (parts_pdf, operations_pdf, spec_pdf):
        monkeypatch.setattr(module, "fit_report", forbidden)
    assert build(builder, attach(fixture_document(builder), mixed()), tmp_path).startswith(b"%PDF")


@pytest.mark.parametrize("kind,route", [(PARTS, "parts-manual"), (SPEC, "specification-sheet")])
def test_identity_letter_preserves_captures(mmle_client, kind, route, tmp_path):
    before = _real(mmle_client, route)
    root = tmp_path / "capture-proof"
    captured = capture_document(root, before["document"], route)
    images_before = {p["pageId"]: p["renderRequest"]["image"]["sha256"]
                     for p in captured["pages"] if p.get("renderRequest")}
    files_before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    response = command(mmle_client, route, before, setup(kind, "Letter"))
    assert response.status_code == 200, response.text
    current = response.json()["document"]
    assert figure_revisions(current) == figure_revisions(before["document"])
    if kind == PARTS:
        from ai_inspector.parts_manual.artifacts import attach_render_artifacts
        ready = attach_render_artifacts(root, "MMLE-50D", current)
    else:
        from ai_inspector.operations_manual.artifacts import attach_draft_render_artifacts
        ready = attach_draft_render_artifacts(root, "MMLE-50D", {**current, "documentRevision": current["figureRevision"]})
    images_after = {p["pageId"]: p["renderRequest"]["image"]["sha256"]
                    for p in ready["pages"] if p.get("renderRequest") and p["renderRequest"]["image"]["status"] == "ready"}
    assert images_after == images_before
    assert files_before == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("kind,route", [(WI, "work-instructions"), (SPEC, "specification-sheet")])
def test_fixed_block_geometry_inventory(mmle_client, kind, route):
    before = _real(mmle_client, route)
    response = command(mmle_client, route, before, setup(kind))
    assert response.status_code == 200, response.text
    after = response.json()["document"]
    g = layout.geometry(kind, setup(kind))
    for old_page, new_page in zip(before["document"]["pages"], after["pages"]):
        for old, new in zip(old_page.get("layoutBlocks", []), new_page.get("layoutBlocks", [])):
            assert new["frame"] == g.rect(old["frame"])
            for key in ("style", "fontSize", "columns", "columnWidths", "items", "rows"):
                if key in old:
                    assert new[key] == old[key], key  # Typography, counts, fractions and semantic items are not lengths.
            if "rowHeights" in old:
                assert new["rowHeights"] == [g.h(h) for h in old["rowHeights"]]
            if "columnGap" in old:
                assert new["columnGap"] == g.w(old["columnGap"])
            # Neither compiler emits nested item/cell frames or standalone point positions.
            assert not list(frames({k: v for k, v in old.items() if k != "frame"}))
            assert not ({"x", "y", "width", "height", "columnPositions", "itemFrames", "padding", "radius"} & old.keys())


def test_fit_attribution_uses_the_drawn_element_and_alias(tmp_path):
    document = fixture_document("parts")
    page = document["pages"][0]
    document["aliasMap"] = {page["pageId"]: {
        "contents_heading": {"targetId": "stable-contents-heading"},
        "header_title": {"targetId": "stable-header-title"}}}
    report = parts_pdf.fit_report(tmp_path, "PROOF", document)
    assert any(r["targetId"] == "stable-contents-heading" and r["reason"] == "text_does_not_fit" for r in report)
    assert not any(r["targetId"] in {page["pageId"], "stable-header-title"} for r in report)


@pytest.mark.parametrize("case", ["glyph", "rotation", "overflow"])
def test_rich_pdf_refusal_messages_match_committed_code(case, tmp_path, monkeypatch):
    from ai_inspector.documentation import rich_layout
    from ai_inspector.documentation.rich_text import from_plain
    frame = {"x": .1, "y": .2, "width": .5, "height": .4, "rotation": 0}
    value = "Text"
    if case == "glyph":
        value = "Text \U0001f642"
    elif case == "rotation":
        frame["rotation"] = 90
    else:
        frame["height"] = .01
        value = "Text\n" * 20
    document = _fit_document("operations", from_plain(value), frame=frame)
    previous = legacy_module(rich_layout, monkeypatch, COMMIT)
    with pytest.raises(DocumentEditError) as old:
        previous.prepare_pdf_objects(fitz, document, (960, 540))
    with pytest.raises(DocumentEditError) as new:
        rich_layout.prepare_pdf_objects(fitz, document, (960, 540))
    assert new.value.code == old.value.code and str(new.value) == str(old.value)
    old_details = deepcopy(new.value.details)
    for target in old_details.get("targets", []):
        target.pop("reason", None)
    assert old_details == old.value.details


# --- Supervisor additions (P4b-1 gate) ---

def test_html_drawn_items_keep_the_renderers_need_on_a_stretched_page():
    """The HTML renderer breaks a line 2 pt before the Helvetica width the flow engine measures, and draws a
    label and a quantity in bold. On A4 one item of the real manual was 0.9 pt short of its column: the layout
    kept one row for it and the export refused the page. The design page keeps its old estimate."""
    design = flow.FlowLayoutEngine()
    assert design._html_width(500.0, "Label", 3, 9.4) == 500.0
    assert design._html_width(500.0, "Label", 3, 9.4, short=4.0) == 500.0
    paper = flow.FlowLayoutEngine(geometry=layout.geometry(OPS, setup(OPS)))
    plain = paper._html_width(500.0, "", 1, 9.4)
    assert plain == pytest.approx(497.5)
    assert paper._html_width(500.0, "", 1, 9.4, short=4.0) == pytest.approx(493.5)
    assert paper._html_width(500.0, "Label words", 1, 9.4) < plain - 1
    assert paper._html_width(500.0, "", 3, 9.4) < plain - 10


@pytest.mark.parametrize("size", [7.2, 7.8, 9.4])
def test_the_renderers_need_is_what_the_estimate_reserves(size):
    """The measurement behind the 2.5 pt: a one-line HTML box needs the Helvetica width plus 2 pt."""
    text = "Remove the lift from service and request qualified electrical or battery service before use"
    css = "div { font-family: Arial, sans-serif; font-size: %spt; line-height: 1.22; }" % size
    width = fitz.get_text_length(text, fontname="helv", fontsize=size)
    page = fitz.open().new_page(width=900, height=200)
    def fits(extra):
        spare, scale = page.insert_htmlbox(fitz.Rect(20, 20, 20 + width + extra, 20 + size * 1.22 + 3),
                                           "<div>%s</div>" % text, css=css, scale_low=1)
        return spare >= 0 and scale == 1
    assert not fits(1.0)
    assert fits(2.5)


def test_old_findings_of_the_design_page_do_not_block_another_paper_or_the_way_back(mmle_client):
    """The contents block of the real operations manual is 5 pt over its frame on the design page and fits on
    Letter. Going from Letter to A4, and clearing the setup, must not be refused for it."""
    route = "operations-manual"
    before = _real(mmle_client, route)
    response = command(mmle_client, route, before, setup(OPS, "Letter"))
    assert response.status_code == 200, response.text
    response = command(mmle_client, route, response.json(), setup(OPS))
    assert response.status_code == 200, response.text
    on_a4 = response.json()
    assert on_a4["document"]["publicationLayout"]["page"]["width"] == pytest.approx(841.89)
    response = command(mmle_client, route, on_a4, None)
    assert response.status_code == 200, response.text
    assert "pageSetup" not in response.json()["document"]
    assert len(response.json()["document"]["pages"]) == len(before["document"]["pages"])
