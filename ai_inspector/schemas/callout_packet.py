"""CalloutPacket builder and serialization for pipeline provenance tracking.

Every detection becomes a packet that accumulates data through each pipeline stage:
  detection -> crop -> rotation/OCR -> parse -> normalize -> validate -> match

This provides a "debug superpower" -- you can answer "why did this callout become
Unknown/Extra?" by inspecting the packet's provenance chain.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..contracts import (
    CalloutPacket,
    CropResult,
    DetectionResult,
    OCRResult,
    ReaderResult,
    RotationResult,
)


def create_packet(detection: DetectionResult) -> CalloutPacket:
    """
    Create a new CalloutPacket from a detection result.

    Args:
        detection: YOLO detection result

    Returns:
        New CalloutPacket with detection info populated
    """
    return CalloutPacket(
        det_id=detection.det_id,
        detection=detection,
    )


def create_packets(detections: List[DetectionResult]) -> List[CalloutPacket]:
    """Create packets for a list of detections."""
    return [create_packet(d) for d in detections]


def attach_crop(packet: CalloutPacket, crop: CropResult) -> CalloutPacket:
    """Attach crop result to a packet."""
    packet.crop = crop
    return packet


def attach_rotation(packet: CalloutPacket, rotation: RotationResult) -> CalloutPacket:
    """Attach rotation/OCR result to a packet."""
    packet.rotation = rotation
    return packet


def attach_reader(packet: CalloutPacket, reader: ReaderResult) -> CalloutPacket:
    """Attach parsed reader result to a packet."""
    packet.reader = reader
    return packet


def attach_normalization(packet: CalloutPacket, normalized: Dict[str, Any]) -> CalloutPacket:
    """Attach unit-normalized data to a packet."""
    packet.normalized = normalized
    return packet


def attach_validation(
    packet: CalloutPacket,
    validated: bool,
    error: Optional[str] = None,
) -> CalloutPacket:
    """Attach validation result to a packet."""
    packet.validated = validated
    packet.validation_error = error
    return packet


def attach_match(
    packet: CalloutPacket,
    matched: bool,
    status: Optional[str] = None,
) -> CalloutPacket:
    """Attach match result to a packet."""
    packet.matched = matched
    packet.match_status = status
    return packet


def packet_to_dict(packet: CalloutPacket) -> Dict[str, Any]:
    """
    Serialize a CalloutPacket to a JSON-safe dictionary.

    Handles:
    - Converts dataclasses to dicts
    - Removes PIL Image objects (not JSON serializable)
    - Preserves all provenance metadata

    Returns:
        JSON-serializable dict
    """
    d: Dict[str, Any] = {"det_id": packet.det_id}

    # Detection
    if packet.detection:
        d["detection"] = {
            "class_name": packet.detection.class_name,
            "confidence": packet.detection.confidence,
            "obb_points": packet.detection.obb_points,
            "xywhr": packet.detection.xywhr,
            "det_id": packet.detection.det_id,
        }

    # Crop (exclude PIL Image)
    if packet.crop:
        d["crop"] = {
            "meta": packet.crop.meta,
            # image excluded -- not serializable
        }

    # Rotation
    if packet.rotation:
        rot: Dict[str, Any] = {
            "raw": packet.rotation.raw,
            "rotation_used": packet.rotation.rotation_used,
            "quality_score": packet.rotation.quality_score,
        }
        if packet.rotation.ocr_result:
            rot["ocr"] = {
                "text": packet.rotation.ocr_result.text,
                "confidence": packet.rotation.ocr_result.confidence,
                "meta": packet.rotation.ocr_result.meta,
            }
        d["rotation"] = rot

    # Reader
    if packet.reader:
        d["reader"] = {
            "callout_type": packet.reader.callout_type,
            "raw": packet.reader.raw,
            "parsed": packet.reader.parsed,
            "source": packet.reader.source,
            "ocr_confidence": packet.reader.ocr_confidence,
        }

    # Normalization
    if packet.normalized:
        d["normalized"] = packet.normalized

    # Validation
    d["validated"] = packet.validated
    if packet.validation_error:
        d["validation_error"] = packet.validation_error

    # Match
    d["matched"] = packet.matched
    if packet.match_status:
        d["match_status"] = packet.match_status

    return d


def packets_to_dicts(packets: List[CalloutPacket]) -> List[Dict[str, Any]]:
    """Serialize a list of packets."""
    return [packet_to_dict(p) for p in packets]


def save_packets(
    packets: List[CalloutPacket],
    path: str,
    indent: int = 2,
) -> None:
    """
    Save packets to a JSON file for debugging.

    Args:
        packets: List of CalloutPacket
        path: Output file path
        indent: JSON indent level
    """
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    data = packets_to_dicts(packets)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)


def load_packets_json(path: str) -> List[Dict[str, Any]]:
    """
    Load serialized packets from JSON (as dicts, not reconstructed dataclasses).

    Useful for debugging and analysis.
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def summarize_packets(packets: List[CalloutPacket]) -> Dict[str, Any]:
    """
    Generate a summary of packet pipeline progression.

    Shows how many packets made it through each stage.
    """
    total = len(packets)
    has_detection = sum(1 for p in packets if p.detection is not None)
    has_crop = sum(1 for p in packets if p.crop is not None)
    has_rotation = sum(1 for p in packets if p.rotation is not None)
    has_reader = sum(1 for p in packets if p.reader is not None)
    has_normalized = sum(1 for p in packets if p.normalized is not None)
    validated = sum(1 for p in packets if p.validated)
    invalid = sum(1 for p in packets if p.validation_error is not None)
    matched = sum(1 for p in packets if p.matched)

    # Callout type breakdown
    type_counts: Dict[str, int] = {}
    for p in packets:
        if p.reader:
            ct = p.reader.callout_type
            type_counts[ct] = type_counts.get(ct, 0) + 1

    # Source breakdown (regex vs vlm)
    source_counts: Dict[str, int] = {}
    for p in packets:
        if p.reader:
            src = p.reader.source or "unknown"
            source_counts[src] = source_counts.get(src, 0) + 1

    return {
        "total": total,
        "pipeline_progression": {
            "detection": has_detection,
            "crop": has_crop,
            "rotation": has_rotation,
            "reader": has_reader,
            "normalized": has_normalized,
            "validated": validated,
            "invalid": invalid,
            "matched": matched,
        },
        "callout_types": type_counts,
        "parse_sources": source_counts,
    }
