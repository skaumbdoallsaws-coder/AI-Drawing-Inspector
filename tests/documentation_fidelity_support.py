"""Exact legacy comparison with the explicitly approved P4b-3 additions only."""
from collections import Counter
from copy import deepcopy

import fitz
from lxml import etree


def _characters(page):
    return Counter((c[0], tuple(c[2]), tuple(c[3]), span["font"], span["size"], tuple(span["color"]) if isinstance(span["color"], tuple) else span["color"])
                   for span in page.get_texttrace() for c in span["chars"] if not chr(c[0]).isspace())


def assert_pdf_fidelity_delta(previous, current, document):
    """Existing glyphs retain exact positions/font/size/color; rules, images and links retain geometry."""
    with fitz.open(stream=previous, filetype="pdf") as old, fitz.open(stream=current, filetype="pdf") as new:
        assert len(old) == len(new) == len(document["pages"])
        for index, (a, b, descriptor) in enumerate(zip(old, new, document["pages"])):
            assert a.rect == b.rect
            before, after = _characters(a), _characters(b)
            assert not before - after, (index, "existing glyph moved or disappeared", before - after)
            additions = ""
            kind, page_type = document["documentType"], descriptor.get("pageType")
            if kind in {"operations_and_maintenance_manual", "work_instructions"} and page_type != "operations_cover":
                additions = (f"{document.get('product', {}).get('name') or 'Product'} | "
                             f"{document.get('documentNumber') or 'Document number not specified'} | "
                             f"{document.get('statusLabel') or 'DRAFT'}")
                assert b.search_for(additions), (index, additions)
            if kind == "illustrated_parts_manual":
                additions = {"document_information": "DOCUMENT CONTROL", "table_of_contents": "TABLE OF CONTENTS",
                             "parts_index": "PART NUMBER INDEX" + (" (CONTINUED)" if descriptor.get("continuedFrom") else "")}.get(page_type, "")
                if page_type == "cover":
                    control = descriptor.get("documentControl") or {}
                    additions = (f"Assembly Number: {document.get('product', {}).get('assemblyNumber') or 'Not specified'} "
                                 f"Document Number: {control.get('documentNumber')}")
                    if control.get("revision"):
                        additions += f" Revision: {control['revision']}"
                    if control.get("releaseDate"):
                        additions += f" Release Date: {control['releaseDate']}"
                if additions:
                    assert all(b.search_for(word) for word in additions.split()), (index, additions)
            actual = Counter()
            for char, count in (after - before).items():
                expected_size = 6.6 if kind in {"operations_and_maintenance_manual", "work_instructions"} else (9.2 if page_type == "cover" else 18)
                assert abs(char[4] - expected_size) < .001, (index, "added text size", char)
                actual[chr(char[0])] += count
            assert actual == Counter(c for c in additions if not c.isspace()), (index, actual, additions)
            # seqno is paint sequence, shifted by the additional text; all drawing properties stay.
            clean = lambda page: [{k: v for k, v in d.items() if k != "seqno"} for d in page.get_drawings()]
            assert clean(a) == clean(b), index
            images = lambda p: [{k: v for k, v in image.items() if k != "number"} for image in p.get_image_info()]
            assert images(a) == images(b), index
            links = lambda page: [{k: v for k, v in d.items() if k not in {"xref", "id"}} for d in page.get_links()]
            assert links(a) == links(b), index


def assert_docx_fidelity_delta(previous, current, document):
    """Only the body clearance below the operations/WI header band changes in native OOXML."""
    old, new = deepcopy(previous), deepcopy(current)
    assert old.keys() == new.keys()
    if document["documentType"] in {"operations_and_maintenance_manual", "work_instructions"}:
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        margins = new["word/document.xml"].xpath("//w:sectPr/w:pgMar", namespaces=ns)
        previous_margins = old["word/document.xml"].xpath("//w:sectPr/w:pgMar", namespaces=ns)
        band = document.get("publicationLayout", {}).get("shared", {}).get("header", {"y": 0, "height": 56})
        expected = round((band["y"] + band["height"] + 12) * 20)
        for a, b in zip(previous_margins, margins):
            key = "{" + ns["w"] + "}top"
            assert int(b.get(key)) == expected
            b.set(key, a.get(key))
    for name in new:
        assert etree.tostring(new[name]) == etree.tostring(old[name]), name
