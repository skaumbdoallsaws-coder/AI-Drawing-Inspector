"""P5a-only fixture switching in the sanitized server. Never imported by production.

Model-free assemblies cannot enter the workspace (has_glb is required). Preserve
the real MMLE model/catalogue and use the documented fallback: real plan commands
and an appended manuscript. Only temporary plan/scene files are switched; accepted
captures remain in the real artifact stores under their revision keys.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import threading
import time


def counts(document, scene_path):
    return {"pages": len(document["pages"]),
        "blocks": sum(len(p.get("layoutBlocks", [])) for p in document["pages"]),
        "objects": sum(len(p.get("documentationObjects", {})) for p in document["pages"]),
        "bomRows": sum(len(p.get("bom", [])) for p in document["pages"]),
        "figures": sum(bool(p.get("renderRequest")) for p in document["pages"]),
        "groups": sum(len(p.get("manualGroupItems", [])) for p in document["pages"])
            if any(p.get("pageType") == "assembly_overview" for p in document["pages"]) else len(document.get("sections", [])),
        "sceneBytes": scene_path.stat().st_size if scene_path.exists() else 0}


def install_scale_fixtures(server, scratch):
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from tools.documentation_benchmark_support import prepare, compile_document, capture, fixtures, sections
    from ai_inspector.documentation.rich_text import from_plain
    from ai_inspector.documentation.tables import apply as table_apply
    from ai_inspector.parts_manual.documentation import DocumentationSceneRepository
    from ai_inspector.parts_manual.document import build_manual_document
    from ai_inspector.operations_manual import document as operations

    scratch = Path(scratch).resolve()
    number = "MMLE-50D"
    # Supervisor: sizes of the small parts, large parts and operations fixtures (a debug run may shrink them).
    sizes = [int(value) for value in os.environ.get("INSPECTORPRO_DOC_SMOKE_P5A_PAGES", "50,100,50").split(",")]
    with_generated = os.environ.get("INSPECTORPRO_DOC_SMOKE_P5A_GENERATED") == "1"
    roots = {"parts": server.PARTS_MANUAL_ROOT, "operations": server.OPERATIONS_MANUAL_ROOT}
    lock = threading.RLock()
    variants, inventory, generated_profiles = {}, {}, {}
    control = scratch / "p5a-operations.json"
    original_sections = operations.prototype_sections
    original_build = server.build_operations_manual_document

    def manuscript(*args, **kwargs):
        value = json.loads(control.read_text("ascii")) if control.exists() else {}
        extra = sections(value.get("sections", 0))
        if value.get("tailText"):
            tail = sections(value.get("sections", 0) + 1)[-1]
            tail["blocks"] = [b for b in tail["blocks"] if b["blockType"] != "cad_figure"]
            extra.append(tail)
        return original_sections(*args, **kwargs) + extra

    def build(*args, **kwargs):
        # Keep the harness-only provider swap inside the same lock as fixture switching.
        with lock:
            previous = operations.prototype_sections
            operations.prototype_sections = manuscript
            try:
                return original_build(*args, **kwargs)
            finally:
                operations.prototype_sections = previous

    def files(kind):
        directory = roots[kind] / number.lower()
        return [directory / name for name in (("manual-plan.json", "documentation-scene.json")
                if kind == "parts" else ("documentation-scene.json",))]

    def remember(kind):
        return {p.name: p.read_bytes() if p.exists() else None for p in files(kind)}

    def restore(kind, values):
        for p in files(kind):
            p.parent.mkdir(parents=True, exist_ok=True)
            if values[p.name] is None:
                p.unlink(missing_ok=True)
            else:
                temporary = p.with_suffix(".p5a-tmp")
                temporary.write_bytes(values[p.name])
                os.replace(temporary, p)

    def checked(value):
        if isinstance(value, JSONResponse):
            raise RuntimeError(value.body.decode("utf-8"))
        return value

    # Required benchmark fixtures, in the phase's stores, never on the library path.
    # They are not substituted for a live CAD model or a renderer.
    # Supervisor: only on request. They cost seven minutes of start-up and no workspace can open them.
    for key, kind, size, assembly in ((("generated-p50", "parts", 50, "SCALE-P50"),
            ("generated-p100", "parts", 100, "SCALE-P100"),
            ("generated-o50", "operations", 50, "SCALE-O50")) if with_generated else ()):
        started = time.monotonic()
        inputs = prepare(roots[kind], kind, size, assembly_number=assembly)
        server.assembly_profiles[assembly] = inputs["profile"]
        generated_profiles[assembly] = inputs["profile"]
        repo = DocumentationSceneRepository(roots[kind], "illustrated_parts_manual" if kind == "parts"
                                            else "operations_and_maintenance_manual")
        loaded = repo.read(assembly, inputs["catalog"]["sourceRevision"], inputs["planRevision"])
        document = compile_document(roots[kind], inputs, loaded["scene"], loaded["revision"])
        inventory[key] = {"assembly": assembly, "requestedPages": size,
            "path": "not opened: workspace requires has_glb; use MMLE fallback",
            "prepareSeconds": round(time.monotonic() - started, 1),
            **counts(document, roots[kind] / assembly.lower() / "documentation-scene.json")}

    server.build_operations_manual_document = build
    assembly, catalog = server._parts_manual_catalog_for_assembly(number)
    # Loading the real catalogue can reload the assembly library. Keep the
    # generated profiles for HTTP-only PDF evidence, not for a fake model view.
    server.assembly_profiles.update(generated_profiles)
    helpers = fixtures(); png = helpers["_png"](2400, 1800)

    def author(kind, baseline, extra=None):
        """Use public commands; every tenth page has the same four kinds as the benchmark."""
        repo = DocumentationSceneRepository(roots[kind], baseline["documentType"])
        binding = (number, baseline["sourceRevision"], baseline["manualPlanRevision"])
        loaded = repo.read(*binding, identity_document=baseline)
        import hashlib
        asset = hashlib.sha256(png).hexdigest()
        # Every browser image route is the shared parts asset route.
        for root in {roots[kind], roots["parts"]}:
            p = root / number.lower() / "documentation-assets" / (asset + ".png")
            p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(png)
        for page in baseline["pages"]:
            if page["pageNumber"] % 10 and page["pageId"] != extra: continue
            rich = from_plain("Scale text")
            rich["doc"]["content"][0]["content"][0]["marks"] = [{"type": "bold"}]
            table, _ = table_apply(from_plain(""), {"operation": "create_table", "rows": 2, "columns": 2,
                "headerRow": True}, width=180)
            for row in table["doc"]["content"][-1]["content"]:
                for cell in row["content"]:
                    cell["content"][0]["content"] = [{"type": "text", "text": "Cell"}]
            for i, (typ, content) in enumerate((("text", rich), ("text", table), ("image", None), ("shape", None))):
                oid = f"document-object-p5a-{page['pageNumber']}-{i}"
                obj = {"objectId": oid, "type": typ, "source": "user", "name": f"Scale {typ} {page['pageNumber']} {i}",
                    "content": "", "frame": {"x": .04 + .24*i, "y": .65, "width": .22, "height": .24},
                    "styleOverrides": {"fontSize": 9, "fill": "#ffffff"}}
                if typ == "shape": obj.update(shapeType="rectangle", styleOverrides={"fill": "#c7e1f2"})
                if typ == "image": obj.update(contentMode="contain", asset={"assetId": asset, "mimeType": "image/png",
                    "filename": "fixture.png", "url": f"/api/parts-manual/{number}/documentation-assets/{asset}"})
                loaded = repo.apply_command(*binding, base_revision=loaded["revision"], identity_document=baseline,
                    page_targets={page["pageId"]: {}}, command={"operation": "add_object", "pageId": page["pageId"],
                    "targetType": "document_object", "targetId": oid, "documentObject": obj})
                if content:
                    loaded = repo.apply_command(*binding, base_revision=loaded["revision"], identity_document=baseline,
                        page_targets={page["pageId"]: {"document_object": [oid]}}, command={"operation": "replace_rich_text",
                        "pageId": page["pageId"], "targetType": "document_object", "targetId": oid, "richText": content})
        return loaded

    base = {kind: remember(kind) for kind in roots}
    variants["base"] = {"files": deepcopy(base), "operations": {}}
    for key, size in (("parts50", sizes[0]), ("parts100", sizes[1])):
        started = time.monotonic()
        restore("parts", base["parts"])
        # A scale fixture has its own scene. The real MMLE scene is retained above, byte for byte.
        files("parts")[-1].unlink(missing_ok=True)
        plans = server._parts_manual_repository()
        loaded = plans.read(number, catalog["sourceRevision"], known_occurrence_ids=[r["occurrenceId"] for r in catalog["occurrences"]])
        # Supervisor: a plan is publishable only when every part is assigned, and two groups may share a part
        # only when one contains the other. So the real plan stays, and the chain of nested service groups
        # hangs under the real group with the most distinct parts and reuses them (16 on MMLE-50D, the size of
        # the product's own largest parts list; the server benchmark's generated assembly has 20).
        children = {s.get("parentSectionId") for s in loaded["plan"]["sections"]}
        by_occurrence = {r["occurrenceId"]: r for r in catalog["occurrences"]}
        choices = []
        for section in loaded["plan"]["sections"]:
            unique = {}
            for oid in section["occurrenceIds"]:
                row = by_occurrence[oid]
                if row.get("kind") == "part" and not row.get("suppressed"):
                    unique.setdefault(row["definitionId"], oid)
            if section["sectionId"] not in children and section.get("includeInManual", True):
                choices.append((len(unique), section["sectionId"], list(unique.values())[:20]))
        if not choices or max(choices)[0] < 10:
            raise RuntimeError("P5a fallback has no real group with at least 10 distinct parts")
        rows_per_group, parent, occurrences = max(choices, key=lambda choice: choice[0])
        rows_per_group = len(occurrences)
        while True:
            baseline = build_manual_document(loaded["plan"], catalog["occurrences"], assembly, plan_revision=loaded["revision"])
            if len(baseline["pages"]) >= size: break
            loaded = checked(server.parts_manual_section_create(number, server.PartsManualSectionCreateBody(
                baseRevision=loaded["revision"], sourceRevision=catalog["sourceRevision"],
                name=f"Scale service group {len(loaded['plan']['sections'])+1}", occurrenceIds=occurrences,
                parentSectionId=parent)))
            parent = loaded["section"]["sectionId"]
        # Supervisor: the page the phase types on: a full parts list in the middle, with the same four objects.
        lists = [p for p in baseline["pages"] if len(p.get("bom", [])) == rows_per_group]
        typing_page = min(lists, key=lambda p: abs(p["pageNumber"] - len(baseline["pages"]) / 2))["pageId"] if lists else None
        edited = author("parts", baseline, typing_page)
        doc = build_manual_document(loaded["plan"], catalog["occurrences"], assembly, plan_revision=loaded["revision"],
            documentation_scene=edited["scene"], documentation_scene_revision=edited["revision"])
        attached_document = capture(roots["parts"], doc, png, helpers, number)
        # Supervisor: which figure pages the workspace will not treat as captured (Publish PDF needs all).
        waiting = [p["pageId"] for p in attached_document["pages"]
                   if p.get("renderRequest") and (p["renderRequest"].get("image") or {}).get("status") != "ready"]
        print("P5A-FIXTURE " + key + " status " + str(attached_document.get("status")) + " figure pages not ready: "
              + str(len(waiting)) + " " + str(waiting[:6]), flush=True)
        variants[key] = {"files": {"parts": remember("parts"), "operations": deepcopy(base["operations"])}, "operations": {}}
        inventory[key] = {"assembly": number, "kind": "illustrated_parts_manual", "route": "parts-manual",
            "requestedPages": size, "path": "MMLE plan-route fallback; nested service groups reuse the distinct parts of the largest real group",
            "prepareSeconds": round(time.monotonic() - started, 1), "rowsPerGroup": rows_per_group,
            "typingPageId": typing_page,
            **counts(doc, files("parts")[-1])}
        if key == "parts100" and os.environ.get("INSPECTORPRO_DOC_SMOKE_PROFILE") == "1":
            # Supervisor: where one open of the large parts fixture goes on the server (to server.log).
            import cProfile, io as text_io, pstats
            for label in ("first", "second"):
                profile = cProfile.Profile(); profile.enable()
                try:
                    server.parts_manual_documentation_scene_get(number)
                finally:
                    profile.disable()
                out = text_io.StringIO()
                pstats.Stats(profile, stream=out).sort_stats("cumulative").print_stats(45)
                print("P5A-PROFILE open " + key + " " + label, flush=True)
                for line in out.getvalue().splitlines():
                    if line.strip():
                        print("P5A-PROFILE " + line[:230], flush=True)
    restore("parts", base["parts"])

    # The real content provider is extended only while the scratch flag says so.
    started = time.monotonic()
    files("operations")[-1].unlink(missing_ok=True)
    best = None
    for n in range(sizes[2] + 1):
        control.write_text(json.dumps({"sections": n}), encoding="ascii", newline="\n")
        doc = build(assembly, catalog, evidence_root=server.OPERATIONS_MANUAL_EVIDENCE_ROOT)
        if len(doc["pages"]) > sizes[2]: break
        best = (n, doc)
    if best is None: raise RuntimeError("Real operations publication already exceeds the scale fixture's size")
    flag = {"sections": best[0], "tailText": len(best[1]["pages"]) < sizes[2]}
    control.write_text(json.dumps(flag), encoding="ascii", newline="\n")
    baseline = build(assembly, catalog, evidence_root=server.OPERATIONS_MANUAL_EVIDENCE_ROOT)
    edited = author("operations", baseline)
    doc = build(assembly, catalog, evidence_root=server.OPERATIONS_MANUAL_EVIDENCE_ROOT,
        documentation_scene=edited["scene"], documentation_scene_revision=edited["revision"])
    capture(roots["operations"], doc, png, helpers, number)
    variants["operations50"] = {"files": {"parts": deepcopy(base["parts"]), "operations": remember("operations")}, "operations": flag}
    inventory["operations50"] = {"assembly": number, "kind": "operations_and_maintenance_manual", "route": "operations-manual",
        "requestedPages": sizes[2], "path": "MMLE manuscript fallback; append generated sections under scratch flag",
        "prepareSeconds": round(time.monotonic() - started, 1),
        **counts(doc, files("operations")[-1])}
    restore("operations", base["operations"]); control.unlink(missing_ok=True)
    current = "base"

    async def fixture(request: Request):
        nonlocal current
        if request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            return JSONResponse(status_code=403, content={"error": "loopback only"})
        if request.method == "GET": return {"fixtures": inventory, "current": current}
        body = await request.json()
        if set(body) != {"fixture"} or body["fixture"] not in variants:
            return JSONResponse(status_code=422, content={"error": "unknown P5a fixture"})
        with DocumentationSceneRepository.transaction_lock, lock:
            if body["fixture"] != current:
                variants[current]["files"] = {kind: remember(kind) for kind in roots}
                current = body["fixture"]
                for kind in roots: restore(kind, variants[current]["files"][kind])
                control.write_text(json.dumps(variants[current]["operations"]), encoding="ascii", newline="\n")
        return {"current": current, "fixtures": inventory}

    fixture.__annotations__["request"] = Request
    server.app.add_api_route("/__p5a/fixture", fixture, methods=["GET", "POST"])
    if os.environ.get("INSPECTORPRO_DOC_SMOKE_PROFILE") == "1":
        # Supervisor: on request the documentation routes print where a request goes (to server.log). Off
        # unless the phase's profile stage names a label, so no measured request is slowed.
        import cProfile, io as text_io, pstats
        switch = {"label": None}

        def profiled(call, path):
            def wrapper(*args, **kwargs):
                label = switch["label"]
                if not label:
                    return call(*args, **kwargs)
                profile = cProfile.Profile(); began = time.monotonic(); profile.enable()
                try:
                    return call(*args, **kwargs)
                finally:
                    profile.disable()
                    out = text_io.StringIO()
                    pstats.Stats(profile, stream=out).sort_stats("cumulative").print_stats(45)
                    print("P5A-PROFILE route %s %s %.1f s" % (label, path, time.monotonic() - began), flush=True)
                    for line in out.getvalue().splitlines():
                        if line.strip():
                            print("P5A-PROFILE " + line[:230], flush=True)
            return wrapper

        endings = ("/documentation-scene", "/documentation-scene/commands", "/documentation-scene/undo",
                   "/documentation-scene/redo", "/objects")
        for route in server.app.routes:
            path = getattr(route, "path", "")
            if path.endswith(endings) and getattr(route, "dependant", None) is not None:
                route.dependant.call = profiled(route.dependant.call, path)

        async def profile_switch(request: Request):
            if request.client.host not in {"127.0.0.1", "::1", "testclient"}:
                return JSONResponse(status_code=403, content={"error": "loopback only"})
            switch["label"] = (await request.json()).get("label") or None
            return {"label": switch["label"]}

        profile_switch.__annotations__["request"] = Request
        server.app.add_api_route("/__p5a/profile", profile_switch, methods=["POST"])
    return inventory
