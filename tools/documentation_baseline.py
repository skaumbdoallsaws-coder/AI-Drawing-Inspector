"""Offline documentation baseline using temporary stores, never the user's stores.

Use --inventory without application dependencies. --record writes a candidate JSON
only; --check never updates expectations. See docs/documentation-editor-reports/P0.md.
The default uses tracked synthetic fixtures and production Python APIs. --local
uses the authorized ignored MMLE inputs and server.app through TestClient, with
dotenv disabled and all document stores redirected. Its expectations are separate.
"""

from __future__ import annotations

import argparse
import ast
import copy
from contextlib import ExitStack
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ROOT / "docs/documentation-editor-reports/baseline/expected.json"
EXPECTED_LOCAL = EXPECTED.with_name("expected-local.json")
FIXED_TIME = "2026-11-09T12:00:00.000000Z"
DEPENDENCIES = {"numpy": "numpy", "PIL": "Pillow", "fitz": "PyMuPDF", "docx": "python-docx"}
PRIVATE_PARTS = {"ui-data", ".git", ".aws", ".codex", ".agents", "node_modules"}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode("ascii")).hexdigest()


def semantic(value):
    """Remove clocks only, retaining content, IDs, bindings, evidence and geometry.

    The fixture clocks and random IDs are also fixed. Do not strip source revisions,
    evidence, whitespace, list order or generic 'id'/'hash' fields to make a diff pass.
    """
    clocks = {"createdAt", "updatedAt", "capturedAt", "generatedAt", "exportedAt", "builtAt", "at"}
    if isinstance(value, dict):
        return {key: semantic(item) for key, item in value.items() if key not in clocks}
    if isinstance(value, list):
        return [semantic(item) for item in value]
    return value


def tracked_paths(root=ROOT):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    result = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
    # Names only. No file contents from excluded paths are inspected.
    return set(result.stdout.decode("utf-8").split("\0")) - {""}


def safe_source(relative, root=ROOT):
    parts = Path(relative).parts
    if any(part.lower() in PRIVATE_PARTS or part.lower().startswith(".env") for part in parts):
        raise ValueError("private source path is forbidden")
    candidate = (root / relative).resolve()
    candidate.relative_to(root.resolve())
    return candidate


def inventory():
    tracked = tracked_paths()
    required = [
        "ai_inspector/assembly_knowledge/documentation_assembly_registry.json",
        "docs/operations-manual/source-register.json",
        "docs/operations-manual/evidence-register.json",
        "docs/operations-manual/mmle-50d-prototype-plan.example.json",
        "docs/operations-manual/safety-symbol-register.json",
        "docs/specification-sheet/profiles/mmle-50d.json",
    ]
    return {
        "trackedPrerequisites": {name: name in tracked for name in required},
        "mmleGoldenTracked": "tests/specification_sheet_mmle_50d_golden.txt" in tracked,
        "fixtures": {
            "parts": "tests/test_parts_manual.py::_assembly_profile (synthetic manual-fixture)",
            "specification": "same synthetic assembly; generic open-slot compiler, no reviewed MMLE claims",
            "inspection": "tests/test_inspection_sheet.py::_document (synthetic ASM-1)",
            "table": "synthetic cited table; scene API and operations _edited_block only",
        },
        "notBuildableFromTrackedInputsAlone": {
            "tricycle": "No tracked tricycle assembly extraction/model found; test scene labels are not CAD data.",
            "operations_and_maintenance_manual": "MMLE registry/profile/model and evidence JSON are not tracked.",
            "work_instructions": "MMLE assembly and process-map evidence package are not tracked.",
            "reviewed_mmle_specification": "Golden text alone cannot reconstruct evidence/profile/CAD inputs.",
        },
    }


def local_inventory(root=ROOT):
    """Check only authorized engineering inputs; never inspect environment files.

    Presence is separate from git tracking. Once present, malformed inputs or a
    failing compiler are errors, not grounds to turn a failed check into a skip.
    """
    required = [
        "ai_inspector/assembly_knowledge/documentation_assembly_registry.json",
        "docs/operations-manual/source-register.json",
        "docs/operations-manual/evidence-register.json",
        "docs/operations-manual/mmle-50d-prototype-plan.example.json",
        "docs/operations-manual/safety-symbol-register.json",
        "docs/specification-sheet/profiles/mmle-50d.json",
        "400S_Sorted_Library/part_number_registry.json",
    ]
    groups = ["docs/process-map/mmle-50d-synthetic", "docs/semantic-knowledge",
              "generated/training/mmle-50d-497533f6"]
    missing = [name for name in required if not safe_source(name, root).is_file()]
    registry = safe_source(required[0], root)
    if registry.is_file():
        payload = json.loads(registry.read_text(encoding="utf-8-sig"))
        if not any(row.get("assemblyNumber") == "MMLE-50D" for row in payload["assemblies"]):
            raise ValueError("local documentation registry does not include MMLE-50D")
        # The production loader validates every registered assembly, including TR1631.
        for row in payload["assemblies"]:
            for key in ("profilePath", "modelPath"):
                name = row[key]
                safe_source(name, root).relative_to(safe_source("generated/industrial_assets/local_library", root))
                required.append(name)
            required.append(str(Path(row["profilePath"]).with_name("catalog-entry.json")).replace("\\", "/"))
    for group in groups:
        files = [p for p in safe_source(group, root).rglob("*.json") if ".backup-" not in p.name]
        if not files:
            missing.append(group + "/<JSON inputs>")
        required.extend(p.relative_to(root).as_posix() for p in files)
    # Include all supplied evidence/profile JSON, not just the minimum sentinels.
    for group in ("docs/operations-manual", "docs/specification-sheet/profiles"):
        required.extend(p.relative_to(root).as_posix() for p in safe_source(group, root).glob("*.json"))
    missing.extend(name for name in required if not safe_source(name, root).is_file())
    return {"available": not missing, "missingInputs": sorted(set(missing)),
            "inputFiles": sorted(set(required))}


def dependencies_missing(local=False):
    dependencies = {**DEPENDENCIES, **({"fastapi": "fastapi", "httpx": "httpx", "dotenv": "python-dotenv"}
                                     if local else {})}
    return [distribution for module, distribution in dependencies.items()
            if importlib.util.find_spec(module) is None]


def fixture_functions(relative, names, namespace):
    """Reuse explicit test fixture functions without importing server/pytest tests.

    Only named, reviewed FunctionDef nodes are compiled; no imports or other module
    statements run. Real production modules still import normally (no dependency stubs).
    """
    source = safe_source(relative).read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=relative)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in functions} != set(names):
        raise AssertionError(f"fixture functions changed: {relative}")
    module = ast.Module(body=functions, type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), relative, "exec"), namespace)
    return namespace


def file_hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*.json"))}


def pdf_fingerprint(payload):
    import fitz

    with fitz.open(stream=payload, filetype="pdf") as pdf:
        return {"pages": [{"textSha256": fingerprint(page.get_text().replace("\r\n", "\n")),
                           "characters": len(page.get_text()),
                           "sizePt": [page.rect.width, page.rect.height]}
                          for page in pdf]}


def docx_paragraphs(payload):
    # XML traversal includes nested tables/text boxes in document order. Runs are
    # concatenated, paragraphs separated, explicit tabs/breaks retained. No ZIP IDs.
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(io.BytesIO(payload)) as package:
        tree = ET.fromstring(package.read("word/document.xml"))
    texts = []
    for paragraph in tree.iter(ns + "p"):
        texts.append("".join(node.text or "" if node.tag == ns + "t" else
                             "\t" if node.tag == ns + "tab" else "\n"
                             for node in paragraph.iter()
                             if node.tag in {ns + "t", ns + "tab", ns + "br", ns + "cr"}))
    return texts


def docx_fingerprint(payload):
    texts = docx_paragraphs(payload)
    text = "\n".join(texts)
    return {"textSha256": fingerprint(text), "characters": len(text), "paragraphs": len(texts)}


def scene_edit(repository, binding, state, targets, page_id, target_id, text):
    return repository.apply_command(*binding, base_revision=state["revision"], page_targets=targets,
                                    command={"operation": "update_text", "targetType": "page_element",
                                             "pageId": page_id, "targetId": target_id,
                                             "text": text, "actor": "user"})


def parts_baseline(store, fixtures):
    from ai_inspector.parts_manual import (DocumentationSceneRepository, PartsManualRepository,
                                          build_manual_document, build_occurrence_catalog)
    from ai_inspector.parts_manual.artifacts import attach_render_artifacts, store_render_artifact
    from ai_inspector.parts_manual.document import PART_TEXT_PAGE_ID, part_text_target_id
    from ai_inspector.parts_manual.pdf import build_manual_pdf_bytes

    profile = fixtures["_assembly_profile"]()
    assembly = "manual-fixture"
    catalog = build_occurrence_catalog(assembly, profile)
    rows = catalog["occurrences"]
    repo = PartsManualRepository(store)
    initial = repo.read(assembly, catalog["sourceRevision"])
    plan = repo.create_section(assembly, catalog["sourceRevision"], base_revision=initial["revision"],
                               name="Workholding Station", occurrence_ids=[r["occurrenceId"] for r in rows],
                               catalog=rows)
    binding = (assembly, catalog["sourceRevision"], plan["revision"])
    scenes = DocumentationSceneRepository(store)
    state = scenes.read(*binding)

    def build(current):
        return build_manual_document(plan["plan"], rows, profile, plan_revision=plan["revision"],
                                     documentation_scene=current["scene"],
                                     documentation_scene_revision=current["revision"])

    before = build(state)
    definition = next(row["definitionId"] for row in rows if row["partNumber"] == "WB-100")
    target = part_text_target_id(definition, "description")
    targets = {"page-cover": {"page_element": ["header_title"]},
               PART_TEXT_PAGE_ID: {"page_element": [target]}}
    state = scene_edit(scenes, binding, state, targets, "page-cover", "header_title", "BASELINE PARTS MANUAL")
    first = state
    state = scene_edit(scenes, binding, state, targets, PART_TEXT_PAGE_ID, target, "Baseline steel workbench")
    edited = build(state)
    disk = file_hashes(store)
    reopened = DocumentationSceneRepository(store).read(*binding)
    reopened_doc = build(reopened)
    assert edited_without_command(state) == reopened and semantic(edited) == semantic(reopened_doc)
    assert disk == file_hashes(store), "read rewrote the saved store"
    undone = scenes.move_history(*binding, base_revision=state["revision"], direction="undo")
    assert undone["scene"]["pages"] == first["scene"]["pages"]
    redone = scenes.move_history(*binding, base_revision=undone["revision"], direction="redo")
    assert redone["scene"]["pages"] == state["scene"]["pages"]
    assert any(row.get("description") == "Baseline steel workbench"
               for page in edited["pages"] for row in page.get("bom", []))
    exports = {}
    for label, document in (("before", before), ("edited", edited)):
        for page in document["pages"]:
            if not page.get("renderRequest"):
                continue
            items = page["renderRequest"].get("calloutItems", [])
            balloons = [fixtures["_valid_balloon"](row, index, len(items)) for index, row in enumerate(items)]
            store_render_artifact(store, assembly, document, page["pageId"], fixtures["_png"](), balloons=balloons)
        attached = attach_render_artifacts(store, assembly, document)
        exports[label] = pdf_fingerprint(build_manual_pdf_bytes(store, assembly, attached))
    reset = scenes.rebaseline(*binding)
    return {"before": fingerprint(semantic(before)), "edited": fingerprint(semantic(edited)),
            "reopened": fingerprint(semantic(reopened_doc)), "reopenUnchanged": True,
            "readDidNotWrite": True, "pdf": exports, "docx": "unsupported",
            "undo": {"commandsForTwoEdits": state["scene"]["historyCursor"],
                     "oneUndoPreservesFirstEdit": True, "redoRestoresBoth": True,
                     "rebaselineDropsOverrides": reset["scene"]["pages"] == {},
                     "rebaselineDropsHistory": reset["scene"]["commands"] == []}}, profile, catalog


def specification_baseline(store, profile, catalog, fixtures):
    from ai_inspector.parts_manual.documentation import DocumentationSceneRepository
    from ai_inspector.specification_sheet.document import build_specification_sheet_document
    from ai_inspector.specification_sheet.slots import SlotStore
    from ai_inspector.specification_sheet.exports import build_specification_pdf_bytes, build_specification_docx_bytes

    assembly = catalog["assemblyNumber"]
    # Empty, isolated input roots select the generic-sheet path. Local MMLE
    # profiles belong to the separate --local section, not this tracked fixture.
    def build():
        return build_specification_sheet_document(profile, catalog, evidence_root=store / "ev",
                                                 profile_root=store / "pr", slot_root=store)

    before = build()
    slots = SlotStore(store, assembly)
    slots.set_values([{"slot": "spec.weight.value", "value": "95 lb"}], source="workspace")
    edited = build()
    disk = file_hashes(store)
    reopened_slots = SlotStore(store, assembly).read()
    reopened = build()
    assert reopened_slots["values"]["spec.weight.value"]["value"] == "95 lb"
    assert semantic(reopened) == semantic(edited) and disk == file_hashes(store)
    scene = DocumentationSceneRepository(store).read(assembly, edited["sourceRevision"], edited["manualPlanRevision"])
    # Actual persistent scene cursor after the slot edit, not an inferred UI label.
    undo = {"slotEditCreatesSceneUndo": scene["canUndo"],
            "slotStoreHasUndoMethod": callable(getattr(slots, "move_history", None))}
    exports = {}
    for label, document in (("before", before), ("edited", edited)):
        attached = specification_capture(store, assembly, document, fixtures["_png"](2200, 2200))
        exports[label] = {
            "pdf": pdf_fingerprint(build_specification_pdf_bytes(attached, render_root=store, assembly_number=assembly)),
            "docx": docx_fingerprint(build_specification_docx_bytes(attached, render_root=store, assembly_number=assembly)),
        }
    return {"before": fingerprint(semantic(before)), "edited": fingerprint(semantic(edited)),
            "reopened": fingerprint(semantic(reopened)), "reopenUnchanged": True, "readDidNotWrite": True,
            "exports": exports, "undo": undo}


def specification_capture(store, assembly, document, payload):
    """Mirror server's store AND _specification_sheet_attach_capture paths exactly."""
    from ai_inspector.operations_manual.artifacts import store_draft_render_artifact, attach_draft_render_artifacts

    result = copy.deepcopy(document)
    figure_document = {**result, "documentRevision": result["figureRevision"]}
    store_draft_render_artifact(store, assembly, figure_document, result["pages"][0]["pageId"], payload,
                                source_revision=result["sourceRevision"],
                                manual_plan_revision=result["manualPlanRevision"],
                                balloons=None, api_route="specification-sheet")
    probe = attach_draft_render_artifacts(store, assembly, figure_document)
    for page, attached in zip(result.get("pages") or [], probe.get("pages") or []):
        image = ((attached or {}).get("renderRequest") or {}).get("image") or {}
        if image.get("status") == "ready":
            page["renderRequest"]["image"] = {**image, "figureRevision": result["figureRevision"],
                                               "documentRevision": result["documentRevision"]}
    assert all(page["renderRequest"]["image"]["status"] == "ready" for page in result["pages"])
    return result


def table_baseline(store):
    from ai_inspector.parts_manual.documentation import DocumentationSceneRepository
    from ai_inspector.operations_manual.exports import _edited_block

    binding = ("table-fixture", "a" * 64, "b" * 64)
    repo = DocumentationSceneRepository(store)
    before = repo.read(*binding)
    block = {"blockId": "baseline-table", "blockType": "table", "columns": ["Name", "Value"],
             "rows": [{"cells": ["Capacity", "1,100 lb"], "claimIds": ["fixture-claim"],
                       "sourceIds": ["fixture-source"]}]}
    target = "baseline-table.r0.c1"
    edited = scene_edit(repo, binding, before, {"page-table": {"page_element": [target]}},
                        "page-table", target, "1,000 lb")
    page = {"documentationComposition": edited["scene"]["pages"]["page-table"]}
    shown = _edited_block(page, block)
    assert shown["rows"][0]["cells"][1] == "1,000 lb"
    disk = file_hashes(store)
    reopened = DocumentationSceneRepository(store).read(*binding)
    assert reopened == edited_without_command(edited) and disk == file_hashes(store)
    undone = repo.move_history(*binding, base_revision=edited["revision"], direction="undo")
    assert undone["scene"]["pages"] == before["scene"]["pages"]
    return {"editedBlock": fingerprint(semantic(shown)), "scene": fingerprint(semantic(edited["scene"])),
            "reopenUnchanged": True, "readDidNotWrite": True, "oneUndoRestoresCell": True,
            "editedCellKeepsOriginalClaimIds": shown["rows"][0].get("claimIds") == ["fixture-claim"],
            "editedCellKeepsOriginalSourceIds": shown["rows"][0].get("sourceIds") == ["fixture-source"],
            "scope": "isolated table adapter, not a generated operations manual or citation-status UI test"}


def edited_without_command(state):
    return {key: value for key, value in state.items() if key != "command"}


def inspection_baseline(store):
    from ai_inspector.inspection_sheet.document import build_inspection_sheet_document
    from ai_inspector.inspection_sheet.exports import build_inspection_sheet_pdf_bytes
    from ai_inspector.inspection_sheet.store import InspectionSheetStore
    from ai_inspector.utils.drawing_map import normalize_drawing_map
    import fitz

    fixtures = fixture_functions("tests/test_inspection_sheet.py",
                                 {"_annotation", "_drawing_map", "_descriptions", "_profile", "_document", "_drawing_pdf"},
                                 {"build_inspection_sheet_document": build_inspection_sheet_document,
                                  "normalize_drawing_map": normalize_drawing_map, "fitz": fitz})
    before = fixtures["_document"]()
    repo = InspectionSheetStore(store)
    receipt = repo.set_values("ASM-1", [{"name": "header.lot", "value": "BASELINE-LOT"}],
                              before["fields"], source="chat")
    assert receipt["set"] == ["header.lot"]
    edited = fixtures["_document"](repo.values("ASM-1"))
    disk = file_hashes(store)
    reopened = fixtures["_document"](InspectionSheetStore(store).values("ASM-1"))
    assert semantic(edited) == semantic(reopened) and disk == file_hashes(store)
    drawing = fixtures["_drawing_pdf"](store / "p1.pdf")
    exports = {label: pdf_fingerprint(build_inspection_sheet_pdf_bytes(document, drawing_pdfs={"P-1": drawing},
                                                                       built_at="2026-11-09 12:00 UTC")["pdf"])
               for label, document in (("before", before), ("edited", edited))}
    return {"before": fingerprint(semantic(before)), "edited": fingerprint(semantic(edited)),
            "reopened": fingerprint(semantic(reopened)), "reopenUnchanged": True, "readDidNotWrite": True,
            "pdf": exports, "docx": "unsupported", "undoMethod": callable(getattr(repo, "move_history", None))}


def collect():
    missing = dependencies_missing()
    if missing:
        raise RuntimeError("Missing dependencies (no installs attempted): " + ", ".join(missing))
    from PIL import Image, ImageDraw
    from ai_inspector.parts_manual.version import PARTS_MANUAL_DEFAULT_END_CONDITION

    fixtures = fixture_functions("tests/test_parts_manual.py", {"_assembly_profile", "_png", "_valid_balloon"},
                                 {"io": io, "Image": Image, "ImageDraw": ImageDraw,
                                  "PARTS_MANUAL_DEFAULT_END_CONDITION": PARTS_MANUAL_DEFAULT_END_CONDITION})
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    # Short names keep existing <revision>/<page>.json paths under MAX_PATH.
    counter = iter(range(1, 10000))
    with tempfile.TemporaryDirectory(prefix="db-", dir=runtime) as directory, \
            patch("secrets.token_hex", side_effect=lambda n=6: f"{next(counter):0{n * 2}x}"), \
            patch("ai_inspector.parts_manual.repository._utc_now", return_value=FIXED_TIME), \
            patch("ai_inspector.parts_manual.documentation._utc_now", return_value=FIXED_TIME), \
            patch("ai_inspector.specification_sheet.slots.now", return_value=FIXED_TIME), \
            patch("ai_inspector.inspection_sheet.store._now", return_value=FIXED_TIME):
        store = Path(directory)
        parts, profile, catalog = parts_baseline(store / "p", fixtures)
        specification = specification_baseline(store / "s", profile, catalog, fixtures)
        table = table_baseline(store / "t")
        inspection = inspection_baseline(store / "i")
    return {"schemaVersion": 1, "status": "captured", "fixtureKind": "synthetic_tracked_test_data",
            "apiLayer": "production Python repositories and exporters; no HTTP or live CAD proof",
            "inventory": inventory(), "parts": parts, "specification": specification,
            "table": table, "inspection": inspection}


def api_json(client, method, url, **kwargs):
    response = client.request(method, url, **kwargs)
    assert response.status_code == 200, f"{method} {url}: {response.status_code} {response.text[:1000]}"
    return response.json()


def local_citation_target(document):
    """Pin the real two-column compiled target, not a synthetic plan-row shape."""
    page = next((p for p in document["pages"] if p["pageId"] == "page-specifications-1"), None)
    assert page is not None, "MMLE citation probe page page-specifications-1 is missing"
    block = next((b for b in page.get("layoutBlocks", []) if b["blockId"] == "spec-table-1"), None)
    assert block is not None, "MMLE citation probe block spec-table-1 is missing"
    assert block.get("rows") and block["rows"][0]["cells"][0] == "Rated capacity", "MMLE citation probe row changed"
    assert len(block["rows"][0]["cells"]) == 2, "MMLE citation probe expects the published two-column table"
    return page, block


def local_citation_state(document, block):
    row = block["rows"][0]
    # The association to this value is known from the fixture's plan. Current
    # compiled rows have only cells; evidenceClaimIds live on the whole block.
    citations = [{key: entry.get(key) for key in ("sourceId", "title", "authority", "url")}
                 for entry in document.get("evidenceCitations", []) if "CLM-SPEC-001" in entry.get("claimIds", [])]
    return {"cells": row["cells"], "rowKeys": sorted(row),
            "evidenceClaimIds": block.get("evidenceClaimIds", []), "claimCitations": citations}


def local_citation_export(document, block, texts):
    """Measure extracted export text, including the linked source-register rows.

    Neither exporter renders evidenceCitations/authority as an inline cell badge.
    content._source_rows supplies human-readable authority in the source register.
    Match those actual rows by cited source title, without inventing row bindings.
    Normalize wrapping whitespace only for presence checks; fingerprints stay exact.
    """
    normalized = lambda value: " ".join(value.split())
    pdf_pages = [normalized(value) for value in texts["pdf"]]
    docx = normalized(texts["docx"])
    cells = block["rows"][0]["cells"]
    row_text = normalized(" ".join(cells))
    pdf = {"valuePageNumbers": [index for index, text in enumerate(pdf_pages, 1) if cells[1] in text],
           "rowPageNumbers": [index for index, text in enumerate(pdf_pages, 1) if row_text in text]}
    word = {"valuePresent": cells[1] in docx, "rowPresent": row_text in docx}
    assert pdf["rowPageNumbers"], "MMLE cited specification row is missing from PDF text"
    assert word["rowPresent"], "MMLE cited specification row is missing from DOCX text"
    registers = []
    for citation in local_citation_state(document, block)["claimCitations"]:
        for page in document["pages"]:
            for source_block in page.get("layoutBlocks", []):
                if source_block.get("sourceBlockId") != "sources-table":
                    continue
                for row in source_block.get("rows", []):
                    source_cells = row.get("cells", [])
                    if not source_cells or normalized(source_cells[0]) != normalized(citation["title"]):
                        continue
                    register_text = normalized(" ".join(source_cells))
                    registers.append({"sourceId": citation["sourceId"], "authority": citation["authority"],
                                      "pageId": page["pageId"], "blockId": source_block["blockId"],
                                      "cells": source_cells,
                                      "pdfPageNumbers": [index for index, text in enumerate(pdf_pages, 1)
                                                         if register_text in text],
                                      "docxRowPresent": register_text in docx})
    return {"pdf": pdf, "docx": word, "sourceRegister": registers}


def work_instruction_text_capture_probe(client, store, document, capture, store_capture):
    """Record the export gate before recapturing only its pending work-instruction pages.

    A successful first export proves all figures were ready before the text edit.
    After P1b fixes capture binding, this same probe records false and writes none.
    The caller passes the production artifact writer; no capture repair is hidden
    inside the ordinary export/fingerprint path or applied to other document types.
    """
    response = client.post("/api/work-instructions/MMLE-50D/pdf")
    assert response.status_code in {200, 422}, f"work instruction export: {response.status_code} {response.text[:1000]}"
    receipt = response.json()
    pending = []
    if response.status_code == 422:
        assert receipt.get("error") == "work_instruction_capture_required", receipt
        assert receipt.get("status") == "CAPTURE_REQUIRED", receipt
        assert receipt.get("documentRevision") == document["documentRevision"], "capture refusal has a stale revision"
        pending = [page["pageId"] for page in receipt["pendingPages"]]
        assert pending and len(pending) == len(set(pending)) == receipt["requiredCaptureCount"], receipt
        pages = {page["pageId"]: page for page in document["pages"]}
        assert all(page_id in pages and pages[page_id].get("renderRequest") for page_id in pending), receipt
        for page_id in pending:
            store_capture(store, "MMLE-50D", document, page_id, capture(1920, 1080),
                          source_revision=document["sourceRevision"], manual_plan_revision=document["manualPlanRevision"],
                          api_route="work-instructions")
    facts = {"textEditInvalidatesPageCapture": bool(pending), "pagesNeedingCaptureAfterTextEdit": pending,
             "textEditExportHttpStatus": response.status_code, "recapturedPageIds": list(pending)}
    return facts, receipt if response.status_code == 200 else None


def local_document_baseline(client, route, store, capture):
    """Use the same real HTTP handlers as the neighboring MMLE workflow tests."""
    from ai_inspector.operations_manual.artifacts import store_draft_render_artifact
    from ai_inspector.operations_manual.exports import _edited_block

    base = f"/api/{route}/MMLE-50D"
    state = api_json(client, "POST", base + "/generate?rebaseline=true")
    document = state["document"]
    if route == "specification-sheet":
        page = document["pages"][0]
        api_json(client, "POST", base + f"/document/{page['pageId']}/render",
                 data={"documentRevision": document["documentRevision"], "figureRevision": document["figureRevision"],
                       "sourceRevision": document["sourceRevision"], "manualPlanRevision": document["manualPlanRevision"],
                       "renderPipelineVersion": str(document["renderPipelineVersion"]), "balloons": "[]"},
                 files={"file": ("product.png", capture(2200, 2200), "image/png")})
    else:
        for page in document["pages"]:
            if page.get("renderRequest"):
                # Existing workflow tests use this production artifact API for
                # synthetic captures. Generation, edits and export use server.app.
                store_draft_render_artifact(store, "MMLE-50D", document, page["pageId"], capture(1920, 1080),
                                            source_revision=document["sourceRevision"],
                                            manual_plan_revision=document["manualPlanRevision"], api_route=route)
    state = api_json(client, "GET", base + "/documentation-scene")
    before = state["document"]

    def exported(receipt=None):
        if receipt is None:
            receipt = api_json(client, "POST", base + "/pdf")
        payloads = {}
        for kind in ("pdf", "docx"):
            url = receipt[kind]["url"]
            assert url.startswith(base + "/"), "export URL escaped the bound local document"
            response = client.get(url)
            assert response.status_code == 200, response.text[:1000]
            payloads[kind] = response.content
        texts = None
        if route == "operations-manual":
            import fitz

            with fitz.open(stream=payloads["pdf"], filetype="pdf") as pdf:
                texts = {"pdf": [page.get_text() for page in pdf],
                         "docx": "\n".join(docx_paragraphs(payloads["docx"]))}
        return {"pdf": pdf_fingerprint(payloads["pdf"]), "docx": docx_fingerprint(payloads["docx"])}, texts

    before_exports, before_texts = exported()
    citation = None
    if route == "specification-sheet":
        target_id = "spec.rated_capacity.value"
        api_json(client, "POST", base + "/values", json={"values": [{"slot": target_id, "value": "1,000 lb"}]})
    else:
        if route == "operations-manual":
            page, block = local_citation_target(before)
            assert block["rows"][0]["cells"][1] == "1,100 lb", "MMLE citation probe's published capacity changed"
            assert "CLM-SPEC-001" in block.get("evidenceClaimIds", []), "MMLE capacity block has no expected claim"
            assert local_citation_state(before, block)["claimCitations"], "MMLE capacity claim has no source receipt"
            target_id = "spec-table-1.r0.c1"
            replacement = "1,000 lb"
        else:
            page = next(page for page in before["pages"] if page["pageId"] == "page-work-instructions-cover")
            block = next(block for block in page.get("layoutBlocks", []) if block["blockId"] == "wi-cover-status")
            assert page.get("renderRequest") and block.get("blockType") == "paragraph" and block.get("text")
            target_id, replacement = block["blockId"], "Baseline work instruction note."
        api_json(client, "POST", base + "/documentation-scene/commands", json={
            "baseRevision": state["revision"], "sourceRevision": before["sourceRevision"],
            "manualPlanRevision": before["manualPlanRevision"], "operation": "update_text",
            "pageId": page["pageId"], "targetType": "page_element", "targetId": target_id,
            "text": replacement, "actor": "user"})
    edited_state = api_json(client, "GET", base + "/documentation-scene")
    edited = edited_state["document"]
    if route == "operations-manual":
        compiled_page, compiled_block = local_citation_target(edited)
        shown = _edited_block(compiled_page, compiled_block)
        assert shown["rows"][0]["cells"][1] == replacement
        original = local_citation_state(before, block)
        effective = local_citation_state(edited, shown)
        citation = {
            "pageId": page["pageId"], "blockId": block["blockId"], "targetId": target_id, "claimId": "CLM-SPEC-001",
            "before": original, "compiledAfter": local_citation_state(edited, compiled_block), "effectiveAfter": effective,
            "compiledBlockKeepsCapacityClaim": "CLM-SPEC-001" in compiled_block.get("evidenceClaimIds", []),
            "changedValueKeepsBlockClaimIds": effective["evidenceClaimIds"] == original["evidenceClaimIds"],
            "changedValueKeepsCitationAuthorities": effective["claimCitations"] == original["claimCitations"],
        }
    disk = file_hashes(store)
    reopened = api_json(client, "GET", base + "/documentation-scene")
    assert semantic(edited) == semantic(reopened["document"])
    assert edited_state["revision"] == reopened["revision"] and disk == file_hashes(store)
    capture_facts, export_receipt = {}, None
    if route == "work-instructions":
        capture_facts, export_receipt = work_instruction_text_capture_probe(
            client, store, edited, capture, store_draft_render_artifact)
    after_exports, after_texts = exported(export_receipt)
    if citation:
        citation["exports"] = {"before": local_citation_export(before, block, before_texts),
                               "edited": local_citation_export(edited, shown, after_texts)}
    undo_body = {"baseRevision": edited_state["revision"], "sourceRevision": edited["sourceRevision"],
                 "manualPlanRevision": edited["manualPlanRevision"]}
    undo_response = client.post(base + "/documentation-scene/undo", json=undo_body)
    undo = {"canUndoAfterEdit": edited_state["canUndo"], "httpStatus": undo_response.status_code}
    if undo_response.status_code == 200:
        undone = undo_response.json()
        # Scene undo changes revision/history metadata, so compare effective text
        # and composition via the original scene projection, not whole envelopes.
        undo["restoresScenePages"] = undone["scene"]["pages"] == state["scene"]["pages"]
        if route == "specification-sheet":
            undo["restoresSlotValue"] = undone["document"]["slots"][target_id]["value"] == before["slots"][target_id]["value"]
        redone = api_json(client, "POST", base + "/documentation-scene/redo",
                          json={**undo_body, "baseRevision": undone["revision"]})
        undo["redoRestoresScenePages"] = redone["scene"]["pages"] == edited_state["scene"]["pages"]
        if route == "specification-sheet":
            undo["redoRestoresSlotValue"] = redone["document"]["slots"][target_id]["value"] == "1,000 lb"
    else:
        assert route == "specification-sheet", undo_response.text
        undo["error"] = undo_response.json().get("error")
        undo["slotValueSurvivesUndoAttempt"] = api_json(client, "GET", base + "/documentation-scene")[
            "document"]["slots"][target_id]["value"] == "1,000 lb"
    golden = {}
    if route == "specification-sheet":
        golden_hash = fingerprint(safe_source("tests/specification_sheet_mmle_50d_golden.txt").read_text(encoding="utf-8"))
        golden = {"trackedGoldenTextSha256": golden_hash,
                  "beforeMatchesTrackedGolden": before_exports["pdf"]["pages"][0]["textSha256"] == golden_hash}
    return {"before": fingerprint(semantic(before)), "edited": fingerprint(semantic(edited)),
            "reopened": fingerprint(semantic(reopened["document"])), "reopenUnchanged": True,
            "readDidNotWrite": True, "exports": {"before": before_exports, "edited": after_exports},
            "undo": undo, **golden, **capture_facts, **({"citationDefect": citation} if citation else {})}


def collect_local():
    available = local_inventory()
    if not available["available"]:
        return {"schemaVersion": 1, "status": "skipped", "reason": "local inputs absent",
                "missingInputs": available["missingInputs"]}
    missing = dependencies_missing(local=True)
    if missing:
        raise RuntimeError("Missing dependencies (no installs attempted): " + ", ".join(missing))
    from PIL import Image
    from fastapi.testclient import TestClient

    def capture(width, height):
        buffer = io.BytesIO()
        Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
        return buffer.getvalue()

    def input_hashes():
        return {name: hashlib.sha256(safe_source(name).read_bytes()).hexdigest() for name in available["inputFiles"]}

    original_inputs = input_hashes()
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dl-", dir=runtime) as directory, ExitStack() as stack:
        store = Path(directory)
        roots = {"PARTS_MANUAL_ROOT": store / "p", "OPERATIONS_MANUAL_ROOT": store / "o",
                 "WORK_INSTRUCTION_ROOT": store / "w", "SPECIFICATION_SHEET_ROOT": store / "s",
                 "INSPECTION_SHEET_ROOT": store / "i", "ASSEMBLY_APPEARANCE_ROOT": store / "a",
                 "PART_APPEARANCE_ROOT": store / "b"}
        # Explicit local library prevents server's fallback to the user's checkout.
        # MMLE comes from the documentation registry, not the external 100001 library.
        environment = {"INSPECTORPRO_" + name: str(value) for name, value in roots.items()}
        environment["INSPECTORPRO_LIBRARY_DIR"] = str(safe_source("400S_Sorted_Library"))
        stack.enter_context(patch.dict(os.environ, environment))
        stack.enter_context(patch("dotenv.load_dotenv", return_value=False))
        import server

        assert Path(server.__file__).resolve() == ROOT / "server.py", "server import escaped this worktree"
        for name, value in roots.items():
            stack.enter_context(patch.object(server, name, value))
        stack.enter_context(patch.object(server, "LIBRARY_DIR", safe_source("400S_Sorted_Library")))
        for name in ("assembly_profiles", "assembly_part_lookup", "prepared_assembly_sources"):
            stack.enter_context(patch.object(server, name, {}))
        stack.enter_context(patch.object(server, "_INSPECTION_SHEET_STORE", None))
        counter = iter(range(1, 100000))
        stack.enter_context(patch("secrets.token_hex", side_effect=lambda n=6: f"{next(counter):0{n * 2}x}"))
        for clock in ("ai_inspector.parts_manual.documentation._utc_now", "ai_inspector.specification_sheet.slots.now"):
            stack.enter_context(patch(clock, return_value=FIXED_TIME))
        # Like the neighboring tests, do not enter TestClient as a context manager:
        # that would start unrelated application lifespan services.
        client = TestClient(server.app)
        stack.callback(client.close)
        results = {name: local_document_baseline(client, route, roots[store_name], capture)
                   for name, route, store_name in (
                       ("operations", "operations-manual", "OPERATIONS_MANUAL_ROOT"),
                       ("workInstructions", "work-instructions", "WORK_INSTRUCTION_ROOT"),
                       ("reviewedSpecification", "specification-sheet", "SPECIFICATION_SHEET_ROOT"))}
    assert original_inputs == input_hashes(), "local engineering inputs changed during the baseline"
    return {"schemaVersion": 1, "status": "captured", "fixtureKind": "authorized_ignored_local_mmle_inputs",
            "apiLayer": "server.app via TestClient; synthetic captures, no browser/live CAD proof",
            "inputCount": len(original_inputs), "inputsSha256": fingerprint(original_inputs),
            "inputsUnchanged": True, **results}


def compare(actual, expected):
    if actual.get("status") == "skipped":
        raise AssertionError("skipped: local inputs absent; this is not a passing baseline")
    if expected.get("status") != "captured":
        raise AssertionError("Baseline fingerprints are pending Claude's capture/review; this is not a passing gate.")
    if actual != expected:
        changed = [key for key in sorted(set(actual) | set(expected)) if actual.get(key) != expected.get(key)]
        raise AssertionError("Baseline changed: " + ", ".join(changed) + ". Record a candidate and review the diff.")


def write_json(destination, value):
    destination = destination.resolve()
    destination.relative_to(ROOT)
    safe_source(destination.relative_to(ROOT))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes((json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--inventory", action="store_true")
    actions.add_argument("--check", action="store_true")
    actions.add_argument("--record", type=Path, metavar="CANDIDATE_JSON")
    parser.add_argument("--local", action="store_true", help="collect/check the optional local MMLE section only")
    args = parser.parse_args(argv)
    if args.inventory:
        print(json.dumps({**(local_inventory() if args.local else inventory()),
                          "missingDependencies": dependencies_missing(local=args.local)}, indent=2))
        return 0
    expected_path = EXPECTED_LOCAL if args.local else EXPECTED
    if args.record and args.record.resolve() in {EXPECTED.resolve(), EXPECTED_LOCAL.resolve()}:
        parser.error("record to a candidate file; reviewed expectations are never overwritten by the tool")
    try:
        result = collect_local() if args.local else collect()
        if result.get("status") == "skipped":
            print("skipped: local inputs absent")
            print(json.dumps(result, indent=2))
            return 3
        if args.record:
            write_json(args.record, result)
            print(f"Recorded candidate: {args.record}")
        else:
            compare(result, json.loads(expected_path.read_text(encoding="ascii")))
            print("Documentation baseline matches; reopened stores were unchanged.")
    except (AssertionError, RuntimeError, ImportError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
