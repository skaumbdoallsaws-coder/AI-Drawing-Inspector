# AI Engineering Drawing Inspector - Project Status

**Last Updated:** January 22, 2025

---

## Project Goal

Build an AI-powered system that **verifies engineering drawings (PDFs) against CAD model data** from SolidWorks. The inspector checks that drawings contain all required features (thread callouts, hole dimensions, tolerances) that match the CAD model specifications.

---

## Architecture Overview

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│  PDF Drawing    │────▶│  AI Inspector        │────▶│  PASS / FAIL    │
│  (user upload)  │     │  (Colab notebook)    │     │  + details      │
└─────────────────┘     └──────────────────────┘     └─────────────────┘
                              │
                              ▼
                  ┌──────────────────────┐
                  │ Part Context JSON    │
                  │ (from C# Extractor)  │
                  └──────────────────────┘
```

**Key Components:**
- **LightOnOCR-2**: Extracts text from drawing images
- **Qwen2-VL-7B**: Vision-language model for verification reasoning
- **Part Context Database**: CAD-extracted requirements per part

---

## Current Status: Migrating to C# Extractor

### Why the Change?
The VBA macro approach had significant issues:
- Frequent crashes and instability
- Hole diameter API returning 0.0
- Difficult to maintain and debug
- Inconsistent output requiring complex parsing

### New Approach: C# SolidWorks API
- More stable and maintainable
- Proper error handling
- Typed feature extraction
- Clean JSON output directly
- Geometry analysis for ground truth verification

---

## What We Have Built

### 1. C# SolidWorks Extractor (NEW - In Progress)

**Location:** `SolidWorksExtractor/`

**Status:** Architecture refined, ready to build and test

**Schema Version:** 1.0.0

| Component | Purpose |
|-----------|---------|
| `Program.cs` | CLI entry point |
| `Services/SolidWorksConnection.cs` | Connect to SW, open documents |
| `Services/PropertyExtractor.cs` | Custom props, material, mass, bounding box |
| `Services/FeatureExtractor.cs` | Typed feature extraction with routing table |
| `Services/FeatureTypeRouter.cs` | **NEW** - Version-tolerant feature type routing |
| `Services/GeometryAnalyzer.cs` | Cylinder/plane/slot detection from geometry |
| `Services/HoleReconciler.cs` | **NEW** - Dual-source hole extraction (intent + geometry) |
| `Services/AssemblyExtractor.cs` | Mates with limits, hierarchy, transforms |
| `Models/Units.cs` | **NEW** - Explicit units (meters/mm/inches) |
| `Models/ComparisonData.cs` | **NEW** - LLM-ready comparison structures |
| `Output/JsonSerializer.cs` | Versioned JSON output |

**Key Design Refinements:**

1. **Dual-Source Hole Extraction**
   - Source A (Intent): Thread, c'bore/c'sink, depth from IWizardHoleFeatureData2
   - Source B (Truth): Actual geometry scan - diameter, axis, centers
   - Reconciliation: Maps feature intent to geometry instances

2. **Feature Type Routing with Fallbacks**
   - Routing table handles version/locale variations in GetTypeName2()
   - Graceful fallback when GetDefinition() returns null
   - Comprehensive sheet metal type handling

3. **Comparison-Ready Output**
   - Holes grouped logically (patterns, same size)
   - Slot recognition (width x length vs diameter)
   - Required callouts with alternatives

4. **Explicit Units Throughout**
   - All dimensions include: SystemValue (meters), mm, inches
   - Angles include: radians and degrees
   - Prevents scaling errors from VBA approach

5. **Assembly Mate Enhancements**
   - Full MateType enum matching swMateType_e
   - Mate limits (min/max) for distance/angle mates
   - Component path + instance for entity identification

**Features:**
- Hole Wizard: type, diameter, depth, thread info, counterbore/countersink, instance count
- Extrudes/Cuts: end conditions, depths, draft angles
- Fillets/Chamfers: radii, distances, angles
- Patterns: linear, circular, mirror with counts and spacing
- Sheet Metal: thickness, bend radius, K-factor, bend allowance type, flat pattern
- Slots: width, length, depth, centerline detection
- Geometry Ground Truth: cylinder/slot detection independent of features
- Assembly: full hierarchy, transforms, all mate types with limits
- Comparison-ready output for LLM drawing inspection

**Session 3 Enhancements:**
- THRU/BLIND hole classification with axis-extent analysis and confidence levels
- Entry treatment detection (countersink, counterbore, chamfer) from geometry
- Pattern instance centers with bolt circle diameter calculation
- Stable reference frames (part coordinate systems, assembly transforms with Euler/quaternion)
- Per-configuration suppression tracking for all features
- Sheet metal bend filtering (exclude bend cylinders from hole detection)
- Mate entity quality indicators (High/Medium/Low) based on reference type
- Extraction modes (Fast vs Full) for performance optimization
- Expanded RequiredCallouts factory with 11 callout types

### 2. VBA Extraction Pipeline (LEGACY)

**Location:** `vba_extraction_legacy/`

**Status:** Deprecated - kept for reference and existing data

```
vba_extraction_legacy/
├── macros/              # VBA macro source files
├── parsers/             # Python scripts that parse VBA output
├── extracted_data/      # Raw extraction output (.txt files)
└── json_databases/      # Parsed JSON databases (still usable)
```

**Existing Data (from VBA pipeline):**
- `sw_part_context_complete.json` - 202 unique parts (can still be used until C# extractor produces new data)

### 3. Inspector Notebook

**File:** `ai_inspector_unified.ipynb`

**Current state:**
- Uses unified `sw_part_context_complete.json` (from legacy VBA extraction)
- Stage 1 only (verification against checklist)
- RAG and Stage 2 removed (to be added later)
- Supports single file and batch inspection

---

## Data Sources

### Extracted from 400S Assembly (via VBA - legacy)

| Source | Count |
|--------|-------|
| Sub-assemblies processed | 40 |
| Total mates extracted | 1,114 |
| Parts with mate relationships | 239 |
| Unique parts in database | 202 |

### Drawing Files

| Location | Files | Notes |
|----------|-------|-------|
| `400S_Sorted_Library/` | 265 PDFs | Organized by assembly |
| `400S_Unmatched_Files/` | 16 PDFs | Couldn't match to parts |
| `PDF VAULT/` | 1,258 PDFs | All company drawings (not just 400S) |

---

## Known Issues & Gaps

### Issues to be Resolved by C# Extractor

| Issue | VBA Status | C# Solution |
|-------|------------|-------------|
| Hole diameter = 0.0 | Broken | Parses from name + geometry analysis |
| Empty verification checklists | Limited | Comprehensive auto-generation |
| Instance count mismatch | Unreliable | Proper instance counting |
| Unstable extraction | Crashes | Robust error handling |

### Remaining Issues

- **PN Normalization Edge Cases**: Some filename patterns may not match
- **OCR accuracy**: Dependent on drawing quality

---

## File Inventory

### C# Extractor (NEW)
```
SolidWorksExtractor/
├── Program.cs                    # CLI entry point
├── SolidWorksExtractor.csproj    # .NET 4.8 project
├── README.md                     # Documentation
├── Services/
│   ├── SolidWorksConnection.cs   # SW connection handling
│   ├── PropertyExtractor.cs      # Custom props, material
│   ├── FeatureExtractor.cs       # Feature tree traversal
│   ├── FeatureTypeRouter.cs      # Version-tolerant routing
│   ├── GeometryAnalyzer.cs       # Cylinder/slot detection
│   ├── HoleReconciler.cs         # Intent + geometry reconciliation
│   └── AssemblyExtractor.cs      # Mates, hierarchy, transforms
├── Models/
│   ├── PartData.cs               # Part output with schema version
│   ├── FeatureData.cs            # Typed features + config suppression
│   ├── GeometryData.cs           # Ground truth + THRU/BLIND analysis
│   ├── AssemblyData.cs           # Assembly + mate quality indicators
│   ├── Units.cs                  # Explicit units (m/mm/in)
│   ├── ComparisonData.cs         # LLM-ready + RequiredCalloutFactory
│   └── ExtractionOptions.cs      # Fast/Full extraction modes
└── Output/
    └── JsonSerializer.cs         # Versioned JSON output
```

### Legacy VBA Pipeline
```
vba_extraction_legacy/
├── macros/                       # VBA source (.txt, .swp)
├── parsers/                      # Python parsers
├── extracted_data/               # Raw .txt output
│   └── 40 sub-assemblies mates/  # Mate files
└── json_databases/               # Parsed JSON (still usable)
    └── sw_part_context_complete.json
```

### Notebooks
```
├── ai_inspector_unified.ipynb     # CURRENT - Stage 1 only
├── ai_inspector_final_fixed.ipynb # Previous version
└── ai_inspector_rag.ipynb         # Earlier experiments
```

---

## Next Steps

### Immediate
1. **Build C# Extractor** in Visual Studio
2. **Test with single part** - verify feature extraction works
3. **Test with 400S assembly** - extract all components and mates

### Short Term
4. **Generate new JSON database** using C# extractor
5. **Update inspector notebook** to use new JSON format
6. **Compare results** - verify C# output matches/improves on VBA data

### Future
7. **Re-add RAG system** - ASME Y14.5 reference lookup
8. **Re-add Stage 2** - GD&T improvement suggestions
9. **Build visual index** - for drawing similarity search

---

## Quick Start for Next Session

### To build and test C# Extractor:
1. Open `SolidWorksExtractor/SolidWorksExtractor.csproj` in Visual Studio
2. Verify Interop DLL paths match your SolidWorks 2023 installation
3. Build solution (F6)
4. Open a part in SolidWorks
5. Run: `bin\Debug\SolidWorksExtractor.exe`

### To extract from 400S assembly:
```bash
SolidWorksExtractor.exe "path\to\400S.sldasm" --resolve
```

### To use existing data with inspector (legacy):
```python
import json
with open('vba_extraction_legacy/json_databases/sw_part_context_complete.json') as f:
    db = json.load(f)
print(db.get('318127'))  # Lookup by NEW PN
```

---

## Change Log

### January 22, 2025 (Session 3) - QC-Ready Refinements
Implemented 9 "must-have" items to prevent real-world inspection failures:

1. **THRU vs BLIND Classification**: Axis-extent analysis projects boundary edges onto cylinder axis to determine if hole opens at both ends. Includes confidence levels (High/Medium/Low) and classification reasoning.

2. **Entry Treatment Detection**: Analyzes faces adjacent to hole entry for counterbore (larger cylinder), countersink (cone), or chamfer (small angled face). Extracts diameter, depth, and angle.

3. **Pattern Output Enhancement**: Explicit instance centers with X/Y/Z coordinates, axis direction vectors, bolt circle diameter calculation from instance positions, angle per instance for circular patterns.

4. **Stable Reference Frames**: Extracts part coordinate systems (origin planes, axes) and assembly transforms with Euler angles (XYZ rotation) and quaternions for unambiguous orientation.

5. **Configuration Support**: Tracks suppression state per configuration for all features. `SuppressionByConfig` dictionary shows which configs have feature active/suppressed.

6. **Sheet Metal Bend Filtering**: Detects sheet metal parts, collects bend radii, marks cylinders matching bend radii as `IsSheetMetalBend=true` to exclude from hole detection.

7. **Mate Entity Quality Indicators**: Rates mate references as High (named planes/axes), Medium (named with issues), or Low (anonymous faces). Helps identify fragile mate references.

8. **Extraction Modes**: `--fast` skips expensive operations (geometry analysis, per-config suppression, pattern locations). `--full` (default) does complete extraction.

9. **Expanded RequiredCallouts**: Factory methods for 11 callout types: Hole, Thread, SheetMetalThickness, BendRadius, Material, SurfaceFinish, BreakEdges, Fillet, Chamfer, Pattern, GDT.

New file: `Models/ExtractionOptions.cs` - Controls extraction depth and performance.

### January 22, 2025 (Session 2) - Architecture Refinements
Based on user feedback for QC-ready extraction:

- **Added FeatureTypeRouter**: Version-tolerant routing with aliases and fallbacks
- **Added HoleReconciler**: Dual-source extraction (intent + geometry reconciliation)
- **Added slot detection**: GeometryAnalyzer now detects slots (width x length)
- **Added Units model**: Explicit meters/mm/inches throughout to prevent scaling errors
- **Added ComparisonData model**: LLM-ready structures with hole groups, patterns, callouts
- **Enhanced MateData**: Full enum types, mate limits, component paths with instances
- **Added schema versioning**: JSON output includes version for compatibility

Key design decisions:
- Treat GetTypeName2() as routing hint, not guarantee
- Always provide both feature intent AND geometry ground truth for holes
- Group holes logically for pattern/instance comparison
- Include alternative callout formats for fuzzy matching

### January 22, 2025 (Session 1)
- **Reorganized project structure**: Moved all VBA-related files to `vba_extraction_legacy/`
- **Created C# SolidWorksExtractor**: Full scaffold with typed feature extraction
  - Services: Connection, Property, Feature, Geometry, Assembly extractors
  - Models: Part, Feature, Geometry, Assembly data structures
  - Output: Custom JSON serializer
- **Decision**: Migrate from VBA to C# for more reliable extraction

---

## Contact / Notes

- Assembly: **400S** (band saw machine)
- Parts use **OLD PN** in CAD filenames (e.g., `017-134.SLDPRT`)
- Drawings use **NEW PN** on title block (e.g., `318127`)
- Database supports lookup by both OLD and NEW PN
- SolidWorks version: **2023**
