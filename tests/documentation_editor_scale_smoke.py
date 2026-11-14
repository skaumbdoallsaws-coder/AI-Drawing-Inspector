"""Browser half of P5a; imported only by --phase P5a.

All measured intervals start and end in one page evaluation. Playwright drives
trusted input through a binding, but its RPC latency is not a key/selection clock.
No assertion turns a missed provisional performance budget into a failed gate.
"""
from collections import Counter
import io
import json
import math
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

PARTS = "illustrated_parts_manual"
OPS = "operations_and_maintenance_manual"
SURFACE = "#documentationPublicationSurface"


def statistics(values):
    if not values or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("Missing measurement")
    ordered = sorted(values)
    n = len(ordered)
    return {"samples": values, "median": ordered[n//2] if n % 2 else sum(ordered[n//2-1:n//2+1])/2,
            "p95": ordered[math.ceil(n*.95)-1]}


def run(page, browser, request, server, output, report, record, handlers, *, T, slow):
    from tests.smoke_documentation_editor import wait_for_p4b_publication_capture
    import fitz
    from PIL import Image

    start = getattr(server, "started", time.monotonic())
    # Supervisor: the phase's time limit. 40 minutes is the gate; a longer one is for measuring a slow build.
    limit = float(os.environ.get("DOC_SMOKE_P5A_MINUTES", "40")) * 60
    # Supervisor: a debug run may name the stages it wants and shorten the open/close cycles.
    only = {name.strip() for name in os.environ.get("DOC_SMOKE_P5A_ONLY", "").split(",") if name.strip()}
    cycles = int(os.environ.get("DOC_SMOKE_P5A_CYCLES", "20"))
    skipped, older_contrast = [], {}
    failures, fixtures, documents, pdfs = set(), {}, {}, {}
    probe = Path(__file__).with_name("documentation_editor_scale_probe.js").read_text("utf-8")
    measurements = {"schemaVersion": 1, "waitFactor": slow, "deviceScale": 1,
        "viewport": page.viewport_size, "clock": "performance.now in the page; milliseconds",
        "percentile": "nearest rank", "fixtures": fixtures, "measurements": {}, "findings": {},
        "accessibility": [], "scaling": [], "cycles": {}, "paths": {}}
    destination = output / "p5a-measurements.json"
    report["p5a"] = {"measurements": destination.name}
    outer_record = record

    def flush():
        destination.write_text(json.dumps(measurements, indent=2, ensure_ascii=True) + "\n", encoding="ascii", newline="\n")

    def record(name, ok, detail=None):
        name = "p5a_" + name
        if name not in failures:
            outer_record(name, ok, detail)
        if not ok:
            failures.add(name)
            # Supervisor: a failed check is in the measurements file at once, not only in the final report.
            measurements.setdefault("failedChecks", []).append({"name": name, "at": round(time.monotonic() - start, 1),
                "detail": json.dumps(detail, default=str)[:1500]})
        flush()

    def progress(name):
        measurements["progress"] = {"at": round(time.monotonic() - start, 1), "doing": name}
        flush()

    def step(name, action):
        if time.monotonic() - start >= limit:
            record(name, False, "The phase's time limit expired before this check.")
            return None
        progress(name)
        try:
            return action()
        except Exception as error:
            record(name, False, {"error": type(error).__name__, "message": str(error)[:1800]})
            return None

    def stage(name, action):
        if only and name not in only:
            skipped.append(name)
            return None
        return step(name, action)

    page.context.add_init_script(script=probe)

    def bounded(call, spec):
        # Supervisor: an action whose page code never answers ends with an error instead of holding the phase.
        return page.evaluate("spec => Promise.race([" + call + ", new Promise((_, reject) => setTimeout("
            "() => reject(Error('P5a action ' + spec.action + ' did not finish')), spec.timeout + 15000))])", spec)

    def measure(action, **values):
        spec = {"action": action, "timeout": T(60000), **values}
        spec["timeout"] = min(spec["timeout"], max(1, int((limit - (time.monotonic()-start))*1000)))
        progress("measure " + action)
        if action not in ("selection", "escape", "nudge", "typing"):
            return bounded("P5aProbe.run(spec)", spec)
        # Supervisor: the page arms an observer, this driver sends the trusted input, the page reports the
        # interval from that event to the observed condition. The page never calls the driver.
        instruction = page.evaluate("spec => P5aProbe.arm(spec)", spec)
        if action == "typing":
            for index in range(instruction["count"]):
                page.keyboard.press(instruction["key"])
                page.evaluate("([count, timeout]) => P5aProbe.typed(count, timeout)", [index + 1, spec["timeout"]])
        elif "key" in instruction:
            page.keyboard.press(instruction["key"])
        else:
            x, y = instruction["point"]
            page.mouse.move(x, y, steps=8)
            page.mouse.click(x, y)
        return bounded("P5aProbe.collect(spec)", spec)

    def wait(expression, arg=None, timeout=T(120000)):
        timeout = min(timeout, max(1, int((limit - (time.monotonic()-start))*1000)))
        page.wait_for_function(expression, arg=arg, timeout=timeout)

    def idle():
        wait("() => P5aProbe.idle() && P5aProbe.drawn()")

    def payload():
        return page.evaluate("() => P5aProbe.payload()")

    def scene(route):
        reply = request.get(server.url + f"/api/{route}/MMLE-50D/documentation-scene", timeout=T(120000))
        if not reply.ok:
            raise RuntimeError(reply.text()[:1500])
        return reply.json()

    def select_fixture(key):
        reply = request.post(server.url + "/__p5a/fixture", data={"fixture": key}, timeout=T(120000))
        if not reply.ok:
            raise RuntimeError(reply.text()[:1500])
        return reply.json()

    def close():
        if page.locator("#documentationWorkspace").count():
            page.locator("#documentationWorkspace .documentation-close").evaluate("node => node.click()")
            wait("() => !document.querySelector('#documentationWorkspace')")

    def open_fixture(key, kind):
        close()
        select_fixture(key)
        route = "parts-manual" if kind == PARTS else "operations-manual"
        # Read counts before the interval. The compiler/cache behavior is not changed.
        cache_key = key if key != "base" else "base-" + route
        doc = documents.get(cache_key)
        if doc is None:
            doc = scene(route)["document"]
            documents[cache_key] = doc
        if key == "base":
            fixtures[cache_key] = {"pages": len(doc["pages"]), "case": "real MMLE cover",
                "objects": sum(len(p.get("documentationObjects", {})) for p in doc["pages"]),
                "bomRows": sum(len(p.get("bom", [])) for p in doc["pages"]),
                "figures": sum(bool(p.get("renderRequest")) for p in doc["pages"]),
                "blocks": sum(len(p.get("layoutBlocks", [])) for p in doc["pages"])}
        result = measure("open", kind=kind, pages=len(doc["pages"]))
        documents[cache_key] = payload()["document"]
        return result

    def navigate(page_id):
        return measure("page", pageId=page_id)

    def editor(object_id, table=False):
        node = page.locator(SURFACE + ' [data-documentation-object-id="' + object_id + '"]')
        node.focus()
        wait("id => window.__compareDbg.state.partsManualDocumentationSelection?.targetId === id", object_id)
        page.keyboard.press("Enter")
        wait("() => P5aProbe.mounted() === 1 && !!P5aProbe.editor()")
        target = page.locator(SURFACE + ' .documentation-rich-editor [contenteditable="true"]')
        if table:
            cell = target.locator('td p, th p').first
            cell.click()
            wait("() => !!window.DocumentationRichText.active.editor.state.selection.$from.path.find(n=>n?.type?.name==='tableCell'||n?.type?.name==='tableHeader')")
        else:
            page.keyboard.press("Control+End")
        return target

    def cancel():
        if page.evaluate("() => P5aProbe.mounted()"):
            page.keyboard.press("Escape")
            wait("() => !P5aProbe.mounted() && P5aProbe.drawn()")

    def series(name, action, runs=5, budget=None):
        raw = []
        for i in range(runs):
            value = step(f"measurement_{name}_{i+1}", action)
            if value is None:
                break  # An unavailable action is a failure, not five repeated timeouts.
            raw.append(value)
        data = {"raw": raw, "expectedRuns": runs}
        measurements["measurements"][name] = data
        complete = len(raw) == runs and all("ms" in row for row in raw)
        record("measurement_" + name, complete, {"taken": len(raw), "expected": runs})
        if complete:
            data.update(statistics([r["ms"] for r in raw]))
            if all(r.get("workspaceLoaded") for r in raw):
                # Supervisor: the open as a user gets it: the workspace's own load, without the Refresh.
                data["workspace"] = statistics([r["workspaceMs"] for r in raw])
            if budget is not None:
                detail = {k: data[k] for k in ("p95", "median")}
                detail.update(budget=budget, met=data["p95"] <= budget)
                if "workspace" in data:
                    detail.update(workspaceP95=data["workspace"]["p95"], workspaceMedian=data["workspace"]["median"],
                                  workspaceMet=data["workspace"]["p95"] <= budget)
                data["budget"] = detail
                record("budget_" + name, True, detail)
        flush()
        return data

    def export(key, name):
        result = measure("pdf", timeout=T(180000))
        if result.get("status") != 200:
            raise RuntimeError("PDF refused: " + repr(result.get("response")))
        artifact = result["response"].get("pdf") or result["response"].get("artifact")
        if not artifact or not artifact.get("url", "").startswith("/api/"):
            raise RuntimeError("No managed PDF artifact in response")
        if key.startswith("parts"):
            report.setdefault("exportDownloadHandoffs", []).append(urlsplit(artifact["url"]).path)
        data = request.get(server.url + artifact["url"], timeout=T(120000))
        if not data.ok:
            raise RuntimeError(data.text()[:500])
        pdfs[key] = data.body()
        (output / (name + ".pdf")).write_bytes(pdfs[key])
        # Export opens a PDF tab. Close only the proof context's other tabs after
        # the response clock stopped, so later animation-frame clocks stay foreground.
        for extra in page.context.pages:
            if extra != page:
                extra.close()
        page.bring_to_front()
        idle()
        return result

    def listeners(cdp):
        result = {}
        for expression in ("document", "window"):
            obj = cdp.send("Runtime.evaluate", {"expression": expression, "objectGroup": "p5a-listeners"})["result"]["objectId"]
            rows = cdp.send("DOMDebugger.getEventListeners", {"objectId": obj})["listeners"]
            result[expression] = dict(Counter((r["type"] + ":" + str(r["useCapture"]) + ":" + str(r["passive"]) + ":" + str(r["once"])) for r in rows))
            for object_id in {r.get(key, {}).get("objectId") for r in rows for key in ("handler", "originalHandler")} - {None}:
                cdp.send("Runtime.releaseObject", {"objectId": object_id})
        cdp.send("Runtime.releaseObjectGroup", {"objectGroup": "p5a-listeners"})
        return result

    def heap(cdp):
        cdp.send("HeapProfiler.collectGarbage")
        return {**cdp.send("Runtime.getHeapUsage"), "census": page.evaluate("() => P5aProbe.census(true)")}

    def audit(label):
        value = page.evaluate("() => P5aProbe.audit()")
        value["label"] = label
        measurements["accessibility"].append(value)
        record("names_" + label, bool(value["names"]) and all(v["name"] for v in value["names"]), value["names"])
        record("panels_" + label, all(v["role"] and v["name"] for v in value["panels"]), value["panels"])
        bad = [v for v in value["colors"] if v["ratio"] is None or v["ratio"] < v["minimum"]]
        # Supervisor: two pairs come from styles older than this build (the blue Publish button; the 8 px
        # menu headings of the light theme). They are a recorded finding for the product owner, not a
        # failure of this build; every other pair below its ratio fails.
        older = [v for v in bad if v.get("id") == "documentationPublishRibbon"
                 or (v.get("fontSize") == "8px" and v.get("foreground") == "rgb(117, 130, 140)")]
        for v in older:
            key = (v.get("id") or v.get("name")) + " " + v["foreground"] + " on " + str(v["background"])
            older_contrast.setdefault(key, {**v, "seenIn": []})["seenIn"].append(label)
        bad = [v for v in bad if v not in older]
        record("contrast_" + label, not bad, bad)
        record("live_region_" + label, value["live"] == {"role": "status", "polite": "polite"}, value["live"])
        return value

    # The workspace requires a real assembly/model. The harness preserves MMLE
    # and swaps only its isolated plan/scene/manuscript; no product read is mocked.
    response = request.get(server.url + "/__p5a/fixture", timeout=T(120000))
    if not response.ok:
        raise RuntimeError(response.text())
    fixtures.update(response.json()["fixtures"])
    record("full_scale_fixtures", [fixtures[key]["requestedPages"] for key in ("parts50", "parts100", "operations50")] == [50, 100, 50],
           {key: fixtures[key]["requestedPages"] for key in ("parts50", "parts100", "operations50")})
    for key in ("parts50", "parts100", "operations50"):
        value = fixtures[key]
        # Supervisor: a parts group adds two pages (figure and parts list), so the count can pass the request
        # by one; timings carry the actual count.
        record("fixture_size_"+key, value["requestedPages"] <= value["pages"] <= value["requestedPages"] + 1, value)
    measurements["paths"] = {"open": "MMLE assembly profile -> __compareDbg.openDocumentationWorkflow -> existing type picker -> Refresh",
        "generated": "has_glb gate prevents model-free workspace; use the prescribed MMLE fallback per type",
        "escape": "existing rich editor cancels on Escape; Done/blur commits. Neither shortcut is changed.",
        "export": "ribbon publish callback; timing includes response body, excludes artifact download; cache hits retained"}
    page.goto(server.url + "/?assemblyProfile=MMLE-50D", wait_until="domcontentloaded", timeout=T(90000))
    wait("() => window.__compareDbg?.state.partNumber === 'MMLE-50D' && !!window.__compareDbg.state.assyLiveScene", timeout=T(90000))
    for key, kind in (("base", PARTS), ("parts50", PARTS), ("parts100", PARTS), ("operations50", OPS)):
        if only and "opens" not in only:
            skipped.append("open_" + key)
            continue
        series("open_" + key, lambda key=key, kind=kind: open_fixture(key, kind), budget=5000 if key == "parts100" else None)

    def text_measurements():
        open_fixture("parts100", PARTS)
        doc = documents["parts100"]
        # Supervisor: the fixture's parts lists have as many rows as the largest real group has distinct parts.
        rows_per_group = fixtures["parts100"]["rowsPerGroup"]
        # Supervisor: the fixture authors a text box and a table on a parts list page in the middle of the
        # document (a rich text replacement over HTTP would need the field's observed hash).
        middle = next((p for p in doc["pages"] if p["pageId"] == fixtures["parts100"].get("typingPageId")), None)
        if middle is None or not any(o.get("type") == "text" for o in middle.get("documentationObjects", {}).values()):
            raise RuntimeError("The parts fixture has no authored text on a parts list page")
        documents["parts100"] = doc
        measurements["fixtures"]["parts100"]["measuredObjects"] = sum(len(p.get("documentationObjects", {})) for p in doc["pages"])
        adjacent = doc["pages"][max(0, doc["pages"].index(middle)-1)]
        def turn():
            navigate(adjacent["pageId"])
            return navigate(middle["pageId"])
        series("page_change_parts100", turn)
        record("middle_bom_rows", len(middle.get("bom", [])) == rows_per_group >= 10,
               {"pageId": middle["pageId"], "pageNumber": middle["pageNumber"], "rows": len(middle.get("bom", []))})
        text_ids = [k for k, o in middle["documentationObjects"].items() if o.get("type") == "text"]
        def table(o):
            return isinstance(o.get("content"), dict) and any(n["type"] == "table" for n in o["content"]["doc"]["content"])
        # Supervisor: the fixture names its objects by page number and kind (0 text, 1 table, 2 image, 3 shape);
        # the compiled page carries a rich field's plain projection, so the kind is not read from the content.
        plain_id = "document-object-p5a-%d-0" % middle["pageNumber"]
        table_id = "document-object-p5a-%d-1" % middle["pageNumber"]
        if plain_id not in text_ids or table_id not in text_ids:
            raise RuntimeError("The fixture's text and table objects are not on the measured page: " + ", ".join(text_ids))
        measurements["typingPage"] = {"pageId": middle["pageId"], "textId": plain_id, "tableId": table_id}
        def selection():
            # Supervisor: Escape on a parts manual page goes up to the overview page (an older key of the
            # workspace), so a selection left by the last sample is cleared by activating the page again.
            if page.evaluate("() => !!window.__compareDbg.state.partsManualDocumentationSelection"):
                navigate(middle["pageId"])
            wait("() => !window.__compareDbg.state.partsManualDocumentationSelection")
            return measure("selection", objectId=plain_id)
        series("selection", selection, budget=150)
        # Five Escape attempts demonstrate the real shortcut rather than silently
        # timing a different action under the requested name.
        escapes = []
        for i in range(5):
            editor(plain_id); page.keyboard.type("e")
            escapes.append(measure("escape"))
        # Supervisor: Escape is the editor's Cancel and stays so; Done (or leaving the box) saves, and that is
        # the save the budget is about (save_done below).
        measurements["measurements"]["escape_cancel"] = {**statistics([v["ms"] for v in escapes]), "raw": escapes}
        record("escape_cancels_edit", not any(v["saved"] for v in escapes), escapes)
        saves, undos, redos = [], [], []
        for label, oid, in_table in (("text", plain_id, False), ("table", table_id, True)):
            raw = []
            for i in range(5):
                editor(oid, in_table)
                value = measure("typing")
                raw.append(value)
                if in_table:
                    # Supervisor: the table runs measure typing; their draft is cancelled, which spares four
                    # round trips on the large document per run.
                    cancel()
                    continue
                value_save = measure("save")
                undo = measure("undo")
                redo = measure("redo", expected="x" * 20)
                measure("undo")  # Keep each run at the same length and marks.
                saves.append(value_save); undos.append(undo); redos.append(redo)
            numbers = [x for r in raw for x in r["samples"]]
            data = {**statistics(numbers), "runs": raw}
            measurements["measurements"]["typing_" + label] = data
            record("measurement_typing_" + label, len(raw) == 5 and len(numbers) == 250, {"runs": len(raw), "keys": len(numbers)})
            record("budget_typing_" + label, True, {"met": data["p95"] <= 100, "p95": data["p95"], "median": data["median"], "budget": 100})
        for label, raw, budget in (("save_done", saves, 1000), ("undo", undos, None), ("redo", redos, None)):
            data = {**statistics([v["ms"] for v in raw]), "raw": raw}
            measurements["measurements"][label] = data
            if budget:
                record("budget_" + label, True, {"met": data["p95"] <= budget, "p95": data["p95"], "median": data["median"], "budget": budget})
        series("reload_parts100", lambda: measure("reload"))
        measurements["findings"]["parts_save"] = {"serverP95Ms": 3170, "browser": measurements["measurements"]["save_done"],
            "richReadAfterSave": [[r for r in v["requests"] if r["method"] == "GET" and r["url"].endswith('/documentation-scene')
                and r["start"] >= max((p.get("end", p["start"]) for p in v["requests"]
                    if p["method"] == "POST" and p["url"].endswith('/documentation-scene/commands')), default=float("inf"))] for v in saves]}
        editor(table_id, True)
        page.keyboard.press("Control+End"); page.keyboard.press("ArrowDown"); page.keyboard.type("P5aGap")
        measurements["findings"]["table_gap"] = page.evaluate("""() => ({json:DocumentationRichText.active.editor.getJSON(),
            ancestors:DocumentationRichText.active.editor.state.selection.$from.path.filter(n=>n?.type?.name).map(n=>n.type.name)})""")
        toolbar = page.locator('.documentation-rich-controls').bounding_box()
        canvas = page.locator(SURFACE).bounding_box()
        measurements["findings"]["toolbar_overlap"] = {"toolbar": toolbar, "surface": canvas,
            "verticalOverlapCssPx": max(0, min(toolbar['y']+toolbar['height'], canvas['y']+canvas['height'])-max(toolbar['y'], canvas['y']))}
        cancel()

    def command(current, route, page_id, operation, oid, **values):
        response = request.post(server.url + f"/api/{route}/MMLE-50D/documentation-scene/commands", data={
            "baseRevision": current["revision"], "sourceRevision": current["scene"]["sourceRevision"],
            "manualPlanRevision": current["scene"]["manualPlanRevision"], "pageId": page_id,
            "operation": operation, "targetType": "document_object", "targetId": oid, **values}, timeout=T(120000))
        if not response.ok:
            raise RuntimeError(response.text()[:1500])
        return response.json()

    stage("text_measurements", text_measurements)
    cancel()
    for key, kind in (("parts100", PARTS), ("operations50", OPS)):
        def exports(key=key, kind=kind):
            open_fixture(key, kind)
            series("pdf_" + key, lambda: export(key, "p5a-" + key), runs=3, budget=30000)
        stage("exports_" + key, exports)

    def cpu_profile(name, action):
        # Supervisor: one profiled run of an action, summarised by function: inclusive time (a function is
        # counted once per stack) and self time, in milliseconds.
        cdp = page.context.new_cdp_session(page)
        try:
            cdp.send("Profiler.enable")
            cdp.send("Profiler.setSamplingInterval", {"interval": 1000})
            cdp.send("Profiler.start")
            began = time.monotonic()
            try:
                action()
            finally:
                profile = cdp.send("Profiler.stop")["profile"]
            wall = time.monotonic() - began
        finally:
            cdp.detach()
        nodes = {node["id"]: node for node in profile["nodes"]}
        own = Counter()
        for sample, delta in zip(profile.get("samples", []), profile.get("timeDeltas", [])):
            own[sample] += delta
        def label(node):
            frame = node["callFrame"]
            place = frame.get("url", "").rsplit("/", 1)[-1].split("?")[0] or "native"
            return (frame.get("functionName") or "(anonymous)") + " " + place + ":" + str(frame.get("lineNumber", 0) + 1)
        inclusive, self_time = Counter(), Counter()
        root = profile["nodes"][0]["id"]
        stack = [(root, False, frozenset())]
        totals = {}
        while stack:
            node_id, done, seen = stack.pop()
            node = nodes[node_id]
            key = label(node)
            if done:
                totals[node_id] = own[node_id] + sum(totals[child] for child in node.get("children", []))
                self_time[key] += own[node_id]
                if key not in seen:
                    inclusive[key] += totals[node_id]
                continue
            stack.append((node_id, True, seen))
            for child in node.get("children", []):
                stack.append((child, False, seen | {key}))
        skip = ("(root)", "(program)", "(idle)", "(garbage collector)")
        measurements.setdefault("profiles", {})[name] = {"wallSeconds": round(wall, 1),
            "sampledMs": round(sum(own.values()) / 1000), "idleMs": round(sum(v for k, v in self_time.items() if k.startswith("(idle)")) / 1000),
            "inclusive": [{"ms": round(v / 1000), "function": k} for k, v in inclusive.most_common(60) if not k.startswith(skip)][:45],
            "self": [{"ms": round(v / 1000), "function": k} for k, v in self_time.most_common(40) if not k.startswith(skip[:1])][:30]}
        flush()

    def server_profile(label):
        reply = request.post(server.url + "/__p5a/profile", data={"label": label}, timeout=T(30000))
        if not reply.ok:
            raise RuntimeError(reply.text()[:500])

    def profiles():
        open_fixture("parts100", PARTS)  # warm, as the measured opens are
        cpu_profile("open_parts100", lambda: open_fixture("parts100", PARTS))
        pages = payload()["document"]["pages"]
        middle = pages[len(pages) // 2]
        navigate(pages[len(pages) // 2 - 1]["pageId"])
        cpu_profile("page_change_parts100", lambda: navigate(middle["pageId"]))
        # A text save and its undo, with the server's routes profiled too (server.log, P5A-PROFILE route).
        typed = next(p for p in pages if p["pageId"] == fixtures["parts100"]["typingPageId"])
        navigate(typed["pageId"])
        editor("document-object-p5a-%d-0" % typed["pageNumber"]); page.keyboard.type("p")
        try:
            server_profile("save_parts100")
            cpu_profile("save_parts100", lambda: measure("save"))
            server_profile("undo_parts100")
            cpu_profile("undo_parts100", lambda: measure("undo"))
        finally:
            server_profile(None)
        open_fixture("operations50", OPS)
        target = next(p for p in payload()["document"]["pages"] if p.get("documentationObjects"))
        navigate(target["pageId"])
        oid = next(iter(target["documentationObjects"]))
        page.locator(SURFACE + ' [data-documentation-object-id="' + oid + '"]').focus()
        wait('id=>window.__compareDbg.state.partsManualDocumentationSelection?.targetId===id', oid)
        try:
            server_profile("nudge_operations50")
            cpu_profile("nudge_operations50", lambda: measure("nudge"))
        finally:
            server_profile(None)
        measure("undo")
    if os.environ.get("DOC_SMOKE_PROFILE") == "1":
        stage("profiles", profiles)

    def object_settling():
        open_fixture('operations50', OPS)
        p = next(p for p in payload()['document']['pages'] if p.get('documentationObjects'))
        navigate(p['pageId'])
        oid = next(iter(p['documentationObjects']))
        def nudge():
            page.locator(SURFACE+' [data-documentation-object-id="'+oid+'"]').focus()
            wait('id=>window.__compareDbg.state.partsManualDocumentationSelection?.targetId===id', oid)
            result = measure('nudge')
            measure('undo')
            return result
        data = series('object_batch_operations50', nudge)
        measurements['findings']['object_batch'] = {'priorApproximateMs':2200, 'browser':data}
    stage('object_batch', object_settling)

    def editor_cycles():
        open_fixture("parts100", PARTS)
        targets = [(p["pageId"], k) for p in payload()["document"]["pages"]
            for k, o in p.get("documentationObjects", {}).items() if o.get("type") == "text"][:20]
        if not targets:
            raise RuntimeError("The fixture has no authored text field")
        # Supervisor: twenty cycles always; on twenty different fields at full scale (a smaller debug fixture
        # has fewer and reuses them).
        distinct = len(targets)
        record("editor_cycle_fields", distinct == 20 or fixtures["parts100"]["requestedPages"] != 100, {"distinct": distinct})
        targets = (targets * 20)[:20]
        navigate(targets[0][0])
        cdp = page.context.new_cdp_session(page)
        try:
            before = listeners(cdp)
            observations = []
            for pid, oid in targets:
                navigate(pid); editor(oid)
                opened = page.evaluate("() => P5aProbe.census()")
                page.keyboard.type("x"); cancel()
                closed = page.evaluate("() => P5aProbe.census()")
                observations.append({"pageId": pid, "objectId": oid, "open": opened, "closed": closed})
            after = listeners(cdp)
            measurements["cycles"]["editors"] = {"beforeListeners": before, "afterListeners": after, "cycles": observations}
            record("one_editor", all(v["open"]["editors"] == v["open"]["editorNodes"] == 1
                and v["closed"]["editors"] == v["closed"]["editorNodes"] == 0 for v in observations), observations)
            record("editor_listeners", before == after, {"before": before, "after": after})
        finally:
            cdp.detach()
    stage("editor_cycles", editor_cycles)

    def memory_cycles():
        open_fixture("base", PARTS)
        cdp = page.context.new_cdp_session(page)
        try:
            before = heap(cdp)
            visits = []
            for i in range(cycles):
                open_fixture("parts100", PARTS)
                pages = payload()["document"]["pages"]
                chosen = [pages[0], pages[len(pages)//2], pages[-1]]
                for p in chosen:
                    navigate(p["pageId"])
                open_fixture("base", PARTS)
                visits.append([p["pageId"] for p in chosen])
            after = heap(cdp)
            value = {"before": before, "after": after, "visited": visits,
                "growthBytes": after["usedSize"]-before["usedSize"], "limitBytes": 100*1024**2}
            measurements["cycles"]["memory"] = value
            record("retained_heap", value["growthBytes"] <= value["limitBytes"], value)
            record("memory_cycle_count", cycles == 20, {"cycles": cycles, "gate": 20})
            record("one_surface_after_cycles", after["census"]["surfaces"] == 1, after["census"])
            record("viewer_contexts_after_cycles", all(after["census"][k] <= before["census"][k]
                for k in ("viewers", "contexts", "webglContexts", "canvasNodes")), {"before": before["census"], "after": after["census"]})
        finally:
            cdp.detach()
    stage("memory_cycles", memory_cycles)

    def keyboard_only():
        open_fixture("base", OPS)
        # Only Tab and the controls' existing keyboard handlers move focus below.
        page.evaluate("""() => { window.__p5aPointer={pointerdown:0,mousedown:0,click:0}; window.__p5aPointerEvents=[];
            window.__p5aCount=e=>{if(e.isTrusted){window.__p5aPointer[e.type]++;
                window.__p5aPointerEvents.push({type:e.type,detail:e.detail,pointerType:e.pointerType||null,
                    target:e.target.closest('button,input,select')?.id||e.target.tagName});}};
            for(const type of Object.keys(__p5aPointer))window.addEventListener(type,__p5aCount,true); }""")
        path = []
        def tab_to(selector):
            for i in range(250):
                if page.evaluate("s=>document.activeElement?.matches(s)", selector):
                    path.append({"selector": selector, "tabs": i}); return
                page.evaluate("() => window.__p5aBeforeFocus=document.activeElement")
                page.keyboard.press("Tab")
                wait("() => document.activeElement!==window.__p5aBeforeFocus", timeout=T(5000))
            page.evaluate("() => delete window.__p5aBeforeFocus")
            raise RuntimeError("No Tab path to " + selector)
        def key(key, condition=None):
            page.keyboard.press(key)
            if condition:
                wait(condition, timeout=T(30000))
            else:
                page.evaluate("() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))")
        try:
            # The insert command can be in the responsive More menu.
            insert = '#documentationInsertTextRibbon'
            insert_menu = not page.locator(insert).is_visible()
            if insert_menu:
                tab_to('#documentationOverflowMenuRibbon'); key('Enter')
                wait("() => document.querySelector('#documentationOverflowMenuRibbon')?.getAttribute('aria-expanded')==='true'")
                insert = '.documentation-ribbon-overflow-menu button[aria-label="Insert a text box"]'
                # Resolve the actual accessible label from the source command, no hardcoded shortcut.
                title = page.locator('#documentationInsertTextRibbon').get_attribute('title')
                insert = '.documentation-ribbon-overflow-menu button[aria-label=' + json.dumps(title) + ']'
            tab_to(insert)
            before = payload()["revision"]
            key('Enter', "() => !!window.__compareDbg.state.partsManualDocumentationSelection && P5aProbe.idle()")
            wait("r=>P5aProbe.payload().revision!==r", before)
            if insert_menu:
                wait("() => document.activeElement?.id==='documentationOverflowMenuRibbon'", timeout=T(10000))
                record('keyboard_insert_menu_focus', True, {'opener': 'documentationOverflowMenuRibbon'})
            oid = page.evaluate("() => window.__compareDbg.state.partsManualDocumentationSelection.targetId")
            tab_to('.documentation-canvas-stage'); key('Enter', "() => P5aProbe.mounted()===1")
            page.keyboard.type('Keyboard proof '); key('Control+b'); page.keyboard.type('bold')
            state = page.evaluate("() => DocumentationRichText.active.editor.getJSON()")
            record('keyboard_bold', '"bold"' in json.dumps(state), state)
            audit('keyboard_editor')
            # Supervisor: the keyboard's save is leaving the editor. Escape cancels the draft; focus that
            # moves out of the editor, its toolbar and its Done panel commits it, and Tab moves it out. If
            # Tab lands on Done first, Enter there is the same save.
            current = payload()["revision"]
            presses, landed = 0, None
            while page.evaluate("() => P5aProbe.mounted()") and presses < 12:
                page.keyboard.press("Tab"); presses += 1
                landed = page.evaluate("() => { const e = document.activeElement; return e ? (e.id || e.dataset.richAction"
                    " || e.dataset.documentationObjectId || e.className || e.tagName) : null; }")
                if page.evaluate("() => document.activeElement?.matches('[data-rich-action=\"done\"]')"):
                    page.keyboard.press("Enter")
                try:
                    wait("() => P5aProbe.mounted()===0", timeout=T(2500))
                except Exception:
                    pass  # Focus is still inside the editor's own controls: Tab again.
            path.append({"selector": "leave the editor (focus out saves)", "tabs": presses, "focus": landed})
            wait("() => P5aProbe.mounted()===0", timeout=T(30000))
            wait("r=>P5aProbe.payload().revision!==r && P5aProbe.idle()", current)
            # Supervisor: the compiled page carries the field's plain text; the bold run is read from the
            # drawn object.
            saved = page.evaluate("""id => ({text: P5aProbe.payload().document.pages
                    .map(p => (p.documentationObjects || {})[id]).find(Boolean)?.content || null,
                bold: [...document.querySelectorAll('#documentationPublicationSurface [data-documentation-object-id="'
                    + CSS.escape(id) + '"] strong')].map(node => node.textContent)})""", oid)
            record('keyboard_save', 'Keyboard proof' in str(saved["text"]) and saved["bold"] == ["bold"], saved)
            tab_to('.documentation-canvas-stage')
            current = payload()["revision"]
            key('ArrowRight'); wait("r=>P5aProbe.payload().revision!==r && P5aProbe.idle()", current)
            current = payload()["revision"]
            key('Delete'); wait("r=>P5aProbe.payload().revision!==r && P5aProbe.idle()", current)
            current = payload()["revision"]
            key('Control+z'); wait("r=>P5aProbe.payload().revision!==r && P5aProbe.idle()", current)
            current = payload()["revision"]
            key('Control+y'); wait("r=>P5aProbe.payload().revision!==r && P5aProbe.idle()", current)
            tab_to('#documentationPageSetupRibbon'); key('Enter')
            wait("() => document.querySelector('#documentationPageSetupRibbon')?.getAttribute('aria-expanded')==='true'")
            audit('keyboard_paper_menu')
            # The generic menu's first choice is design, second is Letter.
            key('Home'); key('ArrowDown'); key('Enter')
            wait("() => P5aProbe.idle() && P5aProbe.payload().pageSetupOptions.current?.paper==='Letter'")
            record('keyboard_paper_focus', page.evaluate("() => document.activeElement?.id") == 'documentationPageSetupRibbon')
            key('Enter'); key('Escape')
            record('keyboard_escape_focus', page.evaluate("() => document.activeElement?.id") == 'documentationPageSetupRibbon')
            # Restore design with the same keyboard path; one undo, not a store reset.
            tab_to('.documentation-canvas-stage'); key('Control+z')
            wait("() => P5aProbe.idle() && !P5aProbe.payload().pageSetupOptions.current")
            record('keyboard_sequence', True, {"objectId": oid, "path": path})
        finally:
            counter = page.evaluate("""() => { for(const type of Object.keys(__p5aPointer))window.removeEventListener(type,__p5aCount,true);
                return __p5aPointer; }""")
            page.evaluate('() => delete window.__p5aBeforeFocus')
            events = page.evaluate('() => __p5aPointerEvents')
            # Supervisor: pressing Enter or Space on a button emits a trusted click with detail 0 and no
            # pointerdown or mousedown. Pointer use is a pointerdown, a mousedown or a click with detail > 0.
            pointer = [e for e in events if e['type'] != 'click' or e['detail'] > 0]
            record('keyboard_no_pointer', not pointer, {'counts': counter, 'pointerEvents': pointer})
            measurements['keyboard'] = {'paths': path, 'trustedEvents': counter, 'events': events,
                'interpretation': 'Keyboard activation emits a trusted click with detail 0; only pointerdown, mousedown and clicks with detail > 0 count as pointer use.'}
    stage('keyboard_only', keyboard_only)

    def announcements_and_colors():
        open_fixture('base', OPS)
        current = payload(); pid = next(p['pageId'] for p in current['document']['pages'] if p.get('pageType') == 'operations_content')
        text = 'A measured line with room'
        width = fitz.get_text_length(text, fontname='helv', fontsize=12) + 6.1
        oid = 'document-object-p5a-refusal'
        command(current, 'operations-manual', pid, 'add_object', oid, documentObject={'objectId': oid, 'type': 'text',
            'name': 'Paper fit', 'source': 'user', 'content': text, 'frame': {'x': .1, 'y': .2, 'width': width/960, 'height': 20.5/540},
            'styleOverrides': {'fontSize': 12}})
        measure('reload'); navigate(pid)
        before = payload()['revision']
        page.locator('#documentationPageSetupRibbon').click()
        wait("() => document.querySelector('#documentationPageSetupRibbon')?.getAttribute('aria-expanded')==='true'")
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/documentation-scene/commands'), timeout=T(120000)) as response:
            page.locator('#documentationPageSetup-a4-landscape').click()
        reply = response.value; reply.finished(); body = reply.json(); idle()
        proved = reply.status == 409 and body.get('error') == 'layout_overflow'
        if proved:
            report.setdefault('expectedHttpFailures', []).append({'checked': True, 'status': 409, 'method': 'POST', 'url': reply.url, 'error': 'layout_overflow'})
        record('refusal_announcement', proved and payload()['revision'] == before
            and 'Paper fit' in page.locator('.documentation-status-message').inner_text(), body)
        measure('undo')  # Remove the refusal fixture.
        # Named controls and contrast in both implemented themes; no theme storage changed.
        for theme in ('dark', 'light'):
            page.evaluate("theme=>document.documentElement.setAttribute('data-theme',theme)", theme)
            audit(theme + '_ribbon')
            triggers = page.locator('#contextRibbon .documentation-ribbon-menu-trigger')
            for i in range(triggers.count()):
                trigger = triggers.nth(i)
                if not trigger.is_visible() or trigger.is_disabled():
                    continue
                trigger.click()
                wait("i=>document.querySelectorAll('#contextRibbon .documentation-ribbon-menu-trigger')[i]?.getAttribute('aria-expanded')==='true'", i)
                audit(theme + '_menu_' + str(i))
                trigger.focus(); page.keyboard.press('Escape')
                wait("i=>document.querySelectorAll('#contextRibbon .documentation-ribbon-menu-trigger')[i]?.getAttribute('aria-expanded')==='false'", i)
                record(theme+'_menu_focus_'+str(i), trigger.evaluate('e=>e===document.activeElement'))
            theme_button = page.locator('#documentationThemeRibbon')
            if theme_button.is_visible():
                theme_button.click(); opener = 'documentationThemeRibbon'
            else:
                page.locator('#documentationOverflowMenuRibbon').click()
                wait("() => document.querySelector('#documentationOverflowMenuRibbon')?.getAttribute('aria-expanded')==='true'")
                title = theme_button.get_attribute('title')
                page.locator('.documentation-ribbon-overflow-menu').get_by_role('button', name=title, exact=True).click()
                opener = 'documentationOverflowMenuRibbon'
            wait("() => !!document.querySelector('.documentation-theme-dialog')")
            audit(theme+'_theme_dialog')
            page.keyboard.press('Escape')
            wait("() => !document.querySelector('.documentation-theme-dialog')")
            record(theme+'_theme_focus', page.evaluate('() => document.activeElement?.id') == opener)
            # Use a large fixture's own box for the editor, then return to this document.
            open_fixture('operations50', OPS)
            doc = payload()['document']; p = next(p for p in doc['pages'] if p.get('documentationObjects'))
            navigate(p['pageId']); oid2 = next(k for k,o in p['documentationObjects'].items() if o['type']=='text')
            editor(oid2); audit(theme + '_toolbar')
            for action, selector in (('Symbol','.documentation-symbol-picker'), ('Table','.documentation-table-menu')):
                toggle = page.locator('.documentation-rich-controls button').filter(has_text=action).first
                page.locator(SURFACE + ' .documentation-rich-editor [contenteditable="true"]').focus()
                toggle.click()
                wait('s=>!!document.querySelector(s)&&!document.querySelector(s).hidden', selector)
                audit(theme + '_' + action.lower())
                page.keyboard.press('Escape')
                wait('s=>document.querySelector(s).hidden', selector)
                # Supervisor: opened with the pointer from the text, the focus goes back into the text (also
                # after the Table panel's own field held it); opened from the keyboard, it returns to the
                # panel's button.
                record(theme + '_' + action.lower() + '_pointer_focus', page.evaluate(
                    "() => document.querySelector('.documentation-rich-editor [contenteditable=\"true\"]')?.contains(document.activeElement)"
                    " || document.activeElement?.isContentEditable === true"))
                toggle.focus(); page.keyboard.press('Enter')
                wait('s=>!!document.querySelector(s)&&!document.querySelector(s).hidden', selector)
                page.keyboard.press('Escape')
                wait('s=>document.querySelector(s).hidden', selector)
                record(theme + '_' + action.lower() + '_focus', page.evaluate("() => document.activeElement?.textContent") == action)
                page.locator(SURFACE + ' .documentation-rich-editor [contenteditable="true"]').focus()
            cancel()
        page.evaluate("() => document.documentElement.setAttribute('data-theme','dark')")
        texts = page.evaluate('() => P5aProbe.announcements')
        measurements['announcements'] = texts
        for label, words in (('save', ('saved',)), ('refusal', ('not applied',)), ('undo', ('undid',)), ('export', ('exported', 'published'))):
            found = [r for r in texts if any(w in r['text'].lower() for w in words)]
            record('announcement_' + label, bool(found), found)
    stage('announcements_and_colors', announcements_and_colors)

    def picture(active_page, data, document, page_id, name):
        shown = wait_for_p4b_publication_capture(active_page)
        record(name + '_capture', shown['ready'], shown)
        png = active_page.locator(SURFACE).screenshot(timeout=T(20000))
        (output / (name + '-canvas.png')).write_bytes(png)
        image = Image.open(io.BytesIO(png)).convert('RGB')
        with fitz.open(stream=data, filetype='pdf') as pdf:
            pp = pdf[next(i for i,p in enumerate(document['pages']) if p['pageId'] == page_id)]
            pix = pp.get_pixmap(matrix=fitz.Matrix(2,2), alpha=False)
            pix.save(str(output / (name + '-pdf.png')))
            pw, ph = pp.rect.width, pp.rect.height
            samples = []
            for row in range(1,25):
                for col in range(1,33):
                    x,y = pw*col/33,ph*row/25
                    px,py,sx,sy = round(x*2),round(y*2),round(x/pw*image.width),round(y/ph*image.height)
                    a = [pix.pixel(px+dx,py+dy)[:3] for dx in (-1,0,1) for dy in (-1,0,1)]
                    b = [image.getpixel((sx+dx,sy+dy)) for dx in (-1,0,1) for dy in (-1,0,1)]
                    if any(max(v[k] for v in patch)-min(v[k] for v in patch)>3 for patch in (a,b) for k in range(3)):
                        continue
                    samples.append({'point':[x,y],'pdf':a[4],'canvas':b[4]})
        bad = [s for s in samples if max(abs(a-b) for a,b in zip(s['pdf'],s['canvas']))>8]
        # Supervisor: the header wordmark is drawn heavier and about 12 pt further left on the page than in
        # the PDF (header styles older than this build; a recorded finding). A point inside its box is listed
        # there and does not fail the picture.
        wordmark = [s for s in bad if 20 <= s['point'][0] <= 140 and 8 <= s['point'][1] <= 40]
        if wordmark:
            measurements['findings'].setdefault('header_wordmark', {'box': [20, 8, 140, 40],
                'note': 'The page draws the wordmark heavier and further left than the PDF.', 'points': []})['points'].append(
                    {'picture': name, 'points': wordmark})
        bad = [s for s in bad if s not in wordmark]
        record(name + '_pixels', len(samples)>=30 and not bad, {'samples': len(samples), 'bad': bad, 'wordmark': wordmark})

    def scaling():
        open_fixture('operations50', OPS)
        document = payload()['document']
        chosen = next(p for p in document['pages'] if not p.get('renderRequest') and any(b.get('blockType')=='paragraph' for b in p.get('layoutBlocks', [])))
        if 'operations50' not in pdfs:
            export('operations50', 'p5a-operations50')
        for factor in (1, 1.25, 1.5, 2):
            for width,height in ((1366,768),(1720,1080)):
                name = f'scale_{factor}_{width}_{height}'
                context = browser.new_context(viewport={'width':width,'height':height}, device_scale_factor=factor, service_workers='block')
                context.add_init_script(script=probe)
                def route(r):
                    url = urlsplit(r.request.url)
                    if url.scheme in {'data','blob'} or url.netloc == urlsplit(server.url).netloc:
                        r.continue_()
                    else:
                        report['outboundRequests'].append(r.request.url); r.abort()
                def ws(r):
                    if urlsplit(r.url).netloc == urlsplit(server.url).netloc: r.connect_to_server()
                    else: report['outboundRequests'].append(r.url); r.close()
                context.route('**/*', route); context.route_web_socket('**/*', ws)
                other = context.new_page()
                for event,handler in handlers.items(): other.on(event,handler)
                try:
                    other.goto(server.url+'/?assemblyProfile=MMLE-50D',wait_until='domcontentloaded',timeout=T(90000))
                    other.wait_for_function("() => window.__compareDbg?.state.partNumber==='MMLE-50D' && !!window.__compareDbg.state.assyLiveScene",timeout=T(90000))
                    other.evaluate('spec=>P5aProbe.run(spec)', {'action':'open','kind':OPS,'pages':len(document['pages']),'timeout':T(120000)})
                    other.evaluate('spec=>P5aProbe.run(spec)', {'action':'page','pageId':chosen['pageId'],'timeout':T(120000)})
                    boxes = other.evaluate('() => P5aProbe.clipping()')
                    corners = other.evaluate('() => P5aProbe.corners()')
                    measurements['scaling'].append({'factor':factor,'viewport':[width,height],'controls':boxes,'corners':corners})
                    other.screenshot(path=str(output/('p5a-'+name+'-controls.png')),timeout=T(20000))
                    record(name+'_controls', boxes['count'] > 0 and not boxes['failures'], boxes)
                    record(name+'_corners', all(c['visible'] for c in corners), corners)
                    picture(other, pdfs['operations50'], document, chosen['pageId'], 'p5a-'+name)
                    authored = next(p for p in document['pages'] if p.get('documentationObjects'))
                    oid = next(k for k,o in authored['documentationObjects'].items() if o['type']=='text')
                    other.evaluate('spec=>P5aProbe.run(spec)', {'action':'page','pageId':authored['pageId'],'timeout':T(120000)})
                    other.locator(SURFACE+' [data-documentation-object-id="'+oid+'"]').focus()
                    other.wait_for_function('id=>window.__compareDbg.state.partsManualDocumentationSelection?.targetId===id',arg=oid,timeout=T(20000))
                    other.keyboard.press('Enter')
                    other.wait_for_function('() => P5aProbe.mounted()===1',timeout=T(30000))
                    edit_boxes = other.evaluate('() => P5aProbe.clipping()')
                    other.screenshot(path=str(output/('p5a-'+name+'-editing-controls.png')),timeout=T(20000))
                    record(name+'_editing_controls', edit_boxes['count']>0 and not edit_boxes['failures'], edit_boxes)
                    other.keyboard.press('Escape')
                    other.wait_for_function('() => P5aProbe.mounted()===0',timeout=T(30000))
                except Exception as error:
                    record(name, False, str(error))
                finally:
                    for event,handler in handlers.items(): other.remove_listener(event,handler)
                    context.close()
                    page.bring_to_front()
    stage('scaling', scaling)

    def overflow_findings():
        def frame_for(doc, p):
            regions = doc['publicationLayout']['pageTypes'][p['pageType']]
            return regions['groupIndex' if p['pageType']=='assembly_overview' else 'content']
        def pdf_rows(data, doc, p, name):
            frame = frame_for(doc,p)
            with fitz.open(stream=data,filetype='pdf') as pdf:
                pp = pdf[doc['pages'].index(p)]
                pp.get_pixmap(matrix=fitz.Matrix(1,1)).save(str(output/(name+'-pdf.png')))
                words = pp.get_text('words')
                # Keep all measured words, and separately identify words in this
                # column below its row start. Footer text is outside the row area.
                start_y = frame['y']+24 if p['pageType']=='assembly_overview' else 124
                row_words = [w for w in words if w[0]>=frame['x']-.1 and w[2]<=frame['x']+frame['width']+.1
                    and w[1]>=start_y and w[1]<pp.rect.height-28]
                overflow = [w for w in row_words if w[3]>frame['y']+frame['height']+.5]
                # Drawings are still present outside the PDF media box even when
                # text extraction clips them. Record those row rules/circles too.
                drawings = [list(d['rect']) for d in pp.get_drawings()
                    if d['rect'].x0>=frame['x']-.5 and d['rect'].y0>=start_y and d['rect'].y1>frame['y']+frame['height']+.5]
            return {'frame':frame,'words':words,'rowWords':row_words,'outsideWords':overflow,'outsideDrawings':drawings,
                'compiledRows':len(p.get('manualGroupItems',p.get('entries',[])))}
        for key in ('parts50','parts100'):
            open_fixture(key, PARTS)
            doc = payload()['document']
            if key not in pdfs: export(key, 'p5a-'+key)
            findings = []
            for p in doc['pages']:
                if p.get('pageType') not in {'table_of_contents','assembly_overview','contents'}:
                    continue
                navigate(p['pageId'])
                wait_for_p4b_publication_capture(page)
                value = page.locator(SURFACE).evaluate("""(root,frame)=>{
                    const size=root.getBoundingClientRect(), scale=size.width/parseFloat(root.style.width);
                    return {frame,rows:[...root.querySelectorAll('table tr,.documentation-page-group-row')].map(r=>{
                        const a=r.getBoundingClientRect(), box={x:(a.x-size.x)/scale,y:(a.y-size.y)/scale,
                            width:a.width/scale,height:a.height/scale};
                        return {text:r.innerText,box,outside:box.y+box.height>frame.y+frame.height+.5||box.x+box.width>frame.x+frame.width+.5};})};}
                    """, frame_for(doc,p))
                name = 'p5a-'+key+'-'+p['pageId']
                page.locator(SURFACE).screenshot(path=str(output/(name+'-canvas.png')),timeout=T(20000))
                findings.append({'pageId':p['pageId'],'type':p['pageType'],'canvas':value,
                    'pdf':pdf_rows(pdfs[key],doc,p,name)})
            measurements['findings'][key+'_rows'] = findings
            record(key+'_overflow_evidence', bool(findings), {'pages':[f['pageId'] for f in findings]})
        if 'generated-p50' not in fixtures:
            # Supervisor: the generated assemblies are prepared only with DOC_SMOKE_P5A_GENERATED=1.
            measurements['findings']['generated_group_pdf'] = {'status': 'not prepared in this run'}
            measurements['findings']['search'] = {'status':'carried source finding, no speed change: search reads every target on each result-page request'}
            return
        measurements['findings']['generated_group_inventory'] = {
            'original': {k:fixtures[k] for k in ('generated-p50','generated-p100')},
            'limitation':'Model-free generated assemblies cannot enter this workspace. The fallback repeats nested real groups; its group-index counts differ. No claim of a browser measurement of the original 23/48-group pages.'}
        original_evidence = []
        for key in ('generated-p50','generated-p100'):
            number = fixtures[key]['assembly']
            base = server.url+'/api/parts-manual/'+number
            response = request.get(base+'/document',timeout=T(120000))
            if not response.ok: raise RuntimeError(response.text()[:1200])
            doc = response.json()['document']
            response = request.post(base+'/pdf',data={k:doc[k] for k in ('documentRevision','manualPlanRevision','sourceRevision')},timeout=T(180000))
            if not response.ok: raise RuntimeError(response.text()[:1200])
            response = request.get(server.url+response.json()['artifact']['url'],timeout=T(120000))
            if not response.ok: raise RuntimeError(response.text()[:1200])
            data = response.body(); (output/('p5a-'+key+'.pdf')).write_bytes(data)
            original_evidence.append({'fixture':key,'pages':[
                {'pageId':p['pageId'],'pdf':pdf_rows(data,doc,p,'p5a-'+key+'-'+p['pageId'])}
                for p in doc['pages'] if p['pageType'] in {'table_of_contents','assembly_overview'}]})
        measurements['findings']['generated_group_pdf'] = original_evidence
        record('original_generated_pdf_evidence',len(original_evidence)==2,{'fixtures':[v['fixture'] for v in original_evidence]})
        # Supervisor: a finding, not a failing check. The workspace opens only an assembly that has a model.
        measurements['findings']['generated_group_browser'] = {'status': 'not opened in the browser',
            'reason': 'The workspace has no model-free assembly path. The generated PDFs and the MMLE fallback pages are recorded separately.'}
        measurements['findings']['search'] = {'status':'carried source finding, no speed change: search reads every target on each result-page request'}
    stage('overflow_findings', overflow_findings)
    expected = ('open_base','open_parts50','open_parts100','open_operations50',
        'page_change_parts100','selection','typing_text','typing_table','escape_cancel','save_done','undo','redo',
        'reload_parts100','pdf_parts100','pdf_operations50','object_batch_operations50')
    measurements['findings']['contrast_older_styles'] = {
        'note': 'Below 4.5:1, from styles older than this build; not changed here.', 'pairs': list(older_contrast.values())}
    record('contrast_older_styles_listed', True, measurements['findings']['contrast_older_styles'])
    if only:
        record('all_stages', False, {'ran': sorted(only), 'skipped': skipped, 'note': 'A run of chosen stages is not a gate run.'})
    for name in expected:
        value = measurements['measurements'].get(name)
        if only:
            continue
        if value is None:
            measurements['measurements'][name] = {'unavailable': 'An earlier check failed; no sample was fabricated.'}
            record('measurement_'+name, False, measurements['measurements'][name])
    measurements['elapsedSeconds'] = time.monotonic()-start
    record('measurements_written', destination.exists(), {'file':destination.name,'seconds':measurements['elapsedSeconds']})
    record('phase_time', measurements['elapsedSeconds'] <= limit, {'seconds':measurements['elapsedSeconds'],'budgetSeconds':limit,'waitFactor':slow})
    record('phase_time_gate', limit <= 40*60, {'budgetSeconds': limit, 'gateSeconds': 40*60,
        'note': 'A run with a longer limit measures; it is not a gate run.'})
    flush()
