"""
LightOn OCR-2 Wrapper

High-quality OCR extraction using LightOnOCR-2-1B model.
Designed for engineering drawings with technical callouts.
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image


# Global model instances (loaded lazily)
_ocr_model = None
_ocr_processor = None
_ocr_device = None
_ocr_dtype = None


def load_ocr_model(hf_token: Optional[str] = None, device: str = "auto") -> Tuple[Any, Any]:
    """
    Load LightOnOCR-2-1B model.

    Args:
        hf_token: Hugging Face token for model download
        device: Device to use ("cuda", "cpu", or "auto")

    Returns:
        Tuple of (model, processor)
    """
    global _ocr_model, _ocr_processor, _ocr_device, _ocr_dtype

    if _ocr_model is not None:
        return _ocr_model, _ocr_processor

    import torch
    from transformers import LightOnOcrForConditionalGeneration, LightOnOcrProcessor

    # Determine device
    if device == "auto":
        _ocr_device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        _ocr_device = device

    _ocr_dtype = torch.bfloat16 if _ocr_device == "cuda" else torch.float32

    print("Loading LightOnOCR-2-1B...")
    _ocr_processor = LightOnOcrProcessor.from_pretrained(
        "lightonai/LightOnOCR-2-1B",
        token=hf_token
    )

    _ocr_model = LightOnOcrForConditionalGeneration.from_pretrained(
        "lightonai/LightOnOCR-2-1B",
        torch_dtype=_ocr_dtype,
        token=hf_token
    ).to(_ocr_device)

    mem_gb = _ocr_model.get_memory_footprint() / 1e9
    print(f"LightOnOCR-2 loaded: {mem_gb:.2f} GB on {_ocr_device}")

    return _ocr_model, _ocr_processor


def run_ocr(image: Image.Image, model=None, processor=None) -> List[str]:
    """
    Run LightOnOCR-2 on an image.

    Args:
        image: PIL Image to process
        model: Optional pre-loaded model (uses global if None)
        processor: Optional pre-loaded processor (uses global if None)

    Returns:
        List of extracted text lines
    """
    global _ocr_model, _ocr_processor, _ocr_device, _ocr_dtype

    import torch

    # Use provided or global models
    ocr_model = model or _ocr_model
    ocr_processor = processor or _ocr_processor
    ocr_device = _ocr_device or "cuda"
    ocr_dtype = _ocr_dtype or torch.bfloat16

    if ocr_model is None or ocr_processor is None:
        raise RuntimeError("OCR model not loaded. Call load_ocr_model() first.")

    img = image.convert("RGB")
    conversation = [{"role": "user", "content": [{"type": "image", "image": img}]}]

    inputs = ocr_processor.apply_chat_template(
        conversation, add_generation_prompt=True, tokenize=True,
        return_dict=True, return_tensors="pt"
    )
    inputs = {
        k: v.to(device=ocr_device, dtype=ocr_dtype) if v.is_floating_point() else v.to(ocr_device)
        for k, v in inputs.items()
    }

    with torch.no_grad():
        output_ids = ocr_model.generate(**inputs, max_new_tokens=2048)

    generated_ids = output_ids[0, inputs["input_ids"].shape[1]:]
    output_text = ocr_processor.decode(generated_ids, skip_special_tokens=True)

    return [line.strip() for line in output_text.split('\n') if line.strip()]


def preprocess_ocr_text(ocr_lines: List[str]) -> List[str]:
    """
    Clean LightOnOCR-2 markdown/LaTeX output for regex parsing.

    LightOnOCR-2 outputs markdown-formatted text with LaTeX symbols.
    This function normalizes the output for downstream parsing.

    Args:
        ocr_lines: Raw OCR output lines

    Returns:
        Cleaned text lines
    """
    cleaned = []
    for line in ocr_lines:
        t = line.strip()
        # Skip image references and code blocks
        if t.startswith('![') or t.startswith('```') or not t:
            continue
        # Convert LaTeX diameter symbols to unicode
        t = t.replace('$\\oslash$', '\u2205')
        t = t.replace('$\\emptyset$', '\u2205')
        t = t.replace('$\\phi$', '\u03c6')
        t = t.replace('$\\times$', 'x')
        t = t.replace('$\\pm$', '\u00b1')
        t = t.replace('$\\degree$', '\u00b0')
        t = re.sub(r'\$\\[Oo]slash\$', '\u2205', t)
        # Strip markdown formatting
        t = re.sub(r'^#{1,6}\s*', '', t)  # headers
        t = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', t)  # bold/italic
        t = t.lstrip('- ')  # bullet points
        t = t.strip()
        if t:
            cleaned.append(t)
    return cleaned


# Regex patterns for engineering callout extraction
PATTERNS = {
    'metric_thread': r'M(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)',
    'metric_thread_class': r'M(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)\s*-\s*(6[HhGg])',
    'imperial_thread_unc': r'(\d+/\d+|\d+)\s*-\s*(\d+)\s*UNC',
    'imperial_thread_unf': r'(\d+/\d+|\d+)\s*-\s*(\d+)\s*UNF',
    'imperial_thread': r'(\d+/\d+)\s*[-]\s*(\d+)',
    'acme_thread': r'(\d+/\d+|\d+(?:\.\d+)?)\s*-\s*(\d+)\s*ACME',
    # Imperial holes (decimal inch without unit suffix)
    'thru_hole': r'[oO\u00d8\u2205\u03c6\u2300]?\s*\.?(\d+\.?\d*)\s*(?:THRU|THR)',
    'blind_hole': r'[oO\u00d8\u2205\u03c6\u2300]?\s*\.?(\d+\.?\d*)\s*[xX]\s*(\d+\.?\d*)\s*(?:DEEP|DP)',
    # Metric holes (with mm suffix) - convert to inches
    'metric_thru_hole': r'[oO\u00d8\u2205\u03c6\u2300]\s*(\d+\.?\d*)\s*mm\s*(?:THRU|THR)',
    'metric_blind_hole': r'[oO\u00d8\u2205\u03c6\u2300]\s*(\d+\.?\d*)\s*mm\s*[xX]\s*(\d+\.?\d*)\s*mm?\s*(?:DEEP|DP)',
    'metric_diameter': r'[oO\u00d8\u2205\u03c6\u2300]\s*(\d+\.?\d*)\s*mm',
    # Imperial diameter (decimal inch, no suffix)
    'diameter': r'[oO\u00d8\u2205\u03c6\u2300]\s*\.?(\d+\.?\d*)',
    'major_minor_dia': r'(?:MAJOR|MINOR|MAJ|MIN)\s*[oO\u00d8\u2205\u03c6\u2300]?\s*\.?(\d+\.?\d+)(?:\s*/\s*\.?(\d+\.?\d+))?',
    'fillet': r'(?<![A-Za-z])R\s*\.?(\d+\.?\d*)(?!\w)',
    'chamfer': r'\.?(\d+\.?\d*)\s*[xX]\s*45\s*[\u00b0]?',
    'counterbore': r"(?:CBORE|C'BORE|C-BORE)\s*[oO\u00d8\u2205\u03c6\u2300]?\s*\.?(\d+\.?\d*)",
    'countersink': r'(?:CSK|CSINK|C-SINK)\s*[oO\u00d8\u2205\u03c6\u2300]?\s*\.?(\d+\.?\d*)',
    # Dimension suffixes
    'ref_dim': r'\.?(\d+\.?\d*)\s*(?:\(REF\)|REF\.?)',
    'fab_dim': r'\.?(\d+\.?\d*)\s*\(F\)',
    'stk_dim': r'\.?(\d+\.?\d*)\s*STK\.?',
    'typ_dim': r'\.?(\d+\.?\d*)\s*TYP\.?',
    # GD&T
    'position_tol': r'\u2295\s*\.?(\d+\.?\d*)',  # ⊕ position
    'perpendicularity': r'\u27c2\s*\.?(\d+\.?\d*)',  # ⟂ perpendicularity
    'flatness': r'\u25b1\s*\.?(\d+\.?\d*)',  # ▱ flatness
    'concentricity': r'\u25ce\s*\.?(\d+\.?\d*)',  # ◎ concentricity
    # Surface finish
    'surface_finish': r'(\d+)\s*(?:Ra|μin|MICROINCH)',
}


def parse_ocr_callouts(ocr_lines: List[str], verbose: bool = False) -> List[Dict]:
    """
    Extract engineering callouts from OCR text.

    Preprocesses LightOnOCR-2 markdown/LaTeX, then applies regex patterns
    to extract threads, holes, fillets, chamfers, etc.

    Args:
        ocr_lines: Raw OCR output lines
        verbose: Print debug info

    Returns:
        List of callout dictionaries
    """
    callouts = []
    seen_raws = set()  # deduplicate

    # Preprocess: clean markdown/LaTeX
    cleaned_lines = preprocess_ocr_text(ocr_lines)
    raw_text = "\n".join(cleaned_lines)

    if verbose:
        print(f"  OCR preprocessing: {len(ocr_lines)} raw -> {len(cleaned_lines)} cleaned lines")

    # --- Metric threads with class (M10x1.5-6H) ---
    for match in re.finditer(PATTERNS['metric_thread_class'], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        seen_raws.add(raw)
        callouts.append({
            'calloutType': 'TappedHole',
            'thread': {
                'standard': 'Metric',
                'nominalDiameterMm': float(match.group(1)),
                'pitch': float(match.group(2)),
                'class': match.group(3).upper()
            },
            'raw': raw,
            'source': 'ocr'
        })

    # --- Metric threads (M6x1.0) ---
    for match in re.finditer(PATTERNS['metric_thread'], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        seen_raws.add(raw)
        callouts.append({
            'calloutType': 'TappedHole',
            'thread': {
                'standard': 'Metric',
                'nominalDiameterMm': float(match.group(1)),
                'pitch': float(match.group(2))
            },
            'raw': raw,
            'source': 'ocr'
        })

    # --- UNC threads (1/2-13 UNC) ---
    for match in re.finditer(PATTERNS['imperial_thread_unc'], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        seen_raws.add(raw)
        callouts.append({
            'calloutType': 'TappedHole',
            'thread': {
                'standard': 'Unified',
                'series': 'UNC',
                'size': match.group(1),
                'tpi': int(match.group(2))
            },
            'raw': raw,
            'source': 'ocr'
        })

    # --- UNF threads (1/4-28 UNF) ---
    for match in re.finditer(PATTERNS['imperial_thread_unf'], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        seen_raws.add(raw)
        callouts.append({
            'calloutType': 'TappedHole',
            'thread': {
                'standard': 'Unified',
                'series': 'UNF',
                'size': match.group(1),
                'tpi': int(match.group(2))
            },
            'raw': raw,
            'source': 'ocr'
        })

    # --- ACME threads ---
    for match in re.finditer(PATTERNS['acme_thread'], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        seen_raws.add(raw)
        callouts.append({
            'calloutType': 'TappedHole',
            'thread': {
                'standard': 'ACME',
                'size': match.group(1),
                'tpi': int(match.group(2))
            },
            'raw': raw,
            'source': 'ocr'
        })

    # --- Imperial threads (1/2-13) ---
    for match in re.finditer(PATTERNS['imperial_thread'], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        seen_raws.add(raw)
        callouts.append({
            'calloutType': 'TappedHole',
            'thread': {
                'standard': 'Imperial',
                'fraction': match.group(1),
                'tpi': int(match.group(2))
            },
            'raw': raw,
            'source': 'ocr'
        })

    # --- Metric through holes (with mm suffix) - convert to inches ---
    for match in re.finditer(PATTERNS['metric_thru_hole'], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        seen_raws.add(raw)
        dia_mm = float(match.group(1))
        callouts.append({
            'calloutType': 'Hole',
            'diameterInches': dia_mm / 25.4,
            'diameterMm': dia_mm,
            'isThrough': True,
            'raw': raw,
            'source': 'ocr',
            'units': 'metric'
        })

    # --- Metric blind holes (with mm suffix) - convert to inches ---
    for match in re.finditer(PATTERNS['metric_blind_hole'], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        seen_raws.add(raw)
        dia_mm = float(match.group(1))
        depth_mm = float(match.group(2))
        callouts.append({
            'calloutType': 'Hole',
            'diameterInches': dia_mm / 25.4,
            'diameterMm': dia_mm,
            'depthInches': depth_mm / 25.4,
            'depthMm': depth_mm,
            'isThrough': False,
            'raw': raw,
            'source': 'ocr',
            'units': 'metric'
        })

    # --- Through holes ---
    for match in re.finditer(PATTERNS['thru_hole'], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        seen_raws.add(raw)
        callouts.append({
            'calloutType': 'Hole',
            'diameterInches': float(match.group(1)),
            'isThrough': True,
            'raw': raw,
            'source': 'ocr'
        })

    # --- Blind holes ---
    for match in re.finditer(PATTERNS['blind_hole'], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        seen_raws.add(raw)
        callouts.append({
            'calloutType': 'Hole',
            'diameterInches': float(match.group(1)),
            'depthInches': float(match.group(2)),
            'isThrough': False,
            'raw': raw,
            'source': 'ocr'
        })

    # --- Counterbores ---
    for match in re.finditer(PATTERNS['counterbore'], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        seen_raws.add(raw)
        callouts.append({
            'calloutType': 'Counterbore',
            'diameterInches': float(match.group(1)),
            'raw': raw,
            'source': 'ocr'
        })

    # --- Countersinks ---
    for match in re.finditer(PATTERNS['countersink'], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        seen_raws.add(raw)
        callouts.append({
            'calloutType': 'Countersink',
            'diameterInches': float(match.group(1)),
            'raw': raw,
            'source': 'ocr'
        })

    # --- Fillets ---
    for match in re.finditer(PATTERNS['fillet'], raw_text):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        seen_raws.add(raw)
        callouts.append({
            'calloutType': 'Fillet',
            'radiusInches': float(match.group(1)),
            'raw': raw,
            'source': 'ocr'
        })

    # --- Chamfers ---
    for match in re.finditer(PATTERNS['chamfer'], raw_text):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        seen_raws.add(raw)
        callouts.append({
            'calloutType': 'Chamfer',
            'sizeInches': float(match.group(1)),
            'angle': 45,
            'raw': raw,
            'source': 'ocr'
        })

    # --- Metric diameters (with mm suffix) - convert to inches ---
    for match in re.finditer(PATTERNS['metric_diameter'], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        # Skip if already matched as hole
        if any(raw in c.get('raw', '') for c in callouts):
            continue
        seen_raws.add(raw)
        dia_mm = float(match.group(1))
        callouts.append({
            'calloutType': 'Hole',  # Treat as hole for comparison
            'diameterInches': dia_mm / 25.4,
            'diameterMm': dia_mm,
            'isThrough': None,  # Unknown depth
            'raw': raw,
            'source': 'ocr',
            'units': 'metric'
        })

    # --- Plain diameters (not caught by other patterns) ---
    for match in re.finditer(PATTERNS['diameter'], raw_text):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        # Skip if this looks like part of another callout
        if any(raw in c.get('raw', '') for c in callouts):
            continue
        # Skip if followed by 'mm' (already caught by metric_diameter)
        start_pos = match.start()
        end_pos = match.end()
        if end_pos < len(raw_text) and raw_text[end_pos:end_pos+2].lower() == 'mm':
            continue
        seen_raws.add(raw)
        callouts.append({
            'calloutType': 'Diameter',
            'diameterInches': float(match.group(1)),
            'raw': raw,
            'source': 'ocr'
        })

    return callouts


def clear_ocr_model():
    """Clear the loaded OCR model from memory."""
    global _ocr_model, _ocr_processor, _ocr_device, _ocr_dtype
    import gc
    import torch

    _ocr_model = None
    _ocr_processor = None
    _ocr_device = None
    _ocr_dtype = None

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
