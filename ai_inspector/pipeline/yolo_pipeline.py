"""YOLO-OBB pipeline orchestrator with sequential model loading.

Wires all stages into a single run with GPU-efficient sequential loading:
  YOLO detect → unload → OCR read → unload → VLM understand → unload → match → score

Usage:
    python -m ai_inspector.pipeline.yolo_pipeline --image page.png --sw sw_data.json --out debug/run_001

Or programmatically:
    from ai_inspector.pipeline.yolo_pipeline import YOLOPipeline
    p = YOLOPipeline(hf_token="xxx")
    result = p.run(image_path="page.png", sw_json_path="sw.json")
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
    packets: List[Any] = field(default_factory=list)
    match_results: List[Any] = field(default_factory=list)
    scores: Dict[str, Any] = field(default_factory=dict)
    expansion_summary: Dict[str, Any] = field(default_factory=dict)
    validation_stats: Dict[str, Any] = field(default_factory=dict)
    packet_summary: Dict[str, Any] = field(default_factory=dict)
    page_understanding: Dict[str, Any] = field(default_factory=dict)
    mating_context: Dict[str, Any] = field(default_factory=dict)
    mate_specs: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-safe dict."""
        return {
            "scores": self.scores,
            "expansion_summary": self.expansion_summary,
            "validation_stats": self.validation_stats,
            "packet_summary": self.packet_summary,
            "page_understanding": self.page_understanding,
            "mating_context": self.mating_context,
            "mate_specs": self.mate_specs,
            "match_result_count": len(self.match_results),
            "packet_count": len(self.packets),
        }


class YOLOPipeline:
    """
    Full YOLO-OBB engineering drawing inspection pipeline.

    Models are loaded and unloaded sequentially within run() to
    stay within GPU memory limits (~12 GB RTX 4000 Ada):
      Phase 1: YOLO detect  (~0.04 GB)
      Phase 2: OCR read     (~2.02 GB)
      Phase 3: VLM page     (~4.5 GB)  [optional]
      Phase 4: CPU-only matching/scoring
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

        # CPU-only components (always loaded)
        self._matcher = None
        self._sw_extractor = None

    def load(self) -> None:
        """Load CPU-only components (matcher, SW extractor)."""
        from ..comparison.matcher import FeatureMatcher
        from ..comparison.sw_extractor import SwFeatureExtractor

        self._matcher = FeatureMatcher()
        self._sw_extractor = SwFeatureExtractor()

    def unload(self) -> None:
        """Release resources."""
        self._matcher = None
        self._sw_extractor = None

    @property
    def is_loaded(self) -> bool:
        return self._matcher is not None

    def _apply_class_confidence_thresholds(self, detections: List[Any]) -> List[Any]:
        """Post-filter detections using class-specific confidence thresholds."""
        thresholds = getattr(self.config, "yolo_class_confidence_thresholds", {}) or {}
        if not thresholds:
            return detections

        filtered = []
        for det in detections:
            class_name = getattr(det, "class_name", "")
            conf = float(getattr(det, "confidence", 0.0))
            min_conf = thresholds.get(class_name)
            if min_conf is None or conf >= float(min_conf):
                filtered.append(det)
        return filtered

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
        use_vlm: Optional[bool] = None,
        mating_context_path: Optional[str] = None,
        mate_specs_path: Optional[str] = None,
        part_context_path: Optional[str] = None,
    ) -> PipelineResult:
        """
        Run the full pipeline on a single page.

        Models are loaded/unloaded sequentially to save GPU memory.

        Args:
            image_path: Path to page image (PNG/JPG)
            image: PIL Image (alternative to image_path)
            sw_json_path: Path to SolidWorks JSON file
            sw_data: SW JSON dict (alternative to sw_json_path)
            title_block_text: OCR text from title block for unit detection
            page_id: Page identifier for det_ids
            output_dir: Directory for debug artifacts (None = no output)
            save_crops: Whether to save crop images to output_dir
            use_vlm: Override config.use_vlm for this run
            mating_context_path: Path to sw_mating_context.json for assembly context
            mate_specs_path: Path to sw_mate_specs.json for mate constraints/thread specs
            part_context_path: Path to sw_part_context_complete.json for old/new PN mapping

        Returns:
            PipelineResult with packets, match results, scores, and page understanding
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

        # Ensure CPU components are loaded
        if not self.is_loaded:
            self.load()

        if use_vlm is None:
            use_vlm = self.config.use_vlm

        # --- Stage 1: Load image ---
        if image is None:
            if image_path is None:
                raise ValueError("Either image_path or image must be provided.")
            image = Image.open(image_path).convert("RGB")

        # ============================================================
        # PHASE 1: YOLO Detection (load → detect → unload)
        # ============================================================
        from ..detection.yolo_detector import YOLODetector

        detector = YOLODetector(
            model_path=self.model_path,
            confidence_threshold=self.confidence_threshold,
            device=self.device,
            hf_token=self.hf_token,
        )
        detector.load()
        detections = detector.detect(image, page_id=page_id)
        detections = self._apply_class_confidence_thresholds(detections)
        detector.unload()
        del detector

        # --- Create packets ---
        packets = create_packets(detections)

        # --- OBB cropping (CPU) ---
        crops = crop_detections(image, detections)
        for pkt, crop in zip(packets, crops):
            attach_crop(pkt, crop)

        # ============================================================
        # PHASE 2: OCR (load → rotate+read all crops → unload)
        # ============================================================
        from ..extractors.ocr_adapter import OCRAdapter

        ocr_adapter = OCRAdapter(hf_token=self.hf_token)
        ocr_adapter.load()

        # Rotation + OCR for each crop
        for pkt, crop in zip(packets, crops):
            rotation_result = select_best_rotation(
                crop.image,
                ocr_adapter.read_simple,
                yolo_class=pkt.detection.class_name if pkt.detection else "",
            )
            attach_rotation(pkt, rotation_result)

        # Parse (reuse OCR text from rotation stage)
        for pkt, crop in zip(packets, crops):
            pre_ocr = None
            if pkt.rotation and pkt.rotation.ocr_result:
                pre_ocr = (pkt.rotation.ocr_result.text,
                           pkt.rotation.ocr_result.confidence)
            reader_result = read_crop(
                crop.image,
                ocr_adapter.read_simple,
                yolo_class=pkt.detection.class_name if pkt.detection else "",
                pre_ocr=pre_ocr,
            )
            attach_reader(pkt, reader_result)

        ocr_adapter.unload()
        del ocr_adapter

        # ============================================================
        # PHASE 3: VLM Page Understanding (load → analyze → unload)
        # ============================================================
        page_understanding = {}
        if use_vlm:
            vlm = None
            try:
                from ..extractors.vlm import QwenVLM
                from ..extractors.prompts import PAGE_UNDERSTANDING_PROMPT

                vlm = QwenVLM()
                vlm.load()
                page_understanding = vlm.analyze(image, PAGE_UNDERSTANDING_PROMPT)
            except Exception as e:
                page_understanding = {"error": str(e)}
            finally:
                if vlm is not None:
                    vlm.unload()
                    del vlm

        # ============================================================
        # PHASE 4: CPU-only stages (normalize → validate → match → score)
        # ============================================================

        # --- Unit normalization ---
        # Priority: explicit title_block_text > VLM-detected units > dual hypothesis
        drawing_units = detect_drawing_units(title_block_text)
        if not drawing_units and page_understanding.get("units"):
            vlm_units = page_understanding["units"]
            if vlm_units in ("inch", "metric"):
                drawing_units = vlm_units

        for pkt in packets:
            if pkt.reader and pkt.reader.parsed:
                normalized = normalize_callout(
                    pkt.reader.parsed,
                    raw_text=pkt.reader.raw,
                    drawing_units=drawing_units,
                )
                attach_normalization(pkt, normalized)

        # --- Validate ---
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

        # --- Load SW data + expand both sides ---
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

        # --- Match ---
        match_results = self._matcher.match_all(expanded_callouts, expanded_sw)

        # --- Score ---
        scores = self._matcher.compute_scores(match_results)

        # --- Attach match status to packets ---
        for pkt in packets:
            if pkt.reader and pkt.reader.callout_type:
                pkt_type = pkt.reader.callout_type
                for mr in match_results:
                    if mr.drawing_callout and mr.drawing_callout.get("calloutType") == pkt_type:
                        from ..comparison.matcher import MatchStatus
                        attach_match(pkt, matched=(mr.status == MatchStatus.MATCHED),
                                     status=mr.status.value)
                        break

        # --- Assembly context lookup (CPU-only, fast) ---
        mating_context = {}
        mate_specs = {}
        part_number = None
        # Resolve part number once
        if sw_data:
            part_number = sw_data.get("identity", {}).get("partNumber")
        if not part_number and page_understanding.get("titleBlock"):
            part_number = page_understanding["titleBlock"].get("partNumber")

        if part_number and (mating_context_path or mate_specs_path):
            from ..utils.context_db import ContextDatabase
            ctx_db = ContextDatabase()

            if part_context_path:
                ctx_db.load_part_context(part_context_path)

            if mating_context_path:
                ctx_db.load_mating_context(mating_context_path)
                mating_context = ctx_db.get_mating_context(part_number) or {}

            if mate_specs_path:
                ctx_db.load_mate_specs(mate_specs_path)
                # Direct lookup first
                mate_specs = ctx_db.get_mate_specs(part_number) or {}
                # If not found, collect sibling mate specs (cross-reference)
                if not mate_specs and mating_context_path:
                    sibling_specs = ctx_db.get_mate_specs_for_siblings(part_number)
                    if sibling_specs:
                        mate_specs = {
                            "part_number": part_number,
                            "source": "sibling_cross_reference",
                            "sibling_specs": [s for s in sibling_specs],
                        }

        # --- Debug output ---
        if output_dir:
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)

            save_packets(packets, str(out / "packets.json"))

            results_data = [r.to_dict() for r in match_results]
            with open(out / "results.json", "w", encoding="utf-8") as f:
                json.dump(results_data, f, indent=2, ensure_ascii=False)

            metrics = {
                "scores": scores,
                "expansion": exp_summary,
                "validation": validation_stats,
                "packet_summary": summarize_packets(packets),
                "detection_count": len(detections),
            }
            with open(out / "metrics.json", "w", encoding="utf-8") as f:
                json.dump(metrics, f, indent=2, ensure_ascii=False)

            if page_understanding:
                with open(out / "page_understanding.json", "w", encoding="utf-8") as f:
                    json.dump(page_understanding, f, indent=2, ensure_ascii=False)

            if mating_context:
                with open(out / "assembly_context.json", "w", encoding="utf-8") as f:
                    json.dump(mating_context, f, indent=2, ensure_ascii=False)

            if mate_specs:
                with open(out / "mate_specs.json", "w", encoding="utf-8") as f:
                    json.dump(mate_specs, f, indent=2, ensure_ascii=False)

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
            page_understanding=page_understanding,
            mating_context=mating_context,
            mate_specs=mate_specs,
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
    parser.add_argument("--no-vlm", action="store_true", help="Skip VLM page understanding")
    parser.add_argument("--mating-context", help="Path to sw_mating_context.json")
    parser.add_argument("--mate-specs", help="Path to sw_mate_specs.json")
    parser.add_argument("--part-context", help="Path to sw_part_context_complete.json")

    args = parser.parse_args()

    pipeline = YOLOPipeline(
        model_path=args.model,
        hf_token=args.hf_token,
        confidence_threshold=args.confidence,
    )

    print("Running pipeline on", args.image)
    result = pipeline.run(
        image_path=args.image,
        sw_json_path=args.sw,
        title_block_text=args.title_block,
        output_dir=args.out,
        use_vlm=not args.no_vlm,
        mating_context_path=args.mating_context,
        mate_specs_path=args.mate_specs,
        part_context_path=args.part_context,
    )

    print(f"\nResults:")
    print(f"  Detections: {len(result.packets)}")
    print(f"  Scores: {result.scores}")
    print(f"  Expansion: {result.expansion_summary}")
    print(f"  Validation: {result.validation_stats}")
    if result.page_understanding:
        print(f"  VLM units: {result.page_understanding.get('units', 'N/A')}")
        tb = result.page_understanding.get("titleBlock", {})
        if tb:
            print(f"  Title block: {tb}")
    if result.mating_context:
        print(f"  Assembly: {result.mating_context.get('assembly', 'N/A')}")
        print(f"  Siblings: {result.mating_context.get('siblings_str', 'N/A')}")
    if result.mate_specs:
        src = result.mate_specs.get('source', 'direct')
        print(f"  Mate specs: {src}")
    print(f"\nArtifacts saved to: {args.out}/")

    pipeline.unload()


if __name__ == "__main__":
    main()
