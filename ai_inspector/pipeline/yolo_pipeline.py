"""YOLO-OBB pipeline orchestrator.

Wires all stages into a single run:
  render -> detect -> crop -> rotate+OCR -> parse -> normalize -> validate -> expand -> match -> score

Usage:
    python -m ai_inspector.pipeline.yolo_pipeline --image page.png --sw sw_data.json --out debug/run_001

Or programmatically:
    from ai_inspector.pipeline.yolo_pipeline import YOLOPipeline
    pipeline = YOLOPipeline(model_path="best.pt", hf_token="xxx")
    pipeline.load()
    result = pipeline.run(image_path="page.png", sw_json_path="sw.json")
"""

import json
import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image

from ..config import Config, default_config


@dataclass
class PipelineResult:
    """Result from a single pipeline run."""
    packets: List[Any] = field(default_factory=list)        # List[CalloutPacket]
    match_results: List[Any] = field(default_factory=list)  # List[MatchResult]
    scores: Dict[str, Any] = field(default_factory=dict)
    expansion_summary: Dict[str, Any] = field(default_factory=dict)
    validation_stats: Dict[str, Any] = field(default_factory=dict)
    packet_summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-safe dict."""
        return {
            "scores": self.scores,
            "expansion_summary": self.expansion_summary,
            "validation_stats": self.validation_stats,
            "packet_summary": self.packet_summary,
            "match_result_count": len(self.match_results),
            "packet_count": len(self.packets),
        }


class YOLOPipeline:
    """
    Full YOLO-OBB engineering drawing inspection pipeline.

    Stages:
    1. Load/render page image
    2. YOLO-OBB detection
    3. OBB cropping
    4. Rotation selection + OCR
    5. Regex parsing (+ VLM fallback stub)
    6. Unit normalization
    7. Validation + repair
    8. Quantity expansion (both sides)
    9. Feature matching
    10. Scoring
    11. Debug artifact output
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        hf_token: Optional[str] = None,
        confidence_threshold: Optional[float] = None,
        device: Optional[str] = None,
        config: Optional[Config] = None,
    ):
        self.config = config or default_config
        self.model_path = model_path or self.config.yolo_model_path
        self.hf_token = hf_token
        self.confidence_threshold = confidence_threshold or self.config.yolo_confidence_threshold
        self.device = device

        self._detector = None
        self._ocr_adapter = None
        self._matcher = None
        self._sw_extractor = None

    def load(self) -> None:
        """Load all models (YOLO + OCR)."""
        from ..detection.yolo_detector import YOLODetector
        from ..extractors.ocr_adapter import OCRAdapter
        from ..comparison.matcher import FeatureMatcher
        from ..comparison.sw_extractor import SwFeatureExtractor

        self._detector = YOLODetector(
            model_path=self.model_path,
            confidence_threshold=self.confidence_threshold,
            device=self.device,
            hf_token=self.hf_token,
        )
        self._detector.load()

        self._ocr_adapter = OCRAdapter(hf_token=self.hf_token)
        self._ocr_adapter.load()

        self._matcher = FeatureMatcher()
        self._sw_extractor = SwFeatureExtractor()

    def unload(self) -> None:
        """Release all models from memory."""
        if self._detector:
            self._detector.unload()
        if self._ocr_adapter:
            self._ocr_adapter.unload()

    @property
    def is_loaded(self) -> bool:
        return (
            self._detector is not None and self._detector.is_loaded and
            self._ocr_adapter is not None and self._ocr_adapter.is_loaded
        )

    def run(
        self,
        image_path: Optional[str] = None,
        image: Optional[Image.Image] = None,
        sw_json_path: Optional[str] = None,
        sw_data: Optional[Dict[str, Any]] = None,
        title_block_text: str = "",
        page_id: str = "page_0",
        output_dir: Optional[str] = None,
        save_crops: bool = True,
    ) -> PipelineResult:
        """
        Run the full pipeline on a single page.

        Args:
            image_path: Path to page image (PNG/JPG)
            image: PIL Image (alternative to image_path)
            sw_json_path: Path to SolidWorks JSON file
            sw_data: SW JSON dict (alternative to sw_json_path)
            title_block_text: OCR text from title block for unit detection
            page_id: Page identifier for det_ids
            output_dir: Directory for debug artifacts (None = no output)
            save_crops: Whether to save crop images to output_dir

        Returns:
            PipelineResult with packets, match results, and scores
        """
        from ..extractors.cropper import crop_detections
        from ..extractors.rotation import select_best_rotation
        from ..extractors.crop_reader import read_crop
        from ..extractors.unit_normalizer import normalize_callout, detect_drawing_units
        from ..extractors.validator import validate_and_repair_all
        from ..comparison.quantity_expander import expand_both_sides, expansion_summary
        from ..schemas.callout_packet import (
            create_packets, attach_crop, attach_rotation,
            attach_reader, attach_normalization, attach_validation,
            attach_match, save_packets, summarize_packets,
        )

        if not self.is_loaded:
            raise RuntimeError("Pipeline not loaded. Call load() first.")

        # --- Stage 1: Load image ---
        if image is None:
            if image_path is None:
                raise ValueError("Either image_path or image must be provided.")
            image = Image.open(image_path).convert("RGB")

        # --- Stage 2: YOLO detection ---
        detections = self._detector.detect(image, page_id=page_id)

        # --- Create packets ---
        packets = create_packets(detections)

        # --- Stage 3: OBB cropping ---
        crops = crop_detections(image, detections)
        for pkt, crop in zip(packets, crops):
            attach_crop(pkt, crop)

        # --- Stage 4: Rotation + OCR ---
        for pkt, crop in zip(packets, crops):
            rotation_result = select_best_rotation(
                crop.image,
                self._ocr_adapter.read_simple,
                yolo_class=pkt.detection.class_name if pkt.detection else "",
            )
            attach_rotation(pkt, rotation_result)

        # --- Stage 5: Parse (reuse OCR text from rotation stage) ---
        for pkt, crop in zip(packets, crops):
            # Reuse rotation stage's OCR output instead of re-running OCR
            pre_ocr = None
            if pkt.rotation and pkt.rotation.ocr_result:
                pre_ocr = (pkt.rotation.ocr_result.text,
                           pkt.rotation.ocr_result.confidence)
            reader_result = read_crop(
                crop.image,
                self._ocr_adapter.read_simple,
                yolo_class=pkt.detection.class_name if pkt.detection else "",
                pre_ocr=pre_ocr,
            )
            attach_reader(pkt, reader_result)

        # --- Stage 6: Unit normalization ---
        drawing_units = detect_drawing_units(title_block_text)
        for pkt in packets:
            if pkt.reader and pkt.reader.parsed:
                normalized = normalize_callout(
                    pkt.reader.parsed,
                    raw_text=pkt.reader.raw,
                    drawing_units=drawing_units,
                )
                attach_normalization(pkt, normalized)

        # --- Stage 7: Validate ---
        callout_dicts = []
        for pkt in packets:
            if pkt.normalized:
                d = dict(pkt.normalized)
                d["raw"] = pkt.reader.raw if pkt.reader else ""
                callout_dicts.append(d)
            elif pkt.reader:
                d = dict(pkt.reader.parsed)
                d["raw"] = pkt.reader.raw
                callout_dicts.append(d)
            else:
                callout_dicts.append({"calloutType": "Unknown", "raw": ""})

        validated_callouts, validation_stats = validate_and_repair_all(callout_dicts)

        for pkt, callout in zip(packets, validated_callouts):
            is_valid = not callout.get("_invalid", False)
            error = callout.get("_validation_error")
            attach_validation(pkt, validated=is_valid, error=error)

        # --- Stage 8: Load SW data + expand both sides ---
        sw_features = []
        if sw_json_path:
            with open(sw_json_path, "r", encoding="utf-8-sig") as f:
                sw_data = json.load(f)
        if sw_data:
            sw_features = self._sw_extractor.extract(sw_data)

        expanded_callouts, expanded_sw = expand_both_sides(validated_callouts, sw_features)
        exp_summary = expansion_summary(
            validated_callouts, expanded_callouts,
            sw_features, expanded_sw,
        )

        # --- Stage 9: Match ---
        match_results = self._matcher.match_all(expanded_callouts, expanded_sw)

        # --- Stage 10: Score ---
        scores = self._matcher.compute_scores(match_results)

        # --- Attach match status to packets (best effort) ---
        # Map expanded match results back to original packets by callout type
        for pkt in packets:
            if pkt.reader and pkt.reader.callout_type:
                pkt_type = pkt.reader.callout_type
                # Find any match result for this type
                for mr in match_results:
                    if mr.drawing_callout and mr.drawing_callout.get("calloutType") == pkt_type:
                        from ..comparison.matcher import MatchStatus
                        attach_match(pkt, matched=(mr.status == MatchStatus.MATCHED),
                                     status=mr.status.value)
                        break

        # --- Stage 11: Debug output ---
        if output_dir:
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)

            # Save packets
            save_packets(packets, str(out / "packets.json"))

            # Save results
            results_data = [r.to_dict() for r in match_results]
            with open(out / "results.json", "w") as f:
                json.dump(results_data, f, indent=2, ensure_ascii=False)

            # Save metrics
            metrics = {
                "scores": scores,
                "expansion": exp_summary,
                "validation": validation_stats,
                "packet_summary": summarize_packets(packets),
                "detection_count": len(detections),
            }
            with open(out / "metrics.json", "w") as f:
                json.dump(metrics, f, indent=2, ensure_ascii=False)

            # Save crops
            if save_crops:
                crops_dir = out / "crops"
                crops_dir.mkdir(exist_ok=True)
                for pkt, crop in zip(packets, crops):
                    if crop.image:
                        crop_path = crops_dir / f"{pkt.det_id}.png"
                        crop.image.save(str(crop_path))

        return PipelineResult(
            packets=packets,
            match_results=match_results,
            scores=scores,
            expansion_summary=exp_summary,
            validation_stats=validation_stats,
            packet_summary=summarize_packets(packets),
        )


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="YOLO-OBB Engineering Drawing Inspector Pipeline"
    )
    parser.add_argument("--image", required=True, help="Path to page image (PNG/JPG)")
    parser.add_argument("--sw", help="Path to SolidWorks JSON file")
    parser.add_argument("--model", default="yolo11n-obb.pt", help="YOLO model path")
    parser.add_argument("--out", default="debug/run", help="Output directory")
    parser.add_argument("--confidence", type=float, default=0.25, help="Detection confidence threshold")
    parser.add_argument("--hf-token", help="HuggingFace token for OCR model")
    parser.add_argument("--title-block", default="", help="Title block text for unit detection")

    args = parser.parse_args()

    pipeline = YOLOPipeline(
        model_path=args.model,
        hf_token=args.hf_token,
        confidence_threshold=args.confidence,
    )

    print("Loading models...")
    pipeline.load()

    print(f"Running pipeline on {args.image}...")
    result = pipeline.run(
        image_path=args.image,
        sw_json_path=args.sw,
        title_block_text=args.title_block,
        output_dir=args.out,
    )

    print(f"\nResults:")
    print(f"  Detections: {len(result.packets)}")
    print(f"  Scores: {result.scores}")
    print(f"  Expansion: {result.expansion_summary}")
    print(f"  Validation: {result.validation_stats}")
    print(f"\nArtifacts saved to: {args.out}/")

    pipeline.unload()


if __name__ == "__main__":
    main()
