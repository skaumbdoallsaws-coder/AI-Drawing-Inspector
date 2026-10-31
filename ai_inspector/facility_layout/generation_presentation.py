"""Presentation of server-observed research receipts, never model-authored sources."""
from collections.abc import Mapping
import hashlib

from ai_inspector.chat_content import normalize_chat_content_block
from ai_inspector.research.web import public_url, ResearchError
from .generation_exploration import READ_TOOL, DOCUMENT_TOOL


def generation_preview_summary(receipt):
    """Completion is derived from the validated artifact, not another model call."""
    if receipt.get("validationStatus") != "prototype_geometry_valid":
        raise ValueError("A validated preview receipt is required")
    counts = receipt["counts"]
    placements = counts.get("placements", 0)
    cells = receipt.get("compositionInventory", {}).get("cellCount", 0)
    inventory = f"{placements} {'item' if placements == 1 else 'items'}"
    if cells:
        inventory = f"{cells} {'cell' if cells == 1 else 'cells'}, {inventory} in total"
    lines = [f"Here's the draft: {inventory}. Nothing has been applied or saved."]
    notes = receipt.get("planningNotes", {})
    unknowns = len(notes.get("unknowns", []))
    if unknowns:
        lines.append(f"{unknowns} {'detail still needs' if unknowns == 1 else 'details still need'} "
                     f"confirming; {'it is' if unknowns == 1 else 'they are'} listed in Planning.")
    elif notes.get("assumptions") or notes.get("historicalAssumptions"):
        lines.append("The assumptions are listed in Planning.")
    return "\n\n".join(lines)


def _equipment_sources(result):
    if result.get("action") == "summary":
        documents = result.get("documents", [])
        retrieval = "Capability summary read; underlying manual not opened"
    elif result.get("action") == "page":
        documents = [result]
        retrieval = "Archived PDF page " + str(result.get("pageNumber"))
        if result.get("textStatus") == "no_extractable_text":
            retrieval += "; no extractable text"
    else:
        return []
    sources = []
    for doc in documents:
        try:
            url = public_url(doc.get("url"))
        except ResearchError:
            continue
        revision = doc.get("documentRevision", "")
        identity = "|".join((result.get("assetId", ""), result.get("assetDefinitionRevision", ""), url, revision))
        sources.append({"id": "equipment-" + hashlib.sha256(identity.encode()).hexdigest(),
            "url": url, "title": doc.get("documentId") or result.get("model", "Equipment reference"),
            "description": result.get("applicability", ""), "sourceType": "technical-document", "publisher": "", "inferIdentity": False,
            "specifications": {"Retrieval": retrieval + ("; truncated" if result.get("truncated") else ""),
                "Scope": result.get("model", "") + "; archive " + revision[:12],
                "Review": "Applicability pending; not an approved engineering limit",
                "Link": "Original source URL; linked content may differ from retained archive",
                "Model": result.get("model", ""), "Document SHA-256": revision, "Authority": "Supporting",
                "Use": "Not an approved engineering limit",
                "Extract": "Truncated" if result.get("truncated") else "Bounded local evidence"}})
    return sources


def generation_research_source_block(results):
    sources = {}
    for entry in results:
        # Only sources that were read are listed: a search only discovers candidates, most of them unrelated hits,
        # and no value may come from a search result.
        if not isinstance(entry, Mapping) or entry.get("tool") not in {READ_TOOL, DOCUMENT_TOOL} or entry.get("status") != "succeeded":
            continue
        result = entry.get("result")
        if not isinstance(result, Mapping):
            continue
        if entry["tool"] == DOCUMENT_TOOL:
            for source in _equipment_sources(result):
                key = source["id"]
                # An actual archived-page read supersedes summary-only presentation.
                if key not in sources or result.get("action") == "page":
                    sources[key] = source
            continue
        citations = result.get("citations", [])
        citations = citations if isinstance(citations, list) else []
        retained_sources = result.get("sources", [])
        if not isinstance(retained_sources, list):
            continue
        for source in retained_sources:
            if not isinstance(source, Mapping):
                continue
            try:
                url = public_url(source.get("url"))
            except ResearchError:
                continue
            fetched = (entry["tool"] == READ_TOOL and result.get("complete") is True
                       and result.get("requestedUrl") == url and source.get("retrieval") == "fetched_document")
            prior = sources.get(url)
            if prior and (prior["sourceType"] == "technical-document" or not fetched):
                continue
            citation = next((item for item in citations if isinstance(item, Mapping) and item.get("url") == url), {})
            sources[url] = {
                "id": "research-" + hashlib.sha256(url.encode("utf-8")).hexdigest(),
                "title": source.get("title") or url, "url": url,
                "retrievedAt": result.get("retrievedAt"), "description": citation.get("text", ""),
                "sourceType": "technical-document" if fetched else "web",
                "publisher": "", "inferIdentity": False,
                "specifications": {"Retrieval": "Document read" if fetched else "Read not confirmed",
                    "Extract": "Truncated" if result.get("truncated") else "Bounded provider result",
                    "Authority": "Supporting", "Review": "Pending", "Use": "Not production approval"},
            }
    if not sources:
        return None
    title = "Research sources (unreviewed)" if len(sources) <= 20 else "Research sources (unreviewed; first 20)"
    return normalize_chat_content_block({"type": "sources", "title": title, "sources": list(sources.values())[:20]})
