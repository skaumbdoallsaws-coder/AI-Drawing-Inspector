"""YOLO-OBB class definitions for engineering drawing callout detection."""

# Class names in order matching YOLO model training
# This is the SINGLE SOURCE OF TRUTH for class names
YOLO_CLASSES = [
    "Hole",
    "TappedHole",
    "CounterboreHole",
    "CountersinkHole",
    "Fillet",
    "Chamfer",
    "Thread",
    "Slot",
    "Bend",
    "GDT",           # Geometric Dimensioning & Tolerancing
    "SurfaceFinish",
    "Dimension",
    "Tolerance",
    "Note",
]

# Mapping from class index to name
IDX_TO_CLASS = {i: name for i, name in enumerate(YOLO_CLASSES)}
CLASS_TO_IDX = {name: i for i, name in enumerate(YOLO_CLASSES)}

# Number of classes (full 14-class list)
NUM_CLASSES = len(YOLO_CLASSES)

# --- Finetuned 4-class model ---
# The finetuned YOLO11s-OBB model was trained on only these 4 classes.
# When using model.names from ultralytics, the runtime mapping is
# authoritative. This constant is provided as a reference / fallback.
FINETUNED_CLASSES = ["Hole", "TappedHole", "Fillet", "Chamfer"]
FINETUNED_IDX_TO_CLASS = {i: name for i, name in enumerate(FINETUNED_CLASSES)}
FINETUNED_NUM_CLASSES = len(FINETUNED_CLASSES)

# Classes that map to specific callout types for the parser
CLASS_TO_CALLOUT_TYPE = {
    "Hole": "Hole",
    "TappedHole": "TappedHole",
    "CounterboreHole": "CounterboreHole",
    "CountersinkHole": "CountersinkHole",
    "Fillet": "Fillet",
    "Chamfer": "Chamfer",
    "Thread": "Thread",
    "Slot": "Slot",
    "Bend": "Bend",
    "GDT": "GDT",
    "SurfaceFinish": "SurfaceFinish",
    "Dimension": "Dimension",
    "Tolerance": "Tolerance",
    "Note": "Note",
}

# Classes that the matcher should SKIP (not penalize).
# Includes types not yet implemented in matcher._match_by_type().
FUTURE_TYPES = {
    "Slot", "Bend", "Note",                      # Not matchable
    "CounterboreHole", "CountersinkHole",         # Matching not yet implemented
    "Thread",                                      # Matched via TappedHole only
    "GDT", "SurfaceFinish", "Dimension", "Tolerance",  # Info-only types
}
