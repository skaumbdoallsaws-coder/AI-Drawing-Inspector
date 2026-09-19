"""Document types hosted by the shared Documentation workspace.

The registry keeps product semantics out of the editor shell.  Each document
type supplies its own compiler and release policy while reusing the same page
rail, canvas, scene commands, themes, and undo history.
"""

from __future__ import annotations

import copy
from typing import Any, Dict


class DocumentTypeNotFoundError(KeyError):
    pass


DOCUMENT_TYPE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "illustrated_parts_manual": {
        "documentType": "illustrated_parts_manual",
        "workspace": "documentation",
        "label": "Illustrated Parts Manual",
        "shortLabel": "Parts Manual",
        "status": "available",
        "pageOrientation": "landscape",
        "generationAction": "AI Arrange",
        "supports": {
            "cadFigures": True,
            "flowingText": False,
            "bom": True,
            "controlledPdf": True,
            "docx": False,
        },
    },
    "operations_and_maintenance_manual": {
        "documentType": "operations_and_maintenance_manual",
        "workspace": "documentation",
        "label": "Operations and Maintenance Manual",
        "shortLabel": "Operations Manual",
        "status": "review_available",
        "pageOrientation": "landscape",
        "generationAction": "Generate Manual",
        "supports": {
            "cadFigures": True,
            "flowingText": True,
            "bom": False,
            "controlledPdf": False,
            "reviewPdf": True,
            "docx": True,
            "reviewDocx": True,
        },
        "releaseNotice": (
            "Review PDF and editable DOCX exports are enabled. Controlled release "
            "remains pending until the recorded approval prerequisites are complete."
        ),
    },
    "product_specification_sheet": {
        "documentType": "product_specification_sheet",
        "workspace": "documentation",
        "label": "Product Specification Sheet",
        "shortLabel": "Specification Sheet",
        "status": "review_available",
        "pageOrientation": "portrait",
        "generationAction": "Generate Sheet",
        "supports": {
            "cadFigures": True,
            "flowingText": False,
            "bom": False,
            "controlledPdf": False,
            "reviewPdf": True,
            "docx": True,
            "reviewDocx": True,
        },
        "releaseNotice": (
            "Review PDF and editable DOCX exports are enabled. Controlled release "
            "requires the recorded product-data approval."
        ),
    },
    "work_instructions": {
        "documentType": "work_instructions",
        "workspace": "documentation",
        "label": "Assembly Work Instructions",
        "shortLabel": "Work Instructions",
        "status": "review_available",
        "pageOrientation": "landscape",
        "generationAction": "Generate Instructions",
        "supports": {
            "cadFigures": True,
            "flowingText": True,
            "bom": False,
            "controlledPdf": False,
            "reviewPdf": True,
            "docx": True,
            "reviewDocx": True,
        },
        "releaseNotice": (
            "Prototype review PDF and editable DOCX exports are enabled from the "
            "assumed process baseline. Controlled manufacturing release remains blocked."
        ),
    },
    "inspection_sheet": {
        "documentType": "inspection_sheet",
        "workspace": "documentation",
        "label": "Inspection Sheet",
        "shortLabel": "Inspection Sheet",
        "status": "planned",
        "pageOrientation": "portrait",
        "generationAction": "Generate Draft",
        "supports": {
            "cadFigures": True,
            "flowingText": False,
            "bom": False,
            "controlledPdf": False,
            "docx": False,
        },
    },
}


def document_type_definition(document_type: str) -> Dict[str, Any]:
    key = str(document_type or "").strip()
    definition = DOCUMENT_TYPE_REGISTRY.get(key)
    if definition is None:
        raise DocumentTypeNotFoundError(key)
    return copy.deepcopy(definition)


def document_type_summaries() -> list[Dict[str, Any]]:
    return [copy.deepcopy(value) for value in DOCUMENT_TYPE_REGISTRY.values()]
