"""GPT-4o Vision-based callout extraction from engineering drawings.

Replaces the YOLO -> crop -> OCR -> regex pipeline with a single
GPT-4o vision API call.  The model sees the full drawing image and
(optionally) a list of SolidWorks reference features, then returns
structured callout JSON that the downstream matcher can consume directly.

Usage:
    from ai_inspector.extractors.vlm_extractor import extract_callouts
    callouts = extract_callouts(image, sw_features, api_key="sk-...")
"""

import base64
import io
import json
import re
from typing import Any, Dict, List, Optional

from PIL import Image

from ..config import Config, default_config


# ──────────────────────────────────────────────────────────────
# Prompt template
# ──────────────────────────────────────────────────────────────

EXTRACTION_SYSTEM = (
    "You are an expert engineering drawing reader. You extract dimensional "
    "callouts from 2D engineering drawings with perfect accuracy. You output "
    "ONLY valid JSON — no markdown fences, no commentary."
)

EXTRACTION_PROMPT = '''\
Examine this engineering drawing image carefully.

Extract EVERY dimensional callout visible on the drawing. Include callouts \
from ALL views (front, top, side, section, detail views). Do NOT skip any \
dimension, hole, thread, fillet, chamfer, or tolerance annotation.

{sw_context}

{assembly_context}

Return a JSON array. Each element must use one of these calloutType values \
and include the corresponding fields:

**"Hole"** — Any diameter callout (⌀ symbol or "DRILL"), with or without tolerance:
{{
  "calloutType": "Hole",
  "raw": "<exact text from drawing>",
  "quantity": <int, default 1>,
  "diameter": <float in INCHES>,
  "depth": "<'THRU' or depth as float in inches; omit if not shown>",
  "tolerancePlus": <float, upper tolerance if shown; omit if not shown>,
  "toleranceMinus": <float, lower tolerance if shown; omit if not shown>
}}

**"TappedHole"** — Any thread callout (M##x#.#, #-## UNC/UNF, etc.):
{{
  "calloutType": "TappedHole",
  "raw": "<exact text from drawing>",
  "quantity": <int, default 1>,
  "diameter": <float in INCHES if shown>,
  "depth": "<'THRU' or depth as float in inches; omit if not shown>",
  "thread": {{
    "standard": "Metric" | "Imperial" | "Unified",
    "nominalDiameterMm": <float, for Metric>,
    "pitch": <float, mm pitch for Metric>,
    "tpi": <int, threads per inch for Imperial/Unified>,
    "threadClass": "<e.g. 6H, UNC, UNF>",
    "raw": "<original thread spec text>"
  }}
}}

**"Fillet"** — Radius callout (R followed by value):
{{
  "calloutType": "Fillet",
  "raw": "<exact text from drawing>",
  "quantity": <int, default 1>,
  "radius": <float in INCHES>
}}

**"Chamfer"** — Chamfer callout (distance X angle):
{{
  "calloutType": "Chamfer",
  "raw": "<exact text from drawing>",
  "quantity": <int, default 1>,
  "size": <float in INCHES>,
  "angle": <float in degrees, default 45>
}}

**"Dimension"** — Any linear dimension with or without tolerance:
{{
  "calloutType": "Dimension",
  "raw": "<exact text from drawing>",
  "quantity": <int, default 1>,
  "nominal": <float in INCHES>,
  "tolerancePlus": <float; omit if not shown>,
  "toleranceMinus": <float; omit if not shown>,
  "isReference": <true if dimension is in parentheses like (17.19)>
}}

**"Angle"** — Angular dimension:
{{
  "calloutType": "Angle",
  "raw": "<exact text from drawing>",
  "nominal": <float in degrees>
}}

Rules:
- ANY callout with a ⌀ symbol is a "Hole" (even if it has tolerances like ⌀1.00 +.00/-.09).
- ANY callout with a thread spec (M10x1.5, 1/4-20 UNC, etc.) is a "TappedHole".
- ANY callout starting with R is a "Fillet".
- ANY callout with "X 45°" pattern is a "Chamfer".
- All other dimensions (linear distances with ± tolerances) are "Dimension".
- Angular dimensions are "Angle".
- Convert fractions to decimals (33/64 = 0.515625).
- If the drawing uses millimeters, convert ALL values to inches (divide by 25.4).
- Include the quantity prefix (2X, 4X) in the "quantity" field.
- The "raw" field MUST contain the EXACT text you read from the drawing — critical for traceability.
- Do NOT include title block text, border dimensions, scale, material, or treatment info.
- Do NOT include general tolerance block values (e.g. ".XX ± .01") — only specific dimension callouts.
- Dimensions in parentheses like (17.19) are reference dimensions — set "isReference": true.
- For bilateral tolerances like 17.69±.03, set tolerancePlus=0.03 and toleranceMinus=0.03.
- For unilateral tolerances like +.00/-.09, set tolerancePlus=0.0 and toleranceMinus=0.09.

Be thorough. It is better to extract too many callouts than to miss one.

Return ONLY the JSON array. No explanation, no markdown.
'''


def _build_sw_context(sw_features: Optional[List[Any]]) -> str:
    """Build the SW reference section of the prompt."""
    if not sw_features:
        return (
            "No SolidWorks reference data is available.  "
            "Extract every callout you can find on the drawing."
        )

    lines = [
        "The SolidWorks CAD model for this part contains these features.",
        "Use this as a guide — search the drawing for callouts that match "
        "these features, but ALSO report any callouts NOT in this list.",
        "",
        "Reference features from CAD:",
    ]
    for i, feat in enumerate(sw_features):
        d = feat.to_dict() if hasattr(feat, "to_dict") else dict(feat)
        parts = [f"  {i+1}. {d.get('calloutType', '?')}"]
        if d.get("diameter") is not None:
            parts.append(f"dia={d['diameter']:.4f}\"")
        if d.get("radius") is not None:
            parts.append(f"R={d['radius']:.4f}\"")
        if d.get("thread"):
            t = d["thread"]
            parts.append(f"thread={t.get('raw', '')}")
        if d.get("quantity", 1) > 1:
            parts.append(f"qty={d['quantity']}")
        lines.append(" ".join(parts))

    return "\n".join(lines)


def _build_assembly_context(
    mating_context: Optional[Dict[str, Any]] = None,
    mate_specs: Optional[Dict[str, Any]] = None,
) -> str:
    """Build the assembly context section of the prompt."""
    if not mating_context and not mate_specs:
        return ""

    lines = [
        "",
        "ASSEMBLY CONTEXT — This part is used in an assembly. The mating "
        "relationships below tell you which features are CRITICAL for assembly "
        "fit. Search the drawing especially hard for callouts matching these "
        "interface features.",
        "",
    ]

    if mating_context:
        assembly = mating_context.get("assembly", "")
        if assembly:
            lines.append(f"Assembly: {assembly}")
        siblings = mating_context.get("siblings", [])
        if siblings:
            sibling_descs = [
                f"{s.get('pn', '?')} ({s.get('desc', '?')})"
                for s in siblings
            ]
            lines.append(f"Sibling components: {', '.join(sibling_descs)}")
        lines.append("")

    if mate_specs:
        source = mate_specs.get("source", "direct")
        specs_list = (
            mate_specs.get("sibling_specs", [mate_specs])
            if source == "sibling_cross_reference"
            else [mate_specs]
        )

        lines.append("Mate constraints (features that MUST exist on this part):")
        for spec in specs_list:
            for m in spec.get("mates_with", []):
                mate_type = m.get("mate_type", "?")
                part = m.get("part", "?")
                desc = m.get("description", "")
                thread = m.get("thread", "")
                pitch = m.get("pitch", "")
                length = m.get("length", "")

                line = f"  - {mate_type} mate with {part}"
                if desc:
                    line += f" ({desc})"
                if thread:
                    line += f" => REQUIRES tapped hole: {thread}"
                    if pitch:
                        line += f" pitch={pitch}"
                    if length:
                        line += f" length={length}"
                    line += (
                        " — LOOK CAREFULLY for this thread callout on the drawing. "
                        "It may appear as a tapped hole spec, a drill size, or a "
                        "thread note."
                    )
                elif mate_type == "Concentric":
                    line += (
                        " => REQUIRES a coaxial hole or bore on this part. "
                        "Look for a diameter callout."
                    )
                lines.append(line)

    return "\n".join(lines)


def _encode_image(image: Image.Image, max_dimension: int = 2048) -> str:
    """Encode PIL Image to base64 PNG, resizing if needed."""
    w, h = image.size
    if max(w, h) > max_dimension:
        scale = max_dimension / max(w, h)
        image = image.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _parse_response(text: str) -> List[Dict[str, Any]]:
    """Parse GPT-4o response into a list of callout dicts."""
    # Strip markdown fences if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    parsed = json.loads(cleaned)

    if isinstance(parsed, dict) and "callouts" in parsed:
        parsed = parsed["callouts"]

    if not isinstance(parsed, list):
        raise ValueError(f"Expected JSON array, got {type(parsed).__name__}")

    # Validate and clean each callout
    ACCEPTED_TYPES = {
        "Hole", "TappedHole", "Fillet", "Chamfer",
        "Dimension", "Angle",
    }
    valid = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        ct = item.get("calloutType", "")
        if ct not in ACCEPTED_TYPES:
            continue
        # Ensure raw field exists
        if "raw" not in item:
            item["raw"] = ""
        # Default quantity
        if "quantity" not in item:
            item["quantity"] = 1
        valid.append(item)

    return valid


def extract_callouts(
    image: Image.Image,
    sw_features: Optional[List[Any]] = None,
    api_key: Optional[str] = None,
    config: Optional[Config] = None,
    mating_context: Optional[Dict[str, Any]] = None,
    mate_specs: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Extract callouts from an engineering drawing using GPT-4o vision.

    Args:
        image: PIL Image of the drawing page
        sw_features: Optional list of SwFeature objects from SW JSON
                     (used as extraction guidance — not required)
        api_key: OpenAI API key (or uses OPENAI_API_KEY env var)
        config: Config override (uses default_config if None)
        mating_context: Assembly mating context (parent assembly, siblings)
        mate_specs: Mate specifications (thread specs, mate types)

    Returns:
        List of callout dicts ready for the normalization/matching pipeline.
        Each dict has: calloutType, raw, diameter/radius/size, thread, quantity, etc.
    """
    cfg = config or default_config

    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    # Encode image
    b64_image = _encode_image(image)

    # Build prompt
    sw_context = _build_sw_context(sw_features)
    assembly_context = _build_assembly_context(mating_context, mate_specs)
    prompt_text = EXTRACTION_PROMPT.format(
        sw_context=sw_context,
        assembly_context=assembly_context,
    )

    # Call GPT-4o with vision
    response = client.chat.completions.create(
        model=cfg.vision_extraction_model,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{b64_image}",
                            "detail": cfg.vision_extraction_detail,
                        },
                    },
                    {"type": "text", "text": prompt_text},
                ],
            },
        ],
        max_tokens=cfg.vision_extraction_max_tokens,
        temperature=cfg.vision_extraction_temperature,
    )

    raw_text = response.choices[0].message.content
    tokens_used = response.usage.total_tokens if response.usage else 0

    # Parse response
    callouts = _parse_response(raw_text)

    # Attach metadata
    for callout in callouts:
        callout["_source"] = "gpt4o_vision"
        callout["_tokens_used"] = tokens_used

    return callouts
