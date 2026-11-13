"""Generated inputs for the server benchmark; all stores and evidence are supplied temp roots.

Only the operations content provider is replaced: it normally supplies a fixed,
product-specific manuscript. The real document compiler, flow planner, identity,
scene, capture validation and export paths run unchanged.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

NUMBER = "BENCH"
KINDS = {"parts": "illustrated_parts_manual", "operations": "operations_and_maintenance_manual"}


def profile(count):
    parts = [f"part-{i:05d}" for i in range(count)]
    return {"identity": {"assemblyNumber": NUMBER, "description": "Benchmark fixture", "revision": "A"},
        "statistics": {"totalComponents": count, "uniquePartCount": count, "totalMates": 0},
        "components": [{"name": name + "-1", "type": "Part", "level": 1,
            "activeConfiguration": "Default", "partDataKey": name + ".sldprt",
            "referencedFileName": name + ".SLDPRT", "transform": {"translation": [i * .01, 0, 0]}}
            for i, name in enumerate(parts)],
        "partDataCache": {name + ".sldprt": {"identity": {"partNumber": f"B-{i:05d}",
            "description": "Machined mounting component", "customProperties": {"PartNo": f"B-{i:05d}"}}}
            for i, name in enumerate(parts)},
        "partColorMapping": {}, "mates": [], "mateRelationships": [], "explodeSteps": []}


def sections(count):
    from ai_inspector.operations_manual.content import _section, _heading, _paragraph, _figure
    return [_section(f"bench-{i}", f"Service procedure {i+1}", [
        _heading(f"heading-{i}", 1, f"Service procedure {i+1}"),
        _paragraph(f"body-{i}", 2, "Inspect the mounting components and check their condition before service. " * 12),
        # Supervisor: the manual's own figure height. A lower frame is wider than the capture envelope allows
        # (4096 x 3072 px) and the compiler refuses it.
        _figure(f"figure-{i}", 3, "OM-FIG-001", "Benchmark managed CAD fixture", claims=(), height=320)])
        for i in range(count)]


def compile_document(root, inputs, scene=None, revision=None):
    if inputs["kind"] == "parts":
        from ai_inspector.parts_manual.document import build_manual_document
        return build_manual_document(inputs["plan"], inputs["catalog"]["occurrences"], inputs["profile"],
            plan_revision=inputs["planRevision"], documentation_scene=scene, documentation_scene_revision=revision)
    from ai_inspector.operations_manual import document
    with patch.object(document, "prototype_sections", lambda *args, **kwargs: sections(inputs["sections"])):
        return document.build_operations_manual_document(inputs["profile"], inputs["catalog"],
            evidence_root=root / "e" / "source", documentation_scene=scene, documentation_scene_revision=revision)


def fixtures():
    # Reuse the tracked, validated synthetic CAD image/manifest generators used by P0.
    # Extract just functions, not the pytest module or its fixtures.
    import io
    from PIL import Image, ImageDraw
    from tools.documentation_baseline import fixture_functions
    from ai_inspector.parts_manual.version import PARTS_MANUAL_DEFAULT_END_CONDITION
    return fixture_functions("tests/test_parts_manual.py", ["_png", "_valid_balloon"],
        {"io": io, "Image": Image, "ImageDraw": ImageDraw,
         "PARTS_MANUAL_DEFAULT_END_CONDITION": PARTS_MANUAL_DEFAULT_END_CONDITION})


def capture(root, document, png, helpers):
    if document["documentType"] == KINDS["parts"]:
        from ai_inspector.parts_manual.artifacts import store_render_artifact, attach_render_artifacts
        for page in document["pages"]:
            if not page.get("renderRequest"): continue
            rows = page["renderRequest"].get("calloutItems", [])
            balloons = []
            # Short, disjoint leaders in up to four lanes (48 groups at 100 pages).
            # The real manifest validator checks every route and balloon; no readiness bypass.
            for i, row in enumerate(rows):
                value = helpers["_valid_balloon"](row, i % 12, 12)
                offset = .10 + (i // 12) * .23
                placed = set()
                def place(v):
                    # The fixture shares bounds dictionaries between its anchor and projected regions.
                    if isinstance(v, (list, dict)):
                        if id(v) in placed: return
                        placed.add(id(v))
                    if isinstance(v, list):
                        for child in v: place(child)
                    elif isinstance(v, dict):
                        if "x" in v: v["x"] = offset + (v["x"] - .40) * .5
                        if "left" in v and "right" in v:
                            v["left"], v["right"] = offset + (v["left"]-.40)*.5, offset + (v["right"]-.40)*.5
                        for child in v.values(): place(child)
                place(value)
                balloons.append(value)
            store_render_artifact(root, NUMBER, document, page["pageId"], png, balloons=balloons)
        return attach_render_artifacts(root, NUMBER, document)
    from ai_inspector.operations_manual.artifacts import store_draft_render_artifact, attach_draft_render_artifacts
    for page in document["pages"]:
        if page.get("renderRequest"):
            store_draft_render_artifact(root, NUMBER, document, page["pageId"], png,
                source_revision=document["sourceRevision"], manual_plan_revision=document["manualPlanRevision"])
    return attach_draft_render_artifacts(root, NUMBER, document)


def attached(root, document):
    if document["documentType"] == KINDS["parts"]:
        from ai_inspector.parts_manual.artifacts import attach_render_artifacts
        return attach_render_artifacts(root, NUMBER, document)
    from ai_inspector.operations_manual.artifacts import attach_draft_render_artifacts
    return attach_draft_render_artifacts(root, NUMBER, document)


def prepare(root, kind, requested):
    from ai_inspector.parts_manual import build_occurrence_catalog, PartsManualRepository
    from ai_inspector.parts_manual.documentation import DocumentationSceneRepository
    from ai_inspector.documentation.rich_text import from_plain
    from ai_inspector.documentation.tables import apply as table_apply
    from ai_inspector.documentation.layout import geometry
    from ai_inspector.operations_manual.document import _contents_capacity
    root.mkdir(parents=True, exist_ok=True)
    n = max(1, (requested - 4 + 1)//2) if kind == "parts" else 1
    if kind == "operations":
        capacity = _contents_capacity(geometry(KINDS[kind], None))
        while n + 2 + (n+2+capacity-1)//capacity < requested: n += 1
    data = profile(n*20 if kind == "parts" else 1)
    catalog = build_occurrence_catalog(NUMBER, data)
    inputs = {"kind": kind, "profile": data, "catalog": catalog, "sections": n, "requestedPages": requested}
    if kind == "parts":
        plans = PartsManualRepository(root)
        loaded = plans.read(NUMBER, catalog["sourceRevision"])
        rows = catalog["occurrences"]
        for i in range(n):
            loaded = plans.create_section(NUMBER, catalog["sourceRevision"], base_revision=loaded["revision"],
                name=f"Mounting group {i+1}", occurrence_ids=[r["occurrenceId"] for r in rows[i*20:(i+1)*20]], catalog=rows)
        inputs.update(plan=loaded["plan"], planRevision=loaded["revision"])
    else:
        evidence = root / "e" / "source"; evidence.mkdir(parents=True)
        # Supervisor: the compiler reads these three claims for its fixed front pages (cover, document control,
        # about this manual). Generated statements, no sources: the benchmark publishes nothing.
        claims = [{"claimId": claim_id, "statement": statement, "sourceIds": [], "status": "benchmark_fixture"}
                  for claim_id, statement in (
                      ("CLM-IDENTITY-001", "Benchmark fixture assembly BENCH, revision A."),
                      ("CLM-USE-001", "Generated publication for timing the documentation editor."),
                      ("CLM-CAD-001", "Generated CAD occurrence list of the benchmark fixture."))]
        for filename, value in {"source-register.json": {"sources": []}, "evidence-register.json": {"claims": claims},
            "mmle-50d-prototype-plan.example.json": {}, "safety-symbol-register.json": {"status": "approved", "symbols": []}}.items():
            (evidence / filename).write_text(json.dumps(value), encoding="utf-8")
        # Supervisor: a section with the manual's figure height takes more than one page, so the number of
        # sections for the requested page count is found by compiling (the estimate above is the upper bound).
        low, high = 1, n
        while low < high:
            middle = (low + high + 1) // 2
            if len(compile_document(root, {**inputs, "sections": middle})["pages"]) <= requested:
                low = middle
            else:
                high = middle - 1
        inputs["sections"] = low
    baseline = compile_document(root, inputs)
    inputs["planRevision"] = baseline["manualPlanRevision"]
    repo = DocumentationSceneRepository(root, KINDS[kind])
    binding = (NUMBER, baseline["sourceRevision"], baseline["manualPlanRevision"])
    loaded = repo.read(*binding, identity_document=baseline)
    helpers = fixtures(); png = helpers["_png"](2400, 1800)
    key = hashlib.sha256(png).hexdigest()
    image_path = root / NUMBER.lower() / "documentation-assets" / (key + ".png")
    image_path.parent.mkdir(parents=True, exist_ok=True); image_path.write_bytes(png)
    for page in baseline["pages"]:
        if page["pageNumber"] % 10: continue
        rich = from_plain("Benchmark rich note")
        rich["doc"]["content"][0]["content"][0]["marks"] = [{"type": "bold"}]
        table, _ = table_apply(from_plain(""), {"operation": "create_table", "rows": 2, "columns": 2,
                                              "headerRow": True}, width=180)
        for row, labels in zip(table["doc"]["content"][-1]["content"], (("Item", "Setting"), ("Mount", "10 N m"))):
            for cell, label in zip(row["content"], labels):
                cell["content"][0]["content"] = [{"type": "text", "text": label}]
        values = [("text", rich), ("text", table), ("image", ""), ("shape", "")]
        for i, (object_type, content) in enumerate(values):
            object_id = f"document-object-bench-{page['pageNumber']}-{i}"
            # Supervisor: a text object is created plain and then given its rich content, as the product does.
            value = {"objectId": object_id, "type": object_type, "name": "Benchmark " + object_type,
                "source": "user", "frame": {"x": .06 + i*.23, "y": .65, "width": .21, "height": .24},
                "content": "", "styleOverrides": {"fontSize": 9}}
            if object_type == "image": value.update(asset={"assetId": key, "filename": "cad.png", "mimeType": "image/png",
                "url": f"/api/parts-manual/{NUMBER}/documentation-assets/{key}"}, contentMode="contain")
            if object_type == "shape": value.update(shapeType="rectangle", styleOverrides={"fill": "#c7e1f2"})
            loaded = repo.apply_command(*binding, base_revision=loaded["revision"], identity_document=baseline,
                page_targets={page["pageId"]: {}}, command={"operation": "add_object", "pageId": page["pageId"],
                    "targetType": "document_object", "targetId": object_id, "documentObject": value})
            if object_type == "text":
                loaded = repo.apply_command(*binding, base_revision=loaded["revision"], identity_document=baseline,
                    page_targets={page["pageId"]: {"document_object": [object_id]}},
                    command={"operation": "replace_rich_text", "pageId": page["pageId"],
                             "targetType": "document_object", "targetId": object_id, "richText": content})
    # Even the smallest case has a real persisted scene, not an ephemeral empty-read fast path.
    loaded = repo.apply_command(*binding, base_revision=loaded["revision"], identity_document=baseline,
        page_targets={baseline["pages"][0]["pageId"]: {"page_element": ["header_title"]}},
        command={"operation": "update_text", "pageId": baseline["pages"][0]["pageId"],
                 "targetType": "page_element", "targetId": "header_title", "text": "Benchmark publication"})
    document = compile_document(root, inputs, loaded["scene"], loaded["revision"])
    capture(root, document, png, helpers)
    (root / "input.json").write_text(json.dumps(inputs), encoding="utf-8")
    (root / "base.json").write_text(json.dumps(baseline), encoding="utf-8")
    return inputs
