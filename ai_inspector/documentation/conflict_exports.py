"""Read-only conflict projection and visible review-export notices."""
from copy import deepcopy

from .refresh import exposure, open_conflicts

CONFLICT_MARKER = "Open manual edit conflict"


def project_review(document, *states, owned=False):
    reviews = [exposure(state or {}) for state in states]
    conflicts = {c.get("conflictId", c["targetId"]): c for review in reviews for c in open_conflicts(review)}
    orphans = {o["orphanId"]: o for review in reviews for o in review["orphans"]}
    if not conflicts and not orphans:
        return document
    result = document if owned else deepcopy(document)
    result.update(conflicts=list(conflicts.values()), orphans=list(orphans.values()), openConflictCount=len(conflicts))
    def mark(owner, keys):
        matches = [c for c in conflicts.values() if c["targetId"] in keys]
        if matches:
            owner["manualConflicts"] = [{"conflictId": c.get("conflictId"), "targetId": c["targetId"],
                                         "alias": c.get("alias")} for c in matches]
    for slot, value in result.get("slots", {}).items():
        mark(value, {"slot:" + slot})
    for page in result.get("pages", []):
        aliases = result.get("aliasMap", {}).get(page["pageId"], {})
        def stable(alias):
            return (aliases.get(alias) or {}).get("targetId", alias)
        for block in page.get("layoutBlocks", []):
            bid = block.get("blockId", "")
            keys = {block.get("stableId"), stable(bid)}
            keys.update("slot:" + slot for slot in (block.get("slots") or {}).values())
            if block.get("slot"):
                keys.add("slot:" + block["slot"])
            mark(block, keys)
            for index, row in enumerate(block.get("rows", [])):
                keys = set(row.get("cellIds") or []) | {row.get("rowId")}
                keys.update(stable(bid + ".r" + str(index) + ".c" + str(i)) for i in range(len(row.get("cells", []))))
                keys.update("slot:" + slot for slot in row.get("slots") or [] if isinstance(slot, str))
                mark(row, keys)
            for index, item in enumerate(block.get("items", [])):
                mark(item, {item.get("itemId"), stable(bid + ".i" + str(index))})
        for row in page.get("bom", []):
            from ai_inspector.parts_manual.document import part_text_target_id
            if row.get("definitionId"):
                mark(row, {part_text_target_id(row["definitionId"], field) for field in ("description", "partNumber")})
    return result


def marker(owner, fallback=""):
    items = owner.get("manualConflicts") or []
    return (CONFLICT_MARKER + ": " + ", ".join(str(c.get("conflictId") or c["targetId"]) for c in items)) if items else fallback


def summary(document):
    count, orphan_count = len(open_conflicts(document)), len(document.get("orphans") or [])
    return "Open manual edit conflicts: " + str(count) + "; unplaced manual content: " + str(orphan_count) if count or orphan_count else ""


def mark_pdf(pdf, document):
    notice = summary(document)
    if not notice or document.get("exportMode", "review") not in {"draft", "review"}:
        return
    # The footer is separate from body layout. Stable IDs, never text matching,
    # connect each page notice to the exact target and its review entry.
    for index, descriptor in enumerate(document.get("pages", [])):
        page = pdf[index]
        page.insert_text((8, page.rect.height - 4), notice, fontsize=5, color=(0.6, 0.22, 0.02))
        conflicts = [c for c in open_conflicts(document) if c.get("pageId") == descriptor["pageId"]]
        for row, conflict in enumerate(conflicts):
            label = CONFLICT_MARKER + " " + str(conflict.get("conflictId") or "") + ": " + str(conflict.get("alias") or conflict["targetId"])
            page.insert_text((8, 8 + row * 6), label, fontsize=4.5, color=(0.6, 0.22, 0.02))


def mark_docx(output, document):
    notice = summary(document)
    if notice and document.get("exportMode", "review") in {"draft", "review"}:
        output.add_paragraph(notice)
        for conflict in open_conflicts(document):
            output.add_paragraph(CONFLICT_MARKER + " " + str(conflict.get("conflictId") or "") + ": "
                                 + str(conflict.get("alias") or conflict["targetId"]))
