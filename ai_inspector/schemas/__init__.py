"""Schemas and packet management for the YOLO-OBB pipeline."""

from ..contracts import CalloutPacket, ReaderResult
from .callout_packet import (
    create_packet,
    create_packets,
    attach_crop,
    attach_rotation,
    attach_reader,
    attach_normalization,
    attach_validation,
    attach_match,
    packet_to_dict,
    packets_to_dicts,
    save_packets,
    load_packets_json,
    summarize_packets,
)
from .callout_schema import (
    REQUIRED_FIELDS,
    VALID_CALLOUT_TYPES,
    POSITIVE_NUMERIC_FIELDS,
    ANGLE_FIELDS,
    QUANTITY_FIELDS,
    get_required_fields,
    is_valid_callout_type,
)

__all__ = [
    "CalloutPacket",
    "ReaderResult",
    "create_packet",
    "create_packets",
    "attach_crop",
    "attach_rotation",
    "attach_reader",
    "attach_normalization",
    "attach_validation",
    "attach_match",
    "packet_to_dict",
    "packets_to_dicts",
    "save_packets",
    "load_packets_json",
    "summarize_packets",
    "REQUIRED_FIELDS",
    "VALID_CALLOUT_TYPES",
    "POSITIVE_NUMERIC_FIELDS",
    "ANGLE_FIELDS",
    "QUANTITY_FIELDS",
    "get_required_fields",
    "is_valid_callout_type",
]
