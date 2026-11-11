"""Pure three-way publication refresh. Only the existing store owners do I/O."""
from copy import deepcopy

from .commands import DocumentEditError, digest, document_id, scene_field_key
from .identity import catalog_from, compile_identities

REFRESH_RECEIPT_LIMIT = 100
_BINDING = ("sourceRevision", "manualPlanRevision")


def binding(value):
    return {key: str(value.get(key) or "") for key in _BINDING}


def open_conflicts(state):
    values = state.get("conflicts") or []
    return [c for c in (values.values() if isinstance(values, dict) else values)
            if c.get("status", "open") == "open"]


def exposure(state):
    from .resolution import with_hash, orphan_review
    return {"openConflictCount": len(open_conflicts(state)),
            "conflicts": [with_hash(c) for c in (list((state.get("conflicts") or {}).values())
                if isinstance(state.get("conflicts"), dict) else state.get("conflicts") or [])],
            "orphans": [orphan_review(o, state) for o in state.get("orphans") or []],
            "resolutionHistory": deepcopy(state.get("resolutionHistory") or [])}


def assert_writable(state, targets=(), *, pages=(), whole=False):
    targets, pages = {key for key in targets if key}, {key for key in pages if key}
    for conflict in open_conflicts(state):
        watched = {conflict.get("targetId"), conflict.get("scopeId"),
                   conflict.get("previousTargetId"), conflict.get("alias")}
        if whole or watched & targets or conflict.get("pageId") in pages:
            raise DocumentEditError("manual_edit_conflict", "Resolve this target's open conflict first.",
                                    targetId=conflict["targetId"], conflictId=conflict.get("conflictId"))


def command_targets(command):
    targets = [command.get("targetId"), scene_field_key(str(command.get("pageId") or ""),
        str(command.get("targetType") or ""), str(command.get("targetId") or ""))]
    if command.get("targetType") == "figure":
        targets.append(command.get("pageId"))
    for target in command.get("transforms") or []:
        targets.extend([target.get("targetId"), scene_field_key(str(command.get("pageId") or ""),
            str(target.get("targetType") or ""), str(target.get("targetId") or ""))])
    for row in command.get("frames") or []:
        targets.extend([row["targetId"], scene_field_key(command["pageId"], "document_object", row["targetId"])])
    for key, meta in (command.get("fieldMeta") or {}).items():
        targets.extend([key, *((meta or {}).get("aliases") or [])])
    return targets


def guard_command(state, command):
    targets = [*command_targets(command), *(command.get("identityResetTargets") or [])]
    assert_writable(state, targets, pages=[command.get("pageId")] if command.get("operation") == "reset_page" else [])


def guard_change(state, change):
    targets, pages, whole = list(change.get("versionKeys", [])), [], False
    for item in change.get("changes", []):
        path = item["path"]
        if path[0] in {"values", "fieldMeta"}:
            if len(path) == 1:
                whole = True
            else:
                targets.append("slot:" + path[1] if path[0] == "values" else path[1])
        elif path[0] == "pages":
            if len(path) < 4:
                pages.append(path[1])
            else:
                targets.append(path[3])
    resolving = set(change.get("resolutionIds") or [])
    guarded = {**state, "conflicts": [c for c in open_conflicts(state) if c.get("conflictId") not in resolving]}
    assert_writable(guarded, targets, pages=pages, whole=whole)
    for target in targets:
        identity = state.get("identities", {}).get(target, {})
        # Only a refresh unplaces a generated identity. A row the user renamed or deleted in the same binding
        # is tombstoned too (P1c-1), and undoing that change must still restore it.
        if (not resolving and identity.get("state") == "tombstone" and identity.get("tombstonedBy") == "refresh"
                and identity.get("ownership") != "authored"):
            raise DocumentEditError("undo_conflict", "This generated target is now unplaced.", targetId=target)


def validate_refresh_metadata(state):
    def invalid():
        raise DocumentEditError("unsupported_document_schema", "Invalid publication refresh metadata.")
    baselines = state.get("generatedBaseline", {})
    if not isinstance(baselines, dict):
        invalid()
    for key, item in baselines.items():
        if not isinstance(key, str) or not isinstance(item, dict):
            invalid()
        if ("payload" not in item or item.get("hash") != digest(item["payload"])
                or not isinstance(item.get("binding"), dict) or not isinstance(item.get("evidence"), dict)
                or any(not isinstance(item["binding"].get(field), str) for field in _BINDING)):
            invalid()
    conflicts = state.get("conflicts", [])
    if not isinstance(conflicts, (dict, list)):
        invalid()
    for item in conflicts.values() if isinstance(conflicts, dict) else conflicts:
        if not isinstance(item, dict) or not isinstance(item.get("targetId"), str):
            invalid()
        # Accept the small pre-P1c conflict guard shape without rewriting it.
        if "conflictId" not in item:
            continue
        # "evidence" is accepted only for stores written by P1c-2a; no new refresh creates it.
        if (item.get("kind") not in {"value", "evidence", "missing_baseline", "revision_scoped"}
                or not all(key in item for key in ("B", "C", "N", "oldSourceRefs", "newSourceRefs",
                    "createdRevision", "status", "resolutionReceipt", "pageId", "alias"))
                or item.get("status") not in {"open", "resolved"}
                or not isinstance(item["conflictId"], str) or not 1 <= len(item["conflictId"]) <= 64
                or type(item["createdRevision"]) is not int or item["createdRevision"] < 0):
            invalid()
        for side in ("B", "C", "N"):
            value = item.get(side)
            if value is not None and (not isinstance(value, dict) or value.get("hash") != digest(value.get("payload"))):
                invalid()
    if not isinstance(state.get("orphans", []), list):
        invalid()
    for item in state.get("orphans", []):
        if not isinstance(item, dict) or not isinstance(item.get("orphanId"), str):
            invalid()
        if "C" in item and (not isinstance(item["C"], dict) or item["C"].get("hash") != digest(item["C"].get("payload"))):
            invalid()
    from .resolution import validate_resolution_metadata
    validate_resolution_metadata(state)
    receipts = state.get("refreshReceipts", [])
    if not isinstance(receipts, list) or len(receipts) > REFRESH_RECEIPT_LIMIT:
        invalid()
    for item in receipts:
        if not isinstance(item, dict) or not all(key in item for key in ("refreshId", "fromBinding", "toBinding", "actor", "at", "counts", "conflictIds")):
            invalid()
        if (not isinstance(item["refreshId"], str) or not isinstance(item["at"], str)
                or item["actor"] not in {"user", "sage", "system"}
                or not isinstance(item["conflictIds"], list) or not isinstance(item["counts"], dict)
                or any(type(value) is not int or value < 0 for value in item["counts"].values())):
            invalid()
        for field in ("fromBinding", "toBinding"):
            if not isinstance(item[field], dict) or any(not isinstance(item[field].get(key), str) for key in _BINDING):
                invalid()


def inventory(document):
    """Generated payloads and exact source evidence, independent of scene edits."""
    from .targets import text_targets
    document = compile_identities(document)
    catalog = catalog_from(document)
    state = {"documentId": document_id(catalog["documentType"], catalog["assemblyNumber"]),
             **binding(document), "scene": {"pages": {}}}
    targets = text_targets(state, document)
    result = {}
    for key, target in targets.items():
        attributes = target["attributes"]
        meta = attributes.get("provenance") or attributes.get("row", {}).get("provenance") or attributes.get("item", {}).get("provenance") or {}
        owner = attributes.get("row") or attributes.get("item") or attributes
        evidence = {"claimIds": deepcopy(meta.get("claimIds", owner.get("claimIds", attributes.get("evidenceClaimIds", [])))),
                    "sourceIds": deepcopy(meta.get("sourceIds", owner.get("sourceIds", attributes.get("sourceIds", []))))}
        if key.startswith("slot:"):
            slot = document["slots"][key[5:]]
            default = slot.get("default") or {}
            payload = {"value": default.get("value")}
            evidence.update(source=default.get("source"), claimIds=deepcopy(slot.get("claimIds") or []))
        else:
            payload = {"text": target["text"]}
        result[key] = {"payload": payload, "hash": digest(payload), "binding": binding(document),
                       "evidence": evidence, "pageId": target["pageId"], "alias": target["alias"],
                       "label": attributes.get("name") or meta.get("displayName") or target["alias"],
                       "scopeId": meta.get("targetId", key),
                       "identity": deepcopy(catalog["identities"].get(key, {}))}
    for page in document.get("pages", []):
        for block in page.get("layoutBlocks", []):
            values = {block["blockId"]: {"rows": [row.get("cells", []) for row in block.get("rows", [])],
                      "items": [item.get("text", "") for item in block.get("items", [])]}}
            values.update({block["blockId"] + ".r" + str(i): {"cells": row.get("cells", [])}
                           for i, row in enumerate(block.get("rows", []))})
            for alias, payload in values.items():
                entry = catalog["aliasMap"][page["pageId"]].get(alias)
                if entry and entry.get("safe"):
                    key = entry["targetId"]
                    result.setdefault(key, {"payload": payload, "hash": digest(payload), "binding": binding(document),
                        "evidence": {"claimIds": deepcopy(block.get("evidenceClaimIds", [])), "sourceIds": []},
                        "pageId": page["pageId"], "alias": alias, "label": alias, "scopeId": key,
                        "identity": deepcopy(catalog["identities"].get(key, {}))})
        if document["documentType"] == "illustrated_parts_manual":
            for alias, payload in (("bom", page.get("bom")), ("group_index", page.get("manualGroupItems"))):
                if payload is not None:
                    key = scene_field_key(page["pageId"], "page_element", alias)
                    result[key] = {"payload": deepcopy(payload), "hash": digest(payload), "binding": binding(document),
                        "evidence": {}, "pageId": page["pageId"], "alias": alias, "storageId": alias,
                        "label": alias, "scopeId": key, "identity": {"scope": "source"}, "targetKind": "presentation"}
        request = page.get("renderRequest")
        if request:
            groups = set(request.get("manualGroupNames", [])) | {row["sectionId"]
                for row in page.get("availableManualGroupItems", page.get("manualGroupItems", [])) if row.get("sectionId")}
            callouts = {str(row.get("calloutId") or "callout-item-" + str(int(row.get("itemNumber") or 0))): row
                        for row in request.get("calloutItems", [])}
            for target_type, values in (("occurrence", {key: {} for key in request.get("occurrenceIds", [])}),
                                       ("manual_group", {key: {} for key in groups}),
                                       ("balloon", callouts), ("leader", callouts)):
                for alias, row in values.items():
                    key = scene_field_key(page["pageId"], target_type, alias)
                    relation = {k: deepcopy(row[k]) for k in ("definitionId", "sectionId", "occurrenceIds") if k in row}
                    payload = {"override": None, "sourceTarget": relation}
                    result[key] = {"payload": payload, "hash": digest(payload), "binding": binding(document),
                        "evidence": {}, "pageId": page["pageId"], "alias": alias, "label": alias, "scopeId": key,
                        "identity": {"scope": "source"}, "targetKind": target_type}
            payload = {k: deepcopy(v) for k, v in request.items() if k not in {"image", "composition"}}
            result[page["pageId"]] = {"payload": payload, "hash": digest(payload), "binding": binding(document),
                "evidence": {}, "pageId": page["pageId"], "alias": page["pageId"], "label": page.get("title", "Figure"),
                "scopeId": page["pageId"], "identity": {"scope": "source"}, "targetKind": "figure"}
    return result


def edited_targets(state, *, slots=False):
    if slots:
        return {"slot:" + key for key in state.get("values", {})}
    return {key for page in state.get("pages", {}).values() for key in page.get("pageElementOverrides", {})}


def derive_baselines(state, document, *, slots=False):
    """Upgrade only in memory and only when the old binding is provably current."""
    result = deepcopy(state)
    if document is None or binding(state) != binding(document):
        return result
    generated = inventory(document)
    keys = edited_targets(state, slots=slots)
    if not slots:
        keys |= {scene_field_key(page, "page_element", key) for page, value in state.get("pages", {}).items()
                 for key in value.get("pageElementOverrides", {})}
        for page_id, page in state.get("pages", {}).items():
            if page.get("figureOverride"):
                keys.add(page_id)
            for collection, target_type in (("occurrenceOverrides", "occurrence"), ("manualGroupOverrides", "manual_group"),
                                            ("balloonOverrides", "balloon"), ("leaderOverrides", "leader")):
                keys.update(scene_field_key(page_id, target_type, key) for key in page.get(collection, {}))
    conflicted = {key for item in open_conflicts(state) for key in (item.get("targetId"), item.get("previousTargetId"))}
    for key in keys:
        if key in generated and key not in conflicted:
            result.setdefault("generatedBaseline", {}).setdefault(key, deepcopy(generated[key]))
    return result


def capture_baselines(state, document, targets):
    if document is None:
        return
    generated = inventory(document)
    for key in targets:
        if key in generated:
            state.setdefault("generatedBaseline", {}).setdefault(key, deepcopy(generated[key]))


def three_way(B, C, N, *, revision_scoped=False):
    if N is None:
        return "orphan"
    if C == N["payload"]:
        return "kept"
    if B is None:
        return "missing_baseline"
    if revision_scoped:
        return "preserved" if B["payload"] == N["payload"] else "revision_scoped"
    if C == B["payload"]:
        return "adopted"
    if B["payload"] == N["payload"]:
        return "preserved"
    return "value"


def refresh(state, document, *, refresh_id, actor, at, slots=False):
    """Return a candidate and receipt; no clocks, allocation, mutation or I/O."""
    validate_refresh_metadata(state)
    old_binding, new_binding = binding(state), binding(document)
    if old_binding == new_binding:
        return deepcopy(state), None
    result = deepcopy(state)
    generated = inventory(document)
    catalog = catalog_from(document)
    counts = dict.fromkeys(("adopted", "preserved", "kept", "conflicts", "orphans", "carriedRevisionScoped"), 0)
    conflicts = exposure(state)["conflicts"]
    result["conflicts"], result["orphans"] = conflicts, deepcopy(state.get("orphans") or [])
    for orphaned in result["orphans"]:
        command = orphaned.get("command", {})
        if "C" not in orphaned and command:
            orphaned.update(targetId=command.get("targetId", orphaned["orphanId"]),
                pageId=command.get("pageId"), alias=command.get("targetId"), label=command.get("targetId"),
                C={"payload": deepcopy(command), "hash": digest(command)},
                link={"status": "stale", "binding": deepcopy(orphaned.get("sourceBinding", old_binding))})
    baselines = result.setdefault("generatedBaseline", {})
    remapped, processed, updated_conflicts = {}, set(), set()
    page_ids = {p["pageId"] for p in document.get("pages", [])}
    scoped_candidates = {}
    for key, value in generated.items():
        ident = value["identity"]
        if ident.get("scope") == "revision":
            address = (ident.get("parentId"), digest(ident.get("ordinal")), key.split("-", 2)[1])
            scoped_candidates.setdefault(address, []).append(key)
    new_scoped = {address: keys[0] for address, keys in scoped_candidates.items() if len(keys) == 1}

    def orphan(key, value, reason, page, previous=None):
        from .resolution import target_kind
        known = previous or baselines.get(key) or {}
        item = {"orphanId": "o-" + digest([key, page, value, reason])[:20], "targetId": key,
                "pageId": page, "alias": known.get("alias", key), "label": known.get("label", key),
                "targetKind": known.get("targetKind") or target_kind(key, value),
                "C": {"payload": deepcopy(value), "hash": digest(value),
                      "fieldMeta": deepcopy(state.get("fieldMeta", {}).get(known.get("scopeId", key), {}))}, "reason": reason,
                "link": {"status": "stale", "binding": old_binding}, "B": deepcopy(baselines.get(key))}
        if not any(o.get("orphanId") == item["orphanId"] for o in result["orphans"]):
            result["orphans"].append(item)
            counts["orphans"] += 1

    def decide(key, override, page):
        scoped_key = scene_field_key(page, "page_element", key)
        if key not in generated and (scoped_key in generated or scoped_key in baselines):
            key = scoped_key
        processed.add(key)
        B = baselines.get(key)
        ident = (B or {}).get("identity") or state.get("identities", {}).get(key, {})
        if slots and override.get("selectedGenerated") and key in generated:
            baselines[key] = deepcopy(generated[key])
            counts["adopted"] += 1
            return key, {"value": generated[key]["payload"]["value"],
                         "source": generated[key]["evidence"].get("source"), "selectedGenerated": True}
        if slots and state.get("identities", {}).get(key, {}).get("ownership") == "authored":
            counts["kept"] += 1
            if key in generated:
                baselines[key] = deepcopy(generated[key])
            return key, deepcopy(override)
        scoped = ident.get("scope") == "revision"
        new_key = new_scoped.get((ident.get("parentId"), digest(ident.get("ordinal")), key.split("-", 2)[1])) if scoped else key
        N = generated.get(new_key)
        if new_key is not None:
            processed.add(new_key)
        field = "value" if slots or key.startswith("slot:") else "text"
        C = ({field: override["value" if slots else "text"]} if ("value" if slots else "text") in override
             else deepcopy((B or {}).get("payload", (N or {}).get("payload", {}))))
        if "richText" in override:
            C["richText"] = deepcopy(override["richText"])
        existing = next((c for c in conflicts if c.get("status", "open") == "open"
                         and key in {c.get("targetId"), c.get("previousTargetId")}), None)
        policy = three_way(B, C, N, revision_scoped=scoped)
        if N is None:
            orphan(key, override, "parent_or_ordinal_deleted" if scoped else "target_deleted", page)
            if existing:
                existing["N"] = None
                existing["newSourceRefs"] = {}
            return None, None
        if existing:
            updated_conflicts.add(existing.get("conflictId"))
            existing.update(N=deepcopy(N), newSourceRefs=deepcopy(N["evidence"]), targetId=new_key,
                            pageId=N["pageId"], alias=N["alias"])
            counts["conflicts"] += 1
        elif policy in {"value", "missing_baseline", "revision_scoped"}:
            conflicts.append({"conflictId": "c-" + digest([refresh_id, key])[:20],
                "targetId": new_key, "previousTargetId": key, "pageId": N["pageId"], "alias": N["alias"],
                "scopeId": N["scopeId"], "kind": policy, "B": deepcopy(B),
                "C": {"payload": deepcopy(C), "hash": digest(C), "override": deepcopy(override),
                      "fieldMeta": deepcopy(state.get("fieldMeta", {}).get(N["scopeId"], {}))}, "N": deepcopy(N),
                "oldSourceRefs": deepcopy((B or {}).get("evidence", {})), "newSourceRefs": deepcopy(N["evidence"]),
                "createdRevision": state.get("editRevision", 0) + 1, "status": "open", "resolutionReceipt": None})
            counts["conflicts"] += 1
        else:
            counts[policy] += 1
            baselines[new_key] = deepcopy(N)
            if scoped:
                counts["carriedRevisionScoped"] += 1
            if policy == "adopted":
                if slots:
                    return None, None
                override = {k: deepcopy(v) for k, v in override.items() if k not in {"text", "richText"}}
                if not override:
                    return None, None
        if new_key != key:
            remapped[key] = new_key
        # Only an exact parent+ordinal match is permitted for binding-scoped IDs.
        return new_key, deepcopy(override)

    if slots:
        values = {}
        for slot, value in state.get("values", {}).items():
            key, kept = decide("slot:" + slot, value, "page-product-specification")
            if key is not None:
                values[key[5:]] = kept
        result["values"] = values
    else:
        pages = {}
        for page_id, page in state.get("pages", {}).items():
            retained = deepcopy(page)
            retained.pop("pageElementOverrides", None)
            if page_id not in page_ids:
                for collection, value in retained.items():
                    if collection == "documentObjects":
                        for object_id, item in value.items():
                            orphan(object_id, item, "page_deleted", page_id,
                                   {"alias": object_id, "label": item.get("name", object_id)})
                    elif collection.endswith("Overrides") and isinstance(value, dict):
                        for key, item in value.items():
                            orphan(key, item, "page_deleted", page_id)
                    elif value:
                        orphan(page_id if collection == "figureOverride" else page_id + "/" + collection,
                               value, "page_deleted", page_id)
                retained = {}
            if retained:
                current_page = next(p for p in document["pages"] if p["pageId"] == page_id)
                request = current_page.get("renderRequest") or {}
                collections = {"occurrenceOverrides": "occurrence", "manualGroupOverrides": "manual_group",
                               "balloonOverrides": "balloon", "leaderOverrides": "leader"}
                for collection, target_type in collections.items():
                    for key, value in list(retained.get(collection, {}).items()):
                        stable = scene_field_key(page_id, target_type, key)
                        B, N = baselines.get(stable), generated.get(stable)
                        # Old numbered callout aliases are not proof that a new
                        # source item is the same item. Never repoint an annotation.
                        ambiguous = target_type in {"balloon", "leader"} and (B is None or N is None
                            or B["payload"].get("sourceTarget") != N["payload"].get("sourceTarget"))
                        if N is None or ambiguous:
                            orphan(stable, value, "source_identity_changed" if ambiguous else "target_deleted", page_id)
                            retained[collection].pop(key)
                        else:
                            baselines[stable] = deepcopy(N)
                            processed.add(stable)
                            counts["kept"] += 1
                if retained.get("figureOverride") and page_id in generated:
                    baselines[page_id] = deepcopy(generated[page_id])
                    processed.add(page_id)
                    counts["kept"] += 1
                counts["kept"] += len(retained.get("documentObjects", {}))
                pages[page_id] = {**pages.get(page_id, {}), **retained}
            for key, override in page.get("pageElementOverrides", {}).items():
                new_key, kept = decide(key, override, page_id)
                if new_key is not None:
                    destination = generated[new_key]["pageId"]
                    # Parts text is definition-wide and uses its owner's established storage page.
                    if new_key.startswith("part."):
                        destination = "page-parts-index"
                    pages.setdefault(destination, {}).setdefault("pageElementOverrides", {})[generated[new_key].get("storageId", new_key)] = kept
        result["pages"] = pages
    # A conflict can outlive its displayed target. Update its proposal even when
    # the manual payload is now unplaced, without silently reattaching the orphan.
    for conflict in open_conflicts(result):
        if conflict.get("conflictId") in updated_conflicts:
            continue
        key = conflict["targetId"]
        ident = (conflict.get("B") or {}).get("identity", {})
        new_key = new_scoped.get((ident.get("parentId"), digest(ident.get("ordinal")), key.split("-", 2)[1])) \
            if ident.get("scope") == "revision" else key
        proposed = generated.get(new_key)
        if proposed is not None:
            processed.add(new_key)
        conflict["N"] = deepcopy(proposed)
        conflict["newSourceRefs"] = deepcopy((proposed or {}).get("evidence", {}))
    # Metadata for preserved manual values stays manual. Adopted values lose old
    # manual support only when the whole evidence scope has no remaining override.
    if remapped:
        def remap_meta(value):
            if isinstance(value, dict):
                return {remapped.get(k, k): remap_meta(v) for k, v in value.items()}
            if isinstance(value, list):
                return [remap_meta(v) for v in value]
            return remapped.get(value, value) if isinstance(value, str) else value
        result["fieldMeta"] = remap_meta(result.get("fieldMeta", {}))
    edited = (edited_targets(result, slots=True) if slots else
              {key for page in result.get("pages", {}).values()
               for key, override in page.get("pageElementOverrides", {}).items() if "text" in override})
    for key, meta in list(result.get("fieldMeta", {}).items()):
        aliases = set(meta.get("aliases", [key]))
        if not aliases & edited:
            result["fieldMeta"].pop(key, None)
    result.update(new_binding)
    result["identityAliases"] = deepcopy(catalog["aliasMap"])
    result["aliasRevision"] = catalog["aliasRevision"]
    identities = result.setdefault("identities", {})
    for key, item in identities.items():
        if key not in catalog["identities"] and item.get("ownership") != "authored":
            item["state"] = "tombstone"
            item["tombstonedBy"] = "refresh"
    for key, item in catalog["identities"].items():
        identities[key] = {**identities.get(key, {}), **deepcopy(item)}
        identities[key].pop("storagePage", None)
        identities[key].pop("tombstonedBy", None)
    if not slots:
        for page_id, page in result.get("pages", {}).items():
            for key in page.get("pageElementOverrides", {}):
                identities.setdefault(key, {"id": key, "state": "active"})["storagePage"] = page_id
    for key in set(generated) - processed:
        if key in baselines:
            baselines[key] = deepcopy(generated[key])
    counts["adopted"] += len(set(generated) - processed)
    counts["conflicts"] = len(open_conflicts(result))
    counts["orphans"] = len(result["orphans"])
    receipt = {"refreshId": refresh_id, "fromBinding": old_binding, "toBinding": new_binding,
               "actor": actor, "at": at, "counts": counts,
               "conflictIds": [c["conflictId"] for c in open_conflicts(result) if "conflictId" in c]}
    result["refreshReceipts"] = [*result.get("refreshReceipts", []), receipt][-REFRESH_RECEIPT_LIMIT:]
    result["editRevision"] = state.get("editRevision", 0) + 1
    result["editEpoch"] = state.get("editEpoch", 0) + 1
    result["updatedAt"] = at
    from .resolution import with_hash
    result["conflicts"] = [with_hash(c) for c in result["conflicts"]]
    result["orphans"] = [with_hash(o) for o in result["orphans"]]
    validate_refresh_metadata(result)
    return result, receipt


def reset_preview(state):
    ids = edited_targets(state, slots="values" in state)
    if "values" in state and any(state.get(key) is not None for key in ("rows", "type", "units")):
        ids.add("@sheet")
    for page, composition in state.get("pages", {}).items():
        ids.update(composition.get("documentObjects", {}))
        ids.update(page + "/" + key for key, value in composition.items()
                   if key not in {"pageElementOverrides", "documentObjects"} and value)
    ids.update(c["targetId"] for c in open_conflicts(state))
    ids.update(o.get("targetId", o.get("orphanId", "")) for o in state.get("orphans", []))
    return {"affectedIds": sorted(ids), "counts": {"targets": len(ids), "conflicts": len(open_conflicts(state)),
            "orphans": len(state.get("orphans", []))}, "previewHash": digest(state)}
