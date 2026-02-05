# AI Engineering Drawing Inspector - Project Status

**Last Updated:** February 5, 2026

---

## Project Goal

Build an AI-powered system that **verifies engineering drawings (PDFs) against CAD model data** from SolidWorks. The inspector checks that drawings contain all required features (thread callouts, hole dimensions, tolerances) that match the CAD model specifications.

---

## Current Status: YOLO-OBB Pipeline Complete — Ready for Integration Testing

### Latest Milestone (February 5, 2026)

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

### Architecture (v4.0)

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
| `test_ocr_pipeline.ipynb` | M3 + M4 + M5 (Rotation + OCR + Parse) | ✅ Created, ⏳ Not validated |
| `test_normalize_validate.ipynb` | M7 + M8 (Units + Validation) | ✅ Created, ⏳ Not validated |
| `test_matching.ipynb` | M9 + M10 (Expansion + Matching) | ✅ Created, ⏳ Not validated |
| `test_full_pipeline.ipynb` | Full end-to-end | ✅ Created, ⏳ Not validated |

### Remaining Work
| Phase | Module | Status | Notes |
|-------|--------|--------|-------|
| 9 | `analyzers/machined_part.py` | ⏳ PENDING | Awaiting pipeline validation |
| 10 | `report/qc_report.py` | ⏳ PENDING | Will integrate after testing |
| 11 | Other analyzers | ⏳ PENDING | One at a time after machined_part |

---

## Next Steps (Priority Order)

### 1. Set Up Test Data on Google Drive
Create folders and upload test files:
```
/content/drive/MyDrive/ai_inspector_data/
├── sample_pages/
│   ├── 100227201_01.png      # Machined part drawing
│   ├── 1008176_01.png        # Machined part drawing
│   └── 1008178_02.png        # Machined part drawing
└── sw_json/
    ├── 100227201.json        # Matching SW export
    ├── 1008176.json
    └── 1008178.json
```

### 2. Run Test Notebooks in Sequence
Open each notebook in Colab (GPU runtime) and run all cells:
1. `tests/notebooks/test_detection.ipynb` — Verify YOLO detects callouts
2. `tests/notebooks/test_ocr_pipeline.ipynb` — Verify OCR reads text
3. `tests/notebooks/test_normalize_validate.ipynb` — Verify unit conversion
4. `tests/notebooks/test_matching.ipynb` — Verify feature matching
5. `tests/notebooks/test_full_pipeline.ipynb` — End-to-end validation

### 3. Fix Any Issues Found
Debug and fix any failures discovered during testing.

### 4. Integrate with QC Report
Connect the YOLO pipeline output to the existing `report/qc_report.py` for final QC reports.

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

### February 5, 2026 - YOLO-OBB Finetuning Complete

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
- **Colab GPU:** Required (T4 or better)
- **Total GPU memory:** ~19 GB (LightOnOCR ~2GB + Qwen ~5GB 4-bit)
- **GPT-4o-mini cost:** ~$0.01-0.02 per report
- **Unique drawings in library:** 258
- **Drawing types:** 7 (machined parts most common at 71%)
