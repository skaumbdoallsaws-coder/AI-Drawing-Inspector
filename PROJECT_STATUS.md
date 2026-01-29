# AI Engineering Drawing Inspector - Project Status

**Last Updated:** January 29, 2026

---

## Project Goal

Build an AI-powered system that **verifies engineering drawings (PDFs) against CAD model data** from SolidWorks. The inspector checks that drawings contain all required features (thread callouts, hole dimensions, tolerances) that match the CAD model specifications.

---

## Current Status: v4.0 In Development - Modular Type-Aware Architecture

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

| Phase | Module | Status | Notes |
|-------|--------|--------|-------|
| 1 | `classifier/drawing_classifier.py` | ✓ DONE | Classification logic from 258 drawing analysis |
| 2 | `setup.py` + `pyproject.toml` | ✓ DONE | Editable install support |
| 3 | Package skeleton (`__init__.py` files) | ✓ DONE | All directories created |
| 4 | `utils/pdf_render.py` | PENDING | Extract from v3 notebook |
| 5 | `utils/sw_library.py` | PENDING | Extract from v3 notebook |
| 6 | `extractors/ocr.py` | PENDING | LightOnOCR wrapper |
| 7 | `extractors/vlm.py` | PENDING | Qwen wrapper |
| 8 | `analyzers/base.py` | PENDING | Shared extraction logic |
| 9 | `analyzers/machined_part.py` | PENDING | First type-specific analyzer |
| 10 | `comparison/` | PENDING | Matcher + DiffResult |
| 11 | `report/qc_report.py` | PENDING | Type-aware report |
| 12 | Other analyzers | PENDING | One at a time |
| 13 | `notebooks/ai_inspector_v4.ipynb` | PENDING | Slim orchestrator |

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
