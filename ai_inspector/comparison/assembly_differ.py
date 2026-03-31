"""Assembly Revision Diff Engine.

Compares two revisions of the same assembly and produces a structured diff
covering parts (added/removed/changed), dimensions, features, physical
properties, and mates.

Phase 1 constraint: part numbers must be stable across revisions.
"""

import json
import re
from collections import Counter
from pathlib import Path


# ---------------------------------------------------------------------------
# Dimension matching
# ---------------------------------------------------------------------------

def _dimension_identity_key(dim):
    """Identity key for a dimension — stable properties only, excludes value."""
    dtype = dim.get("dimensionType", "")
    tol_type = dim.get("toleranceType", "none")
    is_ref = dim.get("isReference", False)
    view_name = dim.get("_viewName", "")
    pos = dim.get("positionSheet", [0, 0])
    pos_bucket = (round(pos[0], 2), round(pos[1], 2))
    return (dtype, tol_type, is_ref, view_name, pos_bucket)


def _dimension_comparison_fields(dim):
    """Mutable fields to compare after identity match."""
    return {
        "value": round(dim.get("dimensionValue", 0), 6),
        "tolerancePlus": round(dim.get("tolerancePlus", 0), 6),
        "toleranceMinus": round(dim.get("toleranceMinus", 0), 6),
        "text": dim.get("dimensionText", ""),
    }


def _diff_dimensions(dims_a, dims_b):
    """Compare two lists of dimension annotations. Returns list of changes."""
    # Build identity -> comparison mappings using lists to handle key collisions.
    # Multiple dimensions can share the same coarse identity bucket in dense drawings.
    # We use a dict of lists: key -> [fields, fields, ...]
    map_a = {}
    for d in dims_a:
        key = _dimension_identity_key(d)
        map_a.setdefault(key, []).append(_dimension_comparison_fields(d))

    map_b = {}
    for d in dims_b:
        key = _dimension_identity_key(d)
        map_b.setdefault(key, []).append(_dimension_comparison_fields(d))

    changes = []
    keys_a = set(map_a.keys())
    keys_b = set(map_b.keys())

    # Matched: present in both — pair by index within the bucket
    for key in keys_a & keys_b:
        list_a = map_a[key]
        list_b = map_b[key]
        # Pair up to min(len) entries, rest are added/removed
        for i in range(min(len(list_a), len(list_b))):
            old = list_a[i]
            new = list_b[i]
            if old != new:
                delta = round(new["value"] - old["value"], 6) if old["value"] and new["value"] else 0
                changes.append({
                    "identity": {"dimensionType": key[0], "view": key[3], "position": key[4]},
                    "old": old,
                    "new": new,
                    "delta_value": delta,
                    "tolerance_changed": (
                        old["tolerancePlus"] != new["tolerancePlus"]
                        or old["toleranceMinus"] != new["toleranceMinus"]
                    ),
                })
        # Extra in A = removed (unique _uid per entry)
        for i in range(len(list_b), len(list_a)):
            changes.append({
                "identity": {"dimensionType": key[0], "view": key[3], "position": key[4]},
                "old": list_a[i], "new": None, "status": "removed",
                "_uid": (key, "a", i),
            })
        # Extra in B = added
        for i in range(len(list_a), len(list_b)):
            changes.append({
                "identity": {"dimensionType": key[0], "view": key[3], "position": key[4]},
                "old": None, "new": list_b[i], "status": "added",
                "_uid": (key, "b", i),
            })

    # Keys only in B = added
    uid_counter = 0
    for key in keys_b - keys_a:
        for fields in map_b[key]:
            changes.append({
                "identity": {"dimensionType": key[0], "view": key[3], "position": key[4]},
                "old": None, "new": fields, "status": "added",
                "_uid": (key, "b", uid_counter),
            })
            uid_counter += 1

    # Keys only in A = removed
    uid_counter = 0
    for key in keys_a - keys_b:
        for fields in map_a[key]:
            changes.append({
                "identity": {"dimensionType": key[0], "view": key[3], "position": key[4]},
                "old": fields, "new": None, "status": "removed",
                "_uid": (key, "a", uid_counter),
            })
            uid_counter += 1

    # Fallback: if >50% unmatched, attempt value-proximity matching
    total = max(len(dims_a), len(dims_b), 1)
    raw_added = [c for c in changes if c.get("status") == "added"]
    raw_removed = [c for c in changes if c.get("status") == "removed"]
    unmatched_count = len(raw_added) + len(raw_removed)
    if unmatched_count > total * 0.5 and unmatched_count > 2:
        # Flatten: build flat_key -> (fields, dimensionType, viewName) from raw entries
        flat_a = {}
        for i, c in enumerate(raw_removed):
            flat_a[("rem", i)] = {
                **c["old"],
                "_dtype": c["identity"]["dimensionType"],
                "_view": c["identity"].get("view", ""),
            }
        flat_b = {}
        for i, c in enumerate(raw_added):
            flat_b[("add", i)] = {
                **c["new"],
                "_dtype": c["identity"]["dimensionType"],
                "_view": c["identity"].get("view", ""),
            }

        matched_fallback, matched_flat_a, matched_flat_b = _fallback_value_match(flat_a, flat_b)

        # Build sets of raw entry indices that were matched (including identical-value matches)
        matched_rem_indices = {fk[1] for fk in matched_flat_a}
        matched_add_indices = {fk[1] for fk in matched_flat_b}

        # Remove matched raw entries by index, keep unmatched ones
        surviving = []
        rem_idx = 0
        add_idx = 0
        for c in changes:
            if c.get("status") == "removed":
                if rem_idx not in matched_rem_indices:
                    surviving.append(c)
                rem_idx += 1
            elif c.get("status") == "added":
                if add_idx not in matched_add_indices:
                    surviving.append(c)
                add_idx += 1
            else:
                surviving.append(c)
        surviving.extend(matched_fallback)
        changes = surviving

    # Strip internal fields from output
    for c in changes:
        c.pop("_uid", None)

    return changes


def _fallback_value_match(unmatched_a, unmatched_b):
    """Match unmatched dimensions by closest value within same type+view.

    Returns (matched_changes, matched_keys_a, matched_keys_b) so the caller
    can remove only successfully re-matched entries and preserve the rest.
    """
    results = []
    used_b = set()
    matched_keys_a = set()

    for key_a, fields_a in unmatched_a.items():
        dtype_a = fields_a.get("_dtype", "")
        view_a = fields_a.get("_view", "")
        best_key_b = None
        best_dist = float("inf")

        for key_b, fields_b in unmatched_b.items():
            if key_b in used_b:
                continue
            dtype_b = fields_b.get("_dtype", "")
            view_b = fields_b.get("_view", "")
            if dtype_a == dtype_b and view_a == view_b:
                dist = abs(fields_a["value"] - fields_b["value"])
                if dist < best_dist:
                    best_dist = dist
                    best_key_b = key_b

        if best_key_b is not None and best_dist < 0.1:  # Max 100mm difference
            used_b.add(best_key_b)
            matched_keys_a.add(key_a)
            fields_b = unmatched_b[best_key_b]
            # Compare only the actual dimension fields (exclude _dtype, _view helpers)
            cmp_a = {k: v for k, v in fields_a.items() if not k.startswith("_")}
            cmp_b = {k: v for k, v in fields_b.items() if not k.startswith("_")}
            # Skip if values are actually identical (position shift only)
            if cmp_a == cmp_b:
                continue
            delta = round(fields_b["value"] - fields_a["value"], 6)
            results.append({
                "identity": {"dimensionType": dtype_a, "view": view_a, "match": "fallback"},
                "old": cmp_a,
                "new": cmp_b,
                "delta_value": delta,
                "tolerance_changed": (
                    fields_a["tolerancePlus"] != fields_b["tolerancePlus"]
                    or fields_a["toleranceMinus"] != fields_b["toleranceMinus"]
                ),
            })

    return results, matched_keys_a, used_b


# ---------------------------------------------------------------------------
# Mate matching
# ---------------------------------------------------------------------------

def _mate_identity_key(mate):
    """Identity key for a mate — excludes mutable distance/angle."""
    e1 = mate.get("entity1", {})
    e2 = mate.get("entity2", {})

    def _entity_tuple(e):
        return (
            e.get("componentFileName", "").lower(),
            e.get("instanceNumber", 0),
            e.get("geometryType", ""),
            tuple(round(x, 4) for x in (e.get("point") or [0, 0, 0])),
        )

    et1 = _entity_tuple(e1)
    et2 = _entity_tuple(e2)
    sorted_entities = tuple(sorted([et1, et2]))
    mate_type = mate.get("type", "")
    return (sorted_entities, mate_type)


def _mate_comparison_fields(mate):
    """Mutable fields to compare after identity match."""
    return {
        "distance": round(mate.get("distance", 0), 6),
        "angle": round(mate.get("angle", 0), 6),
        "isFlipped": mate.get("isFlipped", False),
        "alignment": mate.get("alignment", ""),
    }


def _mate_description(mate):
    """Human-readable description of a mate."""
    e1 = mate.get("entity1", {})
    e2 = mate.get("entity2", {})
    t = mate.get("type", "?")
    c1 = e1.get("componentFileName", "?").replace(".SLDPRT", "").replace(".sldprt", "")
    c2 = e2.get("componentFileName", "?").replace(".SLDPRT", "").replace(".sldprt", "")
    return f"{t} between {c1} and {c2}"


def _diff_mates(mates_a, mates_b):
    """Compare two mate lists. Returns changed, added, removed."""
    map_a = {}
    desc_a = {}
    for m in mates_a:
        key = _mate_identity_key(m)
        map_a[key] = _mate_comparison_fields(m)
        desc_a[key] = _mate_description(m)

    map_b = {}
    desc_b = {}
    for m in mates_b:
        key = _mate_identity_key(m)
        map_b[key] = _mate_comparison_fields(m)
        desc_b[key] = _mate_description(m)

    keys_a = set(map_a.keys())
    keys_b = set(map_b.keys())

    changed = []
    for key in keys_a & keys_b:
        if map_a[key] != map_b[key]:
            changed.append({
                "description": desc_a[key],
                "old": map_a[key],
                "new": map_b[key],
            })

    added = [{"description": desc_b[k]} for k in keys_b - keys_a]
    removed = [{"description": desc_a[k]} for k in keys_a - keys_b]

    return changed, added, removed


# ---------------------------------------------------------------------------
# Feature canonicalization and diffing
# ---------------------------------------------------------------------------

def _canonicalize_features(part_data):
    """Build sorted, order-independent feature signatures for diffing."""
    features = part_data.get("features", {})
    canonical = {}

    for hole in features.get("holeWizardHoles", []):
        sig = (
            "hole",
            hole.get("type", ""),
            round(hole.get("diameter", 0), 4),
            round(hole.get("depth", 0), 4),
            hole.get("isThrough", False),
            hole.get("count", 1),
        )
        canonical.setdefault("holes", []).append(sig)

    for ext in features.get("extrudes", []):
        sig = (
            "extrude",
            round(ext.get("depth", 0), 4),
            ext.get("endCondition", ""),
        )
        canonical.setdefault("extrudes", []).append(sig)

    for fil in features.get("fillets", []):
        sig = ("fillet", round(fil.get("radius", 0), 4), fil.get("count", 1))
        canonical.setdefault("fillets", []).append(sig)

    for cham in features.get("chamfers", []):
        sig = (
            "chamfer",
            round(cham.get("distance", 0), 4),
            round(cham.get("angle", 0), 2),
            cham.get("count", 1),
        )
        canonical.setdefault("chamfers", []).append(sig)

    # Sort all lists for order-independent comparison
    for key in canonical:
        canonical[key] = sorted(canonical[key])

    return canonical


def _diff_features(part_a, part_b):
    """Compare canonicalized features between two part revisions."""
    canon_a = _canonicalize_features(part_a)
    canon_b = _canonicalize_features(part_b)

    all_keys = set(list(canon_a.keys()) + list(canon_b.keys()))
    changes = []

    for key in all_keys:
        sigs_a = canon_a.get(key, [])
        sigs_b = canon_b.get(key, [])
        if sigs_a != sigs_b:
            # Use multiset comparison to preserve duplicate counts.
            # Convert to sorted string lists so we can count occurrences properly.
            strs_a = sorted(str(s) for s in sigs_a)
            strs_b = sorted(str(s) for s in sigs_b)
            # Count additions and removals including multiplicity
            count_a = Counter(strs_a)
            count_b = Counter(strs_b)
            added_count = sum((count_b - count_a).values())
            removed_count = sum((count_a - count_b).values())
            if added_count or removed_count:
                changes.append({
                    "category": key,
                    "added_count": added_count,
                    "removed_count": removed_count,
                    "details": f"{key}: {removed_count} removed, {added_count} added",
                })

    return changes


# ---------------------------------------------------------------------------
# Physical property diffing
# ---------------------------------------------------------------------------

def _diff_physical(part_a, part_b):
    """Compare physical properties (mass, volume, bbox) between revisions."""
    phys_a = part_a.get("physical", {})
    phys_b = part_b.get("physical", {})
    changes = {}

    for field in ("mass", "volume", "surfaceArea"):
        va = phys_a.get(field)
        vb = phys_b.get(field)
        if va is not None and vb is not None:
            if abs(va - vb) > 1e-9:
                changes[field] = {
                    "old": round(va, 6),
                    "new": round(vb, 6),
                    "delta": round(vb - va, 6),
                    "delta_pct": round((vb - va) / va * 100, 1) if va != 0 else None,
                }

    return changes if changes else None


# ---------------------------------------------------------------------------
# Drawing map loading
# ---------------------------------------------------------------------------

def _load_drawing_map_dims(parts_dir, part_number):
    """Load dimension annotations from a drawing map file, if it exists."""
    if not parts_dir:
        return []
    dm_path = parts_dir / f"{part_number}_drawing_map.json"
    if not dm_path.exists():
        return []
    try:
        with open(dm_path, "r", encoding="utf-8-sig") as f:
            dm = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    dims = []
    for sheet in dm.get("sheets", []):
        for view in sheet.get("views", []):
            view_name = view.get("viewName", "")
            for ann in view.get("annotations", []):
                if ann.get("annotationType") == "displayDimension":
                    ann["_viewName"] = view_name
                    dims.append(ann)
    return dims


# ---------------------------------------------------------------------------
# Top-level diff function
# ---------------------------------------------------------------------------

def compute_assembly_diff(assy_a, assy_b, parts_dir_a=None, parts_dir_b=None):
    """Compare two assembly revision JSONs and return structured diff.

    Args:
        assy_a: Parsed JSON dict for revision A
        assy_b: Parsed JSON dict for revision B
        parts_dir_a: Path to revA/parts/ directory (optional, for drawing maps)
        parts_dir_b: Path to revB/parts/ directory (optional, for drawing maps)

    Returns:
        Dict with changed_parts, added_parts, removed_parts, mate changes, summary.
    """
    pdc_a = assy_a.get("partDataCache", {})
    pdc_b = assy_b.get("partDataCache", {})

    # Build partNumber -> partDataCache key mapping
    # Prefer customProperties.PartNo (stable across extractions) over identity.partNumber
    def _pn_map(pdc):
        result = {}
        for key, val in pdc.items():
            ident = val.get("identity") or {}
            pn = ((ident.get("customProperties") or {}).get("PartNo", "")).strip()
            if not pn:
                pn = (ident.get("partNumber") or "").strip()
            if pn:
                result[pn] = key
        return result

    pn_to_key_a = _pn_map(pdc_a)
    pn_to_key_b = _pn_map(pdc_b)

    all_pns_a = set(pn_to_key_a.keys())
    all_pns_b = set(pn_to_key_b.keys())

    added_parts = sorted(all_pns_b - all_pns_a)
    removed_parts = sorted(all_pns_a - all_pns_b)
    common_parts = all_pns_a & all_pns_b

    changed_parts = {}
    unchanged_parts = []

    for pn in sorted(common_parts):
        part_a = pdc_a[pn_to_key_a[pn]]
        part_b = pdc_b[pn_to_key_b[pn]]
        desc = (part_b.get("identity") or {}).get("description", "")

        # Dimension diff (from drawing maps)
        dims_a = _load_drawing_map_dims(parts_dir_a, pn) if parts_dir_a else []
        dims_b = _load_drawing_map_dims(parts_dir_b, pn) if parts_dir_b else []
        dim_changes = _diff_dimensions(dims_a, dims_b) if (dims_a or dims_b) else []

        # Feature diff
        feat_changes = _diff_features(part_a, part_b)

        # Physical diff
        phys_changes = _diff_physical(part_a, part_b)

        if dim_changes or feat_changes or phys_changes:
            changed_parts[pn] = {
                "description": desc,
                "dimensions_changed": dim_changes,
                "features_changed": feat_changes,
                "physical_changed": phys_changes,
            }
        else:
            unchanged_parts.append(pn)

    # Mate diff
    mates_a = assy_a.get("mates", [])
    mates_b = assy_b.get("mates", [])
    mates_changed, mates_added, mates_removed = _diff_mates(mates_a, mates_b)

    # Build summary
    summary_parts = []
    if changed_parts:
        summary_parts.append(f"{len(changed_parts)} part(s) changed")
    if added_parts:
        summary_parts.append(f"{len(added_parts)} added")
    if removed_parts:
        summary_parts.append(f"{len(removed_parts)} removed")
    if mates_changed or mates_added or mates_removed:
        mc = len(mates_changed) + len(mates_added) + len(mates_removed)
        summary_parts.append(f"{mc} mate change(s)")
    total_dim_changes = sum(len(v.get("dimensions_changed", [])) for v in changed_parts.values())
    if total_dim_changes:
        summary_parts.append(f"{total_dim_changes} dimension(s) modified")

    return {
        "changed_parts": changed_parts,
        "added_parts": added_parts,
        "removed_parts": removed_parts,
        "unchanged_parts": unchanged_parts,
        "mates_changed": mates_changed,
        "mates_added": mates_added,
        "mates_removed": mates_removed,
        "summary": ", ".join(summary_parts) if summary_parts else "No changes detected",
    }
