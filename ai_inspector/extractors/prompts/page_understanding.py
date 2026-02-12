"""Page understanding prompt for Qwen VLM holistic drawing analysis."""

PAGE_UNDERSTANDING_PROMPT = '''Analyze this engineering drawing page and extract the following information. Return ONLY a JSON object.

{
  "units": "inch" or "metric",
  "titleBlock": {
    "partNumber": "part number if visible",
    "partName": "part name/description if visible",
    "revision": "revision letter/number if visible",
    "material": "material specification if visible",
    "scale": "drawing scale if visible (e.g. 1:1, 2:1)",
    "drawnBy": "name if visible",
    "date": "date if visible"
  },
  "generalNotes": ["list each general note verbatim"],
  "surfaceFinish": {
    "roughness": null,
    "unit": "Ra_microinch or Ra_micrometer",
    "note": "full surface finish note if present"
  },
  "views": ["list of views shown: FRONT, TOP, RIGHT, LEFT, BOTTOM, BACK, ISOMETRIC, SECTION, DETAIL"],
  "datumReferences": ["A", "B", "C"],
  "toleranceBlock": {
    "linear_2place": "e.g. ±0.01",
    "linear_3place": "e.g. ±0.005",
    "angular": "e.g. ±0.5°"
  },
  "drawingType": "one of: MACHINED_PART, SHEET_METAL, WELDMENT, ASSEMBLY, CASTING, GEAR"
}

IMPORTANT RULES:
1. For "units": Look at the title block for "INCHES", "MILLIMETERS", "MM", or "IN". Also check dimension values - if most are small decimals like 0.500, 1.250 it is likely "inch". If values are larger like 12.7, 32.0 it is likely "metric".
2. For "generalNotes": Copy each note exactly as written. Common notes include: REMOVE ALL BURRS, BREAK SHARP EDGES, UNLESS OTHERWISE SPECIFIED, INTERPRET PER ASME Y14.5.
3. For "datumReferences": List all datum letters (A, B, C, etc.) referenced in feature control frames.
4. For "toleranceBlock": Extract the default tolerance block values (usually in or near the title block).
5. For "drawingType": Classify based on overall part geometry, notes, and features visible.
6. Return null for any field you cannot determine from the drawing.

Only return valid JSON, no other text.'''
