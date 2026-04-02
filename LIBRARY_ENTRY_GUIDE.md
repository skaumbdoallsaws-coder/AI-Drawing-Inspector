# InspectorPro Library Entry Guide

Step-by-step instructions for adding new parts and assemblies to the `400S_Sorted_Library/` database.

---

## Part Number Assignment

Use `next_pn.py` to generate an unused part number:

```
python next_pn.py          # next available in 1030xxx series (default)
python next_pn.py 1020     # next available in 1020xxx series
python next_pn.py 1040     # next available in 1040xxx series
```

| Type | Format | Range | Example |
|------|--------|-------|---------|
| Parts | 7-digit | `10xxxxx` | `1030017` |
| Assemblies | 7-digit | `6000xxx` | `6000100` |

---

## Part Entry — Complete Workflow

### Prerequisites in SolidWorks

Set these **Custom Properties** on the part file (File > Properties > Custom tab):

| Property | Example | Notes |
|----------|---------|-------|
| `PartNo` | `1030017` | Primary lookup key |
| `Description` | `HOLDER` | Part name shown in the UI |
| `Revision` | `A` | Optional |
| `Material` | `Plain Carbon Steel` | Optional — extractor also reads assigned material |

### Step 1: Run the SolidWorks Extractor on the Part

Open the part in SolidWorks, then run:

```
SolidWorksExtractor.exe <part_file>.SLDPRT --output 400S_Sorted_Library
```

**What this produces:**

| File | Description |
|------|-------------|
| `{PN}.json` | Raw part profile — identity, physical properties, features, geometry, sketches |
| `{PN}_colored.glb` | Per-feature colored 3D model (enables feature highlighting in app) |
| `{PN}_feature_colors.json` | Feature-to-color mapping for the GLB |
| `{PN}.STL` | 3D mesh (fallback viewer, geometry diff input) |
| `{PN}_view_front.png` | Front view screenshot |
| `{PN}_view_top.png` | Top view screenshot |
| `{PN}_view_right.png` | Right view screenshot |
| `{PN}_view_isometric.png` | Isometric view screenshot |

### Step 2: Run the Drawing Extractor

Open the part's drawing (`.SLDDRW`) in SolidWorks, then run:

```
SolidWorksExtractor.exe <drawing_file>.SLDDRW --output 400S_Sorted_Library
```

**What this produces:**

| File | Description |
|------|-------------|
| `{PN}_drawing_map.json` | Every annotation on the drawing — dimensions, notes, GD&T — organized by sheet/view with sheet coordinates and bounding boxes |

This map powers: Dimension Explorer, dimension overlay, FAI balloons, view boundary detection, and ASME reference linking.

### Step 3: Copy the Drawing PDF

Copy the engineering drawing PDF to the library:

```
copy <drawing>.pdf 400S_Sorted_Library\{PN}.pdf
```

### Step 4: Verify the Raw Extractor Output

Open `{PN}.json` and check:

- [ ] `identity.customProperties.PartNo` matches the assigned part number
- [ ] `identity.description` is populated
- [ ] `physical.assignedMaterial` has a value
- [ ] `features` section has the expected holes, extrudes, cuts, etc.
- [ ] `sketches` section is populated (needed for sketch-line verification)

If identity fields are null, patch them manually in the JSON.

### Step 5: Generate the Inspection Profile (Claude Browser)

The `_inspection_profile.json` is an **AI-enriched** file — NOT a copy of the raw extractor JSON. It contains human-quality descriptions that the inspection engine (Iris) reasons from.

#### What to upload to Claude browser:

| File | Purpose |
|------|---------|
| `{PN}.json` | Raw extractor data (features, dimensions, physical) |
| `{PN}_drawing_map.json` | Drawing annotations and view layout |
| `{PN}.pdf` | Engineering drawing for visual reference |
| `{PN}_view_front.png` | CAD front view |
| `{PN}_view_top.png` | CAD top view |
| `{PN}_view_right.png` | CAD right view |
| `{PN}_view_isometric.png` | CAD isometric view |

#### What to ask Claude to generate:

```json
{
  "part_number": "1030017",
  "part_name": "HOLDER",
  "part_description": "A detailed 2-3 sentence description of the part — shape, function, key dimensions, material. Written as a senior engineer would describe it to a colleague.",
  "features": [
    {
      "name": "Human-readable name (e.g., 'M5 Countersunk Mounting Holes')",
      "type": "HoleWizard / Extrude / Cut / Chamfer / Fillet / etc.",
      "count": 4,
      "spatial_description": "Where this feature appears on the part and how it looks in each standard view (front, top, right, isometric). Be specific about positions, orientations, visual signatures."
    }
  ],
  "view_expectations": {
    "front_or_plan": "What should be visible in the front view — overall shape, visible features, hidden lines, critical dimensions.",
    "side_or_right": "What should be visible in the right/side view.",
    "top": "What should be visible in the top view.",
    "isometric": "What the isometric view reveals about the 3D form.",
    "section_views": "What section views on the drawing should show.",
    "detail_views": "What detail views on the drawing should show."
  }
}
```

**Quality standard:** The `part_description` should read like engineering documentation. Each `spatial_description` should be specific enough that someone who has never seen the part could find the feature on the drawing.

**Reference example:** `400S_Sorted_Library/1020001_inspection_profile.json` (Piston)

#### Save as: `{PN}_inspection_profile.json`

### Step 6: Generate Dimension Descriptions (Claude Browser)

Upload the same files as Step 5 (or continue the same Claude session).

#### What to ask Claude to generate:

```json
{
  "partNumber": "1030017",
  "partName": "HOLDER",
  "generatedBy": "Claude",
  "descriptions": {
    "ViewName/AnnotationName": "What this dimension measures",
    "Drawing View1/RD1": "Overall holder width",
    "Section View C-C/RD1": "Bore depth from top face",
    "Detail View B (1 : 1)/RD2": "Chamfer width on bore entry"
  }
}
```

**How Claude should build it:**
1. Read the drawing map to get every annotation by view and name
2. Look at the drawing PDF to see what each dimension measures
3. Write concise, engineering-meaningful descriptions
4. Cover every annotation — no gaps

**Reference example:** `400S_Sorted_Library/1020001_dimension_descriptions.json` (Piston)

#### Save as: `{PN}_dimension_descriptions.json`

### Step 7: Generate Highlight Boxes (Claude Browser)

Upload the rendered drawing image (PDF rendered at 150 DPI or a high-res screenshot).

#### What to ask Claude to generate:

```json
{
  "annotations": [
    {
      "annotationName": "RD1",
      "viewName": "Drawing View2",
      "sheetName": "Sheet1",
      "boxPx": [x1, y1, x2, y2],
      "boxSheet": [sx1, sy1, sx2, sy2],
      "source": "vlm_3pass",
      "pass": 1,
      "quality": "initial"
    }
  ],
  "render": {
    "imageWidth": null,
    "imageHeight": null,
    "dpi": 150
  },
  "pipeline": "vlm_3pass",
  "invalidation": null
}
```

**How Claude should build it:**
1. Render the drawing at 150 DPI
2. For each annotation in the drawing map, locate it on the rendered drawing
3. Record pixel bounding box (`boxPx`) and sheet coordinates (`boxSheet`)
4. Sheet coords: `sx = px_x / img_width * sheet_width`, `sy = (1 - px_y / img_height) * sheet_height`

**Reference example:** `400S_Sorted_Library/1020001_highlight_boxes.json` (Piston — 32 annotations)

#### Save as: `{PN}_highlight_boxes.json`

### Step 8: Optional — Export STEP for Geometry Diff

If this part will have revision comparisons with geometry diff:

1. File → Save As → change type to `.stp` (AP214)
2. Save to: `400S_Sorted_Library/parts/{PN}/revA/{PN}.stp`
3. For Rev B, repeat with the modified part: `400S_Sorted_Library/parts/{PN}/revB/{PN}.stp`

### Part Entry — Complete File Checklist

| # | File | Required | Source | Enables |
|---|------|----------|--------|---------|
| 1 | `{PN}.json` | Yes | SolidWorks Extractor | Part recognition, feature data |
| 2 | `{PN}_inspection_profile.json` | Yes | Claude browser | AI inspection reasoning |
| 3 | `{PN}_colored.glb` | Yes | SolidWorks Extractor (GlbExporter) | Feature highlighting in 3D |
| 4 | `{PN}_feature_colors.json` | Yes | SolidWorks Extractor (PartColorizer) | Feature color mapping |
| 5 | `{PN}.STL` | Yes | SolidWorks Save As | 3D viewer fallback, geometry diff |
| 6 | `{PN}_drawing_map.json` | Yes | SolidWorks Extractor (drawing) | Dimension overlay, FAI, view detection |
| 7 | `{PN}_dimension_descriptions.json` | Yes | Claude browser | Dimension Explorer labels |
| 8 | `{PN}_highlight_boxes.json` | Yes | Claude browser | Dimension highlight rectangles |
| 9 | `{PN}.pdf` | Yes | Drawing PDF | Drawing tab display |
| 10 | `{PN}_view_front.png` | Yes | SolidWorks Extractor | CAD reference view |
| 11 | `{PN}_view_top.png` | Yes | SolidWorks Extractor | CAD reference view |
| 12 | `{PN}_view_right.png` | Yes | SolidWorks Extractor | CAD reference view |
| 13 | `{PN}_view_isometric.png` | Yes | SolidWorks Extractor | CAD reference view |

**Total: 13 files per part**

| Source | Files | Count |
|--------|-------|-------|
| SolidWorks Extractor (part) | .json, _colored.glb, _feature_colors.json, 4 PNGs | 7 |
| SolidWorks Extractor (drawing) | _drawing_map.json | 1 |
| SolidWorks manual | .STL, .pdf | 2 |
| Claude browser | _inspection_profile.json, _dimension_descriptions.json, _highlight_boxes.json | 3 |

### Quick Reference — Adding a New Part

```
1. python next_pn.py                    → get part number
2. Set Custom Properties in SolidWorks  → PartNo, Description
3. SolidWorksExtractor on .SLDPRT       → .json, .glb, _feature_colors, .STL, 4 PNGs
4. SolidWorksExtractor on .SLDDRW       → _drawing_map.json
5. Copy .pdf to library                 → drawing for inspection
6. Claude browser: inspection profile   → _inspection_profile.json
7. Claude browser: dim descriptions     → _dimension_descriptions.json
8. Claude browser: highlight boxes      → _highlight_boxes.json
9. Verify 13 files in 400S_Sorted_Library/
```

---

## Assembly Entry

*(Unchanged from previous version — see assembly sections below)*

### Prerequisites in SolidWorks

Set Custom Properties on the assembly + all component parts.

### Steps

1. Extract all component parts first (per-part workflow above)
2. Run extractor on the assembly file
3. Run `--colorize-only` mode → take screenshots, export GLB
4. Verify assembly JSON
5. Generate functional narrative (Claude browser)
6. Copy all files to `400S_Sorted_Library/assemblies/`

### Assembly File Checklist

| # | File | Location | Source |
|---|------|----------|--------|
| 1 | `{Assy}_assembly.json` | `assemblies/` | SolidWorks Extractor |
| 2 | `{Assy}_colored.glb` | `assemblies/` | SolidWorks Save As GLB (during Colorize-Only) |
| 3 | `{Assy}_narrative.txt` | `assemblies/` | Claude browser |
| 4 | `{Assy}_view_front.png` | `assemblies/` | Extractor (colorized) |
| 5 | `{Assy}_view_top.png` | `assemblies/` | Extractor (colorized) |
| 6 | `{Assy}_view_right.png` | `assemblies/` | Extractor (colorized) |
| 7 | `{Assy}_view_isometric.png` | `assemblies/` | Extractor (colorized) |
| 8+ | Per-part files (13 each) | root | Per-part workflow |

**Total per assembly: 7 assembly-level files + (13 files × N unique parts)**

---

## Revision Support (for Geometry Diff)

For parts with multiple revisions:

```
400S_Sorted_Library/
  parts/
    {PN}/
      revA/
        {PN}.stp              ← STEP solid (AP214)
        {PN}.stl              ← STL mesh
        {PN}_colored.glb      ← colored GLB (if available)
        {PN}_feature_colors.json
      revB/
        {PN}.stp
        {PN}.stl
        {PN}_colored.glb
        {PN}_feature_colors.json
```

Export STEP as AP214 for geometry diff. The geometry diff worker compares the solids and produces overlays automatically.

---

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| Part not found in search | Profile JSON missing or server not restarted | Add .json, restart server |
| No feature highlighting | Missing _colored.glb | Re-run extractor with GLB export |
| No dimension overlay | Missing _drawing_map.json | Run extractor on .SLDDRW |
| "No 3D model available" | Missing .STL and .glb | Export STL from SolidWorks |
| Geometry diff fails | Missing .stp files in parts/{PN}/revX/ | Export STEP from SolidWorks |
| Inspection profile too generic | Used raw .json instead of Claude-enriched profile | Re-generate with Claude browser |
| Dimensions not labeled | Missing _dimension_descriptions.json | Generate with Claude browser |
| No highlight boxes on drawing | Missing _highlight_boxes.json | Generate with Claude browser |
| `identity.partNumber` is null | Custom Properties not set before extraction | Patch JSON or re-extract |
