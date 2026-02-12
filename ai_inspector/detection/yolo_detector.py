"""YOLO11-OBB detector for engineering drawing callouts."""

import logging
import os
from pathlib import Path
from typing import List, Optional, Union

from ..contracts import DetectionResult
from .classes import IDX_TO_CLASS, FINETUNED_IDX_TO_CLASS

logger = logging.getLogger(__name__)


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
        hf_token: Optional[str] = None,
    ):
        # Preserve URI schemes (e.g. hf://) as raw strings.
        # Path() on Windows would corrupt "hf://user/repo" into "hf:/user/repo".
        path_str = str(model_path)
        if "://" in path_str:
            self.model_path: Union[str, Path] = path_str
        else:
            self.model_path = Path(model_path)

        self.confidence_threshold = confidence_threshold
        self.device = device
        self.hf_token = hf_token
        self.model = None

    def load(self) -> None:
        """Load the YOLO model.

        If the model path is an ``hf://`` URI, the weights file is first
        downloaded via :func:`huggingface_hub.hf_hub_download` so that the
        local path (not the URI) is handed to ``ultralytics.YOLO``.  This
        avoids a Windows-specific bug where ``ultralytics`` internally
        converts ``://`` to ``:\\``, producing an invalid path like
        ``hf:\\user\\repo\\file.pt``.

        If *hf_token* was provided, it is injected into the ``HF_TOKEN``
        environment variable **and** forwarded to ``hf_hub_download`` for
        authenticated access.

        Raises:
            RuntimeError: If the model cannot be loaded (file not found,
                download failure, etc.).
        """
        from ultralytics import YOLO

        # Set HF_TOKEN for authenticated HuggingFace downloads.
        if self.hf_token:
            os.environ["HF_TOKEN"] = self.hf_token
            logger.debug("HF_TOKEN set from hf_token parameter.")

        # Resolve hf:// URIs to local cached paths before passing to YOLO.
        # On Windows, ultralytics mangles "hf://user/repo/file" into
        # "hf:\\user\\repo\\file" which triggers OSError: [Errno 22].
        resolved_path = str(self.model_path)
        if resolved_path.startswith("hf://"):
            resolved_path = self._download_hf_model(resolved_path)

        try:
            self.model = YOLO(resolved_path)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load YOLO model from '{self.model_path}': {exc}"
            ) from exc

        if self.device:
            self.model.to(self.device)

        logger.info(
            "YOLO model loaded from '%s' with %d classes: %s",
            self.model_path,
            len(self.model.names),
            self.model.names,
        )

    def _download_hf_model(self, hf_uri: str) -> str:
        """Download a model from HuggingFace Hub and return the local path.

        Parses a URI of the form ``hf://user/repo/filename`` into
        ``repo_id="user/repo"`` and ``filename="filename"``, then delegates
        to :func:`huggingface_hub.hf_hub_download`.

        Args:
            hf_uri: A HuggingFace Hub URI (e.g.
                ``"hf://shadrack20s/ai-inspector-callout-detection/best.pt"``).

        Returns:
            Absolute path to the locally cached weights file.

        Raises:
            RuntimeError: If the URI cannot be parsed or the download fails.
        """
        from huggingface_hub import hf_hub_download  # lazy import

        # Strip the "hf://" prefix and split into components.
        # Expected format after stripping: "user/repo/filename"
        # which may also be "user/repo/sub/dir/filename".
        stripped = hf_uri[len("hf://"):]
        parts = stripped.split("/")

        if len(parts) < 3:
            raise RuntimeError(
                f"Invalid hf:// URI '{hf_uri}'. "
                "Expected format: hf://user/repo/filename"
            )

        repo_id = f"{parts[0]}/{parts[1]}"
        filename = "/".join(parts[2:])

        logger.info(
            "Downloading HuggingFace model: repo_id='%s', filename='%s'",
            repo_id,
            filename,
        )

        try:
            local_path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                token=self.hf_token,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to download model from HuggingFace Hub "
                f"(repo='{repo_id}', file='{filename}'): {exc}"
            ) from exc

        logger.info("Model downloaded to local cache: '%s'", local_path)
        return local_path

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

        # Build the class-index-to-name mapping.
        # Prefer the authoritative model.names dict that ultralytics exposes
        # (it reflects the exact classes the model was trained on).  Fall back
        # to the hardcoded IDX_TO_CLASS only if model.names is unavailable.
        if hasattr(self.model, "names") and self.model.names:
            idx_to_name = self.model.names  # dict {int: str}
        else:
            logger.warning(
                "model.names unavailable; falling back to hardcoded IDX_TO_CLASS"
            )
            idx_to_name = IDX_TO_CLASS

        results = self.model(image, conf=conf, verbose=False)

        detections = []
        for result in results:
            if result.obb is None:
                continue

            obb = result.obb

            for i in range(len(obb)):
                # Use named attributes -- NOT hardcoded indices
                cls_id = int(obb.cls[i].item())
                confidence = float(obb.conf[i].item())

                # OBB polygon points (4 corners)
                # obb.xyxyxyxy gives shape [N, 4, 2]
                points = obb.xyxyxyxy[i].cpu().numpy().tolist()

                # xywhr format if available
                xywhr = obb.xywhr[i].cpu().numpy().tolist() if obb.xywhr is not None else None

                # Map class ID to name using the runtime mapping
                class_name = idx_to_name.get(cls_id, f"Unknown_{cls_id}")

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
