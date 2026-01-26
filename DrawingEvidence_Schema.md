# DrawingEvidence Schema Design

**Version:** 1.1.0
**Updated:** 2026-01-26

## Schema Files

| File | Purpose |
|------|---------|
| `schemas/drawing_evidence_v1.1.schema.json` | JSON Schema for validation |
| `schemas/canonicalization_rules.json` | Formal normalization rules |
| `schemas/sw_to_evidence_mapping.json` | SolidWorks-to-evidence mapping |
| `schemas/canonicalizer.py` | Python reference implementation |

---

## Part 1: JSON Library Analysis Summary

### Feature Groups Histogram (379 parts analyzed)

| Feature Group | Files | % | Coverage Tier |
|--------------|-------|---|---------------|
| geometry.planarFaces | 373 | 98.4% | Core |
| geometry.cylinders | 353 | 93.1% | Core |
| verificationChecklist | 331 | 87.3% | Core |
| comparison.holeGroups | 329 | 86.8% | Core |
| comparison.allHoles | 329 | 86.8% | Core |
| extrudes | 255 | 67.3% | Core |
| otherFeatures | 202 | 53.3% | Extended |
| fillets | 120 | 31.7% | Extended |
| cuts | 115 | 30.3% | Extended |
| revolves | 90 | 23.7% | Extended |
| sheetMetal | 86 | 22.7% | V2 |
| holeWizardHoles | 83 | 21.9% | Core (critical) |
| chamfers | 76 | 20.1% | Extended |
| patterns | 66 | 17.4% | V2 |
| threadedHoles | 37 | 9.8% | Core (critical) |

### Hole Types Distribution

**From comparison.holeGroups:**
| Type | Count | Priority |
|------|-------|----------|
| Blind | 1,108 | V1 |
| Through | 721 | V1 |
| Tapped | 100 | V1 |

**From geometry.cylinders:**
| Type | Count | Priority |
|------|-------|----------|
| HoleWall | 5,140 | Internal |
| ExternalCylinder | 4,790 | V2 |
| ThroughHole | 1,222 | V1 |
| BlindHole | 636 | V1 |
| CountersunkHole | 252 | V1 |

### Verification Checklist Item Types
| Type | Count | Priority |
|------|-------|----------|
| Hole/Diameter | 1,817 | V1 |
| Fillet | 364 | V1 |
| Other | 112 | V2 |

### Identity Field Presence
| Field | Present | % | Status |
|-------|---------|---|--------|
| description | 377 | 99.5% | ALWAYS |
| revision | 377 | 99.5% | ALWAYS |
| partNumber | 375 | 98.9% | ALWAYS |
| material | 245 | 64.6% | SOMETIMES |
| finish | 129 | 34.0% | SOMETIMES |

---

## Part 2: DrawingEvidence Schema

### Design Principles
1. **One stable schema** - no per-part variants
2. **Optional fields** - handle missing data gracefully
3. **Structured + raw** - both normalized values and original OCR text
4. **Evidence linking** - tie each finding to its source location

### V1 Schema (Covers ~87% of parts - holes, fillets, chamfers)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "DrawingEvidence",
  "description": "Evidence extracted from engineering drawing by vision pipeline",
  "type": "object",
  "required": ["schemaVersion", "partNumber", "extractionTime", "sourceFile"],
  "properties": {
    "schemaVersion": {
      "type": "string",
      "const": "1.0.0"
    },
    "partNumber": {
      "type": "string",
      "description": "Part number from drawing title block"
    },
    "revision": {
      "type": ["string", "null"],
      "description": "Revision from title block"
    },
    "extractionTime": {
      "type": "string",
      "format": "date-time"
    },
    "sourceFile": {
      "type": "string",
      "description": "Path to source PDF/image"
    },
    "confidence": {
      "type": "number",
      "minimum": 0,
      "maximum": 1,
      "description": "Overall extraction confidence"
    },

    "foundHoleCallouts": {
      "type": "array",
      "description": "All hole-related callouts found on drawing",
      "items": { "$ref": "#/$defs/HoleCallout" }
    },

    "foundDimensions": {
      "type": "array",
      "description": "Linear dimensions, radii, angles",
      "items": { "$ref": "#/$defs/Dimension" }
    },

    "foundFilletCallouts": {
      "type": "array",
      "description": "Fillet radius callouts",
      "items": { "$ref": "#/$defs/FilletCallout" }
    },

    "foundChamferCallouts": {
      "type": "array",
      "description": "Chamfer callouts",
      "items": { "$ref": "#/$defs/ChamferCallout" }
    },

    "foundNotes": {
      "type": "array",
      "description": "General notes and annotations",
      "items": { "$ref": "#/$defs/Note" }
    },

    "titleBlock": {
      "$ref": "#/$defs/TitleBlock"
    }
  },

  "$defs": {
    "BoundingBox": {
      "type": "object",
      "description": "Location on drawing page (normalized 0-1)",
      "properties": {
        "page": { "type": "integer", "minimum": 1 },
        "x": { "type": "number", "minimum": 0, "maximum": 1 },
        "y": { "type": "number", "minimum": 0, "maximum": 1 },
        "width": { "type": "number", "minimum": 0, "maximum": 1 },
        "height": { "type": "number", "minimum": 0, "maximum": 1 }
      },
      "required": ["page", "x", "y"]
    },

    "HoleCallout": {
      "type": "object",
      "required": ["rawText", "diameterMm"],
      "properties": {
        "rawText": {
          "type": "string",
          "description": "Original OCR text exactly as read",
          "examples": ["Ø.500 THRU", "Ø12.7 x 25.4 DEEP", "M6x1.0 THRU", "4X Ø.250 x .500 DP"]
        },
        "canonical": {
          "type": "string",
          "description": "Normalized callout for matching",
          "examples": ["ø12.70mm THRU", "ø12.70mm x 25.4mm DEEP"]
        },
        "holeType": {
          "type": "string",
          "enum": ["Through", "Blind", "Tapped", "Counterbore", "Countersink", "Unknown"],
          "description": "Classified hole type"
        },
        "diameterMm": {
          "type": "number",
          "description": "Primary diameter in mm"
        },
        "diameterInches": {
          "type": ["number", "null"],
          "description": "Primary diameter in inches (if originally in inches)"
        },
        "diameterRaw": {
          "type": "string",
          "description": "Diameter as written (e.g., '1/2', '.500', '12.7')"
        },
        "depthMm": {
          "type": ["number", "null"],
          "description": "Depth in mm (null for THRU)"
        },
        "depthRaw": {
          "type": ["string", "null"],
          "description": "Depth as written"
        },
        "isThrough": {
          "type": "boolean",
          "description": "True if THRU hole"
        },
        "quantity": {
          "type": "integer",
          "minimum": 1,
          "default": 1,
          "description": "Quantity (from 2X, 4X prefix)"
        },
        "thread": {
          "$ref": "#/$defs/ThreadSpec",
          "description": "Thread specification if tapped"
        },
        "counterbore": {
          "$ref": "#/$defs/CounterboreSpec",
          "description": "Counterbore specification if present"
        },
        "countersink": {
          "$ref": "#/$defs/CountersinkSpec",
          "description": "Countersink specification if present"
        },
        "location": {
          "$ref": "#/$defs/BoundingBox"
        },
        "confidence": {
          "type": "number",
          "minimum": 0,
          "maximum": 1
        }
      }
    },

    "ThreadSpec": {
      "type": "object",
      "properties": {
        "rawText": {
          "type": "string",
          "description": "Thread callout as written",
          "examples": ["M6x1.0", "1/4-20 UNC", "M8x1.25-6H"]
        },
        "standard": {
          "type": "string",
          "enum": ["Metric", "UNC", "UNF", "NPT", "BSP", "ACME", "Unknown"]
        },
        "nominalDiameterMm": {
          "type": "number",
          "description": "Thread major diameter in mm"
        },
        "pitch": {
          "type": ["number", "null"],
          "description": "Thread pitch (mm for metric, null for TPI-based)"
        },
        "tpi": {
          "type": ["integer", "null"],
          "description": "Threads per inch (for inch threads)"
        },
        "class": {
          "type": ["string", "null"],
          "description": "Thread class (e.g., '6H', '2B')"
        },
        "depthMm": {
          "type": ["number", "null"],
          "description": "Thread depth (may differ from hole depth)"
        }
      }
    },

    "CounterboreSpec": {
      "type": "object",
      "properties": {
        "diameterMm": { "type": "number" },
        "depthMm": { "type": "number" }
      }
    },

    "CountersinkSpec": {
      "type": "object",
      "properties": {
        "diameterMm": { "type": "number" },
        "angle": { "type": "number", "description": "Angle in degrees (typically 82 or 90)" }
      }
    },

    "Dimension": {
      "type": "object",
      "required": ["rawText", "valueMm"],
      "properties": {
        "rawText": {
          "type": "string",
          "description": "Dimension as written",
          "examples": ["25.40", "1.000", "45°"]
        },
        "dimensionType": {
          "type": "string",
          "enum": ["Linear", "Radius", "Diameter", "Angle", "Unknown"]
        },
        "valueMm": {
          "type": ["number", "null"],
          "description": "Value in mm (null for angles)"
        },
        "valueInches": {
          "type": ["number", "null"]
        },
        "valueDegrees": {
          "type": ["number", "null"],
          "description": "Value in degrees (for angles)"
        },
        "tolerance": {
          "$ref": "#/$defs/Tolerance"
        },
        "location": {
          "$ref": "#/$defs/BoundingBox"
        },
        "confidence": {
          "type": "number",
          "minimum": 0,
          "maximum": 1
        }
      }
    },

    "Tolerance": {
      "type": "object",
      "properties": {
        "type": {
          "type": "string",
          "enum": ["Bilateral", "Unilateral", "Limit", "Basic", "Reference"]
        },
        "upperMm": { "type": ["number", "null"] },
        "lowerMm": { "type": ["number", "null"] },
        "rawText": { "type": "string" }
      }
    },

    "FilletCallout": {
      "type": "object",
      "required": ["rawText", "radiusMm"],
      "properties": {
        "rawText": {
          "type": "string",
          "examples": ["R.030", "R0.76", "FILLET R3"]
        },
        "canonical": {
          "type": "string",
          "examples": ["Fillet: R0.76mm"]
        },
        "radiusMm": {
          "type": "number"
        },
        "radiusInches": {
          "type": ["number", "null"]
        },
        "quantity": {
          "type": "integer",
          "minimum": 1,
          "default": 1
        },
        "location": {
          "$ref": "#/$defs/BoundingBox"
        },
        "confidence": {
          "type": "number",
          "minimum": 0,
          "maximum": 1
        }
      }
    },

    "ChamferCallout": {
      "type": "object",
      "required": ["rawText"],
      "properties": {
        "rawText": {
          "type": "string",
          "examples": ["45° x .030", "1 x 45°", "C0.5"]
        },
        "canonical": {
          "type": "string",
          "examples": ["Chamfer: 0.76mm x 45°"]
        },
        "chamferType": {
          "type": "string",
          "enum": ["AngleDistance", "DistanceDistance", "Unknown"]
        },
        "distance1Mm": {
          "type": ["number", "null"]
        },
        "distance2Mm": {
          "type": ["number", "null"]
        },
        "angleDegrees": {
          "type": ["number", "null"]
        },
        "quantity": {
          "type": "integer",
          "minimum": 1,
          "default": 1
        },
        "location": {
          "$ref": "#/$defs/BoundingBox"
        },
        "confidence": {
          "type": "number",
          "minimum": 0,
          "maximum": 1
        }
      }
    },

    "Note": {
      "type": "object",
      "required": ["rawText"],
      "properties": {
        "rawText": {
          "type": "string"
        },
        "noteType": {
          "type": "string",
          "enum": ["General", "Material", "Finish", "Process", "Dimension", "Unknown"]
        },
        "location": {
          "$ref": "#/$defs/BoundingBox"
        },
        "confidence": {
          "type": "number",
          "minimum": 0,
          "maximum": 1
        }
      }
    },

    "TitleBlock": {
      "type": "object",
      "properties": {
        "partNumber": { "type": ["string", "null"] },
        "revision": { "type": ["string", "null"] },
        "description": { "type": ["string", "null"] },
        "material": { "type": ["string", "null"] },
        "finish": { "type": ["string", "null"] },
        "drawnBy": { "type": ["string", "null"] },
        "date": { "type": ["string", "null"] },
        "scale": { "type": ["string", "null"] },
        "sheet": { "type": ["string", "null"] }
      }
    }
  }
}
```

---

### V2 Schema Additions (Full coverage)

Add these to the V1 schema for complete coverage:

```json
{
  "foundGdtCallouts": {
    "type": "array",
    "description": "Geometric Dimensioning & Tolerancing feature control frames",
    "items": { "$ref": "#/$defs/GdtCallout" }
  },

  "foundDatumReferences": {
    "type": "array",
    "description": "Datum feature symbols",
    "items": { "$ref": "#/$defs/DatumReference" }
  },

  "foundSlotCallouts": {
    "type": "array",
    "description": "Slot dimensions",
    "items": { "$ref": "#/$defs/SlotCallout" }
  },

  "foundSurfaceFinishSymbols": {
    "type": "array",
    "description": "Surface finish/roughness symbols",
    "items": { "$ref": "#/$defs/SurfaceFinish" }
  },

  "foundWeldSymbols": {
    "type": "array",
    "description": "Welding symbols",
    "items": { "$ref": "#/$defs/WeldSymbol" }
  },

  "foundSheetMetalCallouts": {
    "type": "array",
    "description": "Sheet metal specific callouts (bend radius, K-factor)",
    "items": { "$ref": "#/$defs/SheetMetalCallout" }
  },

  "$defs": {
    "GdtCallout": {
      "type": "object",
      "required": ["rawText", "characteristic"],
      "properties": {
        "rawText": {
          "type": "string",
          "examples": ["|⌖|ø0.05|A|B|C|"]
        },
        "characteristic": {
          "type": "string",
          "enum": [
            "Position", "Concentricity", "Symmetry",
            "Parallelism", "Perpendicularity", "Angularity",
            "Flatness", "Straightness", "Circularity", "Cylindricity",
            "ProfileLine", "ProfileSurface",
            "CircularRunout", "TotalRunout",
            "Unknown"
          ]
        },
        "toleranceValueMm": {
          "type": "number"
        },
        "materialCondition": {
          "type": ["string", "null"],
          "enum": ["MMC", "LMC", "RFS", null]
        },
        "datumReferences": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "datum": { "type": "string" },
              "materialCondition": { "type": ["string", "null"] }
            }
          }
        },
        "location": { "$ref": "#/$defs/BoundingBox" },
        "confidence": { "type": "number" }
      }
    },

    "DatumReference": {
      "type": "object",
      "properties": {
        "symbol": {
          "type": "string",
          "description": "Datum letter (A, B, C, etc.)"
        },
        "location": { "$ref": "#/$defs/BoundingBox" }
      }
    },

    "SlotCallout": {
      "type": "object",
      "required": ["rawText"],
      "properties": {
        "rawText": { "type": "string" },
        "canonical": { "type": "string" },
        "widthMm": { "type": ["number", "null"] },
        "lengthMm": { "type": ["number", "null"] },
        "depthMm": { "type": ["number", "null"] },
        "isThrough": { "type": "boolean" },
        "endType": {
          "type": "string",
          "enum": ["Round", "Square", "Mixed", "Unknown"]
        },
        "quantity": { "type": "integer", "default": 1 },
        "location": { "$ref": "#/$defs/BoundingBox" },
        "confidence": { "type": "number" }
      }
    },

    "SurfaceFinish": {
      "type": "object",
      "properties": {
        "rawText": { "type": "string" },
        "roughnessRa": { "type": ["number", "null"] },
        "roughnessUnit": {
          "type": "string",
          "enum": ["microinch", "micrometer"]
        },
        "machiningRequired": { "type": "boolean" },
        "location": { "$ref": "#/$defs/BoundingBox" }
      }
    },

    "WeldSymbol": {
      "type": "object",
      "properties": {
        "rawText": { "type": "string" },
        "weldType": {
          "type": "string",
          "enum": ["Fillet", "Groove", "Plug", "Spot", "Seam", "Unknown"]
        },
        "size": { "type": ["string", "null"] },
        "length": { "type": ["string", "null"] },
        "pitch": { "type": ["string", "null"] },
        "allAround": { "type": "boolean" },
        "fieldWeld": { "type": "boolean" },
        "location": { "$ref": "#/$defs/BoundingBox" }
      }
    },

    "SheetMetalCallout": {
      "type": "object",
      "properties": {
        "rawText": { "type": "string" },
        "calloutType": {
          "type": "string",
          "enum": ["BendRadius", "BendAngle", "KFactor", "Thickness", "FlatPattern", "Unknown"]
        },
        "valueMm": { "type": ["number", "null"] },
        "valueDegrees": { "type": ["number", "null"] },
        "location": { "$ref": "#/$defs/BoundingBox" }
      }
    }
  }
}
```

---

## Part 3: SolidWorks-to-DrawingEvidence Mapping Table

This table maps each SolidWorks `RequiredCallout` type to the drawing evidence needed to verify it.

### V1 Mappings (87% coverage)

| SolidWorks Source | RequiredCallout Example | DrawingEvidence Field | Match Criteria |
|-------------------|------------------------|----------------------|----------------|
| `comparison.holeGroups[].canonical` | `ø12.70mm THRU` | `foundHoleCallouts[]` | `canonical` exact match OR `diameterMm` ± 0.1mm AND `isThrough` |
| `comparison.holeGroups[].canonical` | `ø12.70mm x 25.4mm DEEP` | `foundHoleCallouts[]` | `diameterMm` ± 0.1mm AND `depthMm` ± 0.5mm |
| `comparison.holeGroups[].canonical` | `ø12.70mm x 25.4mm DEEP (2X)` | `foundHoleCallouts[]` | Above + `quantity` == 2 |
| `comparison.holeGroups[].holeType="Tapped"` | `M6x1.0 x 12mm DEEP` | `foundHoleCallouts[].thread` | `thread.nominalDiameterMm` ± 0.1mm AND `thread.pitch` match |
| `features.fillets[].radius` | `Fillet: R0.76mm` | `foundFilletCallouts[]` | `radiusMm` ± 0.05mm |
| `features.chamfers[]` | `Chamfer: 0.76mm x 45°` | `foundChamferCallouts[]` | `distance1Mm` ± 0.1mm AND `angleDegrees` ± 1° |
| `identity.material` | Material note | `foundNotes[]` OR `titleBlock.material` | Text contains material name |
| `identity.finish` | Finish note | `foundNotes[]` OR `titleBlock.finish` | Text contains finish spec |

### V2 Mappings (Full coverage)

| SolidWorks Source | RequiredCallout Example | DrawingEvidence Field | Match Criteria |
|-------------------|------------------------|----------------------|----------------|
| `comparison.slots[]` | `Slot 10x25mm THRU` | `foundSlotCallouts[]` | `widthMm` AND `lengthMm` ± 0.2mm |
| `features.sheetMetal[]` | `Bend R3.0` | `foundSheetMetalCallouts[]` | `calloutType="BendRadius"` AND `valueMm` |
| (implied by tight tolerance) | `⌖ ø0.05 A B C` | `foundGdtCallouts[]` | `characteristic="Position"` AND `toleranceValueMm` |
| (datum features) | `-A-` | `foundDatumReferences[]` | `symbol` match |
| `features.patterns[]` | Pattern dimensions | `foundDimensions[]` | Pattern spacing dimensions |

---

## Part 4: Matching Algorithm Pseudocode

```python
def match_hole_callout(sw_group: dict, drawing_evidence: dict) -> MatchResult:
    """
    Match a SolidWorks holeGroup to drawing evidence.

    Returns: MatchResult with status, matched_evidence, confidence
    """
    sw_dia_mm = sw_group["diameters"]["pilotOrTapDrillDiameterMm"]
    sw_depth_mm = sw_group.get("depth", {}).get("mm")
    sw_is_thru = sw_group["holeType"] == "Through"
    sw_qty = sw_group["count"]
    sw_is_tapped = sw_group["holeType"] == "Tapped"

    candidates = []

    for hole in drawing_evidence.get("foundHoleCallouts", []):
        # Diameter match (within 0.15mm or 0.5%)
        dia_diff = abs(hole["diameterMm"] - sw_dia_mm)
        dia_pct = dia_diff / sw_dia_mm if sw_dia_mm > 0 else 1
        if dia_diff > 0.15 and dia_pct > 0.005:
            continue

        # Through/Blind match
        if sw_is_thru != hole.get("isThrough", False):
            continue

        # Depth match (for blind holes)
        if not sw_is_thru and sw_depth_mm:
            evidence_depth = hole.get("depthMm")
            if evidence_depth:
                depth_diff = abs(evidence_depth - sw_depth_mm)
                if depth_diff > 0.5 and depth_diff / sw_depth_mm > 0.02:
                    continue

        # Thread match (for tapped holes)
        if sw_is_tapped:
            thread = hole.get("thread")
            if not thread:
                continue
            # Additional thread validation...

        # Quantity match
        evidence_qty = hole.get("quantity", 1)
        if evidence_qty != sw_qty:
            # Partial match - may have multiple callouts
            pass

        candidates.append(hole)

    if candidates:
        best = max(candidates, key=lambda h: h.get("confidence", 0.5))
        return MatchResult("FOUND", best, confidence=0.9)

    return MatchResult("MISSING", None, confidence=0.0)
```

---

## Part 5: Implementation Recommendations

### V1 Priority (Ship first - covers 87% of parts)

1. **HoleCallout extraction** - Most critical, covers 87% of verification items
   - Diameter symbol (ø) detection
   - THRU/DEEP keyword parsing
   - Quantity prefix (2X, 4X) parsing
   - Depth value extraction

2. **FilletCallout extraction** - Second priority, 31% of parts
   - R prefix detection
   - Radius value extraction

3. **ChamferCallout extraction** - Third priority, 20% of parts
   - Angle × distance format
   - C-prefix format (C0.5)

4. **Thread detection** - Critical for 10% of parts
   - Metric format (M6x1.0)
   - Inch format (1/4-20 UNC)

### V2 Additions (Full coverage)

5. **GD&T extraction** - Complex, requires symbol recognition
6. **Slot extraction** - Moderate complexity
7. **Sheet metal callouts** - Specialized
8. **Weld symbols** - Specialized

### Example V1 DrawingEvidence Output

```json
{
  "schemaVersion": "1.0.0",
  "partNumber": "1008794",
  "revision": "2",
  "extractionTime": "2026-01-26T12:00:00Z",
  "sourceFile": "1008794_Rev2.pdf",
  "confidence": 0.92,

  "foundHoleCallouts": [
    {
      "rawText": "Ø1.000 THRU (3X)",
      "canonical": "ø25.40mm THRU (3X)",
      "holeType": "Through",
      "diameterMm": 25.4,
      "diameterInches": 1.0,
      "diameterRaw": "1.000",
      "isThrough": true,
      "quantity": 3,
      "location": { "page": 1, "x": 0.45, "y": 0.32 },
      "confidence": 0.95
    },
    {
      "rawText": "Ø.750 x 1.000 DEEP (2X)",
      "canonical": "ø19.05mm x 25.4mm DEEP (2X)",
      "holeType": "Blind",
      "diameterMm": 19.05,
      "diameterInches": 0.75,
      "diameterRaw": ".750",
      "depthMm": 25.4,
      "depthRaw": "1.000",
      "isThrough": false,
      "quantity": 2,
      "location": { "page": 1, "x": 0.62, "y": 0.45 },
      "confidence": 0.93
    }
  ],

  "foundFilletCallouts": [
    {
      "rawText": "R.030",
      "canonical": "Fillet: R0.76mm",
      "radiusMm": 0.762,
      "radiusInches": 0.030,
      "quantity": 1,
      "location": { "page": 1, "x": 0.55, "y": 0.60 },
      "confidence": 0.88
    }
  ],

  "foundChamferCallouts": [],

  "foundDimensions": [
    {
      "rawText": "10.125",
      "dimensionType": "Linear",
      "valueMm": 257.175,
      "valueInches": 10.125,
      "location": { "page": 1, "x": 0.50, "y": 0.70 },
      "confidence": 0.97
    }
  ],

  "foundNotes": [
    {
      "rawText": "MATERIAL: AISI 1020 STEEL",
      "noteType": "Material",
      "location": { "page": 1, "x": 0.80, "y": 0.90 },
      "confidence": 0.99
    }
  ],

  "titleBlock": {
    "partNumber": "1008794",
    "revision": "2",
    "description": "SHAFT-PINION, 400",
    "material": "AISI 1020",
    "drawnBy": "travisp",
    "date": "11-09-2009"
  }
}
```

---

## Summary

| Schema Version | Coverage | Feature Types |
|----------------|----------|---------------|
| **V1** | ~87% | Holes (Through, Blind, Tapped, CB, CS), Fillets, Chamfers, Notes |
| **V2** | ~98% | V1 + GD&T, Datums, Slots, Surface Finish, Welds, Sheet Metal |

The V1 schema handles the vast majority of parts in your library. GD&T and specialized features can be added in V2 once the core matching pipeline is validated.

---

## V1.1 Schema Improvements

### 1. OCR-Tolerant Identity Fields with SW Fallback

All identity fields now use the `OcrField` wrapper that supports:
- `ocrValue`: What OCR read (nullable if unreadable)
- `swFallback`: Authoritative value from SolidWorks model
- `resolved`: Final merged value (OCR if confident, else fallback)
- `ocrConfidence`: Confidence score (0-1)
- `source`: Which source provided resolved value

```json
"identity": {
  "partNumber": {
    "ocrValue": "1OO8794",
    "swFallback": "1008794",
    "resolved": "1008794",
    "ocrConfidence": 0.72,
    "source": "sw_fallback"
  }
}
```

### 2. Page/View Anchors for Evidence Linking

`Location` now includes view context for multi-view drawings:

```json
"location": {
  "page": 1,
  "sheetName": "SHEET 1 OF 2",
  "viewId": "VIEW_A",
  "viewName": "SECTION A-A",
  "viewType": "Section",
  "bbox": { "x": 0.45, "y": 0.32, "width": 0.15, "height": 0.08 }
}
```

View types: `Front`, `Top`, `Right`, `Left`, `Bottom`, `Back`, `Isometric`, `Section`, `Detail`, `Auxiliary`, `Unknown`

### 3. Unified Typed Callout Array

Instead of separate arrays (`foundHoleCallouts[]`, `foundFilletCallouts[]`), V1.1 uses a single array with discriminated types:

```json
"foundCallouts": [
  {
    "calloutType": "Hole",
    "rawText": "...",
    "canonical": "...",
    "hole": { "diameterMm": 12.7, ... }
  },
  {
    "calloutType": "Fillet",
    "rawText": "R.030",
    "canonical": "Fillet: R0.76mm",
    "fillet": { "radiusMm": 0.76, ... }
  },
  {
    "calloutType": "GdtPosition",
    "rawText": "...",
    "canonical": "...",
    "gdt": { "characteristic": "Position", "toleranceMm": 0.05, ... }
  }
]
```

**Supported calloutTypes:**
- Holes: `Hole`, `TappedHole`, `Counterbore`, `Countersink`
- Edge features: `Fillet`, `Chamfer`
- Dimensions: `LinearDimension`, `RadiusDimension`, `DiameterDimension`, `AngleDimension`
- GD&T: `GdtPosition`, `GdtFlatness`, `GdtPerpendicularity`, `GdtParallelism`, `GdtConcentricity`, `GdtCircularity`, `GdtCylindricity`, `GdtProfileLine`, `GdtProfileSurface`, `GdtRunout`, `GdtTotalRunout`
- Other: `Slot`, `Datum`, `SurfaceFinish`, `Weld`, `BendRadius`, `BendAngle`, `Note`, `Unknown`

### 4. Formalized Canonicalization Rules

See `schemas/canonicalization_rules.json` for complete rules. Key points:

**Fraction Conversion:**
| Input | Decimal (in) | mm | Canonical |
|-------|--------------|-----|-----------|
| `1/2` | 0.5 | 12.7 | `o12.70mm` |
| `3/8` | 0.375 | 9.525 | `o9.53mm` |
| `.500` | 0.5 | 12.7 | `o12.70mm` |

**Quantity Normalization:**
| Input Format | Canonical |
|--------------|-----------|
| `2X o.500 THRU` | `o12.70mm THRU (2X)` |
| `o.500 (2X)` | `o12.70mm THRU (2X)` |
| `o.500 2 PLCS` | `o12.70mm THRU (2X)` |
| `o.500 2 PLACES` | `o12.70mm THRU (2X)` |

**THRU/DEEP Normalization:**
| Input | Canonical |
|-------|-----------|
| `THRU`, `THROUGH`, `THRU ALL` | `THRU` |
| `DEEP`, `DP`, `DEPTH` | `DEEP` |

**Thread Normalization:**
| Input | Canonical |
|-------|-----------|
| `M6X1` | `M6x1.0` |
| `M6 X 1.0` | `M6x1.0` |
| `1/4-20 UNC` | `1/4-20 UNC` |
| `.250-20 UNC` | `1/4-20 UNC` |

**Matching Tolerances:**
| Feature | Absolute | Percent |
|---------|----------|---------|
| Diameter | +/- 0.15mm | +/- 0.5% |
| Depth | +/- 0.5mm | +/- 2% |
| Fillet radius | +/- 0.05mm | +/- 5% |
| Thread pitch | Exact | - |
| Quantity | Exact | - |

### Python Reference Implementation

```python
from schemas.canonicalizer import parse_hole_callout, parse_fillet_callout, match_callouts

# Parse OCR text
result = parse_hole_callout("4X o.375 x 1.000 DEEP")
print(result.canonical)  # "o9.53mm x 25.4mm DEEP (4X)"
print(result.diameter_mm)  # 9.525
print(result.quantity)  # 4

# Match against SolidWorks data
matches, confidence = match_callouts(sw_canonical, drawing_canonical)
```

### Migration from V1 to V1.1

```python
# V1 format
evidence_v1 = {
    "foundHoleCallouts": [...],
    "foundFilletCallouts": [...],
    "foundChamferCallouts": [...]
}

# V1.1 format - all merged into foundCallouts with calloutType discriminator
evidence_v1_1 = {
    "foundCallouts": [
        # All hole callouts with calloutType: "Hole"
        # All fillet callouts with calloutType: "Fillet"
        # All chamfer callouts with calloutType: "Chamfer"
    ]
}
```
