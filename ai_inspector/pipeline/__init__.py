"""Pipeline orchestration for AI Inspector v4."""

# YOLO pipeline (lightweight, no fitz/torch at import time)
from .yolo_pipeline import YOLOPipeline, PipelineResult


def __getattr__(name):
    """Lazy import for v4 orchestrator to avoid pulling in fitz/torch eagerly."""
    _orchestrator_names = {"InspectorPipeline", "InspectionResult", "run_inspection"}
    if name in _orchestrator_names:
        from . import orchestrator
        return getattr(orchestrator, name)
    raise AttributeError(f"module 'ai_inspector.pipeline' has no attribute {name!r}")


__all__ = [
    "InspectorPipeline",
    "InspectionResult",
    "run_inspection",
    "YOLOPipeline",
    "PipelineResult",
]
