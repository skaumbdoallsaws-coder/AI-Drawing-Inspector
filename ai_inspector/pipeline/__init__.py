"""Pipeline orchestration for AI Inspector v4."""

# YOLO pipeline (lightweight, no fitz/torch at import time)
from .yolo_pipeline import YOLOPipeline, PipelineResult


def __getattr__(name):
    """Lazy import for v4 orchestrator and vision pipeline."""
    _orchestrator_names = {"InspectorPipeline", "InspectionResult", "run_inspection"}
    if name in _orchestrator_names:
        from . import orchestrator
        return getattr(orchestrator, name)
    if name == "VisionPipeline":
        from .vision_pipeline import VisionPipeline
        return VisionPipeline
    raise AttributeError(f"module 'ai_inspector.pipeline' has no attribute {name!r}")


__all__ = [
    "InspectorPipeline",
    "InspectionResult",
    "run_inspection",
    "YOLOPipeline",
    "VisionPipeline",
    "PipelineResult",
]
