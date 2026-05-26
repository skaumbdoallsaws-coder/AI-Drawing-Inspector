"""Read/write helpers for per-revision Sketch Dimension Intent Maps.

Output document at parts/{pn}/{rev}/{pn}_sketch_dimension_intent_map.json:

    {
      "schemaVersion": "sketch-dimension-intent-map-0.1.0",
      "partNumber":    "1030034",
      "revision":      "revD",
      "summary":       {"dimensionCount": 1, "reviewedCount": 1},
      "dimensions": [
        {
          "cadFeatureId":       "ice_boss_extrude2",
          "solidWorksName":     "Boss-Extrude2",
          "regionId":           "strut_outer",
          "regionLabel":        "Outer wing strut",
          "sketchFeature":      "Sketch270",
          "dimensionShortName": "D1",
          "dimensionFullName":  "D1@Sketch270",
          "displayName":        "front strut diameter",
          "aliases":            ["front strut", "front strut dia"],
          "controlType":        "diameter",
          "physicalMeaning":    "Changing this adjusts the front strut diameter.",
          "units":              "mm",
          "reviewed":           true,
          "confidence":         "operator_confirmed"
        }
      ]
    }

The shape is deliberately flat because lookup happens from a resolved
edit target cadFeatureId + a user phrase. Unknown future top-level
fields are preserved by the server PUT endpoint before this writer is
called.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


SCHEMA_VERSION = "sketch-dimension-intent-map-0.1.0"
SKETCH_DIMENSION_INTENT_MAP_FILENAME = "{pn}_sketch_dimension_intent_map.json"


def sketch_dimension_intent_map_path(library_dir: Path, pn: str, revision: str) -> Path:
    """Canonical on-disk path.

    parts/{pn}/{rev}/{pn}_sketch_dimension_intent_map.json
    """
    return library_dir / "parts" / pn / revision / SKETCH_DIMENSION_INTENT_MAP_FILENAME.format(pn=pn)


def load_sketch_dimension_intent_map(
    library_dir: Path,
    pn: str,
    revision: str,
) -> Optional[Dict[str, Any]]:
    """Defensive read. Returns None on missing or malformed JSON."""
    p = sketch_dimension_intent_map_path(library_dir, pn, revision)
    if not p.exists():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return doc if isinstance(doc, dict) else None


def write_sketch_dimension_intent_map(
    library_dir: Path,
    pn: str,
    revision: str,
    doc: Dict[str, Any],
) -> Path:
    """Atomic write (.tmp + replace), matching the feature intent map."""
    out_path = sketch_dimension_intent_map_path(library_dir, pn, revision)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    tmp.replace(out_path)
    return out_path
