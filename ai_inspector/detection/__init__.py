"""YOLO-OBB detection module."""

from ..contracts import DetectionResult
from .classes import (
    YOLO_CLASSES, IDX_TO_CLASS, CLASS_TO_IDX, NUM_CLASSES,
    CLASS_TO_CALLOUT_TYPE, FUTURE_TYPES,
    FINETUNED_CLASSES, FINETUNED_IDX_TO_CLASS, FINETUNED_NUM_CLASSES,
)
from .yolo_detector import YOLODetector

__all__ = [
    "DetectionResult",
    "YOLODetector",
    "YOLO_CLASSES",
    "IDX_TO_CLASS",
    "CLASS_TO_IDX",
    "NUM_CLASSES",
    "CLASS_TO_CALLOUT_TYPE",
    "FUTURE_TYPES",
    "FINETUNED_CLASSES",
    "FINETUNED_IDX_TO_CLASS",
    "FINETUNED_NUM_CLASSES",
]
