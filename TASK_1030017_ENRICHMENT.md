# Task: Generate Enriched Files for Part 1030017 (Holder)

**Part Number:** 1030017
**Part Name:** Holder
**Material:** Plain Carbon Steel
**Bounding Box:** 254mm x 254mm x 177.8mm (10" x 10" x 7")

## Input Files (already in 400S_Sorted_Library/)

- `1030017.json` — raw extractor profile (features, dimensions, physical properties)
- `1030017_drawing_map.json` — drawing map (views, annotations, sheet positions)
- `1030017.pdf` — engineering drawing PDF
- `1030017_view_front.png` — CAD front view
- `1030017_view_top.png` — CAD top view
- `1030017_view_right.png` — CAD right view
- `1030017_view_isometric.png` — CAD isometric view

## Output Files to Generate

### 1. `1030017_inspection_profile.json`

**Purpose:** The enriched, human-readable inspection profile that the AI inspection engine (Iris) uses to reason about the part. This is NOT a copy of the raw extractor JSON — it is a curated, descriptive document.

**Format:**
```json
{
  "part_number": "1030017",
  "part_name": "Holder",
  "part_description": "A detailed 2-3 sentence description of what this part is, what it does, its overall shape, key dimensions, and material. Describe it as an engineer would to a colleague.",
  "features": [
    {
      "name": "Human-readable feature name (e.g., 'M5 Countersunk Mounting Holes')",
      "type": "Feature type (e.g., 'HoleWizard', 'Extrude', 'Cut', 'Chamfer', 'Fillet')",
      "count": 4,
      "spatial_description": "Describe where this feature is on the part and how it would appear in each standard view (front, top, right, isometric). Be specific about positions, orientations, and visual signatures. This helps Iris locate the feature on the drawing."
    }
  ],
  "view_expectations": {
    "front_or_plan": "Describe what should be visible in the front view — overall shape, visible features, hidden lines, critical dimensions.",
    "side_or_right": "Describe what should be visible in the right/side view.",
    "top": "Describe what should be visible in the top view.",
    "isometric": "Describe what the isometric view reveals about the 3D form.",
    "section_views": "If the drawing has section views, describe what they should show.",
    "detail_views": "If the drawing has detail views, describe what they should show."
  }
}
```

**How to build it:**
1. Read `1030017.json` to understand the part's features, dimensions, and physical properties
2. Look at the 4 view PNGs to understand the part's shape
3. Look at `1030017_drawing_map.json` to see what views and annotations exist on the drawing
4. Write rich, engineering-quality descriptions for each feature
5. Write view expectations that describe what should appear in each drawing view
6. The `part_description` should read like a senior engineer describing the part to a colleague

**Reference example:** See `1020001_inspection_profile.json` (Piston) for the expected quality level.

**Raw data from extractor (use this to build from):**

Features in `1030017.json`:
- `holeWizardHoles`: 1 entry — "7/8 (0.875) Diameter Hole1" (⌀22.23mm THRU, 4 instances)
- `extrudes`: 2 entries — "Boss-Extrude1", "Boss-Extrude2"
- `cuts`: 1 entry — "Cut-Extrude1"
- `chamfers`: 1 entry — "Chamfer1"
- 5 sketches

Physical properties:
- Mass: 36.59 oz (1037g)
- Material: Plain Carbon Steel
- Bounding box: 254mm x 254mm x 177.8mm

---

### 2. `1030017_dimension_descriptions.json`

**Purpose:** Human-readable descriptions for each dimension annotation on the drawing. These appear in the Dimension Explorer panel and help Iris explain what each dimension represents.

**Format:**
```json
{
  "partNumber": "1030017",
  "partName": "Holder",
  "generatedBy": "Claude",
  "descriptions": {
    "ViewName/AnnotationName": "Description of what this dimension measures",
    "Drawing View1/RD1": "Overall holder width",
    "Section View C-C/RD1": "Bore depth from top face"
  }
}
```

**How to build it:**
1. Read `1030017_drawing_map.json` — it lists every annotation by view name and annotation name
2. Look at the drawing PDF (`1030017.pdf`) to see what each dimension measures
3. Look at the dimension values and types to understand the measurement
4. Write a concise, engineering-meaningful description for each dimension
5. Use the format `"ViewName/AnnotationName": "description"`

**Annotations from the drawing map:**

Sheet 0 has 6 views:
- `Drawing View1` (Named): 6 annotations — DetailItem649, DetailItem652, DetailItem653, + 3 more
- `Drawing View2` (Projected): 4 annotations — DetailItem665, RD1=0.254m, RD2=0.0508m, + 1 more
- `Drawing View3` (Projected): 1 annotation — RD1=0.254m
- `Drawing View4` (Projected): 0 annotations
- `Detail View B (1 : 1)` (Detail): 8 annotations — DetailItem656, DetailItem657, DetailItem660, + 5 more
- `Section View C-C` (Section): 3 annotations — DetailItem664, RD1=0.0762m, RD2=0.1524m

**Reference example:** See `1020001_dimension_descriptions.json` (Piston).

---

### 3. `1030017_highlight_boxes.json`

**Purpose:** Pixel-space bounding boxes for each dimension annotation on the rendered drawing. These enable the dimension overlay (yellow/green highlight rectangles) on the Drawing tab.

**Format:**
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

**How to build it:**
1. Render the drawing PDF at 150 DPI (or use the actual pixel dimensions)
2. For each annotation in the drawing map, locate it on the rendered drawing
3. Record the bounding box in both pixel coordinates (`boxPx`) and sheet coordinates (`boxSheet`)
4. Sheet coordinates are normalized: `sx = px_x / image_width * sheet_width`, `sy = (1 - px_y / image_height) * sheet_height`
5. Each box should tightly wrap the dimension text + leader lines

**Reference example:** See `1020001_highlight_boxes.json` (Piston) — 32 annotations with pixel and sheet coordinates.

---

## Delivery

Save all three files to:
```
C:\Users\skaumb\OneDrive - continentalmachines.com\Desktop\Projects\AI-tool\400S_Sorted_Library\
```

File names:
```
1030017_inspection_profile.json
1030017_dimension_descriptions.json
1030017_highlight_boxes.json
```

## Quality Checklist

- [ ] `_inspection_profile.json` has rich `part_description` (not copied from raw JSON)
- [ ] `_inspection_profile.json` has `spatial_description` for every feature
- [ ] `_inspection_profile.json` has `view_expectations` for all views on the drawing
- [ ] `_dimension_descriptions.json` covers every annotation in the drawing map
- [ ] `_highlight_boxes.json` has a bounding box for every visible dimension on the drawing
- [ ] All descriptions are engineering-quality — specific, accurate, useful for inspection
