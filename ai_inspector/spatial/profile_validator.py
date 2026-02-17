"""
Profile Validator for InspectorPro
Lint-checks inspection profiles for internal feature type consistency.

Runs as a data quality check — not at inspection time, but when profiles
are created or updated.
"""

import json
import re
from pathlib import Path
from typing import Optional


def validate_profile(profile: dict) -> list[dict]:
    """
    Validate an inspection profile for internal consistency.

    Checks feature name vs type, type vs description, and known pattern
    contradictions. Returns a list of issue dicts, each with:
      - feature_name: str
      - feature_type: str
      - issue: str (human-readable description)
      - severity: 'error' or 'warning'
    """
    issues: list[dict] = []
    features = profile.get("features", [])

    for feat in features:
        name = (feat.get("name") or "").lower().strip()
        ftype = (feat.get("type") or "").lower().strip()
        desc = (feat.get("spatial_description") or feat.get("description") or "").lower().strip()
        raw_name = feat.get("name", "<unnamed>")
        raw_type = feat.get("type", "<no type>")

        # ---------------------------------------------------------------
        # 1. NAME vs TYPE contradiction checks
        # ---------------------------------------------------------------

        # Counterbore: name mentions it but type does not
        if _contains(name, "counterbore", "counter bore", "counter-bore") and not _contains(ftype, "counterbore", "counter bore", "counter-bore"):
            issues.append(_issue(
                raw_name, raw_type,
                f"Name contains 'counterbore' but type '{raw_type}' does not mention counterbore",
                "warning"
            ))

        # Countersink: name mentions it but type does not
        if _contains(name, "countersink", "counter sink", "counter-sink", "csk") and not _contains(ftype, "countersink", "counter sink", "counter-sink", "csk"):
            issues.append(_issue(
                raw_name, raw_type,
                f"Name contains 'countersink' but type '{raw_type}' does not mention countersink",
                "warning"
            ))

        # Tapped/threaded: name mentions it but type does not
        if _contains(name, "tapped", "threaded", "thread") and not _contains(ftype, "tapped", "threaded", "thread"):
            issues.append(_issue(
                raw_name, raw_type,
                f"Name contains tapped/threaded keyword but type '{raw_type}' does not mention tapped/thread",
                "warning"
            ))

        # Chamfer: name mentions it but type does not
        if _contains(name, "chamfer") and not _contains(ftype, "chamfer"):
            issues.append(_issue(
                raw_name, raw_type,
                f"Name contains 'chamfer' but type '{raw_type}' does not mention chamfer",
                "warning"
            ))

        # Through vs blind contradiction in name vs type
        if _contains(name, "through") and _contains(ftype, "blind") and not _contains(ftype, "through"):
            issues.append(_issue(
                raw_name, raw_type,
                f"Name says 'through' but type says 'blind' — contradictory hole depth",
                "error"
            ))
        if _contains(name, "blind") and _contains(ftype, "through") and not _contains(ftype, "blind"):
            issues.append(_issue(
                raw_name, raw_type,
                f"Name says 'blind' but type says 'through' — contradictory hole depth",
                "error"
            ))

        # Slot: name mentions it but type does not
        if _contains(name, "slot") and not _contains(ftype, "slot", "cutout", "cut"):
            issues.append(_issue(
                raw_name, raw_type,
                f"Name contains 'slot' but type '{raw_type}' does not mention slot/cutout",
                "warning"
            ))

        # ---------------------------------------------------------------
        # 2. TYPE vs DESCRIPTION contradiction checks
        # ---------------------------------------------------------------

        # Description mentions counterbore but type is plain hole
        if _contains(desc, "counterbore", "counter bore", "counter-bore") and _is_plain_hole(ftype) and not _contains(ftype, "counterbore", "counter bore"):
            issues.append(_issue(
                raw_name, raw_type,
                f"Description mentions 'counterbore' but type is plain '{raw_type}'",
                "warning"
            ))

        # Description mentions tapped/thread but type is plain hole
        if _contains(desc, "tapped", "thread") and _is_plain_hole(ftype) and not _contains(ftype, "tapped", "thread"):
            issues.append(_issue(
                raw_name, raw_type,
                f"Description mentions tapped/thread but type is plain '{raw_type}'",
                "warning"
            ))

        # Description mentions countersink but type is plain hole
        if _contains(desc, "countersink", "counter sink") and _is_plain_hole(ftype) and not _contains(ftype, "countersink", "counter sink"):
            issues.append(_issue(
                raw_name, raw_type,
                f"Description mentions 'countersink' but type is plain '{raw_type}'",
                "warning"
            ))

        # Description mentions blind but type says through
        if _contains(desc, "blind") and _contains(ftype, "through") and not _contains(ftype, "blind") and not _contains(desc, "through"):
            issues.append(_issue(
                raw_name, raw_type,
                f"Description mentions 'blind' but type says 'through'",
                "warning"
            ))

        # ---------------------------------------------------------------
        # 3. KNOWN PATTERNS
        # ---------------------------------------------------------------

        # Set screw without tapped type
        if _contains(name, "set screw") and not _contains(ftype, "tapped", "thread", "set screw"):
            issues.append(_issue(
                raw_name, raw_type,
                f"Name references 'set screw' but type '{raw_type}' is not tapped/threaded",
                "warning"
            ))

        # Contradictory type string: contains both blind and through
        if _contains(ftype, "blind") and _contains(ftype, "through"):
            # Compound groupings using "and" or "with" are intentional
            # e.g. "Through-hole and blind hole", "Small blind holes with through holes"
            if _is_compound_type(ftype):
                issues.append(_issue(
                    raw_name, raw_type,
                    f"Type groups both 'blind' and 'through' features: '{raw_type}' — consider splitting into separate features",
                    "warning"
                ))
            else:
                issues.append(_issue(
                    raw_name, raw_type,
                    f"Type contains contradictory terms: both 'blind' and 'through' in '{raw_type}'",
                    "error"
                ))

    return issues


def validate_all_profiles(library_dir: str) -> dict:
    """
    Run validate_profile on every inspection profile in the given directory.

    Returns a dict with:
      - total_profiles: int
      - profiles_with_issues: int
      - total_issues: int
      - error_count: int
      - warning_count: int
      - results: list of {part_number, part_name, issues: [...]}

    Also prints a summary to stdout.
    """
    lib = Path(library_dir)
    if not lib.exists():
        raise FileNotFoundError(f"Library directory not found: {library_dir}")

    results = []
    total_issues = 0
    error_count = 0
    warning_count = 0
    profiles_with_issues = 0
    total_profiles = 0

    for profile_path in sorted(lib.glob("*_inspection_profile.json")):
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                profile = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            results.append({
                "part_number": profile_path.stem.replace("_inspection_profile", ""),
                "part_name": "<load error>",
                "issues": [{
                    "feature_name": "<file>",
                    "feature_type": "<file>",
                    "issue": f"Could not load profile: {exc}",
                    "severity": "error",
                }]
            })
            total_issues += 1
            error_count += 1
            profiles_with_issues += 1
            total_profiles += 1
            continue

        total_profiles += 1
        issues = validate_profile(profile)

        if issues:
            profiles_with_issues += 1
            total_issues += len(issues)
            for iss in issues:
                if iss["severity"] == "error":
                    error_count += 1
                else:
                    warning_count += 1

        results.append({
            "part_number": profile.get("part_number", profile_path.stem.replace("_inspection_profile", "")),
            "part_name": profile.get("part_name", ""),
            "issues": issues,
        })

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"Profile Validation Summary")
    print(f"{'=' * 60}")
    print(f"Total profiles scanned:    {total_profiles}")
    print(f"Profiles with issues:      {profiles_with_issues}")
    print(f"Total issues found:        {total_issues}")
    print(f"  Errors:                  {error_count}")
    print(f"  Warnings:                {warning_count}")
    print(f"{'=' * 60}")

    if total_issues > 0:
        print(f"\nDetailed Issues:")
        print(f"{'-' * 60}")
        for entry in results:
            if entry["issues"]:
                print(f"\n  Part: {entry['part_number']} ({entry['part_name']})")
                for iss in entry["issues"]:
                    sev = iss["severity"].upper()
                    print(f"    [{sev}] Feature: {iss['feature_name']}")
                    print(f"           Type: {iss['feature_type']}")
                    print(f"           Issue: {iss['issue']}")
    else:
        print("\n  ✓ No issues found — all profiles are internally consistent.")

    print()

    return {
        "total_profiles": total_profiles,
        "profiles_with_issues": profiles_with_issues,
        "total_issues": total_issues,
        "error_count": error_count,
        "warning_count": warning_count,
        "results": results,
    }


# ------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------

def _contains(text: str, *keywords: str) -> bool:
    """Check if text contains any of the given keywords (case-insensitive)."""
    for kw in keywords:
        if kw in text:
            return True
    return False


def _is_compound_type(ftype: str) -> bool:
    """Check if a type string is a compound grouping or dimensional qualifier.

    Recognizes:
    - Conjunctions: "through holes and blind holes", "blind holes with through holes"
    - Dimensional qualifiers: "blind hole through full thickness" (preposition, not type)
    """
    # Compound groupings using conjunctions
    if re.search(r'\b(and|with|/)\b', ftype):
        return True
    # "through full" or "through entire" etc. = dimensional qualifier, not a hole type
    if re.search(r'\bthrough\s+(full|entire|complete|total|the|part)\b', ftype):
        return True
    return False


def _is_plain_hole(ftype: str) -> bool:
    """Check if a type string is a plain 'hole' without qualifiers."""
    ftype = ftype.strip()
    # Match types like "hole", "holes", "through hole", "blind hole"
    # but not "tapped hole", "counterbore", etc.
    if "hole" in ftype:
        if not any(q in ftype for q in ("tapped", "thread", "counterbore", "counter bore",
                                         "countersink", "counter sink")):
            return True
    return False


def _issue(feature_name: str, feature_type: str, issue: str, severity: str) -> dict:
    """Create a standardized issue dict."""
    return {
        "feature_name": feature_name,
        "feature_type": feature_type,
        "issue": issue,
        "severity": severity,
    }


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    lib_dir = sys.argv[1] if len(sys.argv) > 1 else "400S_Sorted_Library"
    result = validate_all_profiles(lib_dir)
    # Exit with error code if there are errors (not warnings)
    sys.exit(1 if result["error_count"] > 0 else 0)
