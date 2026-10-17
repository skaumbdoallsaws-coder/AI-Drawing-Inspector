"""Bounded, revision-bound reads of the curated equipment document collection.

This is evidence retrieval, not specification ingestion or setup approval. Only
registered files are readable; document text never supplies tool authority.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from .web import ResearchError


INDEX_PATH = Path(__file__).with_name("equipment_document_index.json")
MAX_FILE_BYTES = 32 * 1024 * 1024
SEARCH_PAGES = 40
PAGE_CHARS = 6000
NAVIGATION_LINKS = 32
QUALIFICATION = {
    "authority": "supporting", "reviewStatus": "pending", "productionEligible": False,
    "executableConstraints": False,
    "qualification": "Model-scoped reference material, not installed-configuration, fit, safety or production approval. "
                     "Family tables require explicit model-column and condition checks; plain text loses table/figure structure.",
}


def _fail(code, message, **details):
    raise ResearchError(code, message, details=details)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _section(text, heading):
    sections = re.split(r"(?m)^## ", text)
    matches = [part.split("\n", 1)[1].strip() for part in sections[1:]
               if part.split("\n", 1)[0] == heading and "\n" in part]
    if len(matches) != 1:
        _fail("equipment_summary_section_invalid", "The registered summary section is missing or ambiguous.")
    return matches[0]


def _page_navigation(page, page_count, limit):
    # Keep PDF-authored local destinations separate from printed page numbers.
    # URI, launch and other-file links are never followed or returned here.
    links = [link for link in page.get_links() if link.get("kind") in {1, 4}
             and type(link.get("page")) is int and 0 <= link["page"] < page_count
             and not link.get("file") and not link.get("uri")]
    words = page.get_text("words") if links and limit else []
    navigation = []
    for link in links[:limit]:
        rect = link["from"]
        anchor = " ".join(word[4] for word in words
                          if rect.x0 <= (word[0] + word[2]) / 2 <= rect.x1
                          and rect.y0 <= (word[1] + word[3]) / 2 <= rect.y1)
        navigation.append({"anchorText": anchor[:80], "targetPageNumber": link["page"] + 1})
    return navigation, len(links) > limit


class EquipmentDocumentLibrary:
    def __init__(self, root=None, index_path=None):
        self.root = (Path(root) if root else Path(__file__).resolve().parents[2]).resolve()
        self.index_path = Path(index_path) if index_path else INDEX_PATH

    def _path(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or Path(relative).is_absolute():
            _fail("equipment_document_path_invalid", "Registered document must remain inside the project.")
        return path

    @staticmethod
    def _bytes(path, maximum=MAX_FILE_BYTES):
        try:
            with path.open("rb") as handle:
                data = handle.read(maximum + 1)
        except OSError as exc:
            raise ResearchError("equipment_document_unavailable", "Registered local document is unavailable.") from exc
        if len(data) > maximum:
            _fail("equipment_document_budget_exceeded", "Registered document exceeds the reader byte limit.")
        return data

    def _checked(self, relative, expected, *, text=False, maximum=MAX_FILE_BYTES):
        data = self._bytes(self._path(relative), maximum)
        if text:
            data = data.replace(b"\r\n", b"\n")
        if _sha(data) != expected:
            _fail("equipment_document_revision_mismatch", "Document content changed; its binding must be reviewed before reuse.")
        return data

    def _index(self):
        try:
            index = json.loads(self._bytes(self.index_path, 128 * 1024))
        except (ValueError, TypeError) as exc:
            raise ResearchError("equipment_document_index_invalid", "Equipment document index is invalid.") from exc
        if (index.get("schemaVersion") != "equipment-document-index-v1" or not isinstance(index.get("bindings"), list)
                or len(index["bindings"]) > 500):
            _fail("equipment_document_index_invalid", "Unsupported equipment document index.")
        return index

    def availability(self, asset):
        matches = [entry for entry in self._index()["bindings"] if entry["assetId"] == asset["assetId"]]
        if len(matches) != 1:
            return {"status": "unregistered"}
        entry = matches[0]
        return {"status": "registered" if entry["assetDefinitionRevision"] == asset["assetDefinitionRevision"] else "stale_binding",
                "model": entry["model"], "documentCount": len(entry["documents"]),
                "qualification": "Reference registration only; read verifies document availability and content."}

    def _binding(self, asset_id, asset_revision):
        index = self._index()
        matches = [entry for entry in index["bindings"] if entry["assetId"] == asset_id]
        if len(matches) != 1:
            _fail("equipment_documents_unregistered", "No local document binding exists for this equipment. Do not borrow another model's summary.")
        entry = matches[0]
        if entry["assetDefinitionRevision"] != asset_revision:
            _fail("equipment_document_asset_stale", "Catalog revision differs from the document binding; review the association first.")
        summary = self._checked(index["summaryPath"], index["summarySha256"], text=True, maximum=128 * 1024).decode("utf-8")
        hazards = [line for line in summary.splitlines() if any(line.startswith("| " + key + " |") for key in entry["hazardIds"])]
        if len(hazards) != len(entry["hazardIds"]):
            _fail("equipment_document_index_invalid", "A registered source hazard is missing.")
        try:
            verification = json.loads(self._checked(index["verificationPath"], index["verificationSha256"], maximum=128 * 1024))
            documents = []
            for name in entry["documents"]:
                rows = [row for row in verification["documents"] if row["file"] == name]
                if len(rows) != 1 or not rows[0].get("sha256") or not rows[0].get("pages"):
                    _fail("equipment_document_index_invalid", "Document lacks an exact verified PDF reference.")
                documents.append(rows[0])
        except (ValueError, KeyError, TypeError) as exc:
            raise ResearchError("equipment_document_index_invalid", "Document verification manifest is invalid.") from exc
        return index, entry, summary, hazards, documents

    def read(self, arguments):
        if not isinstance(arguments, dict):
            _fail("equipment_document_request_invalid", "Expected an explicit document read object.")
        action = arguments.get("action")
        fields = {"action", "assetId", "assetDefinitionRevision"}
        if action in {"search", "page"}:
            fields |= {"documentId", "documentRevision"}
            fields |= {"query", "startPage"} if action == "search" else {"pageNumber", "textOffset"}
        if action not in {"summary", "search", "page"} or set(arguments) != fields:
            _fail("equipment_document_request_invalid", "Use summary, search or page with its explicit fields.")
        index, entry, summary, hazards, documents = self._binding(arguments["assetId"], arguments["assetDefinitionRevision"])
        result = {**QUALIFICATION, "action": action, "assetId": entry["assetId"],
                  "assetDefinitionRevision": entry["assetDefinitionRevision"], "model": entry["model"],
                  "bindingRevision": _sha(json.dumps(index, sort_keys=True, separators=(",", ":")).encode()),
                  "summaryRevision": index["summarySha256"], "applicability": entry["applicability"], "sourceHazards": hazards}
        if action == "summary":
            return {**result, "summary": _section(summary, entry["summaryHeading"]), "basis": _section(summary, "Basis"),
                    "summaryLocator": {"path": index["summaryPath"], "heading": entry["summaryHeading"]},
                    "documents": [{"documentId": doc["file"], "documentRevision": doc["sha256"],
                                   "pageCount": doc["pages"], "url": doc["url"], "sourceDescription": doc["type"]}
                                  for doc in documents], "complete": True}
        matches = [doc for doc in documents if doc["file"] == arguments["documentId"]]
        if len(matches) != 1:
            _fail("equipment_document_model_mismatch", "Document is not registered for the selected equipment model.")
        doc = matches[0]
        if arguments["documentRevision"] != doc["sha256"]:
            _fail("equipment_document_revision_mismatch", "The supplied reference does not match the registered document. "
                  "Correct a copying error using this exact reference; do not silently replace a requested edition.",
                  failureKind="reference_mismatch", registeredReference={"documentId": doc["file"], "documentRevision": doc["sha256"]})
        relative = str(Path(index["verificationPath"]).parent / doc["file"])
        data = self._checked(relative, doc["sha256"])
        result.update(documentId=doc["file"], documentRevision=doc["sha256"], url=doc["url"],
                      sourceDescription=doc["type"], pageCount=doc["pages"], pageNumbering="one_based_pdf_file_pages")
        try:
            import fitz
            with fitz.open(stream=data, filetype="pdf") as pdf:
                if pdf.is_encrypted or len(pdf) != doc["pages"] or len(pdf) > 800:
                    _fail("equipment_document_format_unsupported", "Encrypted, oversized or changed PDF pagination.")
                if action == "page":
                    number, offset = arguments["pageNumber"], arguments["textOffset"]
                    if type(number) is not int or not 1 <= number <= len(pdf) or type(offset) is not int or offset < 0:
                        _fail("equipment_document_page_invalid", "Select a one-based page and nonnegative text offset.")
                    text = pdf[number - 1].get_text(sort=True)
                    if offset > len(text):
                        _fail("equipment_document_page_invalid", "Text offset exceeds the selected page.")
                    end = min(len(text), offset + PAGE_CHARS)
                    navigation, navigation_truncated = _page_navigation(pdf[number - 1], len(pdf), NAVIGATION_LINKS)
                    return {**result, "pageNumber": number, "textOffset": offset, "text": text[offset:end],
                            "nextTextOffset": end if end < len(text) else None, "truncated": offset > 0 or end < len(text),
                            "internalPageLinks": navigation, "navigationTruncated": navigation_truncated,
                            "needsVisualReview": True, "textStatus": "extracted" if text.strip() else "no_extractable_text",
                            "complete": bool(text.strip()) and offset == 0 and end == len(text)}
                query, start = arguments["query"], arguments["startPage"]
                if (not isinstance(query, str) or not query.strip() or len(query) > 160
                        or type(start) is not int or not 1 <= start <= len(pdf)):
                    _fail("equipment_document_search_invalid", "Use a literal query up to 160 characters and a one-based startPage.")
                hits, no_text, end = [], [], start - 1
                navigation_remaining = NAVIGATION_LINKS
                for number in range(start, min(len(pdf), start + SEARCH_PAGES - 1) + 1):
                    text = " ".join(pdf[number - 1].get_text(sort=True).split())
                    end = number
                    if not text:
                        no_text.append(number)
                    match = re.search(re.escape(" ".join(query.split())), text, re.IGNORECASE)
                    if match:
                        left = max(0, match.start() - 180)
                        navigation, navigation_truncated = _page_navigation(pdf[number - 1], len(pdf), navigation_remaining)
                        navigation_remaining -= len(navigation)
                        hits.append({"pageNumber": number, "excerpt": text[left:left + 600],
                                     "internalPageLinks": navigation, "navigationTruncated": navigation_truncated})
                    if len(hits) == 6:
                        break
                return {**result, "query": query, "matches": hits, "searchedPages": {"first": start, "last": end},
                        "pagesWithoutText": no_text, "nextPage": end + 1 if end < len(pdf) else None,
                        "searchGuidance": "Literal phrase search: punctuation must match. Broaden an empty result to a short distinctive term. "
                                          "Printed page numbers may differ from PDF file pages. internalPageLinks are PDF-authored navigation "
                                          "from the matching page, not claims that the destination answers the query; read the target page to check.",
                        "searchComplete": start == 1 and end == len(pdf) and not no_text,
                        "qualification": QUALIFICATION["qualification"] + " Literal text search is not a semantic or visual absence check."}
        except ResearchError:
            raise
        except (ImportError, RuntimeError, ValueError) as exc:
            raise ResearchError("equipment_document_extraction_failed", "PDF text extraction failed; no engineering fact was admitted.") from exc

    def validate_result(self, result):
        index, _, _, _, documents = self._binding(result["assetId"], result["assetDefinitionRevision"])
        binding_revision = _sha(json.dumps(index, sort_keys=True, separators=(",", ":")).encode())
        if result["bindingRevision"] != binding_revision or result["summaryRevision"] != index["summarySha256"]:
            _fail("equipment_document_revision_mismatch", "The retained document binding has changed.")
        if result["action"] != "summary":
            matches = [doc for doc in documents if doc["file"] == result["documentId"] and doc["sha256"] == result["documentRevision"]]
            if len(matches) != 1:
                _fail("equipment_document_revision_mismatch", "The retained source document has changed.")
            self._checked(str(Path(index["verificationPath"]).parent / matches[0]["file"]), matches[0]["sha256"])
