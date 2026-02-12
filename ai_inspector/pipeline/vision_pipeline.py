"""Vision pipeline orchestrator — GPT-4o replaces YOLO+OCR for extraction.

Uses a single GPT-4o vision API call to extract all callouts from the
drawing image, then feeds them through the existing normalize → validate →
expand → match → score pipeline.  Assembly context and VLM page
understanding are optionally wired in, same as YOLOPipeline.

Usage:
    from ai_inspector.pipeline.vision_pipeline import VisionPipeline
    p = VisionPipeline(api_key="sk-...")
    result = p.run(image_path="page.png", sw_json_path="sw.json")

Or programmatically:
    p = VisionPipeline()  # uses OPENAI_API_KEY env var
    result = p.run(image_path="page.png")
"""

import json
import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image

from ..config import Config, default_config
from .yolo_pipeline import PipelineResult  # Reuse the same result type


class VisionPipeline:
    """
    GPT-4o vision-based engineering drawing inspection pipeline.

    Replaces YOLO → crop → OCR → regex with a single GPT-4o vision call.
    Reuses all downstream modules: normalization, validation, matching,
    scoring, assembly context, and report generation.

    No GPU models required — runs on CPU + OpenAI API.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        config: Optional[Config] = None,
    ):
        self.config = config or default_config
        self.api_key = api_key  # None = uses OPENAI_API_KEY env var

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
        Run the vision pipeline on a single page.

        Same interface as YOLOPipeline.run() — drop-in replacement.

        Args:
            image_path: Path to page image (PNG/JPG)
            image: PIL Image (alternative to image_path)
            sw_json_path: Path to SolidWorks JSON file
            sw_data: SW JSON dict (alternative to sw_json_path)
            title_block_text: OCR text from title block for unit detection
            page_id: Page identifier
            output_dir: Directory for debug artifacts
            save_crops: Ignored (no crops in vision pipeline)
            use_vlm: Override config.use_vlm for VLM page understanding
            mating_context_path: Path to sw_mating_context.json
            mate_specs_path: Path to sw_mate_specs.json
            part_context_path: Path to sw_part_context_complete.json

        Returns:
            PipelineResult with match results, scores, and context
        """
        from ..extractors.vlm_extractor import extract_callouts
        from ..extractors.unit_normalizer import normalize_callout, detect_drawing_units
        from ..extractors.validator import validate_and_repair_all
        from ..comparison.quantity_expander import expand_both_sides, expansion_summary

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

        # --- Stage 2: Load SW data + extract features ---
        sw_features = []
        if sw_json_path:
            with open(sw_json_path, "r", encoding="utf-8-sig") as f:
                sw_data = json.load(f)
        if sw_data:
            sw_features = self._sw_extractor.extract(sw_data)

        # ============================================================
        # PHASE 0: Assembly context lookup (BEFORE extraction)
        # Feed mate specs to GPT-4o so it knows which features are
        # assembly-critical and searches harder for them.
        # ============================================================
        mating_context = {}
        mate_specs = {}
        part_number = None

        if sw_data:
            part_number = sw_data.get("identity", {}).get("partNumber")

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
                mate_specs = ctx_db.get_mate_specs(part_number) or {}
                if not mate_specs and mating_context_path:
                    sibling_specs = ctx_db.get_mate_specs_for_siblings(part_number)
                    if sibling_specs:
                        mate_specs = {
                            "part_number": part_number,
                            "source": "sibling_cross_reference",
                            "sibling_specs": [s for s in sibling_specs],
                        }

        # ============================================================
        # PHASE 1: GPT-4o Vision Extraction (replaces YOLO + OCR)
        # Now assembly-aware: GPT-4o sees mate specs alongside SW features
        # ============================================================
        raw_callouts = extract_callouts(
            image=image,
            sw_features=sw_features if sw_features else None,
            api_key=self.api_key,
            config=self.config,
            mating_context=mating_context if mating_context else None,
            mate_specs=mate_specs if mate_specs else None,
        )

        # Save raw extraction for debugging
        if output_dir:
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            with open(out / "callouts_extracted.json", "w", encoding="utf-8") as f:
                json.dump(raw_callouts, f, indent=2, ensure_ascii=False)

        # ============================================================
        # PHASE 2: VLM Page Understanding (optional, same as YOLO pipeline)
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
        # PHASE 3: CPU-only (normalize → validate → match → score)
        # ============================================================

        # --- Unit normalization ---
        drawing_units = detect_drawing_units(title_block_text)
        if not drawing_units and page_understanding.get("units"):
            vlm_units = page_understanding["units"]
            if vlm_units in ("inch", "metric"):
                drawing_units = vlm_units

        for callout in raw_callouts:
            normalized = normalize_callout(
                callout,
                raw_text=callout.get("raw", ""),
                drawing_units=drawing_units,
            )
            callout.update(normalized)

        # --- Validate ---
        for callout in raw_callouts:
            if "raw" not in callout or not callout["raw"]:
                callout["raw"] = json.dumps(
                    {k: v for k, v in callout.items() if not k.startswith("_")},
                    ensure_ascii=False,
                )

        validated_callouts, validation_stats = validate_and_repair_all(raw_callouts)

        # --- Expand both sides ---
        expanded_callouts, expanded_sw = expand_both_sides(validated_callouts, sw_features)
        exp_summary = expansion_summary(
            validated_callouts, expanded_callouts,
            sw_features, expanded_sw,
        )

        # --- Match ---
        match_results = self._matcher.match_all(expanded_callouts, expanded_sw)

        # --- Score ---
        scores = self._matcher.compute_scores(match_results)

        # --- Fallback: try VLM title block for part number if SW didn't have it ---
        if not part_number and page_understanding.get("titleBlock"):
            part_number = page_understanding["titleBlock"].get("partNumber")

        # --- Debug output ---
        if output_dir:
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)

            # Save validated callouts
            with open(out / "validated_callouts.json", "w", encoding="utf-8") as f:
                json.dump(validated_callouts, f, indent=2, ensure_ascii=False, default=str)

            # Save match results
            results_data = [r.to_dict() for r in match_results]
            with open(out / "results.json", "w", encoding="utf-8") as f:
                json.dump(results_data, f, indent=2, ensure_ascii=False)

            # Save metrics
            metrics = {
                "scores": scores,
                "expansion": exp_summary,
                "validation": validation_stats,
                "extraction_count": len(raw_callouts),
                "pipeline_type": "vision",
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

        return PipelineResult(
            packets=[],  # No YOLO packets in vision pipeline
            match_results=match_results,
            scores=scores,
            expansion_summary=exp_summary,
            validation_stats=validation_stats,
            packet_summary={"extracted_callouts": len(raw_callouts), "pipeline_type": "vision"},
            page_understanding=page_understanding,
            mating_context=mating_context,
            mate_specs=mate_specs,
        )


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Vision Pipeline — GPT-4o Engineering Drawing Inspector"
    )
    parser.add_argument("--image", required=True, help="Path to page image (PNG/JPG)")
    parser.add_argument("--sw", help="Path to SolidWorks JSON file")
    parser.add_argument("--out", default="debug/run_vision", help="Output directory")
    parser.add_argument("--api-key", help="OpenAI API key")
    parser.add_argument("--title-block", default="", help="Title block text for unit detection")
    parser.add_argument("--no-vlm", action="store_true", help="Skip VLM page understanding")
    parser.add_argument("--mating-context", help="Path to sw_mating_context.json")
    parser.add_argument("--mate-specs", help="Path to sw_mate_specs.json")
    parser.add_argument("--part-context", help="Path to sw_part_context_complete.json")

    args = parser.parse_args()

    pipeline = VisionPipeline(api_key=args.api_key)

    print("Running vision pipeline on", args.image)
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
    print(f"  Extracted callouts: {result.packet_summary.get('extracted_callouts', 0)}")
    print(f"  Scores: {result.scores}")
    print(f"  Expansion: {result.expansion_summary}")
    print(f"  Validation: {result.validation_stats}")
    if result.page_understanding:
        print(f"  VLM units: {result.page_understanding.get('units', 'N/A')}")
    if result.mating_context:
        print(f"  Assembly: {result.mating_context.get('assembly', 'N/A')}")
    if result.mate_specs:
        print(f"  Mate specs: {result.mate_specs.get('source', 'direct')}")
    print(f"\nArtifacts saved to: {args.out}/")

    pipeline.unload()


if __name__ == "__main__":
    main()
