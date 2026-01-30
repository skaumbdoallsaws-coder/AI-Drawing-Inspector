"""Page classification prompt - DEPRECATED in v4.

NOTE: v4 uses text-based classification via DrawingClassifier, not VLM.
This prompt is kept for reference but is NOT used in the v4 pipeline.

v4 Classification:
- Uses DrawingClassifier from classifier/drawing_classifier.py
- Classifies drawings into 7 types based on text patterns
- OCR decision is made at drawing level, not page level
"""

# DEPRECATED - v4 uses text-based classification
PAGE_CLASSIFICATION_PROMPT = '''DEPRECATED: This prompt is not used in v4.

v4 uses DrawingClassifier which classifies drawings by text patterns:
- MACHINED_PART: Default (holes, threads, GD&T) -> Use OCR
- SHEET_METAL: FLAT PATTERN, bend callouts -> Use OCR
- ASSEMBLY: BOM table (ITEM NO + QTY) -> Skip OCR
- WELDMENT: "WELDT" keyword -> Skip OCR
- CASTING: DUCTILE IRON, MFG ITEM # -> Use OCR
- PURCHASED_PART: NSK/SKF cross-reference -> Skip OCR
- GEAR: TEETH, PITCH, PRESSURE ANGLE -> Use OCR

See classifier/drawing_classifier.py for implementation.'''
