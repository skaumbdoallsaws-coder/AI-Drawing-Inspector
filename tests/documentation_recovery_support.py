"""Test-only child driver. All mutable paths come from pytest's temporary directory."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import time

from tests.test_documentation_transactions import SceneHarness, request_for, NUMBER, SOURCE, PLAN, PAGE
from ai_inspector.documentation.commands import canonical_bytes
from ai_inspector.parts_manual import documentation as scene_store


def loaded(store):
    return store.repo.read(NUMBER, SOURCE, PLAN)


def snapshot(store):
    return canonical_bytes(loaded(store))


def assert_complete(store, before, after, *, refused=None):
    """One public-read comparison, including scene, history choices and receipts.

    An unsupported future schema must remain unreadable; compare its canonical file
    only after the public reader has produced the expected refusal.
    """
    try:
        actual = snapshot(store)
    except Exception as error:
        if refused is None:
            raise
        assert isinstance(error, refused)
        actual = canonical_bytes(json.loads(store.path.read_bytes()))
    else:
        assert refused is None, "A future schema unexpectedly opened"
    assert actual in (before, after), "Store is neither the complete pre-image nor the complete post-image"
    return actual


def seed(root):
    store = SceneHarness(Path(root))
    store.commit(request_for(store, {"title": "committed", "caption": "original"}))
    return store


def export_document():
    # The flow compiler, not a prebuilt PDF or a fabricated artifact receipt.
    from ai_inspector.operations_manual.flow import FlowLayoutEngine, publication_layout
    blocks = [{"blockId": "body", "blockType": "paragraph", "readingOrder": 1,
               "payload": {"text": "Recovery export complete."}}]
    pages = FlowLayoutEngine(start_page_number=1).layout([
        {"sectionId": "recovery", "title": "Recovery", "blocks": blocks}])
    return {"schemaVersion": 3, "documentType": "operations_and_maintenance_manual",
        "sourceRevision": SOURCE, "manualPlanRevision": PLAN, "documentRevision": "a" * 64,
        "documentNumber": "RECOVERY-001", "title": "Recovery", "status": "draft_review",
        "product": {"name": "Recovery", "assemblyNumber": NUMBER}, "pages": pages,
        "pageCount": len(pages), "publicationLayout": publication_layout(),
        "releaseGate": {"reviewPdfAllowed": True}, "exportMode": "review"}


def child(control):
    config = json.loads((control / "input.json").read_text())
    store = SceneHarness(Path(config["root"]))
    point = config.get("point")
    def barrier():
        (control / "ready").write_text(point or "ready")
        while not (control / "go").exists():
            time.sleep(.01)
    replace_file = os.replace
    def replace(source, destination):
        destination = Path(destination)
        is_scene = destination.name == "documentation-scene.json"
        if is_scene:
            (control / "candidate.json").write_bytes(Path(source).read_bytes())
        if point in {"before_replace", "race"} and is_scene:
            barrier()
        if point == "before_backup" and destination.name == "documentation-scene.v7.json":
            barrier()
        if point == "export_before_replace" and destination.suffix in {".pdf", ".docx"}:
            barrier()
        result = replace_file(source, destination)
        if point == "after_replace" and is_scene:
            barrier()
        if point == "after_backup" and destination.name == "documentation-scene.v7.json":
            barrier()
        if point == "export_payload" and destination.suffix in {".pdf", ".docx"}:
            barrier()
        if point == "export_ready" and destination.name in {"review-pdf.json", "review-docx.json"}:
            barrier()
        return result
    os.replace = replace
    try:
        action = config["action"]
        if action == "commit":
            request = config["request"]
            if point == "race":
                # Both hosts prepared the same pre-image before entering the store.
                result = store.repo.apply_batch(NUMBER, SOURCE, PLAN,
                    base_revision=request["sceneRevision"], expected_revision=request["expectedRevision"],
                    request_id=request["requestId"],
                    commands=[{"operation": "update_text", "pageId": PAGE, "targetType": "page_element",
                               "targetId": key, "text": value} for key, value in request["values"].items()],
                    page_targets=store.page_targets, expected_hashes=request["hashes"], current_hashes=request["hashes"],
                    hashes_revision=request["sceneRevision"], payload=request)["receipt"]
            else:
                result = store.commit(request)
        elif action == "read":
            result = loaded(store)
        elif action == "refresh":
            document = deepcopy(store.document)
            document.update(schemaVersion=3, documentType="work_instructions", sourceRevision="source-2",
                            manualPlanRevision=PLAN, product={"assemblyNumber": NUMBER})
            document["pages"][0]["layoutBlocks"][0]["text"] = "new generated text"
            def rebuild(candidate):
                # Compile while refresh holds its transaction, before any persistent replace.
                export_document()
                barrier()
            from ai_inspector.documentation.identity import compile_identities
            document = compile_identities(document)
            current = store.repo.read(NUMBER, "source-2", PLAN, identity_document=document)
            result = store.repo.refresh(NUMBER, "source-2", PLAN, base_revision=current["revision"],
                identity_document=document, validate_candidate=rebuild)
        elif action == "export":
            from ai_inspector.operations_manual import exports
            result = getattr(exports, "store_prototype_" + config["kind"])(
                Path(config["exports"]), NUMBER, export_document())
        else:
            raise AssertionError(action)
        (control / "result.json").write_bytes(canonical_bytes({"ok": True, "result": result}))
    except Exception as error:
        (control / "result.json").write_bytes(canonical_bytes({"ok": False,
            "type": type(error).__name__, "code": getattr(error, "code", None), "message": str(error)}))
        raise


if __name__ == "__main__":
    child(Path(sys.argv[1]))
