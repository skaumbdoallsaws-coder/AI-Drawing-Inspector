"""Page classification prompt for Qwen VLM."""

PAGE_CLASSIFICATION_PROMPT = '''Analyze this engineering drawing page and classify it. Return ONLY a JSON object:

{
  "drawingType": "ASSEMBLY_BOM" or "PART_DETAIL" or "MIXED",
  "hasExplodedView": true or false,
  "hasBOM": true or false,
  "hasDimensionedViews": true or false,
  "hasDetailViews": true or false,
  "needsOCR": true or false,
  "confidence": 0.0 to 1.0,
  "reason": "brief explanation"
}

Classification rules:
- ASSEMBLY_BOM: Shows exploded view with balloon callouts and/or BOM table. Usually no detailed dimensions. needsOCR=false
- PART_DETAIL: Shows a single part with dimensions, tolerances, section views. needsOCR=true
- MIXED: Has both BOM/exploded AND dimensioned detail views on same page. needsOCR=true

Set needsOCR=false for pages that are primarily BOM tables or exploded assembly views.
Set needsOCR=true for pages with dimension callouts that need text extraction.

Only return valid JSON, no other text.'''
