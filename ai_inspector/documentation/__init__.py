"""Shared technical-document workspace contracts."""

from .registry import (
    DOCUMENT_TYPE_REGISTRY,
    DocumentTypeNotFoundError,
    document_type_definition,
    document_type_summaries,
)

__all__ = [
    "DOCUMENT_TYPE_REGISTRY",
    "DocumentTypeNotFoundError",
    "document_type_definition",
    "document_type_summaries",
]
