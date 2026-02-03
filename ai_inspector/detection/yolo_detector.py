"""YOLO11-OBB detector for engineering drawing callouts."""

from pathlib import Path
from typing import List, Optional, Union

from ..contracts import DetectionResult
from .classes import IDX_TO_CLASS


class YOLODetector:
    """
    YOLO11-OBB detector for engineering drawing callouts.

    Loads a YOLO OBB model and detects oriented bounding boxes
    around engineering callouts (holes, threads, fillets, etc.).

    Usage:
        detector = YOLODetector(model_path="best.pt")
        detector.load()
        detections = detector.detect(image, page_id="page_0")
    """

    def __init__(
        self,
        model_path: Union[str, Path] = "yolo11n-obb.pt",
        confidence_threshold: float = 0.25,
        device: Optional[str] = None,
    ):
        self.model_path = Path(model_path)
        self.confidence_threshold = confidence_threshold
        self.device = device
        self.model = None

    def load(self) -> None:
        """Load the YOLO model."""
        from ultralytics import YOLO
        self.model = YOLO(str(self.model_path))
        if self.device:
            self.model.to(self.device)

    def unload(self) -> None:
        """Release model from memory."""
        if self.model is not None:
            del self.model
            self.model = None

    @property
    def is_loaded(self) -> bool:
        return self.model is not None

    def detect(
        self,
        image,  # PIL.Image or numpy array or file path
        page_id: str = "page_0",
        confidence_threshold: Optional[float] = None,
    ) -> List[DetectionResult]:
        """
        Run detection on a single image.

        Args:
            image: Input image (PIL Image, numpy array, or file path)
            page_id: Identifier for this page (used in det_id)
            confidence_threshold: Override default threshold

        Returns:
            List of DetectionResult sorted by confidence descending
        """
        if not self.is_loaded:
            raise RuntimeError("Model not loaded. Call load() first.")

        conf = confidence_threshold or self.confidence_threshold

        results = self.model(image, conf=conf, verbose=False)

        detections = []
        for result in results:
            if result.obb is None:
                continue

            obb = result.obb

            for i in range(len(obb)):
                # Use named attributes — NOT hardcoded indices
                cls_id = int(obb.cls[i].item())
                confidence = float(obb.conf[i].item())

                # OBB polygon points (4 corners)
                # obb.xyxyxyxy gives shape [N, 4, 2]
                points = obb.xyxyxyxy[i].cpu().numpy().tolist()

                # xywhr format if available
                xywhr = obb.xywhr[i].cpu().numpy().tolist() if obb.xywhr is not None else None

                # Map class ID to name
                class_name = IDX_TO_CLASS.get(cls_id, f"Unknown_{cls_id}")

                det = DetectionResult(
                    class_name=class_name,
                    confidence=confidence,
                    obb_points=points,
                    xywhr=xywhr,
                    det_id=f"{page_id}_{i}",
                )
                detections.append(det)

        # Sort by confidence descending
        detections.sort(key=lambda d: d.confidence, reverse=True)

        return detections

    def detect_batch(
        self,
        images: list,
        page_ids: Optional[List[str]] = None,
    ) -> List[List[DetectionResult]]:
        """
        Run detection on multiple images.

        Args:
            images: List of input images
            page_ids: Optional list of page identifiers

        Returns:
            List of detection lists, one per image
        """
        if page_ids is None:
            page_ids = [f"page_{i}" for i in range(len(images))]

        return [
            self.detect(img, pid)
            for img, pid in zip(images, page_ids)
        ]

    def summary(self, detections: List[DetectionResult]) -> dict:
        """
        Summarize detection results.

        Returns dict with total count and per-class breakdown.
        """
        from collections import Counter
        class_counts = Counter(d.class_name for d in detections)
        return {
            "total": len(detections),
            "by_class": dict(class_counts),
            "avg_confidence": sum(d.confidence for d in detections) / len(detections) if detections else 0.0,
        }
