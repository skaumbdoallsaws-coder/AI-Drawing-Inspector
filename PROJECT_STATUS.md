# AI Engineering Drawing Inspector - Project Status

**Last Updated:** January 27, 2025

---

## Project Goal

Build an AI-powered system that **verifies engineering drawings (PDFs) against CAD model data** from SolidWorks. The inspector checks that drawings contain all required features (thread callouts, hole dimensions, tolerances) that match the CAD model specifications.

---

## Current Status: v2.0 Complete - Multi-Model Pipeline

### Architecture (v2.0 Final)

```
┌─────────────────┐     ┌───────────────────────────────────────────────────────┐     ┌─────────────────┐
│  PDF Drawing    │────▶│  AI Inspector v2 (Colab)                              │────▶│  QC Report      │
│  (user upload)  │     │                                                       │     │  PASS / FAIL    │
└─────────────────┘     │  ┌────────────┐  ┌──────────────────────────────────┐ │     │  + details      │
                        │  │LightOnOCR-2│  │ Qwen2.5-VL-7B (4 analyses)       │ │     └─────────────────┘
                        │  │(Text OCR)  │  │  1. Feature Extraction           │ │
                        │  └─────┬──────┘  │  2. Drawing Quality Audit        │ │
                        │        │         │  3. BOM Extraction               │ │
                        │        │         │  4. Manufacturing Notes          │ │
                        │        │         └───────────────┬──────────────────┘ │
                        │        │              MERGE      │                    │
                        │        └────────────┬────────────┘                    │
                        │                     ▼                                 │
                        │            ┌────────────────┐                         │
                        │            │Merged Evidence │                         │
                        │            └───────┬────────┘                         │
                        │                    │ COMPARE (inches)                 │
                        │                    ▼                                  │
                        │  ┌────────────────────────────────────┐               │
                        │  │  SW JSON Library (C# Extractor)    │               │
                        │  │  comparison.holeGroups             │               │
                        │  └────────────────────────────────────┘               │
                        │                    │                                  │
                        │                    ▼                                  │
                        │  ┌────────────────────────────────────┐               │
                        │  │  GPT-4o-mini (QC Report Generator) │               │
                        │  │  Synthesizes all data into report  │               │
                        │  └────────────────────────────────────┘               │
                        └───────────────────────────────────────────────────────┘
```

### Latest Test Results (Part 320740)

| Metric | Value |
|--------|-------|
| Match Rate | **100%** |
| SW Requirements | 3 (M6x1.0, M5x0.8 7X, ø0.2795" THRU 2X) |
| Found | 3 |
| Missing | 0 |
| Extra | 2 (duplicates - known issue) |

### Pipeline Components

| Component | Model | Status | Notes |
|-----------|-------|--------|-------|
| Text Extraction | LightOnOCR-2-1B | ✓ Working | ~2 GB VRAM |
| Feature Extraction | Qwen2.5-VL-7B | ✓ Working | Holes, threads, fillets, chamfers |
| Drawing Quality Audit | Qwen2.5-VL-7B | ✓ Working | Title block, tolerances, best practices |
| BOM Extraction | Qwen2.5-VL-7B | ✓ Working | Parts list from assembly drawings |
| Manufacturing Notes | Qwen2.5-VL-7B | ✓ Working | Heat treat, finish, plating, welding |
| Evidence Merge | Custom Python | ✓ Working | Links OCR dims with Qwen context |
| SW Comparison | Custom Python | ✓ Working | Inches-based, 0.015" tolerance |
| QC Report Generation | GPT-4o-mini | ✓ Working | Comprehensive markdown report |

---

## Qwen2.5-VL Analysis Capabilities

### 1. Feature Extraction
Identifies machined features from the drawing:
- Tapped holes (M6x1.0, 1/4-20, etc.)
- Through/blind holes with diameters
- Counterbores and countersinks
- Fillets and chamfers
- Slots

### 2. Drawing Quality Audit
Checks drawing completeness and best practices:
- **Title Block:** Part number, description, material, revision, scale, date, signatures
- **Drawing Quality:** Views labeled, dimensions readable, tolerances present
- **Standards:** Surface finish callout, general tolerance block, projection symbol
- **Overall Score:** 1-10 rating with issues list

### 3. BOM Extraction (Assembly Drawings)
Extracts Bill of Materials when present:
- Item numbers and part numbers
- Descriptions and quantities
- Materials (if in BOM)
- Location on drawing

### 4. Manufacturing Notes
Extracts manufacturing specifications:
- **Heat Treatment:** Hardness, process (carburize, through harden)
- **Surface Finish:** Ra values, specific surface callouts
- **Plating/Coating:** Zinc plate, anodize, paint, powder coat
- **Welding:** AWS specs, weld types
- **Special Processes:** Stress relieve, shot peen, passivate
- **Inspection Requirements:** CMM, first article, 100% inspect
- **Certifications:** Material certs, PPAP

---

## Comparison Capabilities & Limitations

### What CAN Be Compared

| Feature Type | SW JSON Source | Drawing Detection | Status |
|--------------|----------------|-------------------|--------|
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
| **GD&T Symbols** | Complex - requires specialized parsing | Future enhancement |

### Units

- **All comparisons done in INCHES** (drawings are in inches)
- Metric threads (M6x1.0) compared in mm for thread specs
- Tolerance: 0.015" for hole diameter matching

### Parts with No Extractable Features

For parts with **only linear dimensions and curves** (no holes, fillets, or chamfers):
- SW requirements list will be **empty**
- Match rate will be **N/A**
- Part will **pass by default** (nothing to fail)

**Affected part types:** Simple plates, spacers, brackets without holes

---

## Known Issues (v2.0)

### 1. Duplicate Detection
**Problem:** Same feature detected by both OCR and Qwen, reported as separate items.

**Impact:** False "Extra" items in report

**Status:** Minor - report still accurate for verification

### 2. Low Feature Count Warning
**Problem:** Parts with 0 requirements silently pass.

**Impact:** No visibility into parts that couldn't be verified

**Planned fix for v3:** Add explicit warning

---

## File Structure

### Active Files
```
├── ai_inspector_v2.ipynb          # STABLE - Full pipeline
├── ai_inspector_v3.ipynb          # DEVELOPMENT - Next version
├── PROJECT_STATUS.md              # This file
├── sw_json_library/               # SW JSON files from C# extractor
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

## v3 Roadmap

### Planned Enhancements
1. **Batch Processing Mode** - Process multiple drawings in sequence
2. **Low Feature Warning** - Alert when part has 0 verifiable requirements
3. **Improved Deduplication** - Better merge logic for OCR+Qwen overlap
4. **GD&T Symbol Detection** - Parse geometric tolerancing symbols
5. **Visual Similarity Search** - Find similar drawings in archive
6. **RAG for ASME Y14.5** - Reference standards for validation

### API Keys Required (Colab Secrets)
- `HF_TOKEN` - Hugging Face (for model downloads)
- `OPENAI_API_KEY` - OpenAI (for GPT-4o-mini reports)

---

## Quick Start

### Run Inspector (Colab)
1. Open `ai_inspector_v2.ipynb` in Google Colab
2. Ensure secrets are set: `HF_TOKEN`, `OPENAI_API_KEY`
3. Upload `sw_json_library.zip` when prompted
4. Upload PDF drawing when prompted
5. Run all cells
6. Review `QCReport.md` for comprehensive results

### Test Part
- **Part:** 320740 (GROUNDING BUS 8 POINT)
- **Expected:** 3 requirements (M6x1.0, M5x0.8 7X, ø0.2795" THRU 2X)
- **Result:** 100% match rate

---

## Change Log

### January 27, 2025 - v2.0 Complete (BOM + Mfg Notes)
- **Added BOM Extraction** - Qwen extracts parts list from assembly drawings
- **Added Manufacturing Notes** - Heat treat, finish, plating, welding, inspection
- **Enhanced GPT Report** - Now includes all 4 Qwen analyses
- **Switched to inches** - All hole comparisons in inches (no mm conversion)
- **Filtered general notes** - "REMOVE ALL BURRS" no longer misclassified

### January 27, 2025 - GPT-4o-mini Integration
- **Added Cell 13** - GPT-4o-mini QC report generation
- **Drawing Quality Audit** - Title block completeness, best practices check
- **Comprehensive reports** - Synthesizes all extracted data

### January 27, 2025 - Working Dual AI Pipeline
- **Built ai_inspector_v2.ipynb** with LightOnOCR-2 + Qwen2.5-VL-7B
- **Achieved 100% match rate** on test part 320740
- **Implemented evidence merge** combining OCR precision with Qwen visual context
- **Fixed Qwen import error** (Qwen2_5_VLForConditionalGeneration)
- **Added json-repair** for handling malformed LLM JSON output

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
- **Total GPU memory:** ~19 GB (LightOnOCR + Qwen)
- **GPT-4o-mini cost:** ~$0.01-0.02 per report
