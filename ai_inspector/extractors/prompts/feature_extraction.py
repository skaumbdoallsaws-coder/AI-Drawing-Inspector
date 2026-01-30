"""Feature extraction prompt for Qwen VLM."""

FEATURE_EXTRACTION_PROMPT = '''Analyze this engineering drawing and identify all features. Return a JSON object with:

{
  "partDescription": "brief description of the part",
  "views": ["list of views shown: TOP, FRONT, SIDE, ISOMETRIC, SECTION, DETAIL"],
  "features": [
    {
      "type": "one of the types listed below",
      "description": "brief description",
      "callout": "the EXACT dimension/callout text visible on the drawing",
      "quantity": 1,
      "location": "where on the part"
    }
  ],
  "material": "material if shown in title block",
  "titleBlockInfo": {
    "partNumber": "if visible",
    "revision": "if visible",
    "scale": "if visible"
  },
  "notes": ["any general notes visible on drawing"]
}

FEATURE TYPE DEFINITIONS - read carefully to classify correctly:

- TappedHole: A hole with INTERNAL THREADS. You MUST see a thread callout like M6x1.0, M10x1.5, 1/2-13 UNC, 3/8-16, or thread symbol lines (angled hatching inside the hole). If there is NO thread callout, it is NOT a TappedHole.

- ThroughHole: A plain round hole that goes completely through the part. Shown with a diameter dimension (e.g., Ø0.500, Ø12.7mm) and the word THRU. No thread lines or thread callout.

- BlindHole: A plain round hole that does NOT go all the way through. Has a diameter AND a depth dimension (e.g., Ø0.500 x 0.750 DEEP). No thread lines.

- Counterbore: A stepped hole with a larger diameter recess. Look for CBORE symbol or two concentric circles with different diameters.

- Countersink: A conical chamfer at a hole opening. Look for CSK symbol or an angle callout (e.g., 82° or 90°) at a hole.

- Slot: An elongated hole (oval/oblong shape). Has width and length dimensions.

- Fillet: A rounded internal corner. Look for R followed by a dimension (e.g., R.125, R3mm). Usually at intersections of surfaces.

- Chamfer: A beveled edge, usually 45°. Look for dimension x 45° callout (e.g., .030 x 45°). Found at edges of holes or part edges.

- Thread: External thread on a shaft or boss. Look for thread callout on an external diameter.

=== DIMENSION SUFFIX RECOGNITION (CRITICAL) ===

ALWAYS check for these suffixes and tag appropriately:
- (F) = FLAT PATTERN dimension (sheet metal pre-bend size) - tag as flat_pattern
- STK. or STOCK = Raw material/stock size - NOT a machined feature, tag as stock_dim
- REF. or REF = REFERENCE ONLY - do NOT include in inspection requirements
- TYP. or TYP = TYPICAL - applies to all similar features
- MAX. or MIN. = Limit dimension - extract the limit value

=== HOLE vs LINEAR DIMENSION (CRITICAL) ===

A HOLE DIAMETER dimension MUST have:
- Diameter symbol: Ø or O (before the number)
- The word "DIA" or "DIAMETER"
- Points to a CIRCULAR feature with a leader line
- Examples: Ø0.500, O12.7mm, .375 DIA, 2X Ø.38, 4X Ø.43 THRU ALL

A LINEAR DIMENSION (NOT a hole):
- Has NO diameter symbol
- Dimension lines with arrows on BOTH ends pointing to surfaces/edges
- Examples: 1.50, 4.00, 2.75 (these are NOT holes!)

=== THREAD CALLOUT FORMATS ===

Recognize these thread formats:
- METRIC INTERNAL: M10X1.5-6H THRU ALL, M12X1.25-6H
- METRIC EXTERNAL: M6X1.0, M8X1.25
- UNIFIED INCH: 3/4-10 UNC-2A, .750-16UNF-2A, 1/4-20 UNC
- ACME (lead screws): 1.00-5 ACME-2G-LH, 1"-5 ACME-2G

=== SHEET METAL FEATURES ===

For sheet metal parts, extract bend information:
- Bend callouts: "UP 90° R .03" or "DOWN 90° R .03"
- Extract as: {"direction": "UP/DOWN", "angle": 90, "radius": 0.03}
- (F) suffix dimensions are flat pattern dimensions

=== GEAR DATA ===

For gear drawings, extract gear parameters into "gearData" object:
- NUMBER OF TEETH, DIAMETRAL PITCH, PRESSURE ANGLE, MODULE

=== GD&T FEATURE CONTROL FRAMES ===

Extract these geometric tolerances:
- Position: Ø0.01(M) A B (datum references A, B)
- Perpendicularity: ⊥ 0.005 A
- Parallelism: // 0.010 A
- Concentricity: ◎ 0.002 A
- Runout: ↗ .002 A

=== SURFACE FINISH ===

Recognize surface finish callouts:
- 63▽ or 63/ = Ra 63 microinches
- 125 Ra MAX = explicit Ra callout
- Extract as: {"roughness": 63, "unit": "Ra_microinch"}

=== COATING & HEAT TREATMENT ===

Extract these specifications:
- PAINT [COLOR]: "PAINT DOALL BLUE", "PAINT BLACK"
- POWDER COAT: "POWDER COAT ORANGE RAL 2009"
- BLACK OXIDE: "BLACK OXIDE PER MIL-C-13924"
- HARDNESS: "HRC 55-60", "RB 80-90"
- CASE DEPTH: ".020-.030 CASE DEPTH"
- MASKING: "MASK THREADS DURING PAINT", "MASK ALL HOLES"

=== IMPORTANT RULES ===

1. Only classify as TappedHole if you see thread callout (M__, __-__ UNC/UNF, ACME)
2. A hole with just diameter is ThroughHole (if THRU) or BlindHole (if has depth)
3. Report EXACT callout text as it appears - do not convert units
4. General notes like "REMOVE BURRS" are NOT features - put in "notes"
5. When unsure if hole or linear dim, check for Ø symbol
6. Dimensions with REF suffix are NOT inspection requirements
7. (F) dimensions are flat pattern only - separate from formed dims

Be thorough - identify ALL holes, threads, chamfers, fillets, and other machined features.
Only return valid JSON, no other text.'''
