"""Exact-value reads with persistent compiler IDs and read-scoped legacy aliases."""
from __future__ import annotations

from copy import deepcopy
import json
import uuid
from typing import Any, Mapping

from .commands import DocumentEditError, binding, canonical_bytes, content_hash, digest, scene_field_key
from .identity import alias_entry
from .rich_text import field_read, enabled as rich_text_enabled, reserved_ids, PLAIN_EDIT_CONSEQUENCE


def target_id(state: Mapping[str, Any], page_id: str, alias: str) -> str:
    if alias.startswith("part.") or alias.startswith("slot:"):
        return alias
    key = ":".join((str(state["sourceRevision"]), str(state["manualPlanRevision"]), page_id, alias))
    return str(uuid.uuid5(uuid.UUID(state["documentId"]), key))


# The only generated-block eligibility table. Both stores and readers use it.
RICH_BLOCK_KINDS = {"paragraph": "paragraph", "note": "notice", "status_panel": "notice", "cad_figure": "caption"}
RICH_DOCUMENT_TYPES = {"operations_and_maintenance_manual", "work_instructions"}


def rich_block_capabilities(document_type, block_type):
    from .rich_text import FEATURES
    kind = RICH_BLOCK_KINDS.get(block_type) if document_type in RICH_DOCUMENT_TYPES else None
    if kind is None:
        return None
    features = ([name for name in FEATURES if name not in {"heading", "namedStyle", "table"}] if kind == "paragraph" else
                ["bold", "italic", "underline", "strike", "subscript", "superscript", "highlight", "color", "link"])
    return {"schemaVersions": [1, 2], "features": features, "listDepth": 6 if kind == "paragraph" else 0}


def text_targets(state: Mapping[str, Any], document: Mapping[str, Any], *, include_objects=True) -> dict[str, dict]:
    """Full values, including provenance/type attributes, never a shortened string."""
    result = {}

    def add(page, alias, value, attributes, *, kind="replace_text", target_type="page_element"):
        page_id = str(page["pageId"])
        entry = alias_entry(document, page_id, alias)
        if entry and not entry.get("safe"):
            return
        stable = entry["targetId"] if entry else (alias if target_type == "document_object" else target_id(state, page_id, alias))
        storage_id = stable if entry else alias
        override = ((state["scene"].get("pages") or {}).get("page-parts-index" if alias.startswith("part.") else page_id) or {}).get("pageElementOverrides", {}).get(alias, {})
        stored_page = state.get("scene", {}).get("identities", {}).get(storage_id, {}).get("storagePage", page_id)
        override = state["scene"].get("pages", {}).get(stored_page, {}).get("pageElementOverrides", {}).get(storage_id, override)
        override = page.get("identityOverrides", {}).get(stable, override)
        if kind == "replace_text" and "text" in override:
            value = override["text"]
        attributes = deepcopy(attributes)
        meta = attributes.get("row", {}).get("provenance") or attributes.get("item", {}).get("provenance") or attributes.get("provenance") or document.get("fieldMeta", {}).get(stable)
        if meta:
            attributes["provenance"] = deepcopy(meta)
            attributes["evidenceClaimIds"] = list(meta.get("activeClaimIds") or [])
            attributes["sourceIds"] = list(meta.get("activeSourceIds") or [])
            attributes["activeEvidenceClaimIds"] = list(meta.get("activeClaimIds") or [])
            attributes["activeSourceIds"] = list(meta.get("activeSourceIds") or [])
        eligible = target_type == "document_object" or rich_block_capabilities(document.get("documentType"), attributes.get("blockType")) is not None
        rich_value = value if target_type == "document_object" else override.get("richText", value)
        storage_page = state.get("scene", {}).get("identities", {}).get(storage_id, {}).get("storagePage", page_id)
        rich = field_read(rich_value, reserved=reserved_ids(state.get("scene", {}).get("pages", {}), storage_page, storage_id,
            aliases=[(page_id, alias)] if target_type == "page_element" else ())) if eligible else None
        if rich and target_type == "page_element":
            from .rich_blocks import base_style
            rich["richTextStyle"] = base_style(attributes, override)
            if rich["richTextError"]:
                rich["text"] = str(value or "")  # Keep the legacy projection visible, read-only.
        if rich and rich["isRichText"]:
            # Valid rich hashes cover the canonical envelope; corrupt values are
            # opaque read-only data, including JSON with an unpaired surrogate.
            attributes["content"] = (rich["richText"] if not rich["richTextError"] else
                {"invalidRichText": json.dumps(rich_value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))})
        text = rich["text"] if rich else "" if value is None else str(value)
        descriptor = {"targetId": stable, "alias": alias, "pageId": page_id,
                      "targetType": target_type, "documentType": document.get("documentType"), "storageId": storage_id, "text": text, "operation": kind,
                      "attributes": attributes, "override": deepcopy(override),
                      "versionKey": alias if kind == "set_slot_value" else scene_field_key(page_id, target_type, storage_id),
                      "versionPage": page_id if kind == "replace_text" and not storage_id.startswith(("part.", "gen-")) else ""}
        if rich:
            descriptor["richField"] = rich
            if rich["richTextError"]:
                descriptor["operation"] = "read_only"
                if "richText" in descriptor["override"]:
                    descriptor["override"]["richText"] = attributes["content"]
        if stable in result:
            # Definition-keyed parts occur on multiple pages. Different effective
            # values are ambiguous, never selected by whichever page came last.
            if result[stable]["text"] != text:
                raise DocumentEditError("ambiguous_legacy_target", "A target has conflicting page values.", targetId=stable)
            result[stable].setdefault("pageIds", [result[stable]["pageId"]]).append(page_id)
        else:
            result[stable] = descriptor

    def add_objects(page):
        if not include_objects:
            return
        objects = (state.get("scene", {}).get("pages", {}).get(page["pageId"], {}).get("documentObjects")
                   or (page.get("documentationComposition") or {}).get("documentObjects")
                   or page.get("documentationObjects") or {})
        from .objects import ordered_objects
        order = (state.get("scene", {}).get("pages", {}).get(page["pageId"], {}).get("objectOrder")
                 or page.get("documentationObjectOrder") or (page.get("documentationComposition") or {}).get("objectOrder"))
        for object_id, item in ordered_objects({"documentObjects": objects, **({"objectOrder": order} if order is not None else {})}):
            if item.get("type") == "text":
                add(page, object_id, item.get("content"), item,
                    kind="read_only" if item.get("locked") else "replace_text", target_type="document_object")

    for page in ([] if document.get("slots") is not None else document.get("pages") or []):
        if document.get("documentType") == "illustrated_parts_manual":
            product = str((document.get("product") or {}).get("name") or "Product")
            figure, revision = str(page.get("figureNumber") or "").strip(), str(document.get("revision") or "").strip()
            metadata = product + " | " + str(document.get("documentNumber") or "")
            if revision:
                metadata += " | Rev " + revision
            cover = page.get("pageType") == "cover"
            add(page, "header_title", "ILLUSTRATED PARTS MANUAL" if cover else
                ("FIGURE " + figure + " - " if figure else "") + str(page.get("title") or ""), {"role": "page_heading"})
            if cover:
                add(page, "cover_subtitle", product, {"role": "cover_subtitle"})
            else:
                add(page, "header_meta", metadata + (" | Figure " + figure if figure else ""), {"role": "page_metadata"})
                add(page, "footer", metadata + " | Figure " + (figure or "N/A"), {"role": "page_footer"})
        for block in page.get("layoutBlocks") or []:
            alias, kind = block.get("blockId"), block.get("blockType")
            if not alias or kind == "contents_list":
                continue
            # A sibling's text is not a dependency. Retain the target's complete
            # row/item payload, type and evidence without unrelated row values.
            attributes = {key: deepcopy(value) for key, value in block.items()
                          if key not in {"rows", "items", "text", "lines", "caption", "frame", "blockId", "rowHeights", "continued"}}
            if kind in {"table", "key_value_table"}:
                for row_index, row in enumerate(block.get("rows") or []):
                    for column, value in enumerate(row.get("cells") or []):
                        add(page, f"{alias}.r{row_index}.c{column}", value,
                            {**attributes, "row": {k: v for k, v in row.items() if k != "cells"},
                             "column": (block.get("columnIds") or [])[column] if column < len(block.get("columnIds") or []) else column})
            elif kind in {"list", "figure_legend"}:
                for index, item in enumerate(block.get("items") or []):
                    add(page, f"{alias}.i{index}", item.get("text"),
                        {**attributes, "item": {k: v for k, v in item.items() if k != "text"}})
            else:
                value = (block.get("caption") if kind == "cad_figure" else
                         block.get("text", "\n".join(str(line) for line in block.get("lines") or [])))
                add(page, alias, value, attributes)
        for row in page.get("bom") or []:
            if not row.get("definitionId"):
                continue
            from ai_inspector.parts_manual.document import part_text_target_id
            for field, value in (("partNumber", row.get("displayPartNumber") or "Not specified"),
                                 ("description", row.get("description") or "")):
                add(page, part_text_target_id(row["definitionId"], field), value,
                    {"definitionId": row["definitionId"], "field": field})
        add_objects(page)
    # Page-authored objects remain scene-owned even when the page also has slots.
    if document.get("slots") is not None:
        for page in document.get("pages") or []:
            add_objects(page)
    if document.get("slots"):
        page = (document.get("pages") or [{"pageId": "page-specification"}])[0]
        for slot, item in document["slots"].items():
            add(page, "slot:" + slot, item.get("value"), {**item, "units": document.get("sheet", {}).get("units")}, kind="set_slot_value")
    return result


def hash_values(targets: Mapping[str, dict]) -> dict[str, dict]:
    # Page placement is not identity; a shared part target hashes the same value
    # from any page. Its definition, field attributes and source remain included.
    def semantic(value):
        if isinstance(value, list):
            return [semantic(item) for item in value]
        if isinstance(value, dict):
            return {key: semantic(item) for key, item in value.items() if key not in {
                "pageId", "pageIds", "alias", "displayName", "frame", "itemNumber",
                "displayText", "lines", "height", "continued", "rowContinuation"}}
        return value
    return {key: semantic({field: value for field, value in target.items() if field not in {"targetId", "richField", "documentType"}})
            for key, target in targets.items()}


def resolve_target(targets: Mapping[str, dict], requested: str, page_id: str | None = None) -> dict:
    found = [target for key, target in targets.items() if (key == requested or target["alias"] == requested or target["alias"] == "slot:" + requested)
             and (page_id is None or page_id in target.get("pageIds", [target["pageId"]]))]
    if len(found) != 1:
        code = "ambiguous_legacy_target" if found else "target_not_found"
        raise DocumentEditError(code, "Read a unique complete target before editing.", targetId=requested)
    return found[0]


def owner_state(state, target):
    """Specification slots and scene objects have independent mutation counters."""
    if target["targetType"] != "document_object" or "editRevision" not in state.get("scene", {}):
        return state
    scene = state["scene"]
    return {**state, "revision": scene["editRevision"], "editEpoch": scene["editEpoch"],
            "fieldVersions": scene["fieldVersions"]}


def capabilities(target):
    if target["operation"] == "read_only":
        return []
    result = [target["operation"]]
    if target["operation"] == "replace_text" and (
            not (target.get("richField") or {}).get("isRichText") or rich_text_enabled()):
        result.append("replace_range")
    if target.get("richField") is not None and rich_text_enabled():
        result.extend(["replace_rich_text", "format_range"])
        caps = rich_text_capabilities(target) or {}
        if "table" in caps.get("features", []) and 3 in caps.get("schemaVersions", []):
            result.extend(["create_table", "modify_table"])
    return result


def rich_text_capabilities(target):
    from .rich_text import FEATURES
    if target.get("targetType") == "document_object" and target.get("richField") is not None:
        return {"schemaVersions": [1, 2, 3], "features": list(FEATURES), "listDepth": 6}
    if target.get("targetType") == "page_element":
        return rich_block_capabilities(target.get("documentType"), target.get("attributes", {}).get("blockType"))
    return None


def _table_structure_read(item):
    """A table address/size read never returns its cell text, including provenance copies."""
    value = item.get("richText")
    if not value or value.get("schemaVersion") != 3:
        return item
    from .tables import grid
    def text_length(node):
        # Already validated by field_read. Count code points without validating a cell as a
        # separate field (a large cell is entitled to the enclosing table's larger node budget).
        if node["type"] == "text":
            return len(node["text"])
        if node["type"] == "hardBreak":
            return 1
        children = node.get("content", [])
        return sum(text_length(child) for child in children) + (0 if node["type"] == "paragraph" else max(0, len(children)-1))
    tables = []
    for table in value["doc"].get("content", []):
        if table["type"] != "table":
            continue
        anchors, _ = grid(table)
        # Parallel arrays avoid repeating each 39-character ID and field names 600 times.
        tables.append({"tableId": table["attrs"]["id"], "style": table["attrs"]["style"],
            "columns": deepcopy(table["attrs"]["columns"]),
            "rows": [{"rowId": row["attrs"]["id"],
                      "cellIds": [c["attrs"]["id"] for c in row["content"]],
                      "headers": [c["type"] == "tableHeader" for c in row["content"]],
                      "textLengths": [text_length(c) for c in row["content"]]}
                     for row in table["content"]],
            "mergedRanges": [{"cellId": a["cell"]["attrs"]["id"],
                              **{k: a[k] for k in ("row", "column", "rowspan", "colspan")}}
                             for a in anchors if a["rowspan"] > 1 or a["colspan"] > 1]})
    if not tables:
        return item
    result = {key: val for key, val in item.items() if key not in {"text", "richText", "provenance"}}
    result.update(tables=tables, structureOnly=True, isExcerpt=True)
    return result


def read_targets(state: dict, targets: Mapping[str, dict], requested: list[dict], *, limit=65536, internal=False,
                 table_structure_only=False) -> dict:
    if not (1 <= len(requested) and (internal or len(requested) <= 12)):
        raise DocumentEditError("invalid_document_operation", "Read 1-12 targets at a time.")
    values = hash_values(targets)
    output = []
    for item in requested:
        target = resolve_target(targets, item["targetId"], item.get("pageId"))
        stable = target["targetId"]
        owned = owner_state(state, target)
        rich = target.get("richField")
        provenance = deepcopy(target["attributes"].get("provenance", target["attributes"]))
        if rich:
            provenance.pop("content", None)
        from .refresh import open_conflicts
        conflict_ids = [c.get("conflictId") for c in open_conflicts(state) if c.get("targetId") == stable
                        or (c.get("scopeId") and c["scopeId"] == target["attributes"].get("provenance", {}).get("targetId"))]
        output.append({"targetId": stable, "hasOpenConflict": bool(conflict_ids), "conflictIds": conflict_ids, "legacyTargetId": target["alias"], "pageId": item.get("pageId") or target["pageId"],
                       "text": target["text"], "isExcerpt": False, "fullLength": len(target["text"]),
                       "contentHash": content_hash(owned, stable, values[stable]), "hashVersion": 1,
                       "aliasRevision": state.get("aliasRevision"),
                       "provenance": provenance,
                       "capabilities": [] if conflict_ids else capabilities(target), "binding": binding(owned),
                       "owner": "slots" if target["operation"] == "set_slot_value" else "scene",
                       "revision": owned["revision"],
                       **({**rich, "richTextEligible": True, "richTextCapabilities": rich_text_capabilities(target),
                           "plainEditConsequence": PLAIN_EDIT_CONSEQUENCE,
                           "wholeFieldReplacementRequired": rich["isRichText"]} if rich else {})})
    if table_structure_only:
        output = [_table_structure_read(item) for item in output]
    from .refresh import open_conflicts
    result = {**binding(state), "documentationRichText": rich_text_enabled(), "openConflictCount": len(open_conflicts(state)), "sceneRevision": state.get("sceneRevision"), "targets": output,
              "aliasRevision": state.get("aliasRevision"),
              "aliasMap": {item["pageId"]: {row["legacyTargetId"]: row["targetId"] for row in output
                           if row["pageId"] == item["pageId"]} for item in output}}
    if limit is not None and len(canonical_bytes({"ok": True, "data": result})) > limit:
        raise DocumentEditError("read_result_too_large", "Retry fewer targets; a legacy field may exceed the limit.",
                                targets=[{"targetId": item["targetId"], "bytes": len(canonical_bytes(item))}
                                         for item in output])
    return result


class ReadBindings:
    """Per-turn read snapshots for the compatible, omitted-precondition API.

    This cache must belong to one authorized gateway, never a process singleton.
    Recording a summary is allowed, but its excerpts cannot authorize replacement.
    It never fetches current data to fill in a missing write precondition.
    """

    def __init__(self, turn_id: str):
        self.turn_id = turn_id
        self.targets: dict[tuple[str, str, str], dict] = {}
        self.objects: dict[tuple[str, str], dict] = {}
        self.object_requests: dict[tuple[str, str], dict] = {}
        self.page_setups: dict[str, dict] = {}
        self.page_setup_requests: dict[tuple[str, str], dict] = {}

    def record(self, document_type: str, read: dict) -> None:
        if "pageSetupBinding" in read:
            self.page_setups[document_type] = deepcopy(read["pageSetupBinding"])
        for page in read.get("objectPages", []):
            self.objects[(document_type, page["pageId"])] = {**deepcopy(page),
                "binding": {**binding(read), "sceneRevision": read["sceneRevision"]}}
        for item in read.get("targets", []):
            captured = {**deepcopy(item), "binding": {
                **binding(read), **item.get("binding", {}), "owner": item.get("owner", "slots" if item["targetId"].startswith("slot:") else "scene"),
                "sceneRevision": read.get("sceneRevision"), "structureHash": read.get("structureHash"), "aliasRevision": read.get("aliasRevision")}}
            for key, old in list(self.targets.items()):
                if key[0] == document_type and old["targetId"] == item["targetId"]:
                    self.targets[key] = captured
            for identifier in {item["targetId"], item.get("legacyTargetId", item["targetId"])}:
                self.targets[(document_type, item["pageId"], identifier)] = captured

    def bind(self, document_type: str, arguments: dict) -> dict:
        captured = []
        operations = []
        for index, item in enumerate(arguments["edits"]):
            read = self.targets.get((document_type, item["pageId"], item["targetId"]))
            if read is None:
                raise DocumentEditError("document_read_required", "Read the complete target before editing.",
                                        operationIndex=index, targetId=item["targetId"])
            if read["isExcerpt"]:
                raise DocumentEditError("full_read_required", "A summary excerpt cannot replace a complete field.",
                                        operationIndex=index, targetId=item["targetId"])
            captured.append(read["binding"])
            operations.append({"operation": "replace_text", "targetId": read["targetId"], "text": item["text"],
                               "expectedContentHash": item.get("expectedContentHash", read["contentHash"]),
                               **({"wholeFieldReplacement": item["wholeFieldReplacement"]} if "wholeFieldReplacement" in item else {}),
                               **({"legacyAlias": item["targetId"]} if item["targetId"] != read["targetId"] else {})})
        if not captured:
            raise DocumentEditError("invalid_document_operation", "Submit at least one edit.")
        first = captured[0]
        for observed in captured:
            if any(first[key] != observed[key] for key in ("documentId", "sourceRevision", "manualPlanRevision", "owner")):
                raise DocumentEditError("document_binding_changed", "Read all targets in the same document binding.")
        if arguments.get("documentId", first["documentId"]) != first["documentId"]:
            raise DocumentEditError("document_binding_changed", "The read belongs to another document.")
        result = {**first, "expectedRevision": arguments.get("expectedRevision", min(x["revision"] for x in captured)),
                  "operations": operations}
        oldest = min(captured, key=lambda item: item["revision"])
        result["sceneRevision"] = oldest.get("sceneRevision")
        result.pop("revision")
        result["requestId"] = arguments.get("requestId") or digest(
            {"turn": self.turn_id, "read": captured, "arguments": result})
        return result


    def bind_objects(self, document_type: str, arguments: dict) -> dict:
        from .objects import object_batch
        object_batch(arguments["operations"])
        page_id = arguments["operations"][0]["pageId"]
        read = self.objects.get((document_type, page_id))
        if read is None:
            raise DocumentEditError("document_read_required", "Read this page's objects before editing.")
        known = {row["objectId"] for row in read["objects"]}
        for operation in arguments["operations"]:
            ids = operation.get("objectIds", [operation["objectId"]] if "objectId" in operation else operation.get("order", []))
            if any(key not in known for key in ids):
                raise DocumentEditError("document_read_required", "Read all selected objects before editing.")
        if arguments["documentId"] != read["binding"]["documentId"]:
            raise DocumentEditError("document_binding_changed", "The read belongs to another document.")
        observed = self.object_requests.setdefault((document_type, arguments["requestId"]), deepcopy(read["binding"]))
        result = {**deepcopy(observed), **deepcopy(arguments)}
        result.pop("revision", None)
        return result

    def update_objects(self, document_type: str, result: dict) -> None:
        for (kind, _page), read in self.objects.items():
            if kind == document_type:
                read["binding"].update(result)

    def bind_operations(self, document_type: str, arguments: dict) -> dict:
        from .commands import operation_store
        destination = operation_store(arguments["operations"])
        if destination == "page_setup":
            if document_type not in self.page_setups:
                raise DocumentEditError("document_read_required", "Read the page setup options before changing paper.")
            observed = self.page_setup_requests.setdefault((document_type, arguments["requestId"]),
                deepcopy(self.page_setups[document_type]))
            if observed["documentId"] != arguments["documentId"]:
                raise DocumentEditError("document_binding_changed", "The read belongs to another document.")
            return {**deepcopy(observed), **deepcopy(arguments)}
        if destination == "objects":
            return self.bind_objects(document_type, arguments)
        captured, operations = [], []
        for index, operation in enumerate(arguments["operations"]):
            matches = [read for (kind, _page, _alias), read in self.targets.items()
                       if kind == document_type and operation["targetId"] in {read["targetId"], read.get("legacyTargetId")}]
            if not matches:
                raise DocumentEditError("document_read_required", "Read the complete target before editing.",
                                        operationIndex=index, targetId=operation["targetId"])
            read = matches[-1]
            structural = read.get("structureOnly") and operation["operation"] in {"create_table", "modify_table"}
            if read["isExcerpt"] and not structural and not (read.get("rangeRead") and operation["operation"] in {"replace_range", "format_range"}):
                raise DocumentEditError("full_read_required", "Read this target in full before replacement.",
                                        operationIndex=index, targetId=operation["targetId"])
            if operation["operation"] == "replace_rich_text":
                from .rich_text import require_enabled
                require_enabled()
                if read.get("conflictIds"):
                    raise DocumentEditError("manual_edit_conflict", "Resolve this target's open conflict first.", targetId=read["targetId"])
                if operation["operation"] not in read.get("capabilities", []):
                    raise DocumentEditError("read_only_derived_field", "This read does not permit rich text replacement.")
            captured.append(read["binding"])
            operations.append({**deepcopy(operation), "targetId": read["targetId"],
                **({"legacyAlias": operation["targetId"]} if operation["targetId"] != read["targetId"] else {})})
        first = min(captured, key=lambda item: item["revision"])
        for observed in captured:
            if any(first[key] != observed[key] for key in ("documentId", "sourceRevision", "manualPlanRevision", "owner")):
                raise DocumentEditError("document_binding_changed", "The targets belong to different source bindings.")
        if first["documentId"] != arguments["documentId"]:
            raise DocumentEditError("document_binding_changed", "The read belongs to another document.")
        result = {**first, **deepcopy(arguments), "operations": operations}
        result.pop("revision", None)
        return result


def summarize_page(page: dict, summary: dict, state: dict, targets: dict, *, table_structure_only=False) -> tuple[dict, list[dict]]:
    """Keep the historical page/block keys; label every editable summary string."""
    captured = []
    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            if "id" in value and "text" in value:
                try:
                    target = resolve_target(targets, value["id"], str(page["pageId"]))
                except DocumentEditError:
                    pass
                else:
                    full = read_targets(state, targets, [{"targetId": target["targetId"], "pageId": page["pageId"]}], limit=None, table_structure_only=table_structure_only)["targets"][0]
                    # Match the prior summary budgets without using normalized
                    # whitespace as the replacement material.
                    budget = max(len(value["text"]), 80)
                    excerpt = len(full.get("text", "")) > budget
                    item = full if full.get("structureOnly") else {**full, "text": full["text"][:budget], "isExcerpt": excerpt}
                    if full.get("structureOnly"):
                        value.pop("text", None)
                    value.update(item)
                    captured.append(item)
            for key, item in list(value.items()):
                if key in {"rows", "items", "blocks"}:
                    visit(item)
    visit(summary)
    known = {item["targetId"] for item in captured}
    extra = []
    for key, target in targets.items():
        if key in known or str(page["pageId"]) not in target.get("pageIds", [target["pageId"]]):
            continue
        full = read_targets(state, targets, [{"targetId": key, "pageId": page["pageId"]}], limit=None, table_structure_only=table_structure_only)["targets"][0]
        item = full if full.get("structureOnly") else {**full, "text": full["text"][:600], "isExcerpt": len(full["text"]) > 600}
        extra.append(item)
        captured.append(item)
    if extra:
        summary["textTargets"] = extra
    return {**summary, **binding(state), "aliasRevision": state.get("aliasRevision"),
            "aliasMap": {item["legacyTargetId"]: item["targetId"] for item in captured}}, captured
