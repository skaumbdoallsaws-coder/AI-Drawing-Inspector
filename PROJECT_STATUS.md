# AI Engineering Drawing Inspector - Project Status

**Last Updated:** January 28, 2026

---

## Project Goal

Build an AI-powered system that **verifies engineering drawings (PDFs) against CAD model data** from SolidWorks. The inspector checks that drawings contain all required features (thread callouts, hole dimensions, tolerances) that match the CAD model specifications.

---

## Current Status: v3.0 In Development - Smart Classification Pipeline

### What's New in v3.0

v3 adds **intelligent page classification**, **multi-page PDF handling**, **conditional OCR**, and **graceful degradation** when CAD data is unavailable. The pipeline now adapts its behavior based on what type of drawing it's processing.

### Architecture (v3.0)

```
┌─────────────────┐     ┌─────────────────────────────────────────────────────────────────┐     ┌─────────────────┐
│  PDF Drawing     │────▶│  AI Inspector v3 (Colab)                                       │────▶│  QC Report      │
│  (single/multi   │     │                                                                 │     │  PASS / FAIL    │
│   page PDF)      │     │  ┌──────────────────────────────────────────────────────────┐   │     │  + details      │
└─────────────────┘     │  │  STAGE 1: Page Classification (Qwen2.5-VL)               │   │     └─────────────────┘
                        │  │  - Classify each page: PART_DETAIL / ASSEMBLY_BOM / MIXED │   │
                        │  │  - Determine which pages need OCR                         │   │
                        │  │  - Robust override: PART_DETAIL always gets OCR           │   │
                        │  └──────────────────────────┬───────────────────────────────┘   │
                        │                             │                                    │
                        │  ┌──────────────────────────▼───────────────────────────────┐   │
                        │  │  STAGE 2: Dual AI Extraction                              │   │
                        │  │  ┌────────────┐  ┌──────────────────────────────────┐     │   │
                        │  │  │LightOnOCR-2│  │ Qwen2.5-VL-7B (4 analyses)       │     │   │
                        │  │  │(Conditional│  │  1. Feature Extraction (enhanced)│     │   │
                        │  │  │ OCR - only │  │  2. Drawing Quality Audit        │     │   │
                        │  │  │ on pages   │  │  3. BOM Extraction               │     │   │
                        │  │  │ that need  │  │  4. Manufacturing Notes          │     │   │
                        │  │  │ it)        │  └──────────────────────────────────┘     │   │
                        │  │  └────────────┘                                           │   │
                        │  └──────────────────────────┬───────────────────────────────┘   │
                        │                             │                                    │
                        │  ┌──────────────────────────▼───────────────────────────────┐   │
                        │  │  STAGE 3: Evidence Merge + Preprocessing                  │   │
                        │  │  - Clean LightOnOCR-2 markdown/LaTeX output               │   │
                        │  │  - Parse callouts with expanded regex patterns             │   │
                        │  │  - Merge OCR + Qwen features with deduplication            │   │
                        │  └──────────────────────────┬───────────────────────────────┘   │
                        │                             │                                    │
                        │  ┌──────────────────────────▼───────────────────────────────┐   │
                        │  │  STAGE 4: Compare to SW JSON (if available)               │   │
                        │  │  - Loads from sw_json_library                              │   │
                        │  │  - If NO SW JSON found: creates stub, reports visual-only  │   │
                        │  │  - Comparison in INCHES (0.015" tolerance)                 │   │
                        │  └──────────────────────────┬───────────────────────────────┘   │
                        │                             │                                    │
                        │  ┌──────────────────────────▼───────────────────────────────┐   │
                        │  │  STAGE 5: GPT-4o-mini Report (classification-aware)       │   │
                        │  │  - Knows drawing type (PART_DETAIL/ASSEMBLY/MIXED)        │   │
                        │  │  - Adapts report based on CAD data availability            │   │
                        │  │  - Covers: features, quality, BOM, mfg notes              │   │
                        │  └──────────────────────────────────────────────────────────┘   │
                        └─────────────────────────────────────────────────────────────────┘
```

---

## v3.0 Features Implemented

### 1. Page Classification (Cell 10a) - NEW
Classifies each page of a multi-page PDF before any processing:
- **PART_DETAIL** - Single part with dimensions, tolerances, section views
- **ASSEMBLY_BOM** - Exploded view with balloon callouts and/or BOM table
- **MIXED** - Has both BOM/exploded AND dimensioned detail views on same page

**Robust OCR override logic:**

| Drawing Type | OCR Decision | Rationale |
|--------------|-------------|-----------|
| PART_DETAIL | Always OCR | Dimension extraction is critical |
| MIXED | Always OCR | Has dimensions that need extraction |
| ASSEMBLY_BOM | Skip OCR | No detailed dimensions, only BOM/balloons |
| ASSEMBLY_BOM + dimensioned views | OCR | Has dimensions despite being assembly |

The VLM's `needsOCR` field is **not trusted** — the override logic enforces rules based on `drawingType`. Logs when override occurs:
```
[OVERRIDE] VLM said needsOCR=False, but PART_DETAIL always needs OCR
```

### 2. Multi-Page PDF Support (Cell 8) - ENHANCED
- Renders all pages of a PDF (not just page 1)
- Each page stored as a `PageArtifact` with: image, page number, drawing_type, needs_ocr, has_bom
- Classification runs per-page, OCR runs only on pages that need it

### 3. Conditional OCR (Cell 10) - ENHANCED
- OCR only runs on pages in the `pages_needing_ocr` list
- Assembly/BOM pages are skipped entirely
- Logs which pages are processed and how many lines extracted per page

### 4. OCR Text Preprocessing (Cell 11) - NEW
LightOnOCR-2 outputs markdown/LaTeX formatted text that standard regex can't parse:
```
# CASTING DIMENSIONS
- MAJOR $\oslash$ 1.0200/1.0400
**NOTES:**
```

New `preprocess_ocr_text()` function:
- Converts LaTeX `$\oslash$` to unicode diameter symbol `∅`
- Converts `$\times$` → `x`, `$\pm$` → `±`, `$\degree$` → `°`
- Strips markdown: `#` headers, `**bold**`, `- bullets`, `![image](...)` refs
- Result: clean text ready for regex parsing

### 5. Expanded Regex Patterns (Cell 11) - NEW
Added patterns that were missing:

| Pattern | Example | Purpose |
|---------|---------|---------|
| `major_minor_dia` | `MAJOR ∅ 1.0200/1.0400` | Casting/machining diameter with tolerance range |
| `counterbore` | `CBORE ∅.750` | Counterbore holes |
| `countersink` | `CSK ∅.500` | Countersink holes |
| `diameter` | `∅.500` (standalone) | Diameter without THRU/DEEP qualifier |
| `imperial_thread` | `1/2-13` | Imperial thread callouts |

All patterns also handle:
- Deduplication via `seen_raws` set
- Leading dot notation (`.500` vs `0.500`)
- Unicode diameter symbols (`∅`, `Ø`, `ø`, `⌀`, `φ`)

### 6. Enriched Qwen Feature Prompt (Cell 10c) - ENHANCED
Added detailed type definitions to help the 7B model classify features:
```
TappedHole: A hole with INTERNAL THREADS. You MUST see a thread callout
            like M6x1.0, M10x1.5, 1/2-13 UNC. If NO thread callout → NOT TappedHole.

ThroughHole: A plain round hole that goes completely through the part.
             Has diameter dimension and THRU text. No thread lines.

BlindHole: A plain round hole that does NOT go all the way through.
           Has diameter AND depth dimension. No thread lines.
```

Key rules added:
1. Only classify as TappedHole if actual thread callout visible
2. A hole with just a diameter = ThroughHole (if THRU) or BlindHole (if has depth)
3. Report EXACT callout text as it appears on the drawing
4. General notes ("REMOVE BURRS") are NOT features — put in `notes` array

### 7. No-SW-JSON Graceful Degradation (Cells 12, 13) - NEW
When no SolidWorks JSON is found for a part:
- Pipeline **does not stop** — continues with visual analysis only
- Cell 12 (DiffResult): Creates stub with `comparisonAvailable: false`
- Cell 13 (GPT Report): Adjusts prompt to focus on drawing quality instead of CAD comparison
- Report clearly states: "No CAD data available — report based on visual analysis only"

### 8. Classification-Aware GPT Report (Cell 13) - ENHANCED
The GPT summarizer now receives `classification_info`:
```python
classification_info = {
    'overall_type': 'PART_DETAIL',     # or ASSEMBLY_BOM, MIXED
    'total_pages': 2,
    'pages_with_ocr': 2,
    'pages_with_bom': 0,
    'ocr_skipped': False
}
```

Report adapts based on drawing type:
- **PART_DETAIL**: Focus on dimensional accuracy, tolerances, feature verification
- **ASSEMBLY_BOM**: Focus on BOM completeness and assembly instructions
- **MIXED**: Report on both aspects

### 9. Fallback Initializations (Cells 11, 12, 13) - NEW
Cells now handle missing variables gracefully:
- `ocr_lines` defaults to `[]` if OCR cell was skipped
- `qwen_understanding` defaults to stub if Qwen cell failed
- `evidence`, `diff_result`, `drawing_quality`, `bom_data`, `mfg_notes` all have fallback stubs
- Prevents cascade failures when cells run out of order or are skipped

---

## Pipeline Components (v3.0)

| Component | Model/Tool | Cell | Status | Notes |
|-----------|-----------|------|--------|-------|
| Page Classification | Qwen2.5-VL-7B | 10a | NEW | Classifies PART_DETAIL/ASSEMBLY_BOM/MIXED |
| OCR Override Logic | Python | 10a | NEW | Enforces OCR rules by drawing type |
| Text Extraction | LightOnOCR-2-1B | 10 | Enhanced | Conditional — only on pages that need it |
| OCR Preprocessing | Python | 11 | NEW | Cleans markdown/LaTeX before regex |
| Feature Extraction | Qwen2.5-VL-7B | 10c | Enhanced | Enriched prompt with type definitions |
| Drawing Quality Audit | Qwen2.5-VL-7B | 10c | Working | Title block, tolerances, best practices |
| BOM Extraction | Qwen2.5-VL-7B | 10c | Working | Parts list from assembly drawings |
| Manufacturing Notes | Qwen2.5-VL-7B | 10c | Working | Heat treat, finish, plating, welding |
| Evidence Merge | Python | 11 | Enhanced | Expanded patterns, deduplication |
| SW Comparison | Python | 12 | Enhanced | Handles missing SW JSON gracefully |
| QC Report | GPT-4o-mini | 13 | Enhanced | Classification-aware, handles no-CAD case |

---

## Test Results

### Part 1008176 - RACK VISE 400 (v3.0 First Run)

| Metric | Value | Notes |
|--------|-------|-------|
| Drawing Type | PART_DETAIL | 2-page multi-page PDF |
| Pages | 2 (Casting dims + Machining dims) | Both classified correctly |
| OCR Override | YES — fixed needsOCR=False | VLM was wrong, override worked |
| OCR Lines | 89 (59 + 30) | Both pages processed |
| Qwen Features | 11 | 7 TappedHole + 3 Chamfer + 1 Fillet |
| SW Requirements | 5 (all plain holes) | No tapped holes in SW JSON |
| Match Rate | 0.0% | See known issues below |
| Quality Score | 8/10 | Good overall quality |
| Material | QT 450-10 CAST IRON | Correctly identified |
| Mfg Notes | Surface finish 125 Ra, mask threads during paint | Correctly extracted |

**Why 0.0% match on first run:**
1. **OCR callouts = 0**: LightOnOCR-2 markdown output wasn't being parsed (NOW FIXED)
2. **Qwen type mismatch**: Qwen called everything "TappedHole" but SW JSON has plain "Hole" types (prompt NOW ENHANCED)
3. **SW JSON data gap**: Part 1008176 has only 5 plain hole groups, no tapped holes in `comparison.holeGroups`

### Part 320740 - GROUNDING BUS 8 POINT (v2.0 Baseline)

| Metric | Value |
|--------|-------|
| Match Rate | **100%** |
| SW Requirements | 3 (M6x1.0, M5x0.8 7X, ø0.2795" THRU 2X) |
| Found | 3 |
| Missing | 0 |

---

## Known Issues (v3.0)

### 1. Qwen 7B Feature Type Accuracy
**Problem:** Qwen2.5-VL-7B at 4-bit quantization sometimes misclassifies plain holes as TappedHoles, and grabs general dimensions instead of hole-specific callouts.

**Root cause:** Model limitation at 7B level — limited spatial reasoning to distinguish hole callouts (leader arrow → circle) from linear dimensions (line between edges).

**Mitigation:** Enhanced prompt with detailed type definitions. The OCR parsing (structured regex) provides more reliable dimension data as a complementary source.

**Status:** Partially addressed with enriched prompt. Full solution may require a larger model or fine-tuning.

### 2. Duplicate Detection
**Problem:** Same feature detected by both OCR and Qwen, reported as separate items.

**Impact:** False "Extra" items in report.

**Status:** Evidence merge logic reduces duplicates but doesn't eliminate them fully.

### 3. SW JSON Data Gaps
**Problem:** Some parts have limited feature data in `comparison.holeGroups` (e.g., no tapped holes, only plain holes).

**Impact:** Features visible in drawing can't be matched to CAD requirements.

**Status:** Data issue — depends on SolidWorks C# extractor output. Not a notebook code issue.

### 4. OCR Markdown Format Variability
**Problem:** LightOnOCR-2 output format (markdown/LaTeX) may vary between drawings.

**Impact:** Regex patterns may not catch all variations.

**Status:** Preprocessing handles known patterns ($\oslash$, #, **, -). Will expand as new formats are encountered.

---

## Notebook Cell Map (v3.0)

| Cell | Name | Function |
|------|------|----------|
| 1 | Install Dependencies | pip installs + HF login |
| 2 | Imports and Configuration | Libraries, GPU setup |
| 3 | BOM-Robust JSON Loader | Loads SW JSON with error handling |
| 4 | PDF Rendering | Multi-page PDF to images (PyMuPDF) |
| 5 | SolidWorks JSON Library | Library path configuration |
| 6 | Part Identity Resolution | Robust filename → part number matching |
| 7 | Load SolidWorks Library | Upload/extract sw_json_library.zip |
| 8 | Upload and Render PDF | User uploads drawing, renders all pages |
| 9 | Resolve Part Identity | Match filename to SW JSON |
| 9b | Load Qwen2.5-VL Model | Load model + define `run_qwen_analysis()` |
| **10a** | **Classify Each Page** | **NEW: Page type classification + OCR decision** |
| 10 | Load LightOnOCR-2 + Run OCR | Conditional OCR on pages that need it |
| 10c | Qwen Drawing Analysis | 4 analyses: features, quality, BOM, mfg notes |
| **11** | **Merge Evidence** | **ENHANCED: Preprocessing + expanded regex + merge** |
| **12** | **Generate DiffResult** | **ENHANCED: Handles missing SW JSON** |
| **13** | **GPT-4o-mini Report** | **ENHANCED: Classification-aware report** |

---

## File Structure

### Active Files
```
├── ai_inspector_v3.ipynb          # DEVELOPMENT - v3 pipeline
├── ai_inspector_v2.ipynb          # STABLE - v2 pipeline (reference)
├── ai_inspector_unified.ipynb     # Simplified single-file version
├── PROJECT_STATUS.md              # This file
├── sw_json_library/               # SW JSON files from C# extractor
├── sw_json_library.zip            # Zipped library for Colab upload
├── schemas/
│   └── sw_to_evidence_mapping.json # Mapping schema v1.1.1
```

### C# Extractor (Generates SW JSON)
```
SolidWorksExtractor/
├── Program.cs
├── Services/
│   ├── HoleReconciler.cs          # Creates comparison.holeGroups
│   ├── GeometryAnalyzer.cs
│   └── ...
└── Models/
    └── ComparisonData.cs
```

### Legacy (Reference Only)
```
vba_extraction_legacy/             # Old VBA approach - deprecated
old_notebooks/                     # Previous notebook versions
old_scripts/                       # Standalone scripts
```

---

## Output Files (per inspection)

| File | Contents |
|------|----------|
| `ResolvedPartIdentity.json` | Part number, confidence, SW JSON path |
| `QwenUnderstanding.json` | All 4 Qwen analyses (features, quality, BOM, mfg notes) |
| `DrawingEvidence.json` | Merged OCR + Qwen callouts (inches) |
| `DiffResult.json` | Comparison results (found/missing/extra) |
| `QCReport.md` | GPT-4o-mini generated comprehensive report |

---

## API Keys Required (Colab Secrets)
- `HF_TOKEN` - Hugging Face (for model downloads)
- `OPENAI_API_KEY` - OpenAI (for GPT-4o-mini reports)

---

## Quick Start

### Run Inspector (Colab)
1. Open `ai_inspector_v3.ipynb` in Google Colab
2. Ensure secrets are set: `HF_TOKEN`, `OPENAI_API_KEY`
3. Upload `sw_json_library.zip` when prompted
4. Upload PDF drawing when prompted
5. Run all cells in order
6. Review `QCReport.md` for comprehensive results

### Test Files Needed
To fully test v3 classification logic:

| # | File Type | Pages | Expected Classification |
|---|-----------|-------|------------------------|
| 1 | Single-page part detail | 1 | PART_DETAIL, OCR=yes |
| 2 | Multi-page part detail | 2+ | PART_DETAIL, OCR=yes (all pages) |
| 3 | Assembly with BOM | 1+ | ASSEMBLY_BOM, OCR=no |
| 4 | Multi-page assembly (BOM + details) | 2+ | MULTI_PAGE_ASSEMBLY, OCR=detail pages only |

---

## Change Log

### January 28, 2026 - v3.0 Development (Smart Classification Pipeline)

**OCR Parsing Overhaul:**
- Added `preprocess_ocr_text()` to clean LightOnOCR-2 markdown/LaTeX output
- Convert `$\oslash$` to unicode `∅` before regex matching
- Strip markdown headers, bold, bullets, image references
- Added regex patterns: MAJOR/MINOR diameter, counterbore, countersink, standalone diameter, imperial threads
- Deduplicate matches with `seen_raws` set

**Qwen Feature Prompt Enhancement:**
- Added detailed type definitions (TappedHole requires thread callout, ThroughHole = plain + THRU, etc.)
- Added classification rules to reduce misclassification
- Instructed model to report exact callout text, not convert units

**Page Classification System:**
- New Cell 10a classifies each page using Qwen VLM
- Robust override: PART_DETAIL and MIXED always get OCR regardless of VLM's `needsOCR` response
- Logging when override triggers

**Multi-Page PDF Support:**
- Conditional OCR based on page classification
- Each page tracked independently (PageArtifact dataclass)

**No-SW-JSON Handling:**
- Pipeline continues without CAD data (creates stub DiffResult)
- GPT report adapts: focuses on visual analysis when no CAD baseline
- Clear messaging about what's missing and why

**Classification-Aware Reporting:**
- GPT receives drawing type, page counts, processing summary
- Adapts report content for PART_DETAIL vs ASSEMBLY vs MIXED

**Robustness:**
- Fallback initializations in Cells 11, 12, 13 for all dependent variables
- Prevents cascade failures from skipped or failed cells
- Widget metadata cleanup (saved 44KB)

### January 27, 2025 - v2.0 Complete (BOM + Mfg Notes)
- Added BOM Extraction - Qwen extracts parts list from assembly drawings
- Added Manufacturing Notes - Heat treat, finish, plating, welding, inspection
- Enhanced GPT Report - Now includes all 4 Qwen analyses
- Switched to inches - All hole comparisons in inches (no mm conversion)
- Filtered general notes - "REMOVE ALL BURRS" no longer misclassified

### January 27, 2025 - GPT-4o-mini Integration
- Added Cell 13 - GPT-4o-mini QC report generation
- Drawing Quality Audit - Title block completeness, best practices check
- Comprehensive reports - Synthesizes all extracted data

### January 27, 2025 - Working Dual AI Pipeline
- Built ai_inspector_v2.ipynb with LightOnOCR-2 + Qwen2.5-VL-7B
- Achieved 100% match rate on test part 320740
- Implemented evidence merge combining OCR precision with Qwen visual context

### January 22, 2025 - C# Extractor Refinements
- Added THRU vs BLIND classification
- Added entry treatment detection
- Added pattern instance centers
- Added extraction modes (Fast/Full)

### January 22, 2025 - Migration to C# Extractor
- Deprecated VBA approach
- Built C# SolidWorksExtractor scaffold
- Designed comparison.holeGroups schema

---

## Technical Notes

- **Assembly:** 400S (band saw machine)
- **SolidWorks version:** 2023
- **Colab GPU:** Required (T4 or better)
- **Total GPU memory:** ~19 GB (LightOnOCR ~2GB + Qwen ~5GB 4-bit)
- **GPT-4o-mini cost:** ~$0.01-0.02 per report
