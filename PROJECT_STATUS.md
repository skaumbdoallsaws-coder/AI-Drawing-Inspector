# AI Engineering Drawing Inspector - Project Status

**Last Updated:** February 14, 2026

---

## Project Goal

Build an AI-powered system that **verifies engineering drawings (PDFs) against CAD model data** from SolidWorks. The inspector checks that drawings contain all required features (thread callouts, hole dimensions, tolerances) that match the CAD model specifications.

---

## Current Status: Dual-Approach Inspection (YOLO+OCR Pipeline + Spatial Vision Inspection)

### Latest Milestone (February 14, 2026)

**Spatial Inspection Notebook — Multi-Page Drawing Support:**
- Reviewed and validated `spatial_inspection.ipynb` end-to-end
- **Multi-page drawing support implemented**: `DRAWING_PATH` now accepts three input formats:
  - Single file path (backward compatible): `"drawing.png"` or `"drawing.pdf"`
  - List of paths: `["sheet1.png", "sheet2.png"]`
  - Glob pattern: `"drawing_samples_batch/*_1008176_*.png"`
  - PDFs automatically extract all pages (previously only rendered page 1)
- **Page-labeled API calls**: Each page sent as `[PAGE X of Y]` labeled image blocks in a single Claude Vision request
- **Cross-page inspection**: Prompt updated to instruct Claude to check ALL sheets before marking a feature MISSING
- **`found_on_page` tracking**: Findings JSON now records which page(s) each feature was found on; display table includes Page column
- Tested on 3 parts:
  - **178683 (CLEVIS)**: 2/2 features present, 100% completeness (prior run, single page)
  - **1008175 (PLATE WEAR)**: 2/2 features present, 85% completeness (single page, dinged for missing views)
  - **1008176 (RACK VISE)**: 4/7 features present, 57% completeness — tested both single-page and multi-page (machining + casting sheets); multi-page correctly identified "Two-page drawing set" and reported features found across both pages

**Spatial Inspection Pipeline Summary (not new, but now documented):**
- Pre-built spatial profiles exist for 100+ parts in `400S_Sorted_Library` (generated once via `generate_inspection_profiles.py`)
- Profile generation: 4 rendered CAD views + SW JSON → Claude Vision → spatial feature descriptions (no dimensions, spatial understanding only)
- Inspection: Profile primes Claude Vision with what to look for → drawing image(s) sent → structured findings JSON → GPT-4o-mini QC report
- No GPU required — runs entirely on API calls (Claude + OpenAI)

**Files Changed:**
- `spatial_inspection.ipynb` — Cells 2 (config docs), 3 (load logic), 4 (multi-image API call), 5 (page column in display)

### Previous Milestone (February 11, 2026)

**Assembly Context + Improved Reporting:**
- **Mating context** wired: `sw_mating_context.json` (62 parts) provides parent assembly + sibling components
- **Mate specifications** wired: `sw_mate_specs.json` (40 parts, 100 mate relationships) provides Concentric/Coincident mates + thread specs (M10x1.5, M8x1.25)
- **Old↔new part number bridging**: `sw_part_context_complete.json` (597 entries) maps between old-style (046, 017-134) and new-style (314884, 199680) part numbers — enables cross-reference when mate_specs uses old keys
- **Sibling cross-reference**: When a part isn't directly in mate_specs, the pipeline looks up its siblings from mating_context, resolves their old PNs via part_context, and collects their mate specs — e.g., 314884 (PAWL) → sibling 199680 → old PN "B18.3.1M - 10 x 1.5 x 30 Hex SHCS" → Concentric mate found
- **GPT-4o report upgraded**: Pre-computed severity summaries (critical vs minor missing, detection coverage assessment, assembly-driven findings, extra↔missing correlations) replace raw JSON dumps — report now has severity tiers, detection caveats, and prioritized next steps
- **Part 314884 (PAWL) end-to-end**: 4 detections, 1 matched (R0.030" fillet), 12 missing (1 critical TappedHole + 11 minor fillets), 3 extra — mating context found (assembly 047-263, 5 siblings), mate specs found via sibling cross-reference (M10x1.5 Concentric mate)
- **Pipeline runtime**: ~380s with VLM enabled (RTX 4000 Ada, 12.9 GB VRAM)

### OCR Quick Wins Implemented (February 11, 2026 - PM)

**Implemented and verified in full pipeline path (not a side notebook):**
- **Canonicalization improvements** in `ai_inspector/extractors/canonicalize.py`:
  - Added stronger diameter-symbol normalization (phi/theta/mojibake variants)
  - Added LaTeX cleanup (`\phi`, `\frac{33}{64}`, etc.) and decimal-repair handling
- **Regex parse improvements** in `ai_inspector/extractors/patterns.py`:
  - Added drill parsing without explicit diameter symbol (e.g., `33/64 DRILL`)
  - Added `THRU ALL` handling and more tolerant tapped-hole parsing for noisy OCR separators
- **OCR robustness in crop reading** in `ai_inspector/extractors/crop_reader.py`:
  - Added hallucinated-tail stripping to remove explanatory prose appended after valid callout text
- **OCR retry behavior** in `ai_inspector/extractors/ocr_adapter.py`:
  - Added confidence-gated second OCR pass with larger crop/token budget and best-pass selection
- **Comparison resilience** in `ai_inspector/comparison/matcher.py`:
  - Added hole↔tapped-hole equivalence matching by diameter (for tap-drill style callouts)
  - Added fallback thread matching from top-level `threadSize`/`pitch` when nested `thread` is absent
  - Added guard to ignore clearly implausible OCR pitch values (prevents false thread mismatches)
- **YOLO post-filtering** in `ai_inspector/pipeline/yolo_pipeline.py`:
  - Added class-specific confidence thresholds to reduce low-confidence false positives

**Validation result (local full notebook run):**
- `tests/notebooks/test_full_pipeline.ipynb` executed successfully to `tests/notebooks/test_full_pipeline_executed_local.ipynb`
- Latest summary for part **314884**: `matched=1, missing=12, extra=1` with `detection_count=2`
- The matched feature is now an **equivalent Hole↔TappedHole** correlation on the `⌀.52 / 33/64 DRILL` style case

### Previous Milestone (February 9, 2026)

**Full 4-Model Pipeline Running Locally:**
- Sequential model loading: YOLO detect → unload → OCR read → unload → VLM page understanding → unload → match → score → GPT-4o report
- Qwen2.5-VL-7B wired for holistic page understanding (title block, tolerances, notes, drawing type, surface finish)
- GPT-4o wired for assembly-aware QC report generation via OpenAI API
- All stages execute without errors on RTX 4000 Ada (12.9 GB VRAM), Python 3.14, Windows 11
- Drawing 176759: 2/2 holes matched (100% instance match rate)
- Drawing 314884 (PAWL): Full pipeline with VLM + mating context + GPT-4o report

### Previous Milestone (February 5, 2026)

**YOLO-OBB Finetuning Complete:**
- Trained YOLO11s-OBB on 224 annotated drawings (550 annotations)
- 4 callout classes: Hole, TappedHole, Fillet, Chamfer
- **mAP50 = 0.729** (target was 0.5) — all classes above 0.70
- Model uploaded to HuggingFace: `hf://shadrack20s/ai-inspector-callout-detection/callout_v2_yolo11s-obb_best.pt`

### What's New in v4.0

v4 introduces a **modular Python package architecture** with **drawing type classification**. Different drawing types (machined parts, weldments, sheet metal, etc.) have different inspection requirements and are handled by specialized analyzers.

**Key Changes from v3:**
- **Modular package structure** (`ai_inspector/`) instead of monolithic notebook
- **Drawing type classifier** determines how to process each drawing
- **Type-specific analyzers** with appropriate feature extraction
- **Conditional OCR** based on drawing type (weldments skip OCR)
- **Slim notebook** (~80 lines) as orchestrator only

### v4 vs v3 Comparison

| Aspect | v3 (Current) | v4 (New) |
|--------|--------------|----------|
| Code structure | Single 300KB notebook | Python package + slim notebook |
| Drawing classification | Page type only (PART_DETAIL/ASSEMBLY) | Full type (7 categories) |
| OCR decision | Based on page type | Based on drawing type |
| Feature extraction | Same for all drawings | Type-specific |
| Testability | Manual notebook runs | Unit tests + integration tests |
| Maintainability | Difficult | Modular, easy to extend |

### Architecture (v4.0) — Model Roles

**Four models, four distinct roles — no overlap. Three GPU models load/unload sequentially (peak ~5.5 GB VRAM):**

| Model | Role | Input | Output | VRAM |
|-------|------|-------|--------|------|
| **YOLO11s-OBB** | Locate + classify callouts | Full page image | Bounding boxes + class labels | ~0.04 GB |
| **LightOnOCR-2-1B** | Read text in each crop | Cropped callout image | Raw text + confidence | ~2.02 GB |
| **Qwen2.5-VL-7B** | Holistic page understanding | Full page image | Title block, notes, context | ~4.5 GB |
| **GPT-4o (API)** | Write QC report | Pre-computed summaries JSON | Severity-tiered pass/fail report | — |

**Assembly context databases (CPU-only, loaded alongside comparison):**

| Database | Entries | Provides |
|----------|---------|----------|
| `sw_mating_context.json` | 62 | Parent assembly, sibling components |
| `sw_mate_specs.json` | 40 | Concentric/Coincident mates, thread specs |
| `sw_part_context_complete.json` | 597 | Old↔new part number mapping for cross-reference |

```
┌─────────────────┐
│  PDF Drawing    │
└────────┬────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────────────┐
│  ai_inspector package                                               │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  STAGE 1: Drawing Type Classification                         │  │
│  │  classifier/drawing_classifier.py                             │  │
│  │  → MACHINED_PART | SHEET_METAL | WELDMENT | ASSEMBLY          │  │
│  │  → CASTING | PURCHASED_PART | GEAR                            │  │
│  │  → Returns: type, confidence, use_ocr, use_qwen               │  │
│  └──────────────────────────┬───────────────────────────────────┘  │
│                             │                                       │
│  ┌──────────────────────────▼───────────────────────────────────┐  │
│  │  STAGE 2: Type-Specific Analyzer                              │  │
│  │  analyzers/{type}.py                                          │  │
│  │  ┌─────────────────┐  ┌─────────────────┐                     │  │
│  │  │ BaseAnalyzer    │  │ Type-Specific   │                     │  │
│  │  │ - title_block   │  │ - OCR (if used) │                     │  │
│  │  │ - quality_audit │  │ - Qwen prompts  │                     │  │
│  │  │ - best_practices│  │ - feature focus │                     │  │
│  │  └─────────────────┘  └─────────────────┘                     │  │
│  └──────────────────────────┬───────────────────────────────────┘  │
│                             │                                       │
│  ┌──────────────────────────▼───────────────────────────────────┐  │
│  │  STAGE 3: Comparison                                          │  │
│  │  comparison/matcher.py + diff_result.py                       │  │
│  │  → Type-aware matching rules                                  │  │
│  │  → Mate-derived requirements (from assembly context)          │  │
│  └──────────────────────────┬───────────────────────────────────┘  │
│                             │                                       │
│  ┌──────────────────────────▼───────────────────────────────────┐  │
│  │  STAGE 4: Report Generation                                   │  │
│  │  report/qc_report.py                                          │  │
│  │  → Type-aware emphasis (weld symbols for weldments, etc.)     │  │
│  │  → Assembly context integration                               │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────┐
│  QC Report      │
│  PASS / FAIL    │
│  + details      │
└─────────────────┘
```

---

## Drawing Types Supported (v4.0)

| Type | % of Library | Use OCR? | Key Features | Critical Checks |
|------|--------------|----------|--------------|-----------------|
| **MACHINED_PART** | 71% | ✓ Yes | holes, threads, GD&T, tolerances | Thread callouts, hole dims |
| **SHEET_METAL** | 10% | ✓ Yes | bends, flat pattern, slots | Bend callouts, (F) dims |
| **ASSEMBLY** | 11% | ✗ No | BOM, balloons, assembly notes | BOM complete, balloons match |
| **WELDMENT** | 4% | ✗ No | weld symbols, BOM, weld callouts | Weld symbols present |
| **CASTING** | 2% | ✓ Yes | critical dims, reference dims | Critical features only |
| **PURCHASED_PART** | 2% | ✗ No | manufacturer table | Cross-reference present |
| **GEAR** | <1% | ✓ Yes | gear data table | Teeth, pitch, pressure angle |

---

## Package Structure (v4.0)

```
AI-tool/
├── ai_inspector/                    # Python package
│   ├── __init__.py                  # Package root, exports main functions
│   │
│   ├── classifier/
│   │   ├── __init__.py
│   │   └── drawing_classifier.py    # Type classification logic ✓ IMPLEMENTED
│   │
│   ├── analyzers/
│   │   ├── __init__.py
│   │   ├── base.py                  # Shared logic (title block, quality)
│   │   ├── machined_part.py         # OCR + Qwen, threads, GD&T
│   │   ├── sheet_metal.py           # Bends, flat pattern
│   │   ├── weldment.py              # Weld symbols, BOM
│   │   ├── assembly.py              # BOM, balloons
│   │   ├── casting.py               # Reference dims
│   │   └── purchased_part.py        # Manufacturer table
│   │
│   ├── extractors/
│   │   ├── __init__.py
│   │   ├── ocr.py                   # LightOn OCR wrapper
│   │   ├── vlm.py                   # Qwen VLM wrapper
│   │   └── title_block.py           # Title block parsing
│   │
│   ├── comparison/
│   │   ├── __init__.py
│   │   ├── matcher.py               # Feature matching
│   │   └── diff_result.py           # DiffResult generation
│   │
│   ├── report/
│   │   ├── __init__.py
│   │   └── qc_report.py             # GPT-4o-mini report
│   │
│   └── utils/
│       ├── __init__.py
│       ├── pdf_render.py            # PDF → image
│       ├── sw_library.py            # SolidWorks JSON library
│       └── schemas.py               # Type definitions
│
├── notebooks/
│   └── ai_inspector_v4.ipynb        # Slim orchestrator (~80 lines)
│
├── tests/
│   ├── test_classifier.py
│   ├── test_analyzers.py
│   └── golden_set/                  # Reference drawings + expected outputs
│
├── setup.py                         # ✓ IMPLEMENTED
├── pyproject.toml                   # ✓ IMPLEMENTED
└── PROJECT_STATUS.md                # This file
```

---

## v4.0 Implementation Progress

### Core Infrastructure
| Phase | Module | Status | Notes |
|-------|--------|--------|-------|
| 1 | `classifier/drawing_classifier.py` | ✅ DONE | Classification logic from 258 drawing analysis |
| 2 | `setup.py` + `pyproject.toml` | ✅ DONE | Editable install support |
| 3 | Package skeleton (`__init__.py` files) | ✅ DONE | All directories created |
| 4 | `utils/pdf_render.py` | ✅ DONE | PDF rendering with PyMuPDF |
| 5 | `utils/sw_library.py` | ✅ DONE | SolidWorks JSON library manager |
| 6 | `extractors/ocr.py` | ✅ DONE | LightOnOCR-2 wrapper + callout parsing |
| 7 | `extractors/vlm.py` | ✅ DONE | Qwen2.5-VL wrapper + all prompts |
| 8 | `config.py` | ✅ DONE | Central configuration dataclass |

### YOLO-OBB Detection Pipeline (M0-M12)
| Module | Component | Status | Notes |
|--------|-----------|--------|-------|
| M1 | `detection/yolo_detector.py` | ✅ DONE | YOLO11-OBB inference wrapper |
| M2 | `extractors/cropper.py` | ✅ DONE | OBB crop extraction with padding |
| M3 | `extractors/rotation.py` | ✅ DONE | 4-rotation OCR quality selector |
| M4 | `extractors/ocr_adapter.py` | ✅ DONE | LightOnOCR-2 with confidence |
| M5 | `extractors/crop_reader.py` | ✅ DONE | OCR → parse → VLM fallback |
| M6 | `schemas/callout_packet.py` | ✅ DONE | Provenance tracking dataclass |
| M7 | `extractors/unit_normalizer.py` | ✅ DONE | Inch/mm detection + conversion |
| M8 | `extractors/validator.py` | ✅ DONE | Schema validation + repair |
| M9 | `comparison/quantity_expander.py` | ✅ DONE | 4X → 4 instances expansion |
| M10 | `comparison/matcher.py` | ✅ DONE | Type-aware feature matching |
| M11 | `pipeline/yolo_pipeline.py` | ✅ DONE | Full pipeline orchestrator |
| M12 | `fine_tuning/evaluate.py` | ✅ DONE | Evaluation harness |

### YOLO Finetuning
| Step | Status | Notes |
|------|--------|-------|
| Image selection | ✅ DONE | 224 images from PDF VAULT + machined parts |
| Roboflow annotation | ✅ DONE | 550 annotations across 4 classes |
| Training notebook | ✅ DONE | `notebooks/train_yolo_obb.ipynb` with TensorBoard |
| Model training | ✅ DONE | yolo11s-obb, mAP50=0.729, early stop at epoch 81 |
| HuggingFace upload | ✅ DONE | `shadrack20s/ai-inspector-callout-detection` |
| Config update | ✅ DONE | Default model points to HuggingFace |

### Test Notebooks
| Notebook | Tests | Status |
|----------|-------|--------|
| `test_detection.ipynb` | M1 + M2 (YOLO + Cropping) | ✅ Created, ⏳ Not validated |
| `test_ocr_pipeline.ipynb` | M3 + M4 + M5 (Rotation + OCR + Parse) | ⚠️ Deprecated for primary validation (full pipeline is source of truth) |
| `test_normalize_validate.ipynb` | M7 + M8 (Units + Validation) | ✅ Created, ⏳ Not validated |
| `test_matching.ipynb` | M9 + M10 (Expansion + Matching) | ✅ Created, ⏳ Not validated |
| `test_full_pipeline.ipynb` | Full end-to-end | ✅ Created, ✅ Validated locally (Feb 11 PM run) |

### VLM + Assembly Context + Reporting (Feb 9-11)
| Module | Component | Status | Notes |
|--------|-----------|--------|-------|
| M13 | `extractors/vlm.py` wired into pipeline | ✅ DONE | Sequential load/unload, Qwen2.5-VL-7B |
| M14 | `extractors/prompts.py` PAGE_UNDERSTANDING | ✅ DONE | Title block, tolerances, notes, drawing type |
| M15 | `utils/context_db.py` mating context | ✅ DONE | load_mating_context(), get_mating_context() |
| M16 | `utils/context_db.py` mate specs | ✅ DONE | load_mate_specs(), get_mate_specs(), sibling cross-ref |
| M17 | `utils/context_db.py` part context bridging | ✅ DONE | load_part_context(), old↔new PN mapping |
| M18 | Pipeline assembly context wiring | ✅ DONE | mating_context_path, mate_specs_path, part_context_path |
| M19 | GPT-4o report with pre-computed summaries | ✅ DONE | Severity tiers, detection caveat, assembly findings |

### Remaining Work
| Phase | Module | Status | Notes |
|-------|--------|--------|-------|
| 9 | OCR post-processing quick wins | ⚙️ IN PROGRESS | Implemented core quick wins in canonicalize/parse/matcher; next is broader symbol coverage and regression hardening |
| 10 | OCR fine-tuning on drawing crops | ⏳ PENDING | 200-500 labeled crops needed |
| 11 | More YOLO classes (GD&T, Datum, Weld, etc.) | ⏳ PENDING | Annotate + retrain (14-class taxonomy ready) |
| 12 | 3D spatial context — Phase 1: multi-view renders | ⏳ PLANNED | SolidWorks API view rendering → multi-image GPT-4o |
| 13 | 3D spatial context — Phase 2: assembly renders | ⏳ PLANNED | Exploded view + highlighted part → GPT-4o |
| 14 | 3D spatial context — Phase 3: VLM-guided discovery | ⏳ PLANNED | 3D-highlighted feature → find on 2D drawing |
| 15 | Other analyzers (sheet metal, weldment, etc.) | ⏳ PENDING | One at a time |

---

## Known Limitations

### OCR Quality (Primary Bottleneck)

LightOnOCR-2-1B is a general-purpose document OCR model. It was **not trained on engineering drawings**, which causes:

| Issue | Example | Impact |
|-------|---------|--------|
| **LaTeX / symbol output** | `$\phi$ 1.28`, `\frac{33}{64}` | Quick-win canonicalization now converts common forms, but not all symbol families |
| **Hallucination** | Generates paragraphs about "project planning" after reading a hole callout | Garbage text after first line; regex grabs first valid match |
| **Non-deterministic** | Same image produces different text on different runs | Inconsistent parse results |
| **Symbol blindness** | Cannot reliably read GD&T symbols, weld symbols, datum references | These are graphical symbols not in its training data |
| **Low recall interaction** | OCR improvements applied, but only 2 detections on latest 314884 run | OCR can only improve what YOLO crops; low detection coverage still dominates misses |

**Root cause:** Same as YOLO before fine-tuning — the model has never seen domain-specific data.

### YOLO Detection Coverage

Currently trained on **4 classes only**: Hole, TappedHole, Fillet, Chamfer. Missing:
- GD&T feature control frames
- Datum references
- Weld symbols
- Surface finish callouts
- Bend callouts (sheet metal)
- General dimensions and tolerances
- Notes and special instructions

### Pipeline Gaps

- ~~**Qwen VLM not wired in**~~ ✅ Wired (Feb 9) — sequential load/unload in pipeline
- ~~**GPT-4o report not connected**~~ ✅ Wired (Feb 9) — pre-computed summaries + severity-tiered prompt
- ~~**Assembly context missing**~~ ✅ Wired (Feb 11) — mating context + mate specs + old/new PN bridging
- **OCR accuracy on domain symbols** — improved via quick wins (LaTeX/fraction normalization, hallucination trimming, tolerant parsing), but still weak on GD&T and noisy thread formats; fine-tuning remains necessary
- **YOLO detection coverage** — still the dominant bottleneck; latest full run on 314884 had detection_count=2, which constrains end-to-end match rate
- **SW extractor** only reads from `comparison.holeGroups` fallback — doesn't handle all C# extractor sections (slots, chamfers, fillets in comparison)
- **No 3D spatial context** — VLM only sees 2D drawing; no visual understanding of the 3D part geometry or assembly interfaces

---

## Next Steps (Priority Order)

### 1. OCR Improvement (Foundation — Fixes Match Rate)

OCR is the weakest link. A misread decimal (⌀.52 → ⌀52) makes the comparison engine unable to match valid features. Two tracks:

**Track A: Quick Wins (implemented; continue hardening)**
- ✅ **Implemented:** canonicalization/post-processing rules in `canonicalize.py` (LaTeX cleanup, symbol normalization, decimal repair)
- ✅ **Implemented:** parser hardening in `patterns.py` (`33/64 DRILL`, `THRU ALL`, noisy tapped-hole separators)
- ✅ **Implemented:** OCR hallucination tail stripping in `crop_reader.py`
- ✅ **Implemented:** OCR retry path in `ocr_adapter.py` and matcher resilience updates in `comparison/matcher.py`
- **Immediate next hardening:** build/expand locked regression cases for symbol-heavy and noisy-thread callouts, then tune thresholds using measurable pass/fail benchmarks

**Track B: Fine-Tuning LightOnOCR (medium-term)**
- **Dataset source:** YOLO crops saved to `debug/*/crops/` — these are the input images
- **Labels needed:** Manually transcribe each crop with correct text (e.g., `⌀.750 THRU`, `M6x1.0-6H`)
- **Dataset size:** Target 200-500 labeled crops for initial fine-tune, 2,000-5,000 for production
- **Note:** This is different data from YOLO training — YOLO annotations are bounding boxes on full pages; OCR annotations are text transcriptions of individual crops
- **Goal:** Eliminate hallucination, output clean single-line engineering text, recognize ⌀/±/GD&T symbols natively

### 2. Expand YOLO to More Classes

Currently trained on **4 classes only** (Hole, TappedHole, Fillet, Chamfer). Detects ~4 callouts on drawings that have 15-30+. Need to annotate and retrain with:
- GD&T feature control frames
- Datum references
- Weld symbols
- Surface finish callouts
- Bend callouts (sheet metal)
- General dimensions and tolerances
- Notes and special instructions

Full 14-class taxonomy already defined in `ai_inspector/detection/classes.py`.

### 3. 3D Spatial Context for VLM (New Direction)

**Problem:** The VLM only sees a flat 2D drawing. It has no spatial understanding of the 3D part geometry. This limits its ability to:
- Identify which drawing view corresponds to which part orientation
- Understand why certain features are critical (assembly interfaces)
- Locate specific dimensions on the actual geometry
- Make sense of the mating relationships it receives as JSON

**Solution: Feed rendered 3D views alongside the 2D drawing as multi-image input to GPT-4o/Claude.**

#### Phase 1: Multi-View Part Renders (low effort, high value)
Add to `SolidWorksExtractor/`:
- Render 6 standard views (front, top, right, back, bottom, isometric) as PNGs via SolidWorks API
- Save alongside the SW JSON
- Feed to GPT-4o as additional images in the report prompt
- Prompt: "Here is the 2D drawing and the 3D CAD model from multiple angles. Identify which drawing views correspond to which 3D orientations. Flag features visible in 3D but missing from the drawing."
- **No model training required** — pure prompt engineering with multi-image input

#### Phase 2: Assembly Context Renders (medium effort, high value)
- Render the assembly with the inspected part highlighted in color
- Render an exploded view showing mating interfaces
- Feed to GPT-4o alongside mating context JSON
- Prompt: "The highlighted part mates with the cap screw via the hole shown. Verify the drawing includes callouts for all interface features."
- **Visually grounds the mating relationships** — the model can see where the M10 screw goes through the part instead of just reading it from JSON

#### Phase 3: VLM-Guided Feature Discovery (higher effort, experimental)
- Use 3D renders to help the VLM find features that YOLO missed
- Show side-by-side: 3D render with feature highlighted → corresponding area on 2D drawing
- "The 3D model shows an M10 tapped hole at this location. Find the corresponding callout on the drawing."
- Could significantly improve recall beyond what YOLO training alone can achieve

**Architecture with 3D context:**
```
                    ┌─────────────┐
                    │ SolidWorks  │
                    │   Model     │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        SW JSON       3D Renders    Assembly
        (precise      (6 views +    Renders
        dimensions)    iso PNG)     (exploded)
              │            │            │
              │            ▼            │
              │     ┌─────────────┐    │
              │     │   GPT-4o    │◄───┘
              │     │ (qualitative│
              │     │  reasoning) │◄─── 2D Drawing
              │     └──────┬──────┘
              │            │
              ▼            ▼
        ┌─────────────────────────────┐
        │   Comparison Engine         │
        │  structured + VLM insights  │
        └─────────────────────────────┘
```

**Key principle:** VLM for qualitative understanding (what am I looking at, which features are at interfaces) + SW JSON for quantitative comparison (dimensions, tolerances). Don't ask the VLM to measure — it can't do precise measurements from rendered images.

### 4. Batch Evaluation on Full Drawing Library
Run pipeline on all 258 drawings with matched SW JSONs to measure:
- Detection recall and precision per class
- OCR accuracy (CER/WER) before and after improvements
- End-to-end match rate against SW data
- Report quality assessment

---

## Drawing Analysis Summary (Basis for v4 Classification)

**Source:** 258 unique drawings from 400S_Sorted_Library (band saw machine)

**Analysis Method:**
1. Rendered all 526 PDFs (258 unique after deduplication)
2. Extracted text via PyMuPDF
3. Classified based on text patterns
4. Spot-checked with visual inspection

**Key Patterns Identified:**

| Pattern | Detection Method | Drawing Type |
|---------|------------------|--------------|
| "WELDT" in title | Text search | WELDMENT |
| BOM table (ITEM NO + QTY) | Column detection | ASSEMBLY |
| Manufacturer table (NSK/SKF) | Multiple supplier names | PURCHASED_PART |
| Gear data (TEETH, PITCH) | Keyword count ≥2 | GEAR |
| "DUCTILE IRON" / "MFG ITEM #" | Material callout | CASTING |
| "FLAT PATTERN" / bend callouts | View label + bend spec | SHEET_METAL |
| Default | No specific signals | MACHINED_PART |

**Reference Drawings Organized:**
```
Drawing_Analysis_By_Type/
├── 01_Machined_Parts/     (184 files)
├── 02_Sheet_Metal/        (26 files)
├── 03_Castings/           (4 files)
├── 04_Assemblies/         (29 files)
├── 05_Weldments/          (11 files)
├── 06_Purchased_Parts/    (4 files)
└── README.md
```

---

## v3.0 Features (Preserved in v4)

All v3 functionality is preserved and will be refactored into modules:

### Core Pipeline (from v3)
- ✓ Page classification (PART_DETAIL/ASSEMBLY_BOM/MIXED)
- ✓ Conditional OCR based on page type
- ✓ Multi-page PDF support
- ✓ LightOnOCR-2 text extraction with markdown cleanup
- ✓ Qwen2.5-VL-7B feature extraction (enhanced prompt)
- ✓ Evidence merge with deduplication
- ✓ SW JSON comparison with tolerance matching
- ✓ GPT-4o-mini report generation
- ✓ Graceful degradation when no CAD data

### Recent Enhancements (from v3)
- ✓ Mate-derived requirements (M8 thread from assembly context)
- ✓ Sheet metal bend hole filtering (skip geometry artifacts)
- ✓ Inspector requirements database integration
- ✓ Dimension suffix recognition ((F), STK., REF., TYP.)
- ✓ Enhanced thread format parsing (Metric, Unified, ACME)
- ✓ GD&T extraction
- ✓ Surface finish callouts
- ✓ Coating/heat treatment specs

---

## Testing Strategy (v4)

### Unit Tests (Fast)
- Classifier logic: text → type mapping
- Title block extraction
- Feature parsing/normalization
- Matching rules

### Integration "Golden Set" (20-30 drawings)
- Representative drawings covering all types
- Expected outputs (or key assertions)
- Run on every commit to prevent regressions

### Full Batch Run (258 drawings)
- Periodic regression/evaluation
- Track metrics:
  - Type classification accuracy
  - OCR extraction rate
  - Match rate distribution
  - Top failure modes

---

## Colab Usage (v4)

```python
# 1. Clone repo and install
!git clone https://github.com/user/AI-tool.git
%cd AI-tool
!pip install -e .

# 2. Import and run
from ai_inspector import pipeline

result = pipeline.run(
    pdf_path="drawing.pdf",
    sw_library_path="sw_json_library.zip"
)

# 3. Display results
result.display()
```

---

## API Keys Required (Colab Secrets)
- `HF_TOKEN` - Hugging Face (for model downloads)
- `OPENAI_API_KEY` - OpenAI (for GPT-4o-mini reports)

---

## Change Log

### February 14, 2026 - Spatial Inspection: Multi-Page Drawing Support

- Reviewed `spatial_inspection.ipynb` pipeline and validated on multiple parts
- Implemented multi-page drawing input: single path, list of paths, glob pattern, and multi-page PDF extraction
- Updated Claude Vision API call to send all pages as labeled `[PAGE X of Y]` image blocks
- Updated inspection prompt to require cross-page checking before marking features MISSING
- Added `found_on_page` field to findings JSON schema and Page column to display output
- Tested backward compatibility (single image) and multi-page mode (2-page list for part 1008176)
- Updated config cell docs with multi-page usage examples
- Updated `PROJECT_STATUS.md` to reflect dual-approach architecture (YOLO+OCR pipeline + spatial vision inspection)

### February 11, 2026 - OCR Quick Wins Integrated into Full Pipeline

- Implemented OCR quick wins directly in pipeline code path (`canonicalize.py`, `patterns.py`, `crop_reader.py`, `ocr_adapter.py`, `matcher.py`, `yolo_pipeline.py`)
- Ran `tests/notebooks/test_full_pipeline.ipynb` locally end-to-end; artifacts written to `tests/notebooks/test_full_pipeline_executed_local.ipynb`
- Confirmed improved robustness on fraction/drill-style parsing and hole↔tapped-hole equivalence matching
- Confirmed remaining limitation: low YOLO recall is currently the strongest constraint on end-to-end match rate

### February 11, 2026 - Assembly Context + Severity-Tiered Reports

**Assembly Context Wired End-to-End:**
- `sw_mating_context.json` (62 entries): parent assembly + sibling components for each part
- `sw_mate_specs.json` (40 entries, 100 mates): Concentric/Coincident mates with thread specs (M10x1.5, M8x1.25)
- Old↔new part number bridging via `sw_part_context_complete.json` (597 entries) — enables cross-reference when databases use different numbering schemes
- Sibling cross-reference: when a part isn't directly in mate_specs, looks up its siblings' specs to infer required features (e.g., 314884 PAWL → sibling 199680 SCR CAP HEX → M10 Concentric mate found)

**GPT-4o Report Upgraded with Pre-Computed Summaries:**
- Severity-grouped missing features: critical (TappedHole, Hole) vs minor (Fillet, Chamfer)
- Detection coverage assessment: flags LOW when YOLO detects fewer callouts than typical for the drawing type
- Assembly-driven findings: extracts Concentric mates that imply required tapped holes / bored holes
- Extra↔missing correlation: flags drawing callouts that may be mismatched versions of missing SW features
- Feature breakdown by type and status
- Prompt restructured: VERDICT → CRITICAL → MINOR → CAVEAT → NEXT STEPS

**Files Changed:**
- `ai_inspector/utils/context_db.py` — Added load_part_context(), load_mate_specs(), get_mate_specs(), get_mate_specs_for_siblings(), old_pn bridging in get_mate_specs()
- `ai_inspector/pipeline/yolo_pipeline.py` — Added mate_specs_path, part_context_path params; mate_specs in PipelineResult; sibling cross-reference logic; mate_specs.json debug output; CLI flags
- `tests/notebooks/test_full_pipeline.ipynb` — Added Cell 8 (mate specs display), updated Cell 13 (pre-computed summaries + severity-tiered prompt), added MATE_SPECS_PATH and PART_CONTEXT_PATH config

**Test Results (Part 314884 PAWL):**
- 4 detections, 1 matched (R0.030" fillet), 12 missing (1 critical TappedHole + 11 fillets), 3 extra
- Mating context: assembly 047-263, siblings: PIN LOWER SPRING, SCR CAP HEX M10X1.5X30, T-NUT
- Mate specs: found via sibling cross-reference (M10x1.5 Concentric mate with part 046)
- Report correctly highlights: "Missing Tapped Hole: 33/64" diameter, critical for assembly with M10X1.5X30 cap screw"

### February 9, 2026 - VLM + GPT-4o Report Wired into Pipeline

**Qwen2.5-VL-7B Wired for Page Understanding:**
- Sequential model loading: YOLO → unload → OCR → unload → VLM → unload (peak ~5.5 GB VRAM)
- Full page understanding: title block, tolerances, notes, drawing type, surface finish, views, datums
- `extractors/vlm.py` + `extractors/prompts.py` integrated into pipeline Phase 3

**GPT-4o Report Generation:**
- All pipeline context assembled as JSON and sent to GPT-4o API
- Mating context included when available
- Report saved as `qc_report.md` in debug output

**Mating Context Wired:**
- `utils/context_db.py` extended with load_mating_context() and get_mating_context()
- Pipeline resolves part number from SW JSON (priority) or VLM title block (fallback)
- Assembly context saved as `assembly_context.json` in debug output

**Files Changed:**
- `ai_inspector/pipeline/yolo_pipeline.py` — VLM Phase 3, mating_context_path, PipelineResult.page_understanding + mating_context
- `ai_inspector/utils/context_db.py` — mating_context support
- `tests/notebooks/test_full_pipeline.ipynb` — 15 cells, full end-to-end with VLM + mating context + GPT-4o report

### February 9, 2026 - Full Pipeline Validated End-to-End

**Pipeline Bugs Fixed (5):**
- `config.py`: Reduced `ocr_max_tokens` 2048 → 128 (prevented runaway OCR generation)
- `extractors/ocr.py`: Added `repetition_penalty=1.2`, image resize to 384px max, per-call `max_tokens` override
- `extractors/ocr_adapter.py`: Passes resize + `max_tokens=64` for crop-level OCR
- `pipeline/yolo_pipeline.py`: Added `encoding="utf-8"` to JSON file writes (Windows cp1252 Unicode crash)
- `extractors/canonicalize.py`: Added LaTeX-to-Unicode conversion (13 patterns: `\phi`→⌀, `\varphi`→⌀, subscript extraction, garbage removal)
- `comparison/sw_extractor.py`: Added fallback extraction from `comparison.holeGroups` (C# extractor format)

**Performance Improvement:**
- Pipeline runtime reduced from **49 minutes** to **16-126 seconds** (depending on detection count)
- Root cause: OCR model was generating thousands of repeated tokens per crop with no size limit or repetition penalty

**Test Results:**
- Drawing 176759 + SolidWorks JSON: 2/2 holes matched (⌀1.28" delta=+0.0005", ⌀.75" delta=+0.0020")
- Drawing 1008193 (complex, 12 callouts): All 12 detected, validated, parsed by regex
- Multiple test images from PDF VAULT ran without errors

**Key Decision: Model Roles Clarified:**
- **YOLO**: Locate and classify callouts (crop extraction)
- **LightOnOCR**: Read text inside each crop (needs fine-tuning)
- **Qwen VLM**: Full-page understanding (title block, notes, context) — NOT used as crop fallback
- **GPT-4o**: Final QC report generation from all combined data

### February 5, 2026 - YOLO-OBB Finetuning Complete

### February 6, 2026 - Detection Threshold Calibration Note

**Test Result Recorded:**
- Ran `test_detection.ipynb` on `00595601_04.png` with finetuned HF model.
- Detections: 5 total (`Fillet` 1, `Hole` 3, `Chamfer` 1, `TappedHole` 0).
- Observed likely false-positive `Fillet` on this page; no `TappedHole` expected from visible callouts.

**Calibration Decision (to revisit):**
- Add class-specific confidence gating for post-processing, with stricter threshold on `Fillet`.
- Proposed starting thresholds for next tuning pass:
  - `Hole`: 0.40
  - `Chamfer`: 0.35
  - `TappedHole`: 0.40
  - `Fillet`: 0.88

**Status:** Deferred for dedicated threshold tuning pass after OCR pipeline validation.

**Model Training:**
- Collected 224 training images from PDF VAULT and machined parts folders
- Annotated 550 callouts in Roboflow (Hole, TappedHole, Fillet, Chamfer)
- Trained yolo11s-obb with drawing-safe augmentation (no flip, no color shift)
- Achieved **mAP50 = 0.729** (per-class: Hole 0.78, TappedHole 0.72, Fillet 0.70, Chamfer 0.71)
- Early stopping triggered at epoch 111 (best at epoch 81)

**Infrastructure Updates:**
- Training notebook updated to use TensorBoard instead of W&B
- Model saved to HuggingFace Hub: `shadrack20s/ai-inspector-callout-detection`
- `config.py` updated to default to HuggingFace model path
- Test notebooks updated to load model from HuggingFace

**Files Changed:**
- `notebooks/train_yolo_obb.ipynb` — v2 with TensorBoard + HuggingFace
- `ai_inspector/config.py` — Default yolo_model_path to HF
- `tests/notebooks/test_detection.ipynb` — Use HF model
- `tests/notebooks/test_full_pipeline.ipynb` — Use HF model

### January 29, 2026 - v4.0 Development Started (Modular Architecture)

**New Package Structure:**
- Created `ai_inspector/` Python package with proper module organization
- Added `setup.py` and `pyproject.toml` for editable install
- Created `classifier/drawing_classifier.py` with full classification logic

**Drawing Type Classification:**
- 7 drawing types: MACHINED_PART, SHEET_METAL, WELDMENT, ASSEMBLY, CASTING, PURCHASED_PART, GEAR
- Type-specific configurations (use_ocr, features_to_extract, critical_checks)
- Based on analysis of 258 unique drawings from 400S library

**Drawing Analysis:**
- Processed all 526 PDFs (258 unique after deduplication)
- Organized into categorized folders by type
- Created classification log and README documentation

**v3 Qwen Prompt Enhancements (merged into v4):**
- Dimension suffixes: (F), STK., REF., TYP., MAX., MIN.
- Thread formats: Metric M##X#.#-6H, Unified UNC/UNF, ACME
- Sheet metal: FLAT PATTERN, bend callouts, gauge materials
- Special types: Casting signals, Purchased parts, Gears
- GD&T: Position, perpendicularity, runout, concentricity
- Surface finish: Ra microinch callouts
- Coating/heat treat: Paint, powder coat, hardness specs
- Weldment signals: WELDT keyword + BOM table

### January 28, 2026 - v3.0 Development (Smart Classification Pipeline)
- Page classification system (PART_DETAIL/ASSEMBLY_BOM/MIXED)
- Conditional OCR based on page type
- Multi-page PDF support
- OCR markdown preprocessing
- Enhanced Qwen feature prompts
- No-SW-JSON graceful degradation
- Mate-derived requirements integration
- Sheet metal hole filtering

### January 27, 2025 - v2.0 Complete
- BOM extraction
- Manufacturing notes
- GPT-4o-mini report integration
- Dual AI pipeline (LightOnOCR + Qwen)

---

## Technical Notes

- **Assembly:** 400S (band saw machine)
- **SolidWorks version:** 2023
- **Local dev environment:** Windows 11, RTX 4000 Ada 12GB, Python 3.14, CUDA 12.8
- **Colab GPU:** T4 or better for inference
- **Peak GPU memory:** ~5.5 GB (models load/unload sequentially: YOLO ~0.04GB → OCR ~2.02GB → VLM ~4.5GB)
- **GPT-4o cost:** ~$0.01-0.05 per report (~2,000-3,500 tokens)
- **Pipeline runtime:** ~330-380s with VLM, ~16-126s without VLM
- **Unique drawings in library:** 258
- **Drawing types:** 7 (machined parts most common at 71%)
- **SW JSON library:** 383 extracted JSON files (C# SolidWorks Extractor)
- **Assembly context:** 62 parts in mating context, 40 parts in mate specs, 597 parts in part context
- **Matched drawing+JSON pairs identified:** 6+ (176759, 314884, 1008176, 1013072, 226121, 231977, 231979)
