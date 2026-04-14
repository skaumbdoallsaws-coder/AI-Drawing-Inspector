"""Helpers for loading, normalizing, and matching SolidWorks drawing maps."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


_SAFE_PART_RE = re.compile(r"[^A-Za-z0-9_-]+")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def sanitize_part_number(part_number: str) -> str:
    """Return a filesystem-safe part number token."""
    return _SAFE_PART_RE.sub("", (part_number or "").strip())


def find_drawing_map_path(part_number: str, library_dir: str | Path) -> Optional[Path]:
    """Locate ``{part}_drawing_map.json`` in the inspection library."""
    safe_part_number = sanitize_part_number(part_number)
    if not safe_part_number:
        return None

    library_path = Path(library_dir)
    filename = f"{safe_part_number}_drawing_map.json"

    direct = library_path / filename
    if direct.exists():
        return direct

    for candidate in (
        library_path / "drawings" / filename,
        library_path / "drawing_maps" / filename,
    ):
        if candidate.exists():
            return candidate
    return None


def load_drawing_map(part_number: str, library_dir: str | Path) -> Optional[Dict[str, Any]]:
    """Load and normalize a drawing map for a part number."""
    path = find_drawing_map_path(part_number, library_dir)
    if path is None:
        return None

    with open(path, "r", encoding="utf-8-sig") as handle:
        raw_data = json.load(handle)

    normalized = normalize_drawing_map(raw_data, part_number=part_number)
    normalized["sourcePath"] = str(path)
    return normalized


def find_drawing_map_revision_path(
    part_number: str,
    revision: str,
    library_dir: str | Path,
) -> Optional[Path]:
    """Locate a drawing map for a specific revision.

    Search order:
      1. ``parts/{pn}/rev{X}/{pn}_drawing_map.json``
      2. Root fallback via ``find_drawing_map_path()``

    The root fallback is required because no revisioned drawing maps exist
    under ``parts/`` yet — the root-level files serve as the baseline.
    """
    safe_pn = sanitize_part_number(part_number)
    safe_rev = re.sub(r"[^\w]", "", (revision or "").strip())
    if not safe_pn or not safe_rev:
        return None

    library_path = Path(library_dir)
    filename = f"{safe_pn}_drawing_map.json"

    # Revision-specific path
    rev_path = library_path / "parts" / safe_pn / f"rev{safe_rev}" / filename
    if rev_path.exists():
        return rev_path

    # Root fallback
    return find_drawing_map_path(safe_pn, library_dir)


def load_drawing_map_revision(
    part_number: str,
    revision: str,
    library_dir: str | Path,
) -> Optional[Dict[str, Any]]:
    """Load and normalize a drawing map for a specific revision.

    Falls back to root drawing map if no revision-specific file exists.
    """
    path = find_drawing_map_revision_path(part_number, revision, library_dir)
    if path is None:
        return None

    with open(path, "r", encoding="utf-8-sig") as handle:
        raw_data = json.load(handle)

    normalized = normalize_drawing_map(raw_data, part_number=part_number)
    normalized["sourcePath"] = str(path)
    normalized["revision"] = revision
    return normalized


def list_drawing_map_revisions(
    part_number: str,
    library_dir: str | Path,
) -> List[str]:
    """List revisions that have drawing maps available.

    Checks ``parts/{pn}/rev*/`` for drawing map files. If none exist but a
    root drawing map is present, returns ``["A"]`` as baseline.
    """
    safe_pn = sanitize_part_number(part_number)
    if not safe_pn:
        return []

    library_path = Path(library_dir)
    parts_dir = library_path / "parts" / safe_pn
    filename = f"{safe_pn}_drawing_map.json"

    revisions = []
    if parts_dir.exists() and parts_dir.is_dir():
        for d in sorted(parts_dir.iterdir()):
            if d.is_dir() and d.name.lower().startswith("rev"):
                rev_label = d.name[3:]  # strip "rev" prefix
                if (d / filename).exists():
                    revisions.append(rev_label)

    # If no revision-specific maps but root exists, surface it as baseline
    if not revisions:
        root_path = find_drawing_map_path(safe_pn, library_dir)
        if root_path is not None:
            # Check if part has any revision directories at all
            if parts_dir.exists():
                rev_dirs = sorted([
                    d.name[3:] for d in parts_dir.iterdir()
                    if d.is_dir() and d.name.lower().startswith("rev")
                ])
                if rev_dirs:
                    # Part has revisions but drawing maps are only at root —
                    # surface root map as available for all revisions
                    revisions = rev_dirs

    return revisions


def normalize_drawing_map(raw_data: Dict[str, Any], part_number: Optional[str] = None) -> Dict[str, Any]:
    """Normalize drawing map variants into a consistent, flattened structure."""
    part_number_value = (
        part_number
        or raw_data.get("partNumber")
        or raw_data.get("part_number")
        or raw_data.get("partNo")
        or ""
    )

    global_sheet_width = _coerce_float(
        raw_data.get("sheetWidth"),
        raw_data.get("sheet_width"),
        raw_data.get("width"),
    )
    global_sheet_height = _coerce_float(
        raw_data.get("sheetHeight"),
        raw_data.get("sheet_height"),
        raw_data.get("height"),
    )

    normalized_sheets: List[Dict[str, Any]] = []
    flat_annotations: List[Dict[str, Any]] = []

    raw_sheets = raw_data.get("sheets")
    if isinstance(raw_sheets, list) and raw_sheets:
        for sheet_index, raw_sheet in enumerate(raw_sheets, start=1):
            sheet_name = (
                raw_sheet.get("sheetName")
                or raw_sheet.get("name")
                or raw_sheet.get("sheet")
                or f"Sheet{sheet_index}"
            )
            sheet_width = _coerce_float(
                raw_sheet.get("sheetWidth"),
                raw_sheet.get("sheet_width"),
                raw_sheet.get("width"),
                global_sheet_width,
            )
            sheet_height = _coerce_float(
                raw_sheet.get("sheetHeight"),
                raw_sheet.get("sheet_height"),
                raw_sheet.get("height"),
                global_sheet_height,
            )

            normalized_views: List[Dict[str, Any]] = []
            raw_views = raw_sheet.get("views") or []
            for view_index, raw_view in enumerate(raw_views, start=1):
                view_name = (
                    raw_view.get("viewName")
                    or raw_view.get("name")
                    or raw_view.get("view")
                    or f"View{view_index}"
                )
                view_outline = _coerce_rect(raw_view.get("viewOutline") or raw_view.get("outline"))

                normalized_annotations: List[Dict[str, Any]] = []
                for annotation_index, raw_annotation in enumerate(raw_view.get("annotations") or [], start=1):
                    normalized_annotation = _normalize_annotation(
                        raw_annotation,
                        annotation_index=annotation_index,
                        sheet_index=sheet_index,
                        sheet_name=sheet_name,
                        sheet_width=sheet_width,
                        sheet_height=sheet_height,
                        view_name=view_name,
                        view_outline=view_outline,
                    )
                    normalized_annotations.append(normalized_annotation)
                    flat_annotations.append(normalized_annotation)

                normalized_primitives: List[Dict[str, Any]] = []
                for primitive_index, raw_primitive in enumerate(raw_view.get("primitives") or [], start=1):
                    normalized_primitive = _normalize_primitive(
                        raw_primitive,
                        primitive_index=primitive_index,
                    )
                    if normalized_primitive is not None:
                        normalized_primitives.append(normalized_primitive)

                normalized_view = {
                    "viewName": view_name,
                    "viewOutline": view_outline,
                    "annotations": normalized_annotations,
                }
                if normalized_primitives:
                    normalized_view["primitives"] = normalized_primitives
                # Pass through optional view metadata from the extractor
                for _vk in ("viewType", "viewOrientation", "viewScale", "viewPosition", "referencedConfiguration"):
                    if raw_view.get(_vk) is not None:
                        normalized_view[_vk] = raw_view[_vk]
                normalized_views.append(normalized_view)

            normalized_sheet = {
                "sheetIndex": sheet_index,
                "sheetName": sheet_name,
                "sheetWidth": sheet_width,
                "sheetHeight": sheet_height,
                "views": normalized_views,
            }
            # Pass through sheet-level metadata for revision diff
            for _sk in ("paperSize", "scale"):
                if raw_sheet.get(_sk) is not None:
                    normalized_sheet[_sk] = raw_sheet[_sk]
            if raw_sheet.get("sheetFormat") is not None:
                normalized_sheet["sheetFormat"] = raw_sheet["sheetFormat"]
            normalized_sheets.append(normalized_sheet)
    else:
        raw_annotations = raw_data.get("annotations") or []
        sheet_name = raw_data.get("sheetName") or "Sheet1"
        sheet_width = global_sheet_width
        sheet_height = global_sheet_height
        normalized_annotations = []

        for annotation_index, raw_annotation in enumerate(raw_annotations, start=1):
            normalized_annotation = _normalize_annotation(
                raw_annotation,
                annotation_index=annotation_index,
                sheet_index=int(raw_annotation.get("sheetIndex") or 1),
                sheet_name=raw_annotation.get("sheetName") or sheet_name,
                sheet_width=_coerce_float(raw_annotation.get("sheetWidth"), sheet_width),
                sheet_height=_coerce_float(raw_annotation.get("sheetHeight"), sheet_height),
                view_name=raw_annotation.get("viewName"),
                view_outline=_coerce_rect(raw_annotation.get("viewOutline") or raw_annotation.get("outline")),
            )
            normalized_annotations.append(normalized_annotation)
            flat_annotations.append(normalized_annotation)

        normalized_sheets.append(
            {
                "sheetIndex": 1,
                "sheetName": sheet_name,
                "sheetWidth": sheet_width,
                "sheetHeight": sheet_height,
                "views": [
                    {
                        "viewName": raw_data.get("viewName"),
                        "viewOutline": _coerce_rect(raw_data.get("viewOutline") or raw_data.get("outline")),
                        "annotations": normalized_annotations,
                    }
                ],
            }
        )

    if global_sheet_width is None and normalized_sheets:
        global_sheet_width = normalized_sheets[0].get("sheetWidth")
    if global_sheet_height is None and normalized_sheets:
        global_sheet_height = normalized_sheets[0].get("sheetHeight")

    return {
        "partNumber": part_number_value,
        "sheetWidth": global_sheet_width,
        "sheetHeight": global_sheet_height,
        "sheetCount": len(normalized_sheets),
        "annotations": flat_annotations,
        "sheets": normalized_sheets,
    }


def apply_drawing_map_to_findings(
    findings: Iterable[Dict[str, Any]],
    drawing_map: Optional[Dict[str, Any]],
    profile: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Attach precise drawing coordinates to inspection findings when possible.

    If *profile* is provided, uses feature spatial_description to extract
    deterministic numeric and view hints for stronger matching.
    """
    # Build profile feature lookup for enriched matching
    profile_hints = _build_profile_hints(profile) if profile else {}

    normalized_findings: List[Dict[str, Any]] = []
    match_count = 0

    for finding in findings:
        feature = dict(finding)
        # Enrich finding with profile hints before matching
        if profile_hints:
            _enrich_finding_from_profile(feature, profile_hints)
        if drawing_map:
            matched_annotation, match_score = match_finding_to_annotation(feature, drawing_map)
        else:
            matched_annotation, match_score = None, 0.0

        if matched_annotation is not None:
            location = {
                "x": matched_annotation["positionSheet"]["x"],
                "y": matched_annotation["positionSheet"]["y"],
                "sheetIndex": matched_annotation.get("sheetIndex"),
                "sheetName": matched_annotation.get("sheetName"),
                "sheetWidth": matched_annotation.get("sheetWidth"),
                "sheetHeight": matched_annotation.get("sheetHeight"),
                "viewName": matched_annotation.get("viewName"),
                "viewOutline": matched_annotation.get("viewOutline"),
                "annotationName": matched_annotation.get("annotationName"),
                "annotationType": matched_annotation.get("annotationType"),
                "leaderPoints": matched_annotation.get("leaders", []),
                "boundsSheet": matched_annotation.get("boundsSheet"),
                "anchorKind": matched_annotation.get("anchorKind"),
                "geometrySource": matched_annotation.get("geometrySource"),
                "textRuns": matched_annotation.get("textRuns", []),
                "textExtent": matched_annotation.get("textExtent"),
                "matchScore": round(match_score, 3),
            }
            # Flag ambiguous matches for frontend styling
            if matched_annotation.get("_ambiguous"):
                location["ambiguous"] = True
                location["ambiguityGap"] = matched_annotation.get("_ambiguity_gap", 0)
            feature["location"] = location
            feature["positionSource"] = "drawing_map"
            feature["drawingMapMatch"] = {
                "annotationName": matched_annotation.get("annotationName"),
                "annotationType": matched_annotation.get("annotationType"),
                "viewName": matched_annotation.get("viewName"),
                "sheetName": matched_annotation.get("sheetName"),
                "matchScore": round(match_score, 3),
            }
            _apply_annotation_truth_overrides(
                feature,
                matched_annotation,
                profile_hints.get((feature.get("name") or "").strip().lower()),
            )
            match_count += 1
        else:
            existing_location = feature.get("location")
            feature["positionSource"] = "vlm_estimate"
            if not _has_numeric_xy(existing_location):
                feature["location"] = None
            feature.pop("drawingMapMatch", None)

        normalized_findings.append(feature)

    metadata = {
        "drawingMapFound": drawing_map is not None,
        "matchedFeatures": match_count,
        "totalFeatures": len(normalized_findings),
    }
    return normalized_findings, metadata


def _annotation_display_text(annotation: Dict[str, Any]) -> str:
    """Return the best available human-readable callout text for an annotation."""
    for key in ("dimensionText", "noteText", "gtolText", "displayText"):
        value = annotation.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    parts: List[str] = []
    for run in annotation.get("textRuns") or []:
        text = run.get("text") if isinstance(run, dict) else None
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return " ".join(parts).strip()


def _apply_annotation_truth_overrides(
    feature: Dict[str, Any],
    matched_annotation: Dict[str, Any],
    profile_hint: Optional[Dict[str, Any]],
) -> None:
    """Ground matched findings to extracted annotation text and deterministic gaps."""
    actual_text = _annotation_display_text(matched_annotation)
    if actual_text:
        model_callout = feature.get("found_callout")
        if model_callout and _normalize_text(model_callout) != _normalize_text(actual_text):
            feature["model_found_callout"] = model_callout
        feature["found_callout"] = actual_text
        feature["drawingCalloutText"] = actual_text

    if not actual_text or not profile_hint:
        return

    gaps: List[str] = []
    actual_norm = _normalize_text(actual_text)
    feature_type = profile_hint.get("feature_type")
    expected_count = _coerce_int(profile_hint.get("count"))
    through_expected = bool(profile_hint.get("through_expected"))

    # Restrict deterministic callout completeness checks to repeated hole patterns.
    # Single-hole / bore features are often represented by section dimensions or
    # other view evidence where "THRU" is not expected in the matched annotation text.
    if feature_type == "hole" and expected_count and expected_count > 1:
        qty_pattern = rf"\b{expected_count}\s*x\b|\b{expected_count}x\b"
        if not re.search(qty_pattern, actual_norm):
            gaps.append(f"missing quantity prefix ({expected_count}X)")
        if through_expected and not re.search(r"\bthru\b|\bthrough\b", actual_norm):
            gaps.append("missing through-hole notation (THRU)")

    if not gaps:
        return

    existing_gaps = feature.get("representation_gaps")
    if not isinstance(existing_gaps, list):
        existing_gaps = []
    existing_norm = {str(item).strip().lower() for item in existing_gaps if item}
    for gap in gaps:
        if gap.lower() not in existing_norm:
            existing_gaps.append(gap)
    feature["representation_gaps"] = existing_gaps

    current_status = str(feature.get("status") or "").upper()
    if current_status == "PRESENT":
        feature["status"] = "PARTIAL"

    current_score = feature.get("representation_score")
    if current_score is None or _coerce_float(current_score, 100.0) > 55:
        feature["representation_score"] = 55
    feature["asme_compliance"] = "MAJOR_GAPS"

    missing_text = ", ".join(gaps)
    feature["observation"] = (
        f"Matched drawing callout is '{actual_text}'. "
        f"The feature is present, but the callout is incomplete: {missing_text}."
    )


_NUM_RE = re.compile(r"[\d]+(?:\.[\d]+)?")

# Extract mm dimension values from text (e.g. "⌀76.2mm", "254mm", "50.8mm")
_MM_VALUE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:mm\b|millimeter)", re.IGNORECASE)
# Extract diameter values (e.g. "⌀152.4mm", "⌀76.2", "diameter 22.23")
_DIAM_VALUE_RE = re.compile(r"[⌀∅Øø]\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
# Extract angle values (e.g. "45°", "0.5°")
_ANGLE_VALUE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*°")
# Detect coordinate-context mm values (e.g. "±101.6mm") — these are spatial
# positions in prose, not drafting dimensions, and should be excluded.
_COORD_MM_RE = re.compile(r"±\s*(\d+(?:\.\d+)?)\s*(?:mm\b|millimeter)", re.IGNORECASE)
# Extract view name hints from spatial descriptions
_VIEW_HINT_RE = re.compile(
    r"(Section View [A-Z]-[A-Z]|Detail View [A-Z]|Drawing View\s*\d+)",
    re.IGNORECASE,
)


def _build_profile_hints(profile: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Extract deterministic match hints from the inspection profile.

    Returns a dict keyed by normalized feature name with:
      - dimension_values_mm: list of floats extracted from spatial_description
      - diameter_values_mm: list of floats specifically identified as diameters
      - view_hints: list of view names mentioned in spatial_description
      - feature_type: normalized type (chamfer, hole, bore, etc.)
    """
    if not profile:
        return {}
    hints = {}
    features = profile.get("features") or []
    if isinstance(features, dict):
        # Flatten dict-style features (extractor format)
        flat = []
        for ftype, flist in features.items():
            if isinstance(flist, list):
                for f in flist:
                    flat.append(f)
        features = flat

    for f in features:
        name = (f.get("name") or "").strip()
        if not name:
            continue
        spatial = f.get("spatial_description") or ""
        ftype = (f.get("type") or "").lower()

        # Extract only explicitly-marked dimension values from spatial description.
        # Plain numbers without unit markers (fractions, counts, coordinates, scale
        # ratios) are excluded — they cause false matches on unrelated annotations.
        mm_values = [float(m.group(1)) for m in _MM_VALUE_RE.finditer(spatial)]
        diam_values = [float(m.group(1)) for m in _DIAM_VALUE_RE.finditer(spatial)]
        angle_values = [float(m.group(1)) for m in _ANGLE_VALUE_RE.finditer(spatial)]

        # Exclude coordinate-context values (e.g. "±101.6mm" from prose positions)
        coord_values = {float(m.group(1)) for m in _COORD_MM_RE.finditer(spatial)}
        if coord_values:
            mm_values = [v for v in mm_values if v not in coord_values]

        # Extract view hints
        view_hints = [m.group(1) for m in _VIEW_HINT_RE.finditer(spatial)]
        count_value = _coerce_int(f.get("count"))
        through_expected = "through" in spatial.lower() or "thru" in spatial.lower()

        # Normalize feature type
        norm_type = None
        type_lower = ftype + " " + name.lower()
        for ft, kws in _FEATURE_TYPE_KEYWORDS.items():
            if any(kw in type_lower for kw in kws):
                norm_type = ft
                break

        # For chamfer features, diameter values reference the parent feature (e.g. bore),
        # not the chamfer itself. Remove them to avoid false matches.
        if norm_type == "chamfer" and diam_values:
            diam_set = set(diam_values)
            mm_values = [v for v in mm_values if v not in diam_set]
            diam_values = []

        hints[name.lower()] = {
            "dimension_values_mm": mm_values + angle_values,
            "diameter_values_mm": diam_values,
            "view_hints": view_hints,
            "feature_type": norm_type,
            "count": count_value,
            "through_expected": through_expected,
            "name": name,
        }
    return hints


def _enrich_finding_from_profile(
    finding: Dict[str, Any],
    profile_hints: Dict[str, Dict[str, Any]],
) -> None:
    """Add profile-derived hints to a finding for better annotation matching.

    Modifies finding in place — adds _profile_nums, _profile_diameters,
    _profile_views if found.
    """
    fname = (finding.get("name") or "").strip().lower()
    hint = profile_hints.get(fname)
    if not hint:
        # Try partial string match
        for key, h in profile_hints.items():
            if key in fname or fname in key:
                hint = h
                break
    if not hint:
        # Try normalized token overlap (handles ⌀ vs D, × vs x, etc.)
        fname_tokens = set(_normalize_text(fname).split())
        if fname_tokens:
            best_overlap = 0.0
            best_hint = None
            for key, h in profile_hints.items():
                key_tokens = set(_normalize_text(key).split())
                if not key_tokens:
                    continue
                shared = len(fname_tokens & key_tokens)
                overlap = shared / min(len(fname_tokens), len(key_tokens))
                if overlap > best_overlap and overlap >= 0.6:
                    best_overlap = overlap
                    best_hint = h
            hint = best_hint
    if not hint:
        return

    # Add profile hints as private fields for the matcher
    if hint["dimension_values_mm"]:
        finding["_profile_nums"] = hint["dimension_values_mm"]
    if hint["diameter_values_mm"]:
        finding["_profile_diameters"] = hint["diameter_values_mm"]
    if hint["view_hints"]:
        finding["_profile_views"] = hint["view_hints"]


# Ordinal-like patterns in feature names: "Groove 1", "Ring 2", single-digit integers
# that are sequence numbers, not dimensions
_ORDINAL_RE = re.compile(
    r"(?:^|\s)(\d)(?:\s|$)"           # single digit surrounded by spaces/boundaries
    r"|(?:groove|ring|bore|cut|slot|hole|feature|fillet|chamfer)\s*(\d+)"  # "Groove 1", "Ring 2"
    r"|(\d+)(?:st|nd|rd|th)\b",       # "1st", "2nd", "3rd"
    re.IGNORECASE,
)

_DIAMETER_HINTS = {"diameter", "dia", "od", "id", "bore", "radius", "rad", "diam"}
_DEPTH_HINTS = {"depth", "deep", "height", "tall", "long", "length"}
_DIAMETER_SYMBOLS = {"ø", "⌀", "∅", "Ø"}
_FEATURE_TYPE_KEYWORDS = {
    "chamfer": {"chamfer", "bevel", "break edge"},
    "fillet": {"fillet", "round", "blend"},
    "hole": {"hole", "bore", "thru"},
    "slot": {"slot", "groove", "channel"},
    "thread": {"thread", "tap"},
}
_SURFACE_FINISH_KEYWORDS = {"surface finish", "roughness", "surface roughness", "rz ", "rms"}


def _extract_numbers(text: str) -> List[float]:
    """Pull all numeric values from a string."""
    if not text:
        return []
    nums = []
    for m in _NUM_RE.finditer(text):
        try:
            nums.append(float(m.group()))
        except ValueError:
            pass
    return nums


def match_finding_to_annotation(
    finding: Dict[str, Any],
    drawing_map: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], float]:
    """Return the best-matching annotation for a finding.

    Uses a hybrid scoring strategy:
      1. Exact numeric match on dimensionValue (meters → mm)
      2. Parsed numeric match from dimensionText / found_callout
      3. Type hints (diameter/depth keywords)
      4. Penalties for isReference, isDangling, hidden
      5. Text similarity as fallback
    """
    annotations = drawing_map.get("annotations") or []
    if not annotations:
        return None, 0.0

    finding_name = (finding.get("name") or "").strip()
    finding_callout = (finding.get("found_callout") or "").strip()
    finding_page = _coerce_int(finding.get("found_on_page"))

    # Extract numbers from the finding's callout ONLY — name numbers are unreliable
    # (e.g. "Ring Groove 3" has ordinal "3", not a dimension)
    callout_nums = _extract_numbers(finding_callout)
    finding_nums = callout_nums  # only trust explicit callout numbers

    # Profile-derived hints (injected by _enrich_finding_from_profile)
    profile_nums = finding.get("_profile_nums") or []
    profile_diameters = finding.get("_profile_diameters") or []
    profile_views = finding.get("_profile_views") or []

    # If callout has no extractable numbers, fall back to profile dimension values
    if not finding_nums and profile_nums:
        finding_nums = profile_nums

    # Detect type hints in the finding name and callout
    name_lower = finding_name.lower()
    callout_lower = finding_callout.lower()
    combined_text = name_lower + " " + callout_lower
    finding_is_diameter = (
        bool(_DIAMETER_HINTS & set(name_lower.split()))
        or any(sym in finding_name for sym in _DIAMETER_SYMBOLS)
        or any(sym in finding_callout for sym in _DIAMETER_SYMBOLS)
    )
    finding_is_depth = bool(_DEPTH_HINTS & set(name_lower.split()))

    # Profile diameters confirm diameter type detection (after name/callout check)
    if not finding_is_diameter and profile_diameters:
        finding_is_diameter = True

    # Detect feature type (chamfer, fillet, etc.) from finding name
    finding_feature_type = None
    for ftype, keywords in _FEATURE_TYPE_KEYWORDS.items():
        if any(kw in combined_text for kw in keywords):
            finding_feature_type = ftype
            break

    best_annotation = None
    best_score = 0.0
    second_best_score = 0.0

    for annotation in annotations:
        if annotation.get("positionSheet") is None:
            continue

        score = _score_annotation_match(
            finding_name, finding_callout, finding_page,
            finding_nums, finding_is_diameter, finding_is_depth,
            finding_feature_type,
            annotation,
            profile_views=profile_views,
        )
        if score > best_score:
            second_best_score = best_score
            best_annotation = annotation
            best_score = score
        elif score > second_best_score:
            second_best_score = score

    if best_score < 0.70:
        return None, best_score

    # Flag ambiguous matches: if runner-up is within 0.05 of best, match is uncertain
    is_ambiguous = (second_best_score > 0.0 and (best_score - second_best_score) < 0.02)
    if is_ambiguous and best_annotation:
        best_annotation = dict(best_annotation)  # copy to avoid mutating original
        best_annotation["_ambiguous"] = True
        best_annotation["_ambiguity_gap"] = round(best_score - second_best_score, 4)

    return best_annotation, best_score


def _score_annotation_match(
    finding_name: str,
    finding_callout: str,
    finding_page: Optional[int],
    finding_nums: List[float],
    finding_is_diameter: bool,
    finding_is_depth: bool,
    finding_feature_type: Optional[str],
    annotation: Dict[str, Any],
    profile_views: Optional[List[str]] = None,
) -> float:
    score = 0.0

    # --- Phase 1: Numeric value matching (strongest signal) ---
    ann_dim_value = _coerce_float(annotation.get("dimensionValue"))
    ann_dim_text = annotation.get("dimensionText") or ""
    ann_note_text = annotation.get("noteText") or ""
    ann_text_nums = _extract_numbers(ann_dim_text)
    # Include note text numbers (handles balloons like "0.3 X 45°")
    if ann_note_text:
        for n in _extract_numbers(ann_note_text):
            if n not in ann_text_nums:
                ann_text_nums.append(n)

    # dimensionValue is in meters, findings are typically in mm
    ann_value_mm = round(ann_dim_value * 1000, 4) if ann_dim_value else None

    numeric_match = False
    value_match = False  # True when matched via dimensionValue (parametric ground truth)
    if finding_nums and ann_value_mm is not None:
        for fn in finding_nums:
            if abs(fn - ann_value_mm) < 0.05:  # within 0.05mm
                score = 0.88
                numeric_match = True
                value_match = True
                break

    if not numeric_match and finding_nums and ann_text_nums:
        for fn in finding_nums:
            for an in ann_text_nums:
                if abs(fn - an) < 0.05:
                    score = 0.78
                    numeric_match = True
                    break
            if numeric_match:
                break

    # --- Phase 2: Type hint bonus ---
    ann_dim_type = (annotation.get("dimensionType") or "").lower()
    ann_dim_text_lower = ann_dim_text.lower()
    ann_ann_type = (annotation.get("annotationType") or "").lower()
    is_diameter_ann = (
        "diam" in ann_dim_type
        or "radial" in ann_dim_type
        or "<mod-diam>" in ann_dim_text_lower
        or "mod diam" in ann_dim_text_lower
    )

    if numeric_match:
        if finding_is_diameter and is_diameter_ann:
            score += 0.12  # diameter matches diameter — strong bonus
        elif finding_is_diameter and not is_diameter_ann:
            score -= 0.08  # diameter finding vs linear annotation — penalty
        elif finding_is_depth and "diam" not in ann_dim_type:
            score += 0.05  # depth matches non-diameter

    # --- Phase 2b: Feature type correlation ---
    ann_feature_name = (annotation.get("featureName") or "").lower()
    ann_feature_type = None
    for ftype, keywords in _FEATURE_TYPE_KEYWORDS.items():
        if any(kw in ann_feature_name for kw in keywords):
            ann_feature_type = ftype
            break
    # Also check annotationType and dimensionType for chamfer dims
    if "chamfer" in ann_ann_type or "chamfer" in ann_dim_type:
        ann_feature_type = ann_feature_type or "chamfer"

    if finding_feature_type and numeric_match and ann_feature_type:
        if finding_feature_type == ann_feature_type:
            score += 0.10  # feature types match
        else:
            score -= 0.12  # cross-type penalty (chamfer matched to fillet, etc.)

    # Chamfer dimension type bonus — swChamferDimension is the actual chamfer callout
    if finding_feature_type == "chamfer" and "chamfer" in ann_dim_type:
        score += 0.12  # chamfer-specific dimension type bonus (strong)

    # --- Phase 2c: Text cross-check penalty ---
    # Only apply when match was text-based (not value-based, since value is parametric truth)
    if numeric_match and not value_match and ann_dim_text and finding_callout:
        callout_lower = finding_callout.lower()
        # Chamfer callout should have angle component; penalize if annotation lacks it
        if finding_feature_type == "chamfer" and ("x" in callout_lower or "\u00b0" in callout_lower):
            if "\u00b0" not in ann_dim_text and "x" not in ann_dim_text_lower:
                score -= 0.10  # annotation text lacks angle — wrong match
        # Radius callout "R x.xx" should match annotation starting with "R "
        if callout_lower.startswith("r ") and not ann_dim_text_lower.startswith("r "):
            score -= 0.05  # callout is radius but annotation text isn't

    # --- Phase 2d: Annotation type guard ---
    # surfaceFinish annotations must only match findings about surface finish/roughness
    # Prepend space so word-boundary keywords like "ra " also match at start
    finding_combined = " " + finding_name.lower() + " " + finding_callout.lower() + " "
    if "surfacefinish" in ann_ann_type.replace(" ", "").lower():
        is_sf = any(kw in finding_combined for kw in _SURFACE_FINISH_KEYWORDS)
        # Also check for "ra" as standalone word (Ra 1.6, Ra 2.0, etc.)
        is_sf = is_sf or " ra " in finding_combined
        if not is_sf:
            return 0.0  # hard reject: surfaceFinish annotation vs non-surface-finish finding

    # --- Phase 3: Text similarity fallback (for non-dimension annotations) ---
    if not numeric_match:
        annotation_candidates = _annotation_match_candidates(annotation)
        if annotation_candidates:
            name_score = 0.0
            callout_score = 0.0
            for candidate in annotation_candidates:
                name_score = max(name_score, _text_similarity(finding_name, candidate))
                callout_score = max(callout_score, _text_similarity(finding_callout, candidate))

            text_score = max(name_score, callout_score)
            if name_score > 0.9:
                text_score += 0.06
            if callout_score > 0.92:
                text_score += 0.08
            score = max(score, text_score)

    # --- Phase 4: Context bonuses ---
    if finding_page is not None and annotation.get("sheetIndex") == finding_page:
        score += 0.03

    # --- Phase 4b: Profile view matching ---
    if profile_views:
        ann_view = (annotation.get("viewName") or "").strip()
        if ann_view and any(_view_name_matches(pv, ann_view) for pv in profile_views):
            score += 0.08  # annotation is in a view the profile expects

    # --- Phase 5: Penalties ---
    if annotation.get("isDangling"):
        score -= 0.08
    if annotation.get("visible") is False:
        score -= 0.10
    if annotation.get("isReference"):
        score -= 0.03  # reference dims are less likely to be the primary match

    return min(score, 0.99)


def _view_name_matches(profile_view: str, annotation_view: str) -> bool:
    """Check if a profile view hint matches an annotation's view name.

    Boundary-safe: 'Detail View B' matches 'Detail View B (1 : 1)' (scale suffix)
    but 'Drawing View1' does NOT match 'Drawing View10' (different view number).
    """
    pv = profile_view.lower().strip()
    av = annotation_view.lower().strip()
    if pv == av:
        return True
    # Annotation may have a scale/parenthetical suffix the profile hint lacks
    if av.startswith(pv):
        rest = av[len(pv):]
        return not rest or not rest[0].isalnum()
    if pv.startswith(av):
        rest = pv[len(av):]
        return not rest or not rest[0].isalnum()
    return False


def _annotation_match_candidates(annotation: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    for key in (
        "featureName",
        "annotationName",
        "dimensionText",
        "displayText",
        "noteText",
        "gtolText",
        "content",
        "text",
    ):
        value = annotation.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())

    for value in annotation.get("matchKeys") or []:
        if isinstance(value, str) and value.strip():
            values.append(value.strip())

    seen = set()
    unique_values = []
    for value in values:
        normalized = _normalize_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_values.append(value)
    return unique_values


def _normalize_annotation(
    raw_annotation: Dict[str, Any],
    annotation_index: int,
    sheet_index: int,
    sheet_name: Optional[str],
    sheet_width: Optional[float],
    sheet_height: Optional[float],
    view_name: Optional[str],
    view_outline: Optional[List[float]],
) -> Dict[str, Any]:
    position = _coerce_xy(
        raw_annotation.get("positionSheet"),
        raw_annotation.get("sheetPosition"),
        raw_annotation.get("position"),
        raw_annotation.get("anchor"),
    )
    leaders = _coerce_leaders(raw_annotation.get("leaders") or raw_annotation.get("leaderPoints"))
    match_keys = raw_annotation.get("matchKeys") or raw_annotation.get("match_keys") or []

    normalized = {
        "annotationId": raw_annotation.get("annotationId") or raw_annotation.get("id") or f"annotation_{annotation_index}",
        "annotationName": raw_annotation.get("annotationName") or raw_annotation.get("name") or f"annotation_{annotation_index}",
        "annotationType": raw_annotation.get("annotationType") or raw_annotation.get("type") or "unknown",
        "sheetIndex": _coerce_int(raw_annotation.get("sheetIndex")) or sheet_index,
        "sheetName": raw_annotation.get("sheetName") or sheet_name,
        "sheetWidth": _coerce_float(raw_annotation.get("sheetWidth"), sheet_width),
        "sheetHeight": _coerce_float(raw_annotation.get("sheetHeight"), sheet_height),
        "viewName": raw_annotation.get("viewName") or view_name,
        "viewOutline": _coerce_rect(raw_annotation.get("viewOutline") or raw_annotation.get("outline") or view_outline),
        "positionSheet": position,
        "boundsSheet": _coerce_rect(raw_annotation.get("boundsSheet") or raw_annotation.get("bounds")),
        "anchorKind": raw_annotation.get("anchorKind") or raw_annotation.get("anchor_kind"),
        "geometrySource": raw_annotation.get("geometrySource") or raw_annotation.get("geometry_source"),
        "leaders": leaders,
        "visible": raw_annotation.get("visible", True),
        "isDangling": bool(raw_annotation.get("isDangling", False)),
        "featureName": raw_annotation.get("featureName") or raw_annotation.get("feature_name"),
        "dimensionText": raw_annotation.get("dimensionText") or raw_annotation.get("displayText"),
        "displayText": raw_annotation.get("displayText"),
        "noteText": raw_annotation.get("noteText"),
        "gtolText": raw_annotation.get("gtolText"),
        "content": raw_annotation.get("content"),
        "text": raw_annotation.get("text"),
        "matchKeys": [value for value in match_keys if isinstance(value, str) and value.strip()],
        "textRuns": _coerce_text_runs(raw_annotation.get("textRuns") or raw_annotation.get("text_runs")),
        "textExtent": raw_annotation.get("textExtent"),
        # Dimension-specific fields for hybrid numeric matching
        "dimensionValue": _coerce_float(raw_annotation.get("dimensionValue")),
        "dimensionType": raw_annotation.get("dimensionType"),
        "isReference": bool(raw_annotation.get("isReference", False)),
        "isDriven": bool(raw_annotation.get("isDriven", False)),
    }
    return normalized


def _normalize_primitive(
    raw_primitive: Dict[str, Any],
    primitive_index: int,
) -> Optional[Dict[str, Any]]:
    points_view = _coerce_point_list(raw_primitive.get("pointsView") or raw_primitive.get("points_view"))
    points_sheet = _coerce_point_list(raw_primitive.get("pointsSheet") or raw_primitive.get("points_sheet"))
    center_view = _coerce_xy(raw_primitive.get("centerView") or raw_primitive.get("center_view"))
    center_sheet = _coerce_xy(raw_primitive.get("centerSheet") or raw_primitive.get("center_sheet"))

    normalized = {
        "primitiveId": raw_primitive.get("primitiveId") or f"primitive_{primitive_index}",
        "primitiveType": (raw_primitive.get("primitiveType") or raw_primitive.get("type") or "polyline"),
        "sourceKind": raw_primitive.get("sourceKind") or raw_primitive.get("source_kind") or "modelEdge",
        "geometrySource": raw_primitive.get("geometrySource") or raw_primitive.get("geometry_source") or "tessellated",
        "boundsView": _coerce_rect(raw_primitive.get("boundsView") or raw_primitive.get("bounds_view")),
        "boundsSheet": _coerce_rect(raw_primitive.get("boundsSheet") or raw_primitive.get("bounds_sheet")),
        "centerView": center_view,
        "centerSheet": center_sheet,
        "radiusView": _coerce_float(raw_primitive.get("radiusView") or raw_primitive.get("radius_view")),
        "radiusSheet": _coerce_float(raw_primitive.get("radiusSheet") or raw_primitive.get("radius_sheet")),
        "rotationDir": _coerce_int(raw_primitive.get("rotationDir") or raw_primitive.get("rotation_dir")),
        "pointsView": points_view,
        "pointsSheet": points_sheet,
    }
    if not points_view and not points_sheet and not center_view and not center_sheet:
        return None
    return normalized


def _coerce_float(*values: Any) -> Optional[float]:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_rect(value: Any) -> Optional[List[float]]:
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        try:
            return [float(value[0]), float(value[1]), float(value[2]), float(value[3])]
        except (TypeError, ValueError):
            return None
    return None


def _coerce_xy(*values: Any) -> Optional[Dict[str, float]]:
    for value in values:
        if value is None:
            continue
        if isinstance(value, dict):
            x = _coerce_float(value.get("x"))
            y = _coerce_float(value.get("y"))
            if x is not None and y is not None:
                return {"x": x, "y": y}
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            x = _coerce_float(value[0])
            y = _coerce_float(value[1])
            if x is not None and y is not None:
                return {"x": x, "y": y}
    return None


def _coerce_point_list(value: Any) -> List[Dict[str, float]]:
    if not isinstance(value, list):
        return []

    points: List[Dict[str, float]] = []
    for item in value:
        point = _coerce_xy(item)
        if point is not None:
            points.append(point)
    return points


def _coerce_leaders(value: Any) -> List[Dict[str, float]]:
    if not isinstance(value, list):
        return []

    leaders: List[Dict[str, float]] = []
    for point in value:
        if isinstance(point, dict):
            x = _coerce_float(point.get("x"))
            y = _coerce_float(point.get("y"))
            z = _coerce_float(point.get("z"), 0.0)
            if x is None or y is None:
                continue
            leaders.append({"x": x, "y": y, "z": z or 0.0})
        elif isinstance(point, (list, tuple)) and len(point) >= 2:
            x = _coerce_float(point[0])
            y = _coerce_float(point[1])
            z = _coerce_float(point[2], 0.0) if len(point) >= 3 else 0.0
            if x is None or y is None:
                continue
            leaders.append({"x": x, "y": y, "z": z or 0.0})
    return leaders


def _coerce_text_runs(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []

    runs: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue

        position = _coerce_xy(item.get("positionSheet"), item.get("position"))
        run: Dict[str, Any] = {
            "text": item.get("text"),
            "positionSheet": position,
            "height": _coerce_float(item.get("height")),
            "width": _coerce_float(item.get("width")),
            "refPosition": _coerce_int(item.get("refPosition")),
            "angle": _coerce_float(item.get("angle")),
            "positionKind": item.get("positionKind") or item.get("position_kind"),
        }
        if all(value is None for value in run.values()):
            continue
        runs.append(run)
    return runs


def _normalize_text(value: str) -> str:
    if not value:
        return ""
    text = value.lower()
    text = text.replace("⌀", " diameter ")
    text = text.replace("ø", " diameter ")
    text = text.replace("Ø", " diameter ")
    text = text.replace("°", " deg ")
    text = text.replace("±", " plusminus ")
    text = text.replace("∅", " diameter ")
    tokens = _TOKEN_RE.findall(text)
    return " ".join(tokens)


def _text_similarity(left: str, right: str) -> float:
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    if left_norm in right_norm or right_norm in left_norm:
        # Penalize when the shorter string is very short (likely a false positive)
        shorter = min(len(left_norm), len(right_norm))
        longer = max(len(left_norm), len(right_norm))
        if shorter <= 3 or shorter < longer * 0.4:
            return 0.50  # weak match for very short substrings
        return 0.94

    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    if not left_tokens or not right_tokens:
        return 0.0

    shared_tokens = left_tokens & right_tokens
    if not shared_tokens:
        return 0.0

    overlap = len(shared_tokens) / max(1, min(len(left_tokens), len(right_tokens)))
    left_numbers = {token for token in left_tokens if token.isdigit()}
    right_numbers = {token for token in right_tokens if token.isdigit()}
    number_bonus = 0.15 if left_numbers and right_numbers and left_numbers & right_numbers else 0.0
    return min(0.89, overlap + number_bonus)


def _has_numeric_xy(location: Any) -> bool:
    if isinstance(location, dict):
        return _coerce_float(location.get("x")) is not None and _coerce_float(location.get("y")) is not None
    return False
