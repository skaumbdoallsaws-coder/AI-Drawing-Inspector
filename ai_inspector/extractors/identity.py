"""Part identity resolution from PDF filename and content."""

import os
import re
from pathlib import Path
from typing import List

from ..models.identity import ResolvedPartIdentity
from ..models.page import PageArtifact
from ..utils.sw_library import SwJsonLibrary


def clean_filename(filename: str) -> str:
    """
    Remove known suffixes like Paint, REV, etc.

    Args:
        filename: Raw filename

    Returns:
        Cleaned filename
    """
    cleaned = re.sub(r"[\s_]*(Paint|PAINT)$", "", filename, flags=re.IGNORECASE)
    return cleaned.strip()


def extract_pn_candidates(filename: str) -> List[str]:
    """
    Extract potential part number candidates from filename.

    Handles common engineering drawing filename patterns:
    - 1013572_01 (base with revision)
    - 101357201-03 (concatenated with revision)
    - 314884W_0 (with letter suffix)
    - 046-935-REV-A (with REV marker)

    Args:
        filename: PDF filename (with or without extension)

    Returns:
        List of candidates, most specific to least specific
    """
    # Remove extension and duplicate markers like (1), (2)
    name_no_ext = os.path.splitext(filename)[0]
    name_no_ext = re.sub(r"\s*\(\d+\)$", "", name_no_ext)
    cleaned = clean_filename(name_no_ext)

    # Split on spaces/underscores to get base part
    parts = re.split(r"[\s_]+", cleaned)
    if not parts:
        return []

    base = parts[0]
    candidates = []

    # 1. Base as-is
    candidates.append(base)

    # 2. Without hyphens
    base_no_hyphen = base.replace("-", "")
    if base_no_hyphen != base:
        candidates.append(base_no_hyphen)

    # 3. Remove letter suffixes (046-935A -> 046-935)
    if base and base[-1].isalpha() and len(base) > 1:
        candidates.append(base[:-1])
        candidates.append(base[:-1].replace("-", ""))

    # 4. Handle revision pattern (046-935-01 -> 046-935)
    rev_match = re.match(r"^(.+)-(\d{1,2})$", base)
    if rev_match:
        main_part = rev_match.group(1)
        candidates.append(main_part)
        candidates.append(main_part.replace("-", ""))

    # 5. Handle REV suffix (046-935-REV-A -> 046-935)
    rev_alpha = re.match(r"^(.+?)[-_]?REV[-_]?[A-Z0-9]*$", base, re.IGNORECASE)
    if rev_alpha:
        candidates.append(rev_alpha.group(1))
        candidates.append(rev_alpha.group(1).replace("-", ""))

    # 6. Progressive peeling - remove trailing digits
    temp = base_no_hyphen
    while len(temp) > 5:
        temp = temp[:-1]
        candidates.append(temp)

    # Remove duplicates, preserve order
    seen = set()
    unique = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            unique.append(c)

    return unique


def resolve_part_identity(
    pdf_path: str,
    artifacts: List[PageArtifact],
    sw_lib: SwJsonLibrary,
) -> ResolvedPartIdentity:
    """
    Resolve part identity using robust filename matching.

    Strategy:
    1. Extract candidates from PDF filename
    2. Try each candidate against SolidWorks library
    3. If no match, try embedded PDF text
    4. Fall back to filename as part number

    Args:
        pdf_path: Path to PDF file
        artifacts: Rendered page artifacts (for direct_text fallback)
        sw_lib: SolidWorks JSON library

    Returns:
        ResolvedPartIdentity with match details
    """
    filename = os.path.basename(pdf_path)
    candidates = extract_pn_candidates(filename)

    # Try each candidate against SW library
    for candidate in candidates:
        entry = sw_lib.lookup(candidate)
        if entry:
            return ResolvedPartIdentity(
                part_number=entry.part_number or candidate,
                confidence=1.0,
                source="filename+sw",
                sw_json_path=entry.json_path,
                candidates_tried=candidates,
            )

    # Try PDF embedded text
    for art in artifacts:
        if art.direct_text:
            text_candidates = extract_pn_candidates(art.direct_text[:200])
            for candidate in text_candidates[:5]:
                entry = sw_lib.lookup(candidate)
                if entry:
                    return ResolvedPartIdentity(
                        part_number=entry.part_number or candidate,
                        confidence=0.8,
                        source="pdf_text+sw",
                        sw_json_path=entry.json_path,
                        candidates_tried=candidates + text_candidates[:5],
                    )

    # Fallback - use first candidate or filename stem
    fallback_pn = candidates[0] if candidates else Path(pdf_path).stem
    return ResolvedPartIdentity(
        part_number=fallback_pn,
        confidence=0.3,
        source="fallback",
        sw_json_path=None,
        candidates_tried=candidates,
    )
