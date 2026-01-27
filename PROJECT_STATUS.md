# AI Engineering Drawing Inspector - Project Status

**Last Updated:** January 27, 2025

---

## Project Goal

Build an AI-powered system that **verifies engineering drawings (PDFs) against CAD model data** from SolidWorks. The inspector checks that drawings contain all required features (thread callouts, hole dimensions, tolerances) that match the CAD model specifications.

---

## Current Status: Working Pipeline with Dual AI Models

### Architecture (v2.0)

```
┌─────────────────┐     ┌──────────────────────────────────────┐     ┌─────────────────┐
│  PDF Drawing    │────▶│  AI Inspector v2 (Colab)             │────▶│  DiffResult     │
│  (user upload)  │     │  ┌────────────┐  ┌────────────────┐  │     │  PASS / FAIL    │
└─────────────────┘     │  │LightOnOCR-2│  │ Qwen2.5-VL-7B  │  │     │  + details      │
                        │  │(Text OCR)  │  │(Visual Under.) │  │     └─────────────────┘
                        │  └─────┬──────┘  └───────┬────────┘  │
                        │        │    MERGE        │           │
                        │        └────────┬────────┘           │
                        │                 ▼                    │
                        │        ┌────────────────┐            │
                        │        │Merged Evidence │            │
                        │        └───────┬────────┘            │
                        └────────────────┼─────────────────────┘
                                         │ COMPARE
                                         ▼
                        ┌────────────────────────────────────┐
                        │  SW JSON Library (C# Extractor)    │
                        │  comparison.holeGroups             │
                        └────────────────────────────────────┘
```

### Latest Test Results (Part 320740)

| Metric | Value |
|--------|-------|
| Match Rate | **100%** |
| SW Requirements | 3 (M6x1.0, M5x0.8 7X, ø7.10mm THRU 2X) |
| Found | 3 |
| Missing | 0 |
| Extra | 2 (duplicates/notes - see Known Issues) |

### Pipeline Components

| Component | Model | Status | Notes |
|-----------|-------|--------|-------|
| Text Extraction | LightOnOCR-2-1B | ✓ Working | 64 lines extracted, 2.02 GB |
| Visual Understanding | Qwen2.5-VL-7B-Instruct | ✓ Working | Features, views, material, 16.58 GB |
| Evidence Merge | Custom Python | ✓ Working | Links OCR dims with Qwen context |
| SW Comparison | Custom Python | ✓ Working | Uses `comparison.holeGroups` |

---

## Comparison Capabilities & Limitations

### What CAN Be Compared

| Feature Type | SW JSON Source | OCR Detection | Status |
|--------------|----------------|---------------|--------|
| Tapped Holes | `comparison.holeGroups[holeType=Tapped]` | M6x1.0 pattern | ✓ Full support |
| Through Holes | `comparison.holeGroups[holeType=Through]` | ø.281 THRU pattern | ✓ Full support |
| Blind Holes | `comparison.holeGroups[holeType=Blind]` | ø.500 x .25 DEEP | ✓ Full support |
| Fillets | `features.fillets[].radius` | R0.125 pattern | ✓ Supported |
| Chamfers | `features.chamfers[]` | .030 x 45° pattern | ✓ Supported |

### What CANNOT Be Compared (Limitations)

| Feature Type | Why Not Supported | Impact |
|--------------|-------------------|--------|
| **Linear Dimensions** | Not stored in SW JSON (only bounding box) | Cannot verify 4.00±.03 type callouts |
| **Curves/Splines** | Only edge counts in SW JSON, no specific dims | Cannot verify curve radii |
| **General Notes** | Not CAD features (e.g., "REMOVE ALL BURRS") | Filtered out - not relevant |
| **Surface Finish** | Text-based, no structured SW data | Future: text matching |
| **GD&T Symbols** | Complex - requires specialized parsing | Future enhancement |

### Parts with No Extractable Features

For parts with **only linear dimensions and curves** (no holes, fillets, or chamfers):
- SW requirements list will be **empty**
- Match rate will be **N/A**
- Part will **pass by default** (nothing to fail)

**Affected part types:** Simple plates, spacers, brackets without holes

---

## Known Issues (Current)

### 1. Duplicate Detection (Imperial/Metric)
**Problem:** Same hole detected twice when OCR finds imperial (.281") and Qwen finds metric (7.10mm).

**Example:**
- OCR: `ø.281 THRU` → matched to SW requirement
- Qwen: `2X .281 THRU (d)` → reported as "Extra"

**Impact:** False "Extra" items in report

**Fix needed:** Improve merge logic to deduplicate imperial/metric versions

### 2. Qwen Note Misclassification
**Problem:** Qwen classifies general notes as feature types.

**Example:** `"REMOVE ALL BURRS AND BREAK SHARP EDGES"` classified as `Chamfer`

**Impact:** False "Extra" chamfer in report

**Fix needed:** Filter notes from Qwen features or improve prompt

### 3. Low Feature Count Warning
**Problem:** Parts with 0 requirements silently pass.

**Impact:** No visibility into parts that couldn't be verified

**Fix needed:** Add warning for low-feature parts

---

## File Structure

### Active Files
```
├── ai_inspector_v2.ipynb          # CURRENT - Dual AI pipeline
├── PROJECT_STATUS.md              # This file
├── Json library/                  # SW JSON files from C# extractor
│   └── 320740.json               # Example part
├── schemas/
│   └── sw_to_evidence_mapping.json # Mapping schema v1.1.1
└── sw_json_library/               # Uploaded to Colab
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
```

---

## Output Files (per inspection)

| File | Contents |
|------|----------|
| `ResolvedPartIdentity.json` | Part number, confidence, SW JSON path |
| `QwenUnderstanding.json` | Qwen's visual analysis (views, features, material) |
| `DrawingEvidence.json` | Merged OCR + Qwen callouts |
| `DiffResult.json` | Comparison results (found/missing/extra) |

---

## Next Steps

### Immediate Fixes
1. ~~Fix Qwen import error~~ ✓ Done (Qwen2_5_VLForConditionalGeneration)
2. Improve merge logic for imperial/metric deduplication
3. Filter general notes from Qwen features
4. Add warning for parts with zero requirements

### Short Term
5. Test with more parts from library
6. Batch processing mode
7. Generate QC report markdown

### Future Enhancements
8. GD&T symbol detection
9. Surface finish text matching
10. RAG for ASME Y14.5 reference
11. Visual similarity search

---

## Quick Start

### Run Inspector (Colab)
1. Open `ai_inspector_v2.ipynb` in Google Colab
2. Upload `sw_json_library.zip` when prompted
3. Upload PDF drawing when prompted
4. Run all cells
5. Check `DiffResult.json` for results

### Test Part
- **Part:** 320740 (GROUNDING BUS 8 POINT)
- **Expected:** 3 requirements (M6x1.0, M5x0.8 7X, ø7.10mm THRU 2X)
- **Result:** 100% match rate

---

## Change Log

### January 27, 2025 - Working Dual AI Pipeline
- **Built ai_inspector_v2.ipynb** with LightOnOCR-2 + Qwen2.5-VL-7B
- **Achieved 100% match rate** on test part 320740
- **Implemented evidence merge** combining OCR precision with Qwen visual context
- **Fixed Qwen import error** (Qwen2_5_VLForConditionalGeneration)
- **Added json-repair** for handling malformed LLM JSON output
- **Documented limitations:**
  - Linear dimensions not in SW JSON
  - Curves/splines not supported
  - General notes filtered (not CAD features)
  - Parts with no holes pass by default

### January 22, 2025 - C# Extractor Refinements
- Added THRU vs BLIND classification
- Added entry treatment detection
- Added pattern instance centers
- Added mate quality indicators
- Added extraction modes (Fast/Full)

### January 22, 2025 - Migration to C# Extractor
- Deprecated VBA approach
- Built C# SolidWorksExtractor scaffold
- Designed comparison.holeGroups schema

---

## Contact / Notes

- Assembly: **400S** (band saw machine)
- SolidWorks version: **2023**
- Colab GPU: Required (for Qwen2.5-VL)
- Total GPU memory needed: ~19 GB (LightOnOCR + Qwen)
