"""
Qwen2.5-VL Vision Language Model Wrapper

Multimodal understanding for engineering drawings.
Extracts features, assesses quality, extracts BOM, and identifies manufacturing notes.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image


# Global model instances (loaded lazily)
_qwen_model = None
_qwen_processor = None


def load_qwen_model(device: str = "auto") -> Tuple[Any, Any]:
    """
    Load Qwen2.5-VL-7B-Instruct model.

    Args:
        device: Device to use ("cuda", "cpu", or "auto")

    Returns:
        Tuple of (model, processor)
    """
    global _qwen_model, _qwen_processor

    if _qwen_model is not None:
        return _qwen_model, _qwen_processor

    import torch
    from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor

    print("Loading Qwen2.5-VL-7B for drawing analysis...")
    model_id = "Qwen/Qwen2.5-VL-7B-Instruct"

    _qwen_processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
    _qwen_model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        model_id,
        torch_dtype=torch.bfloat16,
        device_map="auto" if device == "auto" else device,
        trust_remote_code=True
    )

    mem_gb = _qwen_model.get_memory_footprint() / 1e9
    print(f"Qwen2.5-VL loaded: {mem_gb:.2f} GB")

    return _qwen_model, _qwen_processor


def run_qwen_analysis(image: Image.Image, prompt: str, model=None, processor=None) -> Dict[str, Any]:
    """
    Run Qwen2.5-VL with a given prompt and return parsed JSON.

    Args:
        image: PIL Image to analyze
        prompt: Analysis prompt
        model: Optional pre-loaded model (uses global if None)
        processor: Optional pre-loaded processor (uses global if None)

    Returns:
        Parsed JSON response or dict with parse_error
    """
    global _qwen_model, _qwen_processor

    import torch
    from qwen_vl_utils import process_vision_info

    # Use provided or global models
    qwen_model = model or _qwen_model
    qwen_processor = processor or _qwen_processor

    if qwen_model is None or qwen_processor is None:
        raise RuntimeError("Qwen model not loaded. Call load_qwen_model() first.")

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": prompt}
            ]
        }
    ]

    text = qwen_processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    image_inputs, video_inputs = process_vision_info(messages)

    inputs = qwen_processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt"
    ).to(qwen_model.device)

    with torch.no_grad():
        output_ids = qwen_model.generate(**inputs, max_new_tokens=4096, temperature=0.1)

    generated_ids = output_ids[0, inputs.input_ids.shape[1]:]
    response = qwen_processor.decode(generated_ids, skip_special_tokens=True)

    # Parse JSON from response
    return _parse_json_response(response)


def _parse_json_response(response: str) -> Dict[str, Any]:
    """Parse JSON from model response, with repair if needed."""
    try:
        # Try to find JSON in markdown code block
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find raw JSON object
            json_match = re.search(r'\{[\s\S]*\}', response)
            json_str = json_match.group() if json_match else response

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            # Try json_repair if available
            try:
                from json_repair import repair_json
                print("  Attempting JSON repair...")
                repaired = repair_json(json_str)
                return json.loads(repaired)
            except ImportError:
                pass
            raise

    except Exception as e:
        return {"raw_response": response[:1000], "parse_error": str(e)}


# ============================================================================
# PROMPTS
# ============================================================================

FEATURE_EXTRACTION_PROMPT = """Analyze this engineering drawing and identify all features. Return a JSON object with:

{
  "partDescription": "brief description of the part",
  "views": ["list of views shown: TOP, FRONT, SIDE, ISOMETRIC, SECTION, DETAIL"],
  "features": [
    {
      "type": "one of the types listed below",
      "description": "brief description",
      "callout": "the EXACT dimension/callout text visible on the drawing",
      "quantity": 1,
      "location": "where on the part"
    }
  ],
  "material": "material if shown in title block",
  "titleBlockInfo": {
    "partNumber": "if visible",
    "revision": "if visible",
    "scale": "if visible"
  },
  "notes": ["any general notes visible on drawing"]
}

FEATURE TYPE DEFINITIONS - read carefully to classify correctly:

- TappedHole: A hole with INTERNAL THREADS. You MUST see a thread callout like M6x1.0, M10x1.5, 1/2-13 UNC, 3/8-16, or thread symbol lines (angled hatching inside the hole). If there is NO thread callout, it is NOT a TappedHole.

- ThroughHole: A plain round hole that goes completely through the part. Shown with a diameter dimension (e.g., ⌀0.500, Ø12.7mm) and the word THRU. No thread lines or thread callout.

- BlindHole: A plain round hole that does NOT go all the way through. Has a diameter AND a depth dimension (e.g., ⌀0.500 x 0.750 DEEP). No thread lines.

- Counterbore: A stepped hole with a larger diameter recess. Look for CBORE symbol or two concentric circles with different diameters.

- Countersink: A conical chamfer at a hole opening. Look for CSK symbol or an angle callout (e.g., 82° or 90°) at a hole.

- Slot: An elongated hole (oval/oblong shape). Has width and length dimensions.

- Fillet: A rounded internal corner. Look for R followed by a dimension (e.g., R.125, R3mm). Usually at intersections of surfaces.

- Chamfer: A beveled edge, usually 45°. Look for dimension x 45° callout (e.g., .030 x 45°). Found at edges of holes or part edges.

- Thread: External thread on a shaft or boss. Look for thread callout on an external diameter.

=== DIMENSION SUFFIX RECOGNITION (CRITICAL) ===

ALWAYS check for these suffixes and tag appropriately:
- (F) = FLAT PATTERN dimension (sheet metal pre-bend size) - tag as flat_pattern
- STK. or STOCK = Raw material/stock size - NOT a machined feature, tag as stock_dim
- REF. or REF = REFERENCE ONLY - do NOT include in inspection requirements
- TYP. or TYP = TYPICAL - applies to all similar features
- MAX. or MIN. = Limit dimension - extract the limit value

=== HOLE vs LINEAR DIMENSION (CRITICAL) ===

A HOLE DIAMETER dimension MUST have:
- Diameter symbol: ⌀ or Ø (before the number)
- The word "DIA" or "DIAMETER"
- Points to a CIRCULAR feature with a leader line
- Examples: ⌀0.500, Ø12.7mm, .375 DIA, 2X ⌀.38, 4X ⌀.43 THRU ALL

A LINEAR DIMENSION (NOT a hole):
- Has NO diameter symbol
- Dimension lines with arrows on BOTH ends pointing to surfaces/edges
- Examples: 1.50, 4.00, 2.75 (these are NOT holes!)

=== THREAD CALLOUT FORMATS ===

Recognize these thread formats:
- METRIC INTERNAL: M10X1.5-6H THRU ALL, M12X1.25-6H
- METRIC EXTERNAL: M6X1.0, M8X1.25
- UNIFIED INCH: 3/4-10 UNC-2A, .750-16UNF-2A, 1/4-20 UNC
- ACME (lead screws): 1.00-5 ACME-2G-LH, 1"-5 ACME-2G

=== SHEET METAL RECOGNITION ===

If you see ANY of these, classify drawing as SHEET_METAL:
- "FLAT PATTERN" view label
- Bend callouts: "UP 90° R .03" or "DOWN 90° R .03"
- Multiple (F) suffix dimensions
- Material like "10GA MILD STEEL" or "14GA"

Extract bend info: {"direction": "UP/DOWN", "angle": 90, "radius": 0.03}

=== SPECIAL DRAWING TYPES ===

WELDMENT signals:
- Title/description contains "WELDT" or "WELDMENT"
- Has BOM table (lists multiple parts to be welded together)
- Exploded or assembly view showing component arrangement
- May show weld symbols or ".### WELD LINE" callouts
- Action: Classify as WELDMENT_ASSEMBLY, extract BOM and weld specs

CASTING signals:
- Material contains "DUCTILE IRON", "CASTING"
- "MFG ITEM #: XXX OR EQUIVALENT"
- "ALL DIMENSIONS ARE REFERENCE" note
- Action: Most dims are reference-only, identify critical features

PURCHASED PART signals:
- Manufacturer cross-reference table (NSK, SKF, AST, etc.)
- "ALL DIMENSIONS FOR REFERENCE ONLY"
- Action: Classify as PURCHASED_PART, dims are reference only

GEAR signals:
- Gear data table with NUMBER OF TEETH, DIAMETRAL PITCH, PRESSURE ANGLE
- Action: Extract gear parameters into separate "gearData" object

=== GD&T FEATURE CONTROL FRAMES ===

Extract these geometric tolerances:
- Position: ⊕0.01(M) A B (datum references A, B)
- Perpendicularity: ⟂ 0.005 A
- Parallelism: // 0.010 A
- Concentricity: ◎ 0.002 A
- Runout: ↗ .002 A

=== SURFACE FINISH ===

Recognize surface finish callouts:
- 63√ or 63/ = Ra 63 microinches
- 125 Ra MAX = explicit Ra callout
- Extract as: {"roughness": 63, "unit": "Ra_microinch"}

=== COATING & HEAT TREATMENT ===

Extract these specifications:
- PAINT [COLOR]: "PAINT DOALL BLUE", "PAINT BLACK"
- POWDER COAT: "POWDER COAT ORANGE RAL 2009"
- BLACK OXIDE: "BLACK OXIDE PER MIL-C-13924"
- HARDNESS: "HRC 55-60", "RB 80-90"
- CASE DEPTH: ".020-.030 CASE DEPTH"
- MASKING: "MASK THREADS DURING PAINT", "MASK ALL HOLES"

=== REVISION MARKERS ===

Look for revision indicators:
- Triangle symbols △# pointing to changed features
- REV-# notes: "REV-1: .88 WAS 1.13"
- "# WAS #" format showing old values

=== IMPORTANT RULES ===

1. Only classify as TappedHole if you see thread callout (M__, __-__ UNC/UNF, ACME)
2. A hole with just diameter is ThroughHole (if THRU) or BlindHole (if has depth)
3. Report EXACT callout text as it appears - do not convert units
4. General notes like "REMOVE BURRS" are NOT features - put in "notes"
5. When unsure if hole or linear dim, check for ⌀ symbol
6. Dimensions with REF suffix are NOT inspection requirements
7. (F) dimensions are flat pattern only - separate from formed dims

Be thorough - identify ALL holes, threads, chamfers, fillets, and other machined features.
Only return valid JSON, no other text."""


QUALITY_AUDIT_PROMPT = """Examine this engineering drawing for completeness and best practices. Return a JSON object with:

{
  "titleBlockCompleteness": {
    "hasPartNumber": true/false,
    "partNumberValue": "the part number if visible",
    "hasDescription": true/false,
    "descriptionValue": "the description if visible",
    "hasMaterial": true/false,
    "materialValue": "the material if visible",
    "hasRevision": true/false,
    "revisionValue": "the revision if visible",
    "hasScale": true/false,
    "scaleValue": "the scale if visible",
    "hasDate": true/false,
    "dateValue": "the date if visible",
    "hasDrawnBy": true/false,
    "drawnByValue": "name if visible",
    "hasApprovedBy": true/false,
    "approvedByValue": "name if visible"
  },
  "drawingQuality": {
    "viewsLabeled": true/false,
    "viewsLabeledComment": "are views clearly labeled (FRONT, TOP, etc)?",
    "dimensionsReadable": true/false,
    "dimensionsComment": "are dimensions clear and not overlapping?",
    "tolerancesPresent": true/false,
    "tolerancesComment": "are tolerances specified on critical dimensions?",
    "surfaceFinishSpecified": true/false,
    "surfaceFinishComment": "is surface finish callout present?",
    "generalToleranceBlock": true/false,
    "generalToleranceComment": "is there a general tolerance note/block?",
    "thirdAngleProjection": true/false,
    "projectionComment": "is projection symbol visible (third angle)?",
    "unitsSpecified": true/false,
    "unitsValue": "INCHES or MM if specified"
  },
  "overallAssessment": {
    "completenessScore": "1-10 rating",
    "majorIssues": ["list any major issues found"],
    "minorIssues": ["list any minor issues found"],
    "recommendations": ["suggestions for improvement"]
  }
}

Be thorough and critical - this is a quality audit. Only return valid JSON, no other text."""


BOM_EXTRACTION_PROMPT = """Look at this engineering drawing. If there is a Bill of Materials (BOM) or Parts List table visible, extract it. Return a JSON object:

{
  "hasBOM": true/false,
  "bomLocation": "where on the drawing (e.g., upper right, separate sheet)",
  "bomItems": [
    {
      "itemNumber": "1",
      "partNumber": "the part number",
      "description": "part description",
      "quantity": 1,
      "material": "if specified in BOM"
    }
  ],
  "totalItems": 0,
  "bomNotes": "any notes about the BOM (e.g., 'items not shown', 'see sheet 2')"
}

If there is NO BOM or Parts List visible, return:
{
  "hasBOM": false,
  "bomLocation": null,
  "bomItems": [],
  "totalItems": 0,
  "bomNotes": "No BOM found - this appears to be a detail/part drawing"
}

Only return valid JSON, no other text."""


MANUFACTURING_NOTES_PROMPT = """Examine this engineering drawing for manufacturing-related notes and specifications. Return a JSON object:

{
  "hasManufacturingNotes": true/false,
  "heatTreatment": {
    "specified": true/false,
    "specification": "e.g., HEAT TREAT TO 58-62 HRC",
    "hardness": "e.g., 58-62 HRC",
    "process": "e.g., carburize, through harden, case harden"
  },
  "surfaceFinish": {
    "specified": true/false,
    "generalFinish": "e.g., 125 RMS, 63 Ra",
    "specificFinishes": [
      {"surface": "bore", "finish": "32 Ra"},
      {"surface": "OD", "finish": "63 Ra"}
    ]
  },
  "platingOrCoating": {
    "specified": true/false,
    "type": "e.g., ZINC PLATE, ANODIZE, PAINT BLACK, POWDER COAT",
    "specification": "e.g., PER MIL-C-5541, CLASS 2",
    "thickness": "if specified"
  },
  "weldingNotes": {
    "specified": true/false,
    "weldSpec": "e.g., AWS D1.1",
    "weldTypes": ["fillet", "groove", "spot"],
    "notes": "any welding-specific notes"
  },
  "specialProcesses": [
    {
      "process": "e.g., stress relieve, shot peen, passivate",
      "specification": "details if given"
    }
  ],
  "inspectionRequirements": {
    "specified": true/false,
    "requirements": ["e.g., 100% INSPECT THREADS", "CMM REQUIRED", "FIRST ARTICLE"]
  },
  "generalNotes": [
    "REMOVE ALL BURRS AND SHARP EDGES",
    "BREAK EDGES .005-.015",
    "any other manufacturing notes"
  ],
  "certifications": ["e.g., MATERIAL CERT REQUIRED", "PPAP REQUIRED"]
}

Extract ALL manufacturing-related information visible on the drawing. If a category has no information, set specified to false.
Only return valid JSON, no other text."""


PAGE_CLASSIFICATION_PROMPT = """Classify this engineering drawing page. Return a JSON object:

{
  "pageType": "one of: PART_DETAIL, ASSEMBLY_BOM, MIXED",
  "confidence": 0.0 to 1.0,
  "signals": ["list of visual elements that led to this classification"],
  "hasBOM": true/false,
  "hasDetailViews": true/false,
  "hasDimensions": true/false,
  "hasBalloons": true/false,
  "needsOCR": true/false
}

Classification rules:
- PART_DETAIL: Single part with dimensions, tolerances, section views. No BOM table.
- ASSEMBLY_BOM: Exploded view with balloon callouts and/or BOM table. Few/no dimensions.
- MIXED: Has both BOM/exploded AND dimensioned detail views on same page.

needsOCR should be true for PART_DETAIL and MIXED (have dimensions to extract).
needsOCR should be false for ASSEMBLY_BOM (mostly visual, BOM is tabular).

Only return valid JSON, no other text."""


# ============================================================================
# HIGH-LEVEL ANALYSIS FUNCTIONS
# ============================================================================

def extract_features(image: Image.Image, model=None, processor=None) -> Dict[str, Any]:
    """Extract engineering features from a drawing image."""
    return run_qwen_analysis(image, FEATURE_EXTRACTION_PROMPT, model, processor)


def audit_quality(image: Image.Image, model=None, processor=None) -> Dict[str, Any]:
    """Perform a quality audit on a drawing image."""
    return run_qwen_analysis(image, QUALITY_AUDIT_PROMPT, model, processor)


def extract_bom(image: Image.Image, model=None, processor=None) -> Dict[str, Any]:
    """Extract Bill of Materials from a drawing image."""
    return run_qwen_analysis(image, BOM_EXTRACTION_PROMPT, model, processor)


def extract_manufacturing_notes(image: Image.Image, model=None, processor=None) -> Dict[str, Any]:
    """Extract manufacturing notes from a drawing image."""
    return run_qwen_analysis(image, MANUFACTURING_NOTES_PROMPT, model, processor)


def classify_page(image: Image.Image, model=None, processor=None) -> Dict[str, Any]:
    """Classify a drawing page type."""
    return run_qwen_analysis(image, PAGE_CLASSIFICATION_PROMPT, model, processor)


def full_analysis(image: Image.Image, model=None, processor=None) -> Dict[str, Any]:
    """
    Run all analyses on a drawing image.

    Returns combined results from feature extraction, quality audit,
    BOM extraction, and manufacturing notes.
    """
    return {
        'featureAnalysis': extract_features(image, model, processor),
        'qualityAudit': audit_quality(image, model, processor),
        'bomExtraction': extract_bom(image, model, processor),
        'manufacturingNotes': extract_manufacturing_notes(image, model, processor),
    }


def clear_qwen_model():
    """Clear the loaded Qwen model from memory."""
    global _qwen_model, _qwen_processor
    import gc
    import torch

    _qwen_model = None
    _qwen_processor = None

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
