"""Evidence support for authored document values; source authority is never edited."""
from __future__ import annotations

from copy import deepcopy
from typing import Mapping
import uuid

from .commands import DocumentEditError, content_hash, digest, document_id, scene_field_key
from .identity import stable_target, alias_entry, VERSIONS

EDITED_MARKER = "Edited - source does not verify this value"
EDITED_LEGEND = "Edited values retain their original sources for reference; those sources do not verify the edited values."


def scope_id(document, page_id, alias):
    stable = stable_target(document, page_id, alias)
    if stable != alias or alias.startswith("gen-"):
        return stable
    number = (document.get("product") or {}).get("assemblyNumber") or document.get("assemblyNumber") or ""
    identity = document_id(document["documentType"], number)
    return str(uuid.uuid5(uuid.UUID(identity), ":".join((str(document.get("sourceRevision") or ""),
        str(document.get("manualPlanRevision") or ""), page_id, alias))))


def _leaves(commands):
    for command in commands:
        if command.get("identityOrphan"):
            continue
        if command.get("operation") == "batch":
            yield from _leaves(command.get("commands") or [])
        else:
            yield command


def replay_field_meta(commands):
    result = {}
    for command in _leaves(commands):
        if command.get("operation") == "restore_change":
            from .changes import restore
            restore(result, command["change"]["changes"], root="fieldMeta")
            continue
        page_id, alias = command.get("pageId"), command.get("targetId")
        if command.get("operation") in {"reset_page", "reset"}:
            result = {key: value for key, value in result.items() if not (
                value.get("pageId") == page_id and (command["operation"] == "reset_page"
                or alias in value.get("aliases", []))) and not
                set(value.get("aliases", [])) & set(command.get("identityResetTargets", []))}
        for key, value in (command.get("fieldMeta") or {}).items():
            result[key] = deepcopy(value)
    return result


def _text_history(scene, page_id, aliases):
    history = []
    from .changes import effective_commands
    for command in _leaves(effective_commands((scene.get("commands") or [])[:int(scene.get("historyCursor") or 0)])):
        if command.get("refreshCheckpoint"):
            adopted = set(command.get("adoptedTargets", []))
            history = [item for item in history if item.get("targetId") not in adopted]
            continue
        if command.get("pageId") != page_id and not (str(command.get("targetId", "")).startswith("gen-")
                and command.get("targetId") in aliases):
            continue
        operation, target = command.get("operation"), command.get("targetId")
        if operation == "reset_page":
            history = []
        elif operation == "reset":
            history = [item for item in history if item.get("targetId") != target]
        elif operation == "update_text" and target in aliases:
            history.append(command)
    return history


def _source_ids(document, claims, supplied=()):
    return list(dict.fromkeys([*supplied, *[source["sourceId"] for source in document.get("evidenceCitations") or []
        if set(claims) & set(source.get("claimIds") or [])]]))


def _value(page, alias, generated):
    override = (page.get("documentationComposition") or {}).get("pageElementOverrides", {}).get(alias, {})
    override = page.get("identityOverrides", {}).get(alias, override)
    return override.get("text", generated)


def _scopes(document, scene):
    for page in document.get("pages") or []:
        for block in page.get("layoutBlocks") or []:
            bid, kind = block.get("blockId"), block.get("blockType")
            if not bid or kind == "contents_list":
                continue
            target = lambda alias: stable_target(document, page["pageId"], alias)
            rows = block.get("rows") if kind in {"table", "key_value_table"} else None
            items = block.get("items") if kind in {"list", "figure_legend"} else None
            children = rows if rows is not None else items
            bound_indices = {i for i, child in enumerate(children or []) if
                block.get("evidenceBindingVersion") == 1 and "claimIds" in child}
            unknown = set(range(len(children or []))) - bound_indices
            unknown_fields = {target(f"{bid}.r{i}.c{ci}"): value for i in sorted(unknown)
                for ci, value in enumerate(children[i].get("cells") or [])} if rows is not None else {
                target(f"{bid}.i{i}"): children[i].get("text", "") for i in sorted(unknown)}
            fallback = (scene.get("fieldMeta") or {}).get(scope_id(document, page["pageId"], bid), {})
            whole_block = bool(unknown and (fallback.get("origin") == "manual" or any(
                _value(page, key, value) != value for key, value in unknown_fields.items()) or any(
                cmd.get("text") != unknown_fields[cmd["targetId"]]
                for cmd in _text_history(scene, page["pageId"], unknown_fields))))
            groups = ([(None, block, False)] if whole_block or not bound_indices else
                      [(i, children[i], True) for i in sorted(bound_indices)]
                      + ([(None, block, False)] if unknown else []))
            for index, owner, bound in groups:
                alias = f"{bid}.r{index}" if bound and rows is not None else f"{bid}.i{index}" if bound else bid
                if rows is not None:
                    chosen = [(index, owner)] if bound else list(enumerate(rows))
                    fields = [(target(f"{bid}.r{ri}.c{ci}"), cell) for ri, row in chosen for ci, cell in enumerate(row.get("cells") or [])]
                elif items is not None:
                    chosen = [(index, owner)] if bound else list(enumerate(items))
                    fields = [(target(f"{bid}.i{ii}"), item.get("text", "")) for ii, item in chosen]
                else:
                    fields = [(target(bid), block.get("caption", "") if kind == "cad_figure" else
                               block.get("text", "\n".join(block.get("lines") or [])))]
                original = owner.get("originalEvidence") or {}
                claims = original.get("claimIds", owner.get("claimIds", []) if bound else block.get("evidenceClaimIds", []))
                sources = _source_ids(document, claims, original.get("sourceIds", owner.get("sourceIds", [])))
                watched = list(unknown_fields) if bound_indices and unknown and not bound and not whole_block else [key for key, _ in fields]
                yield page, block, owner, alias, fields, list(claims), sources, bound, watched


def project_document(document, scene=None, *, generated_parts=None):
    """Pure read projection, including legacy positional overrides with no row guesses."""
    result = deepcopy(document)
    supported = {"operations_and_maintenance_manual": 3, "work_instructions": 3,
                 "illustrated_parts_manual": 6}.get(result.get("documentType"))
    if supported and result.get("schemaVersion", 1) > supported:
        raise DocumentEditError("unsupported_document_schema", "This document needs a newer editor.")
    if supported:
        result["schemaVersion"] = supported
    scene = {"fieldMeta": result.get("fieldMeta") or {}} if scene is None else scene
    stored = scene.get("fieldMeta") or {}
    field_meta, targets = {}, []
    for page, block, owner, alias, fields, claims, sources, bound, watched in _scopes(result, scene):
        sid = scope_id(result, page["pageId"], alias)
        generated = {key: value for key, value in fields}
        effective = {key: _value(page, key, value) for key, value in fields}
        previous = stored.get(sid) or {}
        # Read old overrides conservatively; replayed history also detects typing
        # the generated string back after an earlier semantic change.
        history = _text_history(scene, page["pageId"], watched)
        changed = any(effective[key] != generated[key] for key in watched) or any(
            cmd.get("text") != generated[cmd["targetId"]] for cmd in history)
        if previous:
            meta = deepcopy(previous)
        else:
            last = history[-1] if history else {}
            meta = {"origin": "manual" if changed else "generated",
                    "evidenceStatus": "edited_unverified" if changed and (claims or sources) else
                                      "source_backed" if claims or sources else "unbound",
                    "generatedValue": generated, "generatedHash": digest(generated),
                    "changeId": last.get("commandId"), "actor": last.get("actor", "legacy" if changed else "compiler")}
        display_name = str((owner.get("cells") or [""])[0]) if bound and "rows" in block else ""
        if not display_name:
            display_name = str(owner.get("label") or page.get("title") or alias)
        meta.update({"targetId": sid, "pageId": page["pageId"], "alias": sid, "displayName": display_name,
                     "aliases": list(generated), "claimIds": claims, "sourceIds": sources,
                     "sourceRevision": result.get("sourceRevision"),
                     "originalEvidence": {"claimIds": claims, "sourceIds": sources}})
        confirmed_values = {meta.get("confirmationAliases", {}).get(k, k): v for k, v in effective.items()}
        if meta.get("confirmation") and meta["confirmation"].get("valueHash") != digest(confirmed_values):
            meta.pop("confirmation", None)
            meta.update(origin="manual", evidenceStatus="edited_unverified" if claims or sources else "unbound")
        active = meta["evidenceStatus"] == "source_backed"
        known_claims = {claim for child in (block.get("rows") or block.get("items") or [])
                        for claim in (child.get("originalEvidence") or {}).get("claimIds", child.get("claimIds", []))}
        active_claims = [claim for claim in claims if not (not bound and watched != list(generated) and claim in known_claims)]
        meta["activeClaimIds"] = active_claims if active else []
        meta["activeSourceIds"] = (_source_ids(result, active_claims) if active_claims != claims else sources) if active else []
        meta["marker"] = EDITED_MARKER if meta["evidenceStatus"] == "edited_unverified" else ""
        owner["provenance"] = deepcopy(meta)
        owner["originalEvidence"] = deepcopy(meta["originalEvidence"])
        if bound:
            owner["claimIds"], owner["sourceIds"] = meta["activeClaimIds"], meta["activeSourceIds"]
        owner["activeEvidenceClaimIds"] = meta["activeClaimIds"]
        owner["activeSourceIds"] = meta["activeSourceIds"]
        if not bound and not active:
            for child in block.get("rows") or block.get("items") or []:
                child.pop("provenance", None)
                if "claimIds" in child or "sourceIds" in child:
                    child.setdefault("originalEvidence", {"claimIds": list(child.get("claimIds") or []),
                                                           "sourceIds": list(child.get("sourceIds") or [])})
                    if "claimIds" in child:
                        child["claimIds"] = []
                    if "sourceIds" in child:
                        child["sourceIds"] = []
                    child.update(activeEvidenceClaimIds=[], activeSourceIds=[])
        field_meta[sid] = meta
        targets.append({"targetId": sid, "pageId": page["pageId"], "alias": alias,
                        "values": effective, "editAliases": watched, "provenance": deepcopy(meta),
                        "versionKeys": [scene_field_key(page["pageId"], "page_element", key) for key in generated]})
    for page in result.get("pages") or []:
        for block in page.get("layoutBlocks") or []:
            children = block.get("rows") or block.get("items") or []
            if block.get("evidenceBindingVersion") == 1 and children and all("provenance" in row for row in children):
                block["activeEvidenceClaimIds"] = list(dict.fromkeys(claim for row in children
                    for claim in row["provenance"]["activeClaimIds"]))
                block["activeSourceIds"] = list(dict.fromkeys(source for row in children
                    for source in row["provenance"]["activeSourceIds"]))
    # Parts headings, shared BOM descriptions and authored text objects have no
    # cited source binding. They still carry value/origin history in the same store.
    from .targets import text_targets

    number = (result.get("product") or {}).get("assemblyNumber") or result.get("assemblyNumber") or ""
    identity = {"documentId": document_id(result["documentType"], number),
                "sourceRevision": result.get("sourceRevision", ""),
                "manualPlanRevision": result.get("manualPlanRevision", ""), "scene": scene}
    covered = {(target["pageId"], alias) for target in targets for alias in target["values"]}
    original = text_targets({**identity, "scene": {"pages": {}}}, result)
    for key, target in text_targets(identity, result).items():
        alias = target.get("storageId", target["alias"])
        if (target["pageId"], alias) in covered:
            continue
        page_id = "page-parts-index" if alias.startswith("part.") else target["pageId"]
        authored = target["targetType"] == "document_object"
        generated = None if authored else (generated_parts or {}).get(alias, original[key]["text"])
        effective = target["text"]
        history = _text_history(scene, page_id, [alias])
        creation = next((cmd for cmd in reversed(list(_leaves((scene.get("commands") or [])[:
            int(scene.get("historyCursor") or 0)]))) if cmd.get("operation") == "add_object"
            and cmd.get("pageId") == page_id and cmd.get("targetId") == alias), {}) if authored else {}
        last = history[-1] if history else creation
        meta = deepcopy(stored.get(key) or {"origin": "manual" if authored or history or effective != generated else "generated",
            "evidenceStatus": "unbound", "generatedValue": {alias: generated}, "generatedHash": digest({alias: generated}),
            "changeId": last.get("commandId"), "actor": last.get("actor", "compiler")})
        meta.update(targetId=key, pageId=page_id, alias=alias, aliases=[alias], claimIds=[], sourceIds=[],
            sourceRevision=result.get("sourceRevision"), originalEvidence={"claimIds": [], "sourceIds": []},
            activeClaimIds=[], activeSourceIds=[], marker="")
        field_meta[key] = meta
        targets.append({"targetId": key, "pageId": page_id, "alias": alias, "values": {alias: effective},
                        "provenance": deepcopy(meta), "versionKeys": [target["versionKey"]]})
    for page in result.get("pages") or []:
        page["activeEvidenceClaimIds"] = list(dict.fromkeys(claim for target in targets
            if target["pageId"] == page["pageId"] for claim in target["provenance"]["activeClaimIds"]))
    result["fieldMeta"], result["provenanceTargets"] = field_meta, targets
    result["sourceSupportSummary"] = support_summary(targets)
    result["sourceSupport"] = [{"targetId": row["targetId"], "claimIds": row["provenance"]["activeClaimIds"],
        "sourceIds": row["provenance"]["activeSourceIds"], "evidenceStatus": row["provenance"]["evidenceStatus"]}
        for row in targets if row["provenance"]["claimIds"] or row["provenance"]["sourceIds"]]
    return result


def support_summary(targets):
    return {"scopeCounts": {status: sum(row["provenance"]["evidenceStatus"] == status for row in targets)
                           for status in ("source_backed", "edited_unverified", "entered_by_user", "unbound")},
            "activeClaimIds": list(dict.fromkeys(claim for row in targets for claim in row["provenance"]["activeClaimIds"])),
            "activeSourceIds": list(dict.fromkeys(source for row in targets for source in row["provenance"]["activeSourceIds"])),
            "unconfirmedTargets": [{key: row[key] for key in ("targetId", "pageId", "alias")} for row in targets
                                   if row["provenance"]["evidenceStatus"] == "edited_unverified"]}


def prepare_text_command(document, command):
    result = deepcopy(command)
    # Provenance is computed by the host, never accepted from a caller payload.
    result.pop("fieldMeta", None)
    if result.get("targetType") == "page_element":
        entry = alias_entry(document, result.get("pageId"), result.get("targetId"))
        if entry and not entry.get("safe"):
            raise DocumentEditError("ambiguous_legacy_target", "This source has no unique editable identity.")
        result["targetId"] = stable_target(document, result.get("pageId"), result.get("targetId"))
    command = result
    if command.get("operation") != "update_text":
        return result
    changes = {}
    for target in document.get("provenanceTargets") or []:
        alias = command.get("targetId")
        if target["pageId"] != command.get("pageId") or alias not in target.get("editAliases", target["values"]):
            continue
        if target["values"][alias] == command.get("text"):
            continue
        meta = deepcopy(target["provenance"])
        meta.pop("confirmation", None)
        meta.update(origin="manual", evidenceStatus="edited_unverified" if meta["claimIds"] or meta["sourceIds"] else "unbound")
        changes[target["targetId"]] = meta
    if changes:
        result["fieldMeta"] = changes
    return result


def confirmation_targets(state, document):
    result = {}
    for target in document.get("provenanceTargets") or []:
        if target["provenance"]["evidenceStatus"] != "edited_unverified":
            continue
        item = deepcopy(target)
        item["fieldVersions"] = {key: state.get("fieldVersions", {}).get(key, 0) for key in item.pop("versionKeys")}
        item["contentHash"] = content_hash(state, item["targetId"], item)
        result[item["targetId"]] = item
    return result


def confirmation_command(target, *, by):
    meta = deepcopy(target["provenance"])
    meta.pop("confirmationAliases", None)
    meta.update(origin="manual", evidenceStatus="entered_by_user", activeClaimIds=[], activeSourceIds=[], marker="")
    meta["confirmation"] = {"by": by, "valueHash": digest(target["values"])}
    # Reuse the existing text-history shape with the exact current value. The
    # metadata is the change; older scene-3 readers still understand this entry.
    alias = next(iter(target["values"]))
    return {"operation": "update_text", "pageId": target["pageId"], "targetType": "page_element",
            "targetId": alias, "text": target["values"][alias], "fieldMeta": {target["targetId"]: meta}}


def unconfirmed_targets(document):
    return [{"targetId": row["targetId"], "pageId": row["pageId"], "alias": row["alias"]}
            for row in document.get("provenanceTargets") or []
            if row["provenance"]["evidenceStatus"] == "edited_unverified"]


def export_document(document):
    """Old generated JSON gets the same pure provenance projection as live compilation."""
    kind = document.get("documentType")
    supported = VERSIONS.get(kind)
    if supported and document.get("schemaVersion", 1) > supported:
        raise DocumentEditError("unsupported_document_schema", "This document needs a newer editor.")
    if "fieldMeta" in document and document.get("schemaVersion") == supported:
        return document
    if kind == "product_specification_sheet":
        return project_slots(document, {"values": {slot: value for slot, value in document.get("slots", {}).items()
            if value.get("source") in {"workspace", "chat", "research", "sage_draft", "returned_pdf"}}})
    if document.get("documentType") in {"operations_and_maintenance_manual", "work_instructions", "illustrated_parts_manual"}:
        return project_document(document)
    return document


def check_export(document, mode="review"):
    if mode not in {"review", "draft", "customer", "controlled"}:
        raise DocumentEditError("invalid_document_operation", "Unknown document export mode.")
    pending = unconfirmed_targets(export_document(document))
    if mode in {"customer", "controlled"} and pending:
        raise DocumentEditError("unconfirmed_cited_values", "Confirm or undo the edited cited values before export.", targets=pending)


def strip_projection(document):
    """Historical work-instruction hash input, excluding only additive provenance."""
    if isinstance(document, list):
        return [strip_projection(value) for value in document]
    if isinstance(document, dict):
        return {key: strip_projection(value) for key, value in document.items()
                if key not in {"fieldMeta", "provenanceTargets", "provenance", "originalEvidence",
                               "activeEvidenceClaimIds", "activeSourceIds", "sourceSupport", "sourceSupportSummary",
                               "identityVersion", "aliasMap", "aliasRevision", "identities", "identityOrphans",
                               "identityOverrides", "stableId", "rowId", "cellIds", "columnIds", "itemId",
                               "identityStatus", "identityScope", "identitySourceKey", "identityCellFields", "sourceKey", "columnKeys", "bomColumnIds", "legacyDocumentationSceneRevision", "identityBaselineAvailable"}}
    return document


def project_slots(document, stored):
    result = deepcopy(document)
    if result.get("schemaVersion", 1) > 3:
        raise DocumentEditError("unsupported_document_schema", "This sheet needs a newer editor.")
    result["schemaVersion"] = 3
    meta_by_id = {}
    for slot, item in result.get("slots", {}).items():
        sid = "slot:" + slot
        original = item.get("default") or {"value": item.get("value"), "source": item.get("source")}
        claims = list(item.get("claimIds") or [])
        sources = _source_ids(result, claims)
        changed = bool(item.get("overrides"))
        meta = deepcopy((stored.get("fieldMeta") or {}).get(sid) or {})
        if not meta:
            meta = {"origin": "manual" if changed or slot in stored.get("values", {}) or item.get("source") in
                    {"workspace", "chat", "research", "sage_draft", "returned_pdf"} else "generated",
                    "evidenceStatus": "edited_unverified" if changed and claims else "source_backed" if claims else "unbound",
                    "generatedValue": original.get("value"), "generatedHash": digest(original.get("value")),
                    "changeId": None, "actor": item.get("source") or "compiler"}
        meta.update(targetId=sid, claimIds=claims, sourceIds=sources,
                    originalEvidence={"claimIds": claims, "sourceIds": sources})
        if (stored.get("fieldMeta") or {}).get(sid) and meta.get("sourceRevision") is None:
            # A direct legacy store caller had no compiled default. Recover the
            # original value on read and conservatively retain its manual status.
            meta.update(generatedValue=original.get("value"), generatedHash=digest(original.get("value")))
            if claims:
                meta["evidenceStatus"] = "edited_unverified"
        elif changed and claims and meta["evidenceStatus"] == "unbound":
            meta["evidenceStatus"] = "edited_unverified"
        meta["sourceRevision"] = result.get("sourceRevision")
        active = meta["evidenceStatus"] == "source_backed"
        meta.update(activeClaimIds=claims if active else [], activeSourceIds=sources if active else [],
                    marker=EDITED_MARKER if meta["evidenceStatus"] == "edited_unverified" else "")
        item["provenance"] = meta
        item["activeClaimIds"] = meta["activeClaimIds"]
        # Existing claimIds/default/overrides stay intact for engineering gates.
        meta_by_id[sid] = meta
    result["fieldMeta"] = meta_by_id
    page_id = (result.get("pages") or [{"pageId": "page-specification"}])[0]["pageId"]
    result["provenanceTargets"] = [{"targetId": sid, "pageId": page_id, "alias": sid,
        "values": {sid: result["slots"][sid[5:]].get("value")}, "provenance": deepcopy(meta),
        "versionKeys": [sid]} for sid, meta in meta_by_id.items()]
    result["sourceSupportSummary"] = support_summary(result["provenanceTargets"])
    result["sourceSupport"] = [{"targetId": sid, "claimIds": meta["activeClaimIds"],
        "sourceIds": meta["activeSourceIds"], "evidenceStatus": meta["evidenceStatus"]}
        for sid, meta in meta_by_id.items() if meta["claimIds"] or meta["sourceIds"]]
    for page in result.get("pages") or []:
        for block in page.get("layoutBlocks") or []:
            slot = block.get("slot")
            if slot and "slot:" + slot in meta_by_id:
                block["provenance"] = deepcopy(meta_by_id["slot:" + slot])
    return result


def slot_mutation_meta(before, candidate, defaults, *, actor, change_id, effective_values=None):
    for slot in set(before["values"]) | set(candidate["values"]):
        old, new = before["values"].get(slot) or {}, candidate["values"].get(slot) or {}
        sid = "slot:" + slot
        baseline = defaults.get(sid) or before.get("fieldMeta", {}).get(sid) or {}
        generated = baseline.get("generatedValue")
        if not new:
            # Clearing a native slot explicitly returns to its generated default.
            candidate["fieldMeta"].pop(sid, None)
            continue
        if old.get("value", (effective_values or {}).get(slot, generated)) == new.get("value", generated):
            continue
        meta = deepcopy(baseline or {
            "generatedValue": old.get("value"), "generatedHash": digest(old.get("value")),
            "claimIds": [], "sourceIds": [], "sourceRevision": None, "originalEvidence": {"claimIds": [], "sourceIds": []}})
        meta.pop("confirmation", None)
        meta.update(origin="manual", evidenceStatus="edited_unverified" if meta.get("claimIds") else "unbound",
                    actor=actor, changeId=change_id)
        candidate["fieldMeta"][sid] = meta
