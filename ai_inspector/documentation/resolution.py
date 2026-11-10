"""Pure conflict resolution candidates; owners supply locks, receipts and persistence."""
from copy import deepcopy
import re

from .commands import DocumentEditError, digest

RESOLUTION_HISTORY_LIMIT = 100


def conflict_hash(item):
    target = {key: item.get(key) for key in ("targetId", "pageId", "alias", "scopeId", "targetKind")}
    target["targetKind"] = item.get("targetKind") or target_kind(item.get("targetId", ""), (item.get("C") or {}).get("payload"))
    return digest({"target": target, "B": item.get("B"), "C": item.get("C"), "N": item.get("N"),
                   "status": item.get("status", "open"), "reason": item.get("reason"),
                   "relatedConflicts": item.get("relatedConflicts")})


def with_hash(item):
    return {**deepcopy(item), "conflictHash": conflict_hash(item)}


def orphan_review(item, state):
    from .refresh import open_conflicts
    result = deepcopy(item)
    related = [{"conflictId": c["conflictId"], "conflictHash": conflict_hash(c)} for c in open_conflicts(state)
               if c.get("N") is None and c.get("targetId") == item.get("targetId") and c.get("conflictId")]
    if related:
        result["relatedConflicts"] = related
    return with_hash(result)


def validate_resolution_metadata(state):
    history = state.get("resolutionHistory", [])
    if not isinstance(history, list) or len(history) > RESOLUTION_HISTORY_LIMIT:
        raise DocumentEditError("unsupported_document_schema", "Invalid conflict resolution history.")
    for item in history:
        if (not isinstance(item, dict) or item.get("status") not in {"resolved", "detached", "restored"}
                or not isinstance(item.get("resolutionReceipt"), dict)):
            raise DocumentEditError("unsupported_document_schema", "Invalid conflict resolution audit entry.")
    collections = [state.get("conflicts") or [], state.get("orphans") or [], history]
    for collection in collections:
        for item in collection.values() if isinstance(collection, dict) else collection:
            if "conflictHash" in item and item["conflictHash"] != conflict_hash(item):
                raise DocumentEditError("unsupported_document_schema", "Invalid stored conflict hash.")


def resolution_paths(before, after):
    paths = set()
    for root in ("conflicts", "orphans", "resolutionHistory"):
        def entries(state):
            values = state.get(root) or []
            return {item.get("conflictId") or item.get("orphanId"): item
                    for item in (values.values() if isinstance(values, dict) else values)}
        left, right = entries(before), entries(after)
        for key in set(left) | set(right):
            if left.get(key) != right.get(key):
                paths.add((root, key))
    for key in set(before.get("generatedBaseline", {})) | set(after.get("generatedBaseline", {})):
        if before.get("generatedBaseline", {}).get(key) != after.get("generatedBaseline", {}).get(key):
            paths.add(("generatedBaseline", key))
    return paths


def target_kind(key, payload=None):
    key = str(key or "")
    payload = payload if isinstance(payload, dict) else {}
    if re.search(r"\.r[0-9]+\.c[0-9]+$", key):
        return "cell"
    if re.search(r"\.i[0-9]+$", key):
        return "item"
    if key.startswith("slot:"):
        return "slot_label" if key.endswith(".label") else "slot_value"
    if key.startswith("part."):
        return "cell"
    if key.startswith("gen-"):
        return key.split("-", 2)[1]
    if payload.get("type"):
        return "object:" + str(payload["type"])
    for kind in ("occurrence", "manual_group", "balloon", "leader"):
        if "/" + kind + "/" in key:
            return kind
    return "figure" if any(field in payload for field in ("camera", "cameraPreset", "cameraPosition")) else "text"


def storage_address(key, generated):
    page = "page-parts-index" if key.startswith("part.") else generated["pageId"]
    for kind, collection in (("occurrence", "occurrenceOverrides"), ("manual_group", "manualGroupOverrides"),
                             ("balloon", "balloonOverrides"), ("leader", "leaderOverrides")):
        if "/" + kind + "/" in key:
            return page, collection, generated["alias"]
    if generated.get("targetKind") == "figure":
        return page, "figureOverride", None
    if generated.get("targetKind", "").startswith("object:"):
        return page, "documentObjects", key
    return page, "pageElementOverrides", generated.get("storageId", key)


def restore_catalog(state, document, targets, hashes):
    from .commands import content_hash
    from .refresh import inventory
    generated, targets, hashes = inventory(document), deepcopy(targets), dict(hashes)
    for page_id, page in state.get("pages", {}).items():
        for key, item in page.get("documentObjects", {}).items():
            generated[key] = {"payload": deepcopy(item), "hash": digest(item),
                "binding": {field: document[field] for field in ("sourceRevision", "manualPlanRevision")}, "evidence": {},
                "pageId": page_id, "alias": key, "label": item.get("name", key), "scopeId": key,
                "identity": {"ownership": "authored"}, "targetKind": "object:" + str(item["type"])}
    for key, value in generated.items():
        kind = value.setdefault("targetKind", target_kind(key, value["payload"]))
        if key not in targets:
            page, collection, storage = storage_address(key, value)
            container = state.get("pages", {}).get(page, {}).get(collection, {})
            current = container if storage is None else container.get(storage)
            targets[key] = {"targetId": key, "pageId": page, "kind": kind, "attributes": {}}
            hashes[key] = content_hash(state, key, {"generated": value, "current": current})
    return generated, targets, hashes


def validate_request(arguments):
    required = {"documentId", "expectedRevision", "requestId", "resolutions"}
    if not isinstance(arguments, dict) or set(arguments) != required:
        raise DocumentEditError("invalid_document_operation", "Resolve with document, revision, request ID and resolutions.")
    items = arguments["resolutions"]
    if not isinstance(items, list) or not 1 <= len(items) <= 12:
        raise DocumentEditError("invalid_document_operation", "Resolve 1-12 requested targets together.")
    seen = set()
    for item in items:
        if (not isinstance(item, dict) or not {"conflictId", "expectedConflictHash", "choice"} <= set(item)
                or set(item) - {"conflictId", "expectedConflictHash", "choice", "mergedText", "targetId", "expectedContentHash"}
                or not isinstance(item.get("conflictId"), str) or item["conflictId"] in seen
                or not isinstance(item.get("expectedConflictHash"), str)
                or item.get("choice") not in {"keep_manual", "use_generated", "merge_text", "detach", "restore"}):
            raise DocumentEditError("invalid_document_operation", "Each resolution needs a unique conflict and its hash.")
        seen.add(item["conflictId"])
        if item["choice"] == "merge_text":
            if not isinstance(item.get("mergedText"), str) or len(item["mergedText"]) > 2000:
                raise DocumentEditError("invalid_document_operation", "merge_text requires mergedText of at most 2000 characters.")
        elif item.get("mergedText") is not None:
            raise DocumentEditError("invalid_document_operation", "mergedText is only used for merge_text.")
        if item["choice"] == "restore":
            if not all(isinstance(item.get(key), str) and item[key] for key in ("targetId", "expectedContentHash")):
                raise DocumentEditError("invalid_document_operation", "Restore requires an explicit target and its current hash.")
        elif any(item.get(key) is not None for key in ("targetId", "expectedContentHash")):
            raise DocumentEditError("invalid_document_operation", "A new target is only used for restore.")


def resolve(state, document, items, *, receipt, actor, at, targets, hashes, slots=False):
    from .refresh import open_conflicts, assert_writable
    generated, targets, hashes = restore_catalog(state, document, targets, hashes)
    result = deepcopy(state)
    conflicts = result.get("conflicts") or []
    result["conflicts"] = list(conflicts.values()) if isinstance(conflicts, dict) else conflicts
    result.setdefault("orphans", [])
    result.setdefault("resolutionHistory", [])
    adopted, changed, destinations = [], [], set()
    for request in items:
        cid, choice = request["conflictId"], request["choice"]
        conflict = next((c for c in open_conflicts(result) if c.get("conflictId") == cid), None)
        orphan = next((o for o in result["orphans"] if o.get("orphanId") == cid), None)
        item = conflict or orphan
        if item is None:
            raise DocumentEditError("manual_edit_conflict", "This conflict is no longer open.", conflictId=cid)
        reviewed = orphan_review(item, result) if orphan is not None else item
        if request["expectedConflictHash"] != conflict_hash(reviewed):
            raise DocumentEditError("manual_edit_conflict", "The proposed value changed; read the conflict again.", conflictId=cid)
        if (orphan is not None) != (choice in {"detach", "restore"}):
            raise DocumentEditError("invalid_document_operation", "Use detach or restore only for an orphan.")
        key = request.get("targetId") if choice == "restore" else item.get("targetId")
        N = generated.get(key)
        if choice != "detach":
            if N is None or key not in targets:
                raise DocumentEditError("target_not_found", "The target is no longer present; refresh and review its orphan.", targetId=key)
            if targets[key].get("operation") == "read_only" or targets[key].get("attributes", {}).get("locked"):
                raise DocumentEditError("read_only_derived_field", "This destination is not editable.", targetId=key)
            if key in destinations:
                raise DocumentEditError("invalid_document_operation", "Resolve each destination only once.")
            destinations.add(key)
        if conflict is not None and choice != "detach":
            proposal = item.get("N")
            if proposal is None or any(proposal.get(field) != N.get(field) for field in ("payload", "evidence", "binding")):
                raise DocumentEditError("manual_edit_conflict", "The generated proposal changed; refresh and read it again.", conflictId=cid)
        if choice == "restore":
            if hashes.get(key) != request["expectedContentHash"]:
                raise DocumentEditError("content_hash_mismatch", "The restore target changed; read it again.", targetId=key)
            assert_writable(state, [key, N.get("scopeId")])
            old_kind = item.get("targetKind") or target_kind(item.get("targetId", ""), item["C"]["payload"])
            if old_kind != N.get("targetKind", target_kind(key, N["payload"])):
                raise DocumentEditError("invalid_document_operation", "Restore requires a target of the same kind.", targetId=key)
        if choice != "detach":
            scope = N.get("scopeId", key)
            result.setdefault("generatedBaseline", {})[key] = deepcopy(N)
            if choice == "use_generated":
                adopted.append(key)
                if slots:
                    # Suppress an older viewport fallback without treating this as a manual value.
                    result["values"][key[5:]] = {"value": N["payload"]["value"],
                        "source": N["evidence"].get("source"), "selectedGenerated": True}
                else:
                    for page in result.get("pages", {}).values():
                        override = page.get("pageElementOverrides", {}).get(key)
                        if override is not None:
                            for field in ("text", "richText"):
                                override.pop(field, None)
                            if not override:
                                page["pageElementOverrides"].pop(key)
                # A row-wide manual status is kept if another cell remains edited.
                meta = result.get("fieldMeta", {}).get(scope, {})
                siblings = set(meta.get("aliases", [key])) - {key}
                remaining = set("slot:" + s for s in result.get("values", {})) if slots else {
                    k for p in result.get("pages", {}).values() for k, v in p.get("pageElementOverrides", {}).items() if "text" in v}
                if not siblings & remaining:
                    result.setdefault("fieldMeta", {}).pop(scope, None)
            elif choice == "keep_manual":
                meta = result.setdefault("fieldMeta", {}).get(scope)
                if not meta:
                    meta = deepcopy(targets[key].get("attributes", {}).get("provenance") or item["C"].get("fieldMeta") or {})
                    evidence = N.get("evidence") or {}
                    meta.update(origin="manual", evidenceStatus="edited_unverified" if evidence.get("claimIds") or evidence.get("sourceIds") else "unbound",
                        targetId=scope, pageId=N["pageId"], aliases=meta.get("aliases") or [key], actor=actor, changeId=receipt["changeId"])
                    result["fieldMeta"][scope] = meta
            elif choice == "restore" and (N.get("targetKind", "").startswith("object:")
                    or N.get("targetKind") in {"figure", "occurrence", "manual_group", "balloon", "leader", "presentation"}):
                page, collection, storage = storage_address(key, N)
                value = deepcopy(item["C"]["payload"])
                if collection == "documentObjects":
                    value["objectId"] = key
                container = result.setdefault("pages", {}).setdefault(page, {})
                if storage is None:
                    container[collection] = value
                else:
                    container.setdefault(collection, {})[storage] = value
            elif choice in {"merge_text", "restore"}:
                payload = item["C"]["payload"]
                text = request["mergedText"] if choice == "merge_text" else payload.get("text", payload.get("value"))
                if not isinstance(text, str):
                    raise DocumentEditError("invalid_document_operation", "This target does not contain reattachable text.")
                if slots:
                    from ai_inspector.specification_sheet.slots import _clean, parse_slot, MAX_LABEL, MAX_VALUE
                    _, _, part = parse_slot(key[5:])
                    if _clean(text, MAX_LABEL if part == "label" else MAX_VALUE, key) != text:
                        raise DocumentEditError("invalid_document_operation", "The resolution must be an exact valid slot value.")
                    result["values"][key[5:]] = {"value": text, "source": "workspace" if actor == "user" else "sage_draft", "at": at}
                else:
                    page = "page-parts-index" if key.startswith("part.") else N["pageId"]
                    override = result.setdefault("pages", {}).setdefault(page, {}).setdefault("pageElementOverrides", {}).setdefault(key, {})
                    if choice == "restore":
                        original = item["C"].get("override") or payload
                        override.update({field: deepcopy(value) for field, value in original.items()
                            if field in {"style", "translation", "rotation", "scale", "richText"}})
                    else:
                        override.pop("richText", None)
                    override["text"] = text
                evidence = N.get("evidence") or {}
                previous = deepcopy(result.get("fieldMeta", {}).get(scope) or item["C"].get("fieldMeta") or {})
                previous.pop("confirmation", None)
                generated_meta = document.get("fieldMeta", {}).get(scope, {})
                generated_value = generated_meta.get("generatedValue", N["payload"].get("value") if slots else {key: N["payload"].get("text")})
                previous.update(origin="manual", evidenceStatus="edited_unverified" if evidence.get("claimIds") or evidence.get("sourceIds") else "unbound",
                    actor=actor, changeId=receipt["changeId"], sourceRevision=document["sourceRevision"],
                    targetId=scope, pageId=N["pageId"], aliases=[key] if choice == "restore" else previous.get("aliases") or [key],
                    generatedValue=deepcopy(generated_value), generatedHash=digest(generated_value))
                result.setdefault("fieldMeta", {})[scope] = previous
        status = "resolved" if conflict is not None else "detached" if choice == "detach" else "restored"
        audit = {**deepcopy(item), "status": status, "resolutionReceipt": deepcopy(receipt),
                 "resolution": {"choice": choice, "actor": actor, "at": at, "targetId": key}}
        result["resolutionHistory"].append(with_hash(audit))
        # Once a conflicted source disappears, its orphan is the actionable
        # record. Its hash includes these exact linked conflicts, so detach or
        # restore closes them atomically without leaving an unresolvable blocker.
        for linked in reviewed.get("relatedConflicts", []):
            previous = next(c for c in result["conflicts"] if c.get("conflictId") == linked["conflictId"])
            result["conflicts"].remove(previous)
            result["resolutionHistory"].append(with_hash({**previous, "status": "resolved",
                "resolutionReceipt": deepcopy(receipt), "resolution": deepcopy(audit["resolution"])}))
        result["conflicts" if conflict is not None else "orphans"].remove(item)
        changed.append(key or item.get("targetId") or cid)
    result["resolutionHistory"] = result["resolutionHistory"][-RESOLUTION_HISTORY_LIMIT:]
    return result, changed, adopted


def conflict_read(state, *, start=0, limit=20):
    from .refresh import exposure
    if type(start) is not int or start < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise DocumentEditError("invalid_document_operation", "Use a nonnegative offset and a limit of 1-100.")
    review = exposure(state)
    def describe(item):
        result = with_hash(item)
        result["target"] = {key: item.get(key) for key in ("targetId", "pageId", "alias", "label")}
        def text(side):
            payload = (item.get(side) or {}).get("payload")
            return payload.get("text", payload.get("value")) if isinstance(payload, dict) else None
        result["texts"] = {side: text(side) for side in ("B", "C", "N")}
        result["targetKind"] = item.get("targetKind") or target_kind(item.get("targetId", ""), (item.get("C") or {}).get("payload"))
        result["evidenceChanges"] = {"before": deepcopy(item.get("oldSourceRefs", (item.get("B") or {}).get("evidence", {}))),
                                     "after": deepcopy(item.get("newSourceRefs", (item.get("N") or {}).get("evidence", {})))}
        result.setdefault("status", "open")
        return result
    return {"documentId": state["documentId"], "revision": state["revision"],
            "openConflictCount": review["openConflictCount"], "orphanCount": len(review["orphans"]),
            "from": start, "limit": limit,
            **{key: [describe(item) for item in review[key][start:start + limit]]
               for key in ("conflicts", "orphans", "resolutionHistory")},
            "totals": {key: len(review[key]) for key in ("conflicts", "orphans", "resolutionHistory")}}
