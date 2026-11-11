"""Compiler identities and conservative, pure legacy address migration.

IDs describe source relations, or explicitly binding-scoped ordinals for
anonymous values and layout fragments. Display text never allocates identity.
Store owners receive catalogues explicitly; the cache is diagnostic only.
"""
from __future__ import annotations

from collections import Counter, OrderedDict
from copy import deepcopy
import re
import uuid

from .commands import DocumentEditError, digest, document_id, scene_field_key

IDENTITY_VERSION = 1
VERSIONS = {"illustrated_parts_manual": 6, "operations_and_maintenance_manual": 3,
            "product_specification_sheet": 3, "work_instructions": 3}
_POSITIONAL = re.compile(r"[.](?:r[0-9]+(?:[.]c[0-9]+)?|i[0-9]+)$")
_CATALOGS = OrderedDict()


def generated_id(kind, *source_keys):
    return "gen-" + kind + "-" + digest(list(source_keys))[:32]


def source_key(item):
    if item.get("sourceKey") and item.get("relationId"):
        return ["sourceKey", item["sourceKey"], "relationId", item["relationId"]]
    for key in ("sourceKey", "relationId", "rowId", "itemId", "definitionId", "operationId", "actionId", "stepId", "stageId", "sectionId", "key", "slot", "groupId"):
        if item.get(key) and not (key in {"rowId", "itemId"} and str(item[key]).startswith("gen-")):
            return [key, item[key]]
    if "identitySourceKey" in item:
        return deepcopy(item["identitySourceKey"])
    for key in ("sourceDefinitionIds", "claimIds", "sourceIds", "occurrenceIds"):
        value = (item.get("originalEvidence") or {}).get(key, item.get(key))
        if value:
            return [key, sorted(value)]
    return None


def row_target(block, row, column):
    return (row.get("cellIds") or [])[column] if column < len(row.get("cellIds") or []) else None


def item_target(block, item):
    return item.get("itemId")


def _binding(document):
    return {key: str(document.get(key) or "") for key in ("sourceRevision", "manualPlanRevision")}


def _catalog_key(kind, number, source, plan):
    return kind, str(number).strip().casefold(), str(source), str(plan)


def catalog_for(kind, number, source, plan):
    return deepcopy(_CATALOGS.get(_catalog_key(kind, number, source, plan)))


def _number(document):
    return (document.get("product") or {}).get("assemblyNumber") or document.get("assemblyNumber") or ""


def catalog_from(document):
    """Return the generated catalogue explicitly; process cache is never authority."""
    compiled = compile_identities(document)
    return {key: deepcopy(compiled[key]) for key in ("aliasMap", "aliasRevision", "identities")} | {
        "identityBaselineAvailable": compiled.get("identityBaselineAvailable", True),
        **_binding(compiled), "documentType": compiled["documentType"], "assemblyNumber": _number(compiled)}


def compile_identities(document):
    """Source-keyed identities, plus binding-scoped ordinals where no key exists.

    Identity source keys are captured before provenance projection can remove
    active claim/source IDs. Generated annotations never become source keys.
    Authored objects belong to the scene and do not change this catalogue.
    """
    result = deepcopy(document)
    kind = result["documentType"]
    if result.get("schemaVersion", 1) > VERSIONS[kind]:
        raise DocumentEditError("unsupported_document_schema", "This document needs a newer editor.")
    result["schemaVersion"] = VERSIONS[kind]
    aliases, identities = {}, {}
    binding = _binding(result)
    blocks = [block for page in result.get("pages", []) for block in page.get("layoutBlocks", [])]

    def parent(block):
        bid = str(block.get("sourceBlockId") or block.get("blockId") or "")
        slot = block.get("slot") or ((block.get("slots") or {}).get("text") if isinstance(block.get("slots"), dict) else None)
        return "slot:" + slot if slot else generated_id("block", kind, bid)

    def source(item):
        key = source_key(item)
        item["identitySourceKey"] = deepcopy(key)
        return key

    def scoped(role, parent_id, ordinal):
        return generated_id(role, parent_id, "revision", binding, ordinal)

    def register(key, *, safe=True, scope="source", parent_id=None, ordinal=None):
        entry = {"id": key, "state": "active" if safe else "unresolved", "scope": scope}
        if scope == "revision":
            entry.update(parentId=parent_id, ordinal=ordinal, sourceBinding=deepcopy(binding))
        identities[key] = entry
        return key

    block_counts = Counter(parent(block) for block in blocks)
    block_ordinals, child_ordinals = Counter(), Counter()
    row_groups = {}
    for block in blocks:
        for row in block.get("rows", []):
            key = source(row)
            if key is not None:
                row_groups.setdefault(generated_id("row", parent(block), key), []).append(row)
    split_rows = {key for key, rows in row_groups.items() if any(row.get("rowContinuation") for row in rows)}
    duplicate_rows = {key for key, rows in row_groups.items() if len(rows) > 1 and key not in split_rows}
    item_groups = Counter(generated_id("item", parent(block), source(item)) for block in blocks
                          for item in block.get("items", []) if source_key(item) is not None)
    row_ordinals = Counter()
    for page in result.get("pages") or []:
        page_aliases = aliases.setdefault(page["pageId"], {})

        def address(alias, stable, value, *, owner=None, safe=True, fingerprint=None,
                    scope="source", parent_id=None, ordinal=None):
            entry = {"targetId": stable, "fingerprint": fingerprint or digest(value),
                     "sourceBinding": deepcopy(binding), "safe": bool(safe), "scope": scope}
            if owner:
                entry["ownerId"] = owner
            if scope == "revision":
                entry.update(parentId=parent_id, ordinal=ordinal)
            page_aliases[alias] = entry
            register(stable, safe=safe, scope=scope, parent_id=parent_id, ordinal=ordinal)

        for block in page.get("layoutBlocks") or []:
            logical = parent(block)
            fragment = block_ordinals[logical]
            block_ordinals[logical] += 1
            block_scope = "revision" if block_counts[logical] > 1 else "source"
            stable = scoped("block", logical, fragment) if block_scope == "revision" else logical
            if block_scope == "revision":
                register(logical)  # Source parent of the independently editable fragments.
            block["stableId"], block["identityScope"] = stable, block_scope
            alias = block["blockId"]
            address(alias, stable, block.get("text", block.get("caption", block.get("lines", []))),
                    scope=block_scope, parent_id=logical, ordinal=fragment)
            for entry in block.get("entries") or []:
                key = source(entry)
                ordinal = child_ordinals[(logical, "entry")]
                child_ordinals[(logical, "entry")] += 1
                scope = "source" if key is not None else "revision"
                entry["itemId"] = generated_id("entry", logical, key) if key is not None else scoped("entry", logical, ordinal)
                entry["identityStatus"], entry["identityScope"] = "stable", scope
                register(entry["itemId"], scope=scope, parent_id=logical, ordinal=ordinal)
            rows, items = block.get("rows"), block.get("items")
            if isinstance(rows, list):
                keys = list(block.get("columnKeys") or ("label", "value"))
                block["columnIds"] = [register(generated_id("column", logical, key)) for key in keys]
                fingerprints = Counter(digest(row.get("cells")) for row in rows)
                for ri, row in enumerate(rows):
                    key = source(row)
                    ordinal = child_ordinals[(logical, "row")]
                    child_ordinals[(logical, "row")] += 1
                    base = generated_id("row", logical, key)
                    scope = "revision" if key is None or base in split_rows else "source"
                    row_parent = base if base in split_rows else logical
                    if base in split_rows:
                        ordinal = row_ordinals[base]
                        row_ordinals[base] += 1
                    rid = scoped("row", row_parent, ordinal) if scope == "revision" else base
                    safe = base not in duplicate_rows
                    row["rowId"], row["identityScope"] = rid, scope
                    row["identityStatus"] = "stable" if safe else "unresolved"
                    row["cellIds"] = [("slot:" + row["slots"][ci]) if row.get("slots") else
                        generated_id("cell", rid, block["columnIds"][ci]) if ci < len(keys) else
                        scoped("cell", rid, ci) for ci, _ in enumerate(row.get("cells") or [])]
                    fingerprint = digest(row.get("cells"))
                    address(f"{alias}.r{ri}", rid, row.get("cells"), safe=safe, fingerprint=fingerprint,
                            scope=scope, parent_id=row_parent, ordinal=ordinal)
                    page_aliases[f"{alias}.r{ri}"]["legacyAmbiguous"] = fingerprints[fingerprint] > 1 and scope != "revision"
                    for ci, value in enumerate(row.get("cells") or []):
                        cell_scope = "revision" if scope == "revision" or ci >= len(keys) else "source"
                        address(f"{alias}.r{ri}.c{ci}", row["cellIds"][ci], value, owner=rid,
                                safe=safe, fingerprint=fingerprint, scope=cell_scope, parent_id=row_parent, ordinal=[ordinal, ci])
                        page_aliases[f"{alias}.r{ri}.c{ci}"]["legacyAmbiguous"] = fingerprints[fingerprint] > 1 and scope != "revision"
            if isinstance(items, list):
                fingerprints = Counter(digest({k: item.get(k) for k in ("label", "text")}) for item in items)
                for ii, item in enumerate(items):
                    key = source(item)
                    ordinal = child_ordinals[(logical, "item")]
                    child_ordinals[(logical, "item")] += 1
                    scope = "source" if key is not None else "revision"
                    base = generated_id("item", logical, key)
                    item["itemId"] = base if key is not None else scoped("item", logical, ordinal)
                    safe = key is None or item_groups[base] == 1
                    item["identityStatus"], item["identityScope"] = "stable" if safe else "unresolved", scope
                    fingerprint = digest({k: item.get(k) for k in ("label", "text")})
                    address(f"{alias}.i{ii}", item["itemId"], item.get("text"), safe=safe,
                            fingerprint=fingerprint, scope=scope, parent_id=logical, ordinal=ordinal)
                    page_aliases[f"{alias}.i{ii}"]["legacyAmbiguous"] = fingerprints[fingerprint] > 1 and scope != "revision"
        # Existing native BOM field IDs remain definition-keyed.
        from ai_inspector.parts_manual.document import part_text_target_id
        for collection in ("bom", "entries", "revisionHistory", "manualGroupItems"):
            for ordinal, row in enumerate(page.get(collection) or []):
                key = source(row)
                row_parent = generated_id("collection", kind, page.get("sectionId") or page.get("pageType"), collection)
                scope = "source" if key is not None else "revision"
                if row.get("definitionId"):
                    row["rowId"] = generated_id("part", row["definitionId"])
                    row["cellIds"] = {field: part_text_target_id(row["definitionId"], field)
                                      for field in ("partNumber", "description")}
                    row["cellIds"].update({field: generated_id("cell", row["rowId"], field)
                                           for field in ("itemNumber", "quantity")})
                    page["bomColumnIds"] = {field: register(generated_id("column", "parts-bom", field))
                        for field in ("itemNumber", "partNumber", "description", "quantity")}
                else:
                    row["rowId"] = generated_id("row", kind, collection, key) if key is not None else scoped("row", row_parent, ordinal)
                    fields = row.get("identityCellFields")
                    if fields is None:
                        fields = [key for key in row if key not in {"rowId", "cellIds", "identitySourceKey",
                            "identityStatus", "identityScope", "provenance", "originalEvidence", "activeEvidenceClaimIds", "activeSourceIds"}]
                    row["identityCellFields"] = fields
                    row["cellIds"] = {key: generated_id("cell", row["rowId"], key) for key in fields}
                row["identityScope"] = scope
                register(row["rowId"], scope=scope, parent_id=row_parent, ordinal=ordinal)
                for cell_id in row["cellIds"].values():
                    register(cell_id, scope=scope, parent_id=row_parent, ordinal=ordinal)
        if kind == "illustrated_parts_manual":
            section = [page.get("sectionId") or page.get("pageType"), page.get("pageType"),
                       "continuation" if page.get("continuedFrom") else "primary"]
            for alias in ("header_title", "header_meta", "footer", "cover_subtitle"):
                address(alias, generated_id("field", kind, section, alias), None)
    occurrences = Counter(entry["targetId"] for entries in aliases.values() for entry in entries.values())
    for entries in aliases.values():
        for entry in entries.values():
            if occurrences[entry["targetId"]] > 1:
                entry["legacyAmbiguous"] = True
    result["identityVersion"] = IDENTITY_VERSION
    result["aliasMap"] = aliases
    result["aliasRevision"] = digest({"binding": binding, "aliases": aliases})
    result["identities"] = identities
    # Diagnostic cache only. No store, route, revision or alias resolver reads it.
    catalog = {"identityBaselineAvailable": result.get("identityBaselineAvailable", True), "aliasMap": aliases,
               "aliasRevision": result["aliasRevision"], "identities": identities,
               **binding, "documentType": kind, "assemblyNumber": _number(result)}
    key = _catalog_key(kind, _number(result), binding["sourceRevision"], binding["manualPlanRevision"])
    _CATALOGS[key] = deepcopy(catalog)
    _CATALOGS.move_to_end(key)
    while len(_CATALOGS) > 32:
        _CATALOGS.popitem(last=False)
    return result


def alias_entry(document, page, alias):
    return (document.get("aliasMap", {}).get(page) or {}).get(alias)


def stable_target(document, page, alias):
    entry = alias_entry(document, page, alias)
    return entry["targetId"] if entry and entry.get("safe") else alias


def _legacy_uuid(kind, number, source, plan, page, alias):
    return str(uuid.uuid5(uuid.UUID(document_id(kind, number)), ":".join((source, plan, page, alias))))


def migrate_scene(scene, catalog=None):
    """No I/O. Transform the log AND its snapshots, or quarantine the whole entry.

    An unavailable/changed baseline cannot authorize a positional migration.
    Quarantined entries stay in the original log and in the read-only orphan list;
    replay skips them, and named inverse explicitly refuses them.
    """
    result = deepcopy(scene)
    result.setdefault("identities", {})
    result.setdefault("orphans", [])
    result.setdefault("identityAliases", {})
    if not isinstance(result["identities"], dict) or not isinstance(result["identityAliases"], dict) or not isinstance(result["orphans"], list):
        raise DocumentEditError("unsupported_document_schema", "Invalid identity metadata.")
    current = bool(catalog and all(str(scene.get(k) or "") == catalog[k]
                                  for k in ("sourceRevision", "manualPlanRevision")))
    mapping = catalog["aliasMap"] if current else {}
    # Already stable entries may be read without a compiler. Recorded mappings
    # remain an audit trail, never a license to map a new positional command.
    old_ids, translations = {}, {}
    if current:
        for page, entries in mapping.items():
            for alias, entry in entries.items():
                if (entry.get("safe") and not entry.get("legacyAmbiguous")
                        and (catalog.get("identityBaselineAvailable", True) or not _POSITIONAL.search(alias))):
                    translations[(page, alias)] = entry["targetId"]
                    old_ids[_legacy_uuid(catalog["documentType"], catalog["assemblyNumber"],
                        catalog["sourceRevision"], catalog["manualPlanRevision"], page, alias)] = entry["targetId"]
    def mapped(page, value):
        if (page, value) in translations:
            return translations[(page, value)]
        if value in mapping.get(page, {}):
            raise ValueError("ambiguous_identity")
        if _POSITIONAL.search(str(value)):
            raise ValueError("ambiguous_identity" if current else "baseline_unavailable")
        return old_ids.get(value, value)
    def metadata(value, page):
        if isinstance(value, list):
            return [metadata(v, page) for v in value]
        if not isinstance(value, dict):
            return value
        here = value.get("pageId", page)
        output = {}
        for key, val in value.items():
            new_key = mapped(here, key)
            if key in {"targetId", "alias"} and isinstance(val, str):
                val = mapped(here, val)
            elif key in {"aliases", "editAliases"}:
                val = [mapped(here, a) for a in val]
            elif isinstance(val, (dict, list)):
                val = metadata(val, here)
            output[new_key] = val
        if output.get("confirmation") and value.get("aliases"):
            output.setdefault("confirmationAliases", {mapped(here, a): a for a in value["aliases"]})
        if "generatedValue" in output:
            output["generatedHash"] = digest(output["generatedValue"])
        # Confirmation hashes use field-addressed values. Preserve validation
        # through migration by converting those values, never by trusting text.
        return output
    def record(value):
        output = deepcopy(value)
        for change in output.get("changes", []):
            address = change["path"]
            page = address[1] if address[0] == "pages" and len(address) > 1 else ""
            if address[0] == "pages" and len(address) == 4 and address[2] == "pageElementOverrides":
                address[3] = mapped(page, address[3])
            elif address[0] == "fieldMeta" and len(address) == 2:
                address[1] = old_ids.get(address[1], address[1])
            for side in ("before", "after"):
                if change[side].get("present"):
                    val = change[side]["value"]
                    if address[0] == "pages" and len(address) < 4:
                        val = page_image(val, page, address[2] if len(address) == 3 else None)
                    elif address[0] == "fieldMeta":
                        val = metadata(val, page)
                    change[side]["value"] = val
        output["versionKeys"] = [version_key(key) for key in output.get("versionKeys", [])]
        return output
    def page_image(value, page, collection=None):
        if not isinstance(value, dict):
            return value
        if collection == "pageElementOverrides":
            return {mapped(page, key): val for key, val in value.items()}
        return {key: page_image(val, page, key) if key == "pageElementOverrides" else val for key, val in value.items()}
    def version_key(key):
        bits = key.split("/", 2)
        if len(bits) == 3 and bits[1] == "page_element":
            return scene_field_key(bits[0], bits[1], mapped(bits[0], bits[2]))
        return old_ids.get(key, key)
    def command(entry):
        output = deepcopy(entry)
        page = output.get("pageId", "")
        if output.get("operation") == "batch":
            output["commands"] = [command(c) for c in output["commands"]]
        elif output.get("targetType") == "page_element":
            alias = output.get("targetId", "")
            stable = mapped(page, alias)
            if stable != alias:
                output["targetId"] = stable
                output["identityMigration"] = {"alias": alias, **deepcopy(mapping[page][alias])}
        for transform in output.get("transforms", []):
            if transform.get("targetType") == "page_element":
                transform["targetId"] = mapped(page, transform["targetId"])
        if output.get("fieldMeta"):
            output["fieldMeta"] = metadata(output["fieldMeta"], page)
        if output.get("change"):
            output["change"] = record(output["change"])
        return output
    known_orphans = {o["orphanId"] for o in result["orphans"]}
    for index, entry in enumerate(result.get("commands", [])):
        if entry.get("identityOrphan"):
            continue
        try:
            result["commands"][index] = command(entry)
        except ValueError as error:
            oid = "orphan-" + digest(entry)[:24]
            entry["identityOrphan"] = oid
            if oid not in known_orphans:
                result["orphans"].append({"orphanId": oid, "reason": str(error), "command": deepcopy(scene["commands"][index]),
                    "sourceBinding": {k: scene.get(k) for k in ("sourceRevision", "manualPlanRevision")}})
                known_orphans.add(oid)
    versions = {}
    for key, value in result.get("fieldVersions", {}).items():
        try:
            versions[version_key(key)] = value
        except ValueError:
            versions[key] = value
    result["fieldVersions"] = versions
    for row in result.get("receipts", {}).values():
        receipt = row.get("receipt", {})
        ids = receipt.get("changedIds", [])
        translated = []
        for key in ids:
            try:
                translated.append(version_key(key))
            except ValueError:
                # Unresolved receipts are audit records, never write authority.
                translated.append(key)
        if translated != ids:
            row.setdefault("legacyReceipt", deepcopy(receipt))
            receipt.setdefault("legacyChangedIds", ids)
            receipt["changedIds"] = translated
    if current:
        result["identityAliases"] = deepcopy(mapping)
        result["aliasRevision"] = catalog["aliasRevision"]
        live = catalog["identities"]
        for key, value in result["identities"].items():
            if key not in live and value.get("state") == "active" and value.get("ownership") != "authored":
                value["state"] = "tombstone"
        for key, value in live.items():
            result["identities"][key] = {**result["identities"].get(key, {}), **deepcopy(value)}
        for entry in result.get("commands", []):
            leaves = entry.get("commands", []) if entry.get("operation") == "batch" else [entry]
            for leaf in leaves:
                if leaf.get("targetType") == "page_element" and str(leaf.get("targetId", "")).startswith(("gen-", "slot:")):
                    result["identities"].setdefault(leaf["targetId"], {"id": leaf["targetId"], "state": "tombstone"}).setdefault("storagePage", leaf["pageId"])
    result["identityVersion"] = IDENTITY_VERSION
    return result


def track_authored_identities(scene):
    """Infer legacy authored tombstones from retained history without allocating IDs."""
    live = {key for page in scene.get("pages", {}).values() for key in page.get("documentObjects", {})}
    identities = scene.setdefault("identities", {})
    known = {key for key, value in identities.items() if value.get("ownership") == "authored"} | live
    def leaves(commands):
        for command in commands:
            if command.get("identityOrphan"):
                continue
            if command.get("operation") == "batch":
                yield from leaves(command.get("commands", []))
            else:
                yield command
    known.update(command["targetId"] for command in leaves(scene.get("commands", []))
                 if command.get("targetType") == "document_object")
    for key in known:
        identities[key] = {**identities.get(key, {}), "id": key, "ownership": "authored",
                           "state": "active" if key in live else "tombstone"}


def project_scene(document, scene):
    """Join stable overrides to current layout; retain legacy renderer aliases.

    Only this disposable view contains positional keys. The owning store and its
    history use stable keys. Moving a row between pages does not move its identity.
    """
    result = deepcopy(scene or {})
    by_id = {}
    for page in result.get("pages", {}).values():
        for key, value in page.get("pageElementOverrides", {}).items():
            if key.startswith(("gen-", "slot:")):
                if key in by_id and by_id[key] != value:
                    raise DocumentEditError("ambiguous_legacy_target", "Conflicting overrides for one source identity.", targetId=key)
                by_id[key] = value
    for page, aliases in document.get("aliasMap", {}).items():
        target = result.setdefault("pages", {}).setdefault(page, {})
        overrides = target.setdefault("pageElementOverrides", {})
        for alias, entry in aliases.items():
            stable = entry["targetId"]
            if entry.get("safe") and stable in by_id:
                overrides[alias] = deepcopy(by_id[stable])
        # Stable keys are not figure/render geometry inputs.
        target["pageElementOverrides"] = {k: v for k, v in overrides.items() if not k.startswith(("gen-", "slot:"))}
        if not target["pageElementOverrides"]:
            target.pop("pageElementOverrides")
        if not target:
            result["pages"].pop(page)
    return result


def bind_document(document, scene):
    result = compile_identities(document)
    catalog = catalog_from(result)
    migrated = migrate_scene(scene or {}, catalog)
    # Replay only via the store owner's existing pure reducers.
    from ai_inspector.parts_manual.documentation import replay_documentation_commands
    from .provenance import replay_field_meta
    if scene and "commands" in scene:
        active = migrated.get("commands", [])[:migrated.get("historyCursor", 0)]
        migrated["pages"] = replay_documentation_commands(active)
        migrated["fieldMeta"] = replay_field_meta(active)
    view = project_scene(result, migrated)
    # This is an address projection only. Each compiler applies the returned
    # scene through its own composition/legacy-value rules.
    sync_identity_overrides(result, view.get("pages", {}))
    if migrated.get("legacySceneRevision"):
        result["legacyDocumentationSceneRevision"] = migrated["legacySceneRevision"]
    result["identityOrphans"] = deepcopy(migrated.get("orphans", []))
    return result, view


def sync_identity_overrides(document, compositions=None):
    """Index the owner-applied overrides without changing its composition."""
    for page in document.get("pages", []):
        composition = (compositions.get(page["pageId"], {}) if compositions is not None
                       else page.get("documentationComposition", {}))
        overrides = composition.get("pageElementOverrides", {})
        page["identityOverrides"] = {entry["targetId"]: deepcopy(overrides[alias])
            for alias, entry in document.get("aliasMap", {}).get(page["pageId"], {}).items()
            if entry.get("safe") and alias in overrides}


def normalize_command(scene, command, page_targets):
    """Called under the owner lock, after its exact revision/hash checks."""
    result, targets = deepcopy(command), deepcopy(page_targets)
    original_page = str(result.get("pageId") or "")
    if result.get("operation") == "reset_page":
        result["identityResetTargets"] = [entry["targetId"] for entry in
            scene.get("identityAliases", {}).get(original_page, {}).values() if entry.get("safe")]
    if result.get("operation") == "arrange":
        for target in result.get("transforms", []):
            if target.get("targetType") == "page_element":
                converted, targets = normalize_command(scene, {**target, "pageId": original_page}, targets)
                if converted["pageId"] != original_page:
                    raise DocumentEditError("stale_revision", "Arrange this relocated object after a new layout binding.")
                target["targetId"] = converted["targetId"]
    if result.get("targetType") == "page_element":
        alias = result.get("targetId", "")
        entry = scene.get("identityAliases", {}).get(original_page, {}).get(alias)
        if not entry and _POSITIONAL.search(alias):
            raise DocumentEditError("ambiguous_legacy_target", "Read this alias with its compiler baseline before editing.", targetId=alias)
        if entry:
            if not entry.get("safe"):
                raise DocumentEditError("ambiguous_legacy_target", "This source has no unique identity.", targetId=alias)
            result["targetId"] = entry["targetId"]
        stable = result.get("targetId", "")
        if stable.startswith(("gen-", "slot:")):
            if scene.get("identities", {}).get(stable, {}).get("state") == "unresolved":
                raise DocumentEditError("ambiguous_legacy_target", "This source has no unique identity.", targetId=stable)
            known = targets.get(original_page, {}).get("page_element", [])
            allowed = stable in known or any(info["targetId"] == stable and info.get("safe") and key in known
                for key, info in scene.get("identityAliases", {}).get(original_page, {}).items())
            if not allowed:
                raise DocumentEditError("target_not_found", "The target does not belong to this read page.", targetId=stable)
            storage = scene.get("identities", {}).get(stable, {}).get("storagePage", original_page)
            result["pageId"] = storage
            targets.setdefault(storage, {}).setdefault("page_element", []).append(stable)
            rich = targets.get(original_page, {}).get("richTextTargets", {}).get(stable) or targets.get(original_page, {}).get("richTextTargets", {}).get(alias)
            if rich:
                targets[storage].setdefault("richTextTargets", {})[stable] = rich
            for meta in result.get("fieldMeta", {}).values():
                meta["pageId"] = storage
    return result, targets


def editable_targets(document, targets):
    result = deepcopy(targets)
    from .targets import rich_block_capabilities
    for page in document.get("pages", []):
        rich = result.setdefault(page["pageId"], {}).setdefault("richTextTargets", {})
        for block in page.get("layoutBlocks", []):
            if rich_block_capabilities(document.get("documentType"), block.get("blockType")):
                descriptor = {"documentType": document["documentType"], "attributes": {"blockType": block["blockType"]}}
                alias = block["blockId"]
                rich[alias] = descriptor
                entry = document.get("aliasMap", {}).get(page["pageId"], {}).get(alias)
                if entry and entry.get("safe"):
                    rich[entry["targetId"]] = descriptor
    for page, entries in document.get("aliasMap", {}).items():
        unresolved = {entry["targetId"] for entry in entries.values() if not entry.get("safe")}
        known = [key for key in result.get(page, {}).get("page_element", [])
                 if key not in unresolved and (key not in entries or entries[key].get("safe"))]
        additions = [item["targetId"] for alias, item in entries.items() if alias in known and item.get("safe")]
        if page in result:
            result[page]["page_element"] = list(dict.fromkeys([*known, *additions]))
    return result


def check_alias_binding(observed, current):
    if any(op.get("legacyAlias") for op in observed.get("operations", [])) and observed.get("aliasRevision") != current.get("aliasRevision"):
        raise DocumentEditError("ambiguous_legacy_target", "The positional alias belongs to an older layout; read again.")
