# Hybrid YOLO-OBB + OCR/VLM Engineering Drawing Inspector — Build Order (Runnable Milestones)

**Purpose:** Give Claude a clear, step-by-step build plan where the repo is **runnable after every milestone**.  
**Goal:** Implement the pipeline in the enforced order:

> extract → unit-normalize → validate → expand both → match → score

Each milestone includes:
- What to implement
- What you can run immediately
- Definition of done (DoD)

---

## M0 — Project scaffold + contracts (≈1 hour)

### Implement
Create the folder structure (empty files are fine initially):

```
ai_inspector/
  __init__.py
  config.py
  pipeline.py

  detection/
    __init__.py
    classes.py
    yolo_detector.py

  extractors/
    __init__.py
    cropper.py
    rotation.py
    canonicalize.py
    ocr_adapter.py
    patterns.py
    crop_reader.py
    unit_normalizer.py
    validator.py
    vlm.py  # stub for now

  schemas/
    callout_schema.py
    callout_packet.py

  comparison/
    matcher.py
    quantity_expander.py
    sw_extractor.py  # existing

  fine_tuning/
    data_generator.py
    evaluate.py

datasets/
  callouts.yaml
  sidecar_schema.json
```

Define contracts early (prevents coupling issues later):

**Detection output dict**
```python
{"class": str, "confidence": float, "obb_points": [[x,y]*4], "xywhr": list|None, "det_id": str}
```

**Crop output dict**
```python
{"image": PIL.Image, "meta": {...}}
```

**OCR adapter**
```python
read(image)->(text:str, score:float, meta:dict)
read_with_boxes(image)->optional
```

**Reader output (pre-validation)**
```python
{"calloutType": str, "raw": str, ...optional fields...}
```

### Run
- Ensure imports work.

### DoD
- `python -c "import ai_inspector"` runs with zero errors
- No circular imports

---

## M1 — YOLO11-OBB detection + safe parsing (foundation)

### Implement
- `detection/classes.py`: single source of truth for class names + mapping
- `detection/yolo_detector.py`:
  - loads YOLO OBB model
  - returns list of detection dicts using **named attributes** (no hardcoded indices)
  - create stable `det_id` (e.g., `f"{page_id}_{i}"`)

### Run
- Load one rendered drawing PNG and print:
  - total detections
  - top classes + confidences

### DoD
- Detection outputs include:
  - correct `class` names
  - confidence float
  - `obb_points` shape is always 4x2

---

## M2 — OBB cropper with padding + minimum crop constraints

### Implement
- `extractors/cropper.py`
  - input: image + `obb_points`
  - output: rotated crop “as horizontal as possible”
  - support `pad_ratio` (10–25%)
  - enforce **minimum crop size** (expand if too small)
  - store meta: `pad_ratio`, `crop_w`, `crop_h`, `det_id`

### Run
- Save crops to `debug/crops/` and visually inspect 10–20 crops

### DoD
- Crops consistently include full callout text (no clipped ⌀, qty, “DEEP”, etc.)

---

## M3 — Rotation selection (0/90/180/270) + text quality scoring

### Implement
- `extractors/rotation.py`
  - run OCR on rotations {0,90,180,270}
  - pick best via `_compute_text_quality(text, yolo_class)`
  - return `{raw, rotation_used, quality_score}`

### Run
- On ~20 crops, print:
  - chosen rotation
  - OCR text
  - quality score

### DoD
- Fewer upside-down/sideways transcriptions
- Every crop has `rotation_used`

---

## M4 — OCR adapter + canonicalization (stabilize text before parsing)

### Implement
- `extractors/ocr_adapter.py`
  - wrapper around actual OCR model
  - returns `(text, confidence, meta)`
- `extractors/canonicalize.py`
  - normalize symbols BEFORE parsing + CER/WER:
    - `Ø/ø/∅ -> ⌀`
    - `″ -> "`
    - `× -> x`
    - collapse whitespace

### Run
- OCR 20 crops and print:
  - raw OCR
  - canonicalized text
  - confidence

### DoD
- Canonicalized text is stable/consistent
- Confidence exists (even if heuristic-derived)

---

## M5 — Regex parser per YOLO class + OCR confidence gate

### Implement
- `extractors/patterns.py`: regex patterns per callout type
- `extractors/crop_reader.py`:
  1) OCR + canonicalize
  2) regex parse based on YOLO class → calloutType
  3) if regex fails OR OCR quality < threshold → VLM fallback (stub ok)
  4) always return dict with `"raw"`

**Note:** Even if regex matches, allow VLM fallback when OCR looks suspicious.

### Run
- On 1 page:
  - detect → crop → read → print structured callouts

### DoD
- Structured outputs for common: Hole / Fillet / Chamfer / TappedHole
- OCR junk isn’t accepted as valid just because regex matched

---

## M6 — CalloutPacket provenance tracking (debug superpower)

### Implement
- `schemas/callout_packet.py` dataclass
- Every detection becomes a packet; packet accumulates:
  - detection meta
  - crop meta
  - OCR raw + confidence + rotation
  - parsed callout dict

### Run
- Save `debug/packets_page0.json`

### DoD
- You can answer: “why did this become Unknown/Extra?” quickly
- Every callout has provenance

---

## M7 — Unit normalization (drawing-level → callout-level → dual hypothesis)

### Implement
- `extractors/unit_normalizer.py`
  - REQUIRE title block OCR text input (don’t guess if you can OCR)
  - implement:
    1) drawing-level detection from title block
    2) callout-level patterns
    3) dual-hypothesis when both unknown (pick plausible SW match)

Store:
- `normalization_method`
- `_detected_units`
- `_drawing_units`

### Run
- One known imperial drawing + one known metric drawing:
  - verify normalized inches are correct vs expectation

### DoD
- Metric drawings stop systematically failing vs SW inches
- Every packet has unit provenance fields

---

## M8 — Validation + repair (Unknown/_invalid) + schema enforcement

### Implement
- `schemas/callout_schema.py`: matcher-native schema rules
- `extractors/validator.py`:
  - validate_callout
  - validate_and_repair_all

**Rule:** Invalid outputs become:
- `calloutType="Unknown"`
- `_invalid=True`
- `_validation_error="..."`

### Run
- Feed 50 callouts through validation and count:
  - valid
  - unknown/_invalid

### DoD
- No callout reaches matching without `"raw"`
- Invalid outputs become Unknown + _invalid + reason (not dropped)

---

## M9 — Quantity expansion BOTH sides (critical)

### Implement
- `comparison/quantity_expander.py`
  - expand drawing callouts by quantity
  - expand SW features by quantity (instanceCount / edgeCount)
  - `expand_both_sides()` used BEFORE matching and evaluation

### Run
- Synthetic test:
  - SW hole qty=4
  - drawing hole qty=4
  - verify post-expansion both lists length = 4

### DoD
- Expanded instance counts match expected quantities

---

## M10 — Matcher upgrades + scoring (SKIPPED + depth tie-break)

### Implement
In `comparison/matcher.py`:
- Add `MatchStatus.SKIPPED`
- FUTURE_TYPES → SKIPPED (excluded from denominators)
- Depth-aware tie-break:
  - depth is a penalty/tie-break AFTER diameter passes (not a hard reject)
- Ensure matcher reads exactly the expected schema keys

In scoring:
- SKIPPED excluded from denominators
- EXTRA included (penalized)
- TOLERANCE_FAIL included in denominators

### Run
- Match on 1 part and output:
  - counts: matched/missing/extra/skipped/tolerance_fail
  - instance_match_rate

### DoD
- Slot/Bend no longer penalize (SKIPPED)
- Quantity expansion improves match rate (visible immediately)

---

## M11 — Pipeline orchestrator (one command runner)

### Implement
- `pipeline.py` wires:
  - load/render page PNG
  - detect
  - crop
  - OCR + rotation selection
  - parse
  - normalize units
  - validate + repair
  - expand both
  - match
  - score
  - dump debug artifacts: packets + crops + results

### Run
Example CLI:
```bash
python -m ai_inspector.pipeline --image path/to/page.png --sw path/to/sw.json --out debug/run_001
```

### DoD
One command outputs:
- `packets.json`
- `results.json`
- `metrics.json`
- `debug/crops/`

---

## M12 — Evaluation harness (sidecar GT + IoU pairing)

### Implement
In `fine_tuning/evaluate.py`:
- load sidecar GT
- detection eval (OBB polygon IoU preferred; proxy ok for fast iteration)
- IoU pairing (never zip predictions to GT)
- transcription CER/WER on paired only
- parsing accuracy on paired only
- matching metrics computed on expanded instances

### Run
- Evaluate on a small golden set

### DoD
- You get a clear table of stage metrics
- You can identify bottleneck stage quickly (detect vs OCR vs parse vs match)

---

## Daily iteration loop (recommended)
1) Run pipeline on 5 pages
2) Sort failures by stage:
   - detection miss
   - OCR low quality
   - parsing mismatch
   - unit mismatch
   - tolerance fails
3) Fix highest-leverage stage first

---

## Next best immediate step
Start with **M1 + M2** (YOLO detect → padded crops saved to disk).  
Most drawing pipelines succeed or fail right here.
