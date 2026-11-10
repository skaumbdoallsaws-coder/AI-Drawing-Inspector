"""Guarded inverse records shared by the existing scene and slot stores.

Records contain document fields, never storage paths. Store owners hold their
locks, validate bindings and persist the inverse with its receipt atomically.
"""
from copy import deepcopy
from .commands import DocumentEditError, digest, canonical_bytes

MAX_CHANGES = 2000


def image(state, path):
    node = state
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return {"present": False}
        node = node[key]
    return {"present": True, "value": deepcopy(node)}


def restore(state, changes, *, side="after", root=None):
    for item in changes:
        path = item["path"]
        if root is not None:
            if path[0] != root:
                continue
            path = path[1:]
        node = state
        value = item[side]
        for key in path[:-1]:
            if key not in node:
                if not value["present"]:
                    break
                node[key] = {}
            node = node[key]
        else:
            if value["present"]:
                node[path[-1]] = deepcopy(value["value"])
            else:
                node.pop(path[-1], None)


def record(before, after, paths, *, change_id, actor, created_at, version_keys=(), inverse_of=None):
    unique = sorted(set(tuple(path) for path in paths))
    return {"changeId": change_id, "actor": actor, "createdAt": created_at,
            "inverseOf": inverse_of, "versionKeys": sorted(set(version_keys)),
            "changes": [{"path": list(path), "before": image(before, path), "after": image(after, path)}
                        for path in unique]}


def validate_record(value, roots):
    if not isinstance(value, dict) or not isinstance(value.get("changeId"), str) or not value["changeId"]:
        raise DocumentEditError("unsupported_document_schema", "Invalid document change.")
    changes = value.get("changes")
    if not isinstance(changes, list) or not changes:
        raise DocumentEditError("unsupported_document_schema", "Invalid document change fields.")
    for item in changes:
        path = item.get("path")
        if (not isinstance(path, list) or not 1 <= len(path) <= 4 or path[0] not in roots
                or any(not isinstance(key, str) or not key for key in path)):
            raise DocumentEditError("unsupported_document_schema", "Invalid document field address.")
        for side in ("before", "after"):
            value = item.get(side)
            if not isinstance(value, dict) or type(value.get("present")) is not bool:
                raise DocumentEditError("unsupported_document_schema", "Invalid document pre-image.")


def find_change(records, change_id):
    found = next((item for item in records if item["changeId"] == change_id), None)
    if found is None:
        raise DocumentEditError("change_not_found", "This change is no longer in the document history.", changeId=change_id)
    return found


def inspect_change(records, change_id, document):
    found = find_change(records, change_id)
    fields = found["changes"][:32]
    summaries = {}
    for side in ("before", "after"):
        summaries[side] = []
        for item in fields:
            value = deepcopy(item[side])
            if value["present"]:
                encoded = canonical_bytes(value["value"]).decode("utf-8")
                value["contentHash"] = digest(value["value"])
                if len(encoded) > 256:
                    value["value"] = {"preview": encoded[:256], "fullLength": len(encoded), "summaryOnly": True}
            summaries[side].append(value)
    return {"documentId": document,
            **{key: found.get(key) for key in ("changeId", "actor", "createdAt", "inverseOf")},
            "fields": [item["path"] for item in fields], **summaries, "undoable": not found.get("migrationBlocked", False),
            "fieldCount": len(found["changes"]), "summaryTruncated": len(fields) != len(found["changes"]),
            "changeHash": digest(found)}


def inverse(state, chosen, *, change_id, actor, created_at):
    if chosen.get("migrationBlocked"):
        raise DocumentEditError("undo_conflict", "This legacy change has unplaced content; its identity is not proven.",
                                changeId=chosen["changeId"])
    conflicts = ["/".join(item["path"]) for item in chosen["changes"]
                 if image(state, item["path"]) != item["after"]]
    if conflicts:
        raise DocumentEditError("undo_conflict", "A value or its provenance changed after this change.",
                                changeId=chosen["changeId"], targets=conflicts)
    return {**deepcopy(chosen), "changeId": change_id, "actor": actor, "createdAt": created_at,
            "inverseOf": chosen["changeId"],
            "changes": [{"path": item["path"], "before": deepcopy(item["after"]),
                         "after": deepcopy(item["before"])} for item in chosen["changes"]]}


def history_choices(records):
    # Derived from the same log, not a second cursor or undo stack. An inverse
    # cancels its selected record; an inverse of that inverse reapplies it.
    undo, redo = [], []
    for item in records:
        parent = item.get("inverseOf")
        if not parent:
            undo.append(item["changeId"])
            redo = []
        elif parent in undo:
            undo.remove(parent)
            redo.append(item["changeId"])
        elif parent in redo:
            redo.remove(parent)
            undo.append(item["changeId"])
        else:
            # Named inverses can address an older group.
            undo.append(item["changeId"])
    return undo, redo


def effective_commands(commands):
    active = {}
    roots = {}
    for index, command in enumerate(commands):
        change = command.get("change") or {}
        cid = change.get("changeId") or legacy_id(command, index)
        parent = change.get("inverseOf")
        if parent:
            key = roots.get(parent, change.get("legacyId", parent))
            roots[cid] = key
            active[key] = not active.get(key, False)
        else:
            roots[cid] = cid
            active[cid] = True
    for index, command in enumerate(commands):
        change = command.get("change") or {}
        cid = change.get("changeId") or legacy_id(command, index)
        if not change.get("inverseOf") and active.get(cid):
            yield command


def legacy_id(command, index):
    return command.get("commandId") or "legacy-" + digest({"index": index, "command": command})[:32]


def scene_paths(before, after, commands):
    paths = set()
    for page in set(before.get("pages", {})) | set(after.get("pages", {})):
        left, right = before.get("pages", {}).get(page, {}), after.get("pages", {}).get(page, {})
        for collection in set(left) | set(right):
            a, b = left.get(collection), right.get(collection)
            if collection.endswith("Overrides") or collection == "documentObjects":
                for key in set(a or {}) | set(b or {}):
                    if (a or {}).get(key) != (b or {}).get(key):
                        paths.add(("pages", page, collection, key))
            elif a != b:
                paths.add(("pages", page, collection))
    for key in ("theme", "pageMasters"):
        if before.get(key) != after.get(key):
            paths.add((key,))
    for key in set(before.get("fieldMeta", {})) | set(after.get("fieldMeta", {})):
        if before.get("fieldMeta", {}).get(key) != after.get("fieldMeta", {}).get(key):
            paths.add(("fieldMeta", key))
    for command in commands:
        page = command.get("pageId")
        operation = command.get("operation")
        if operation in {"set_theme", "apply_template"}:
            paths.add(("theme",))
            if operation == "apply_template":
                paths.add(("pageMasters",))
        elif operation in {"clear_callouts", "add_callout", "remove_callout", "restore_callouts"}:
            paths.add(("pages", page, "manualCalloutItems"))
        elif operation != "reset_page":
            targets = command.get("transforms", []) if operation == "arrange" else [command]
            for target in targets:
                kind, alias = target.get("targetType"), target.get("targetId")
                if kind == "figure":
                    paths.add(("pages", page, "figureOverride"))
                else:
                    collection = {"page_element": "pageElementOverrides", "document_object": "documentObjects",
                        "manual_group": "manualGroupOverrides", "occurrence": "occurrenceOverrides",
                        "balloon": "balloonOverrides", "leader": "leaderOverrides"}.get(kind)
                    if collection and alias:
                        paths.add(("pages", page, collection, alias))
        if operation == "reset_page":
            # Deleting a page's composition depends on the whole composition.
            paths = {p for p in paths if p[:2] != ("pages", page)}
            paths.add(("pages", page))
        dependencies = {**before.get("fieldMeta", {}), **after.get("fieldMeta", {})}
        touched = [command] if command.get("operation") != "arrange" else command.get("transforms", [])
        for key, meta in dependencies.items():
            if meta.get("pageId") == page and any(c.get("targetId") in meta.get("aliases", []) for c in touched):
                paths.add(("fieldMeta", key))
        for key, meta in (command.get("fieldMeta") or {}).items():
            paths.add(("fieldMeta", key))
            for alias in meta.get("aliases", []):
                paths.add(("pages", meta["pageId"], "pageElementOverrides", alias))
    return paths


def slot_paths(before, after):
    paths = set()
    for collection in ("values", "fieldMeta"):
        for key in set(before.get(collection, {})) | set(after.get(collection, {})):
            if before.get(collection, {}).get(key) != after.get(collection, {}).get(key):
                paths.add((collection, key))
    structural = any(before.get(key) != after.get(key) for key in ("rows", "type", "units"))
    if structural:
        # Row deletion/rename/settings operate on the sheet's dependency set.
        return {(key,) for key in ("values", "fieldMeta", "rows", "type", "units")}
    for collection, key in list(paths):
        paths.add(("fieldMeta", "slot:" + key) if collection == "values" else ("values", key.removeprefix("slot:")))
    return paths
