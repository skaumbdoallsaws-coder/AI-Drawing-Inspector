"""Spatial drawing inspection engine.

Compares engineering drawings against pre-built inspection profiles
using Claude Vision for analysis and GPT-4o-mini for report generation.
"""

import base64
import io
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

INSPECTION_SYSTEM = (
    "You are a senior mechanical engineering drawing inspector with 20+ years of "
    "experience reading engineering drawings per ASME Y14.5. You have been given an "
    "inspection profile that describes what features a part SHOULD have, where they "
    "should appear, and what they should look like in each drawing view. "
    "Your job is to examine the actual engineering drawing and verify every expected "
    "feature is properly represented. You output ONLY valid JSON."
)

INSPECTION_PROMPT = """\
{ref_section}
## Inspection Profile

Below is the spatial inspection profile for part **{part_number}** ({part_name}).
This was generated from the 3D CAD model and describes every feature the part has,
where each feature is located, and what it should look like in each drawing view.

```json
{profile_json}
```

## Your Task

Examine ALL pages/sheets of the engineering drawing and check them against the inspection profile.
{ref_instruction}A feature may appear on ANY sheet — check all of them before marking something MISSING.

For EACH feature listed in the profile:
1. Search the drawing for evidence of that feature (dimension callouts, hole symbols,
   thread notes, fillet radii, chamfer specs, etc.)
2. Determine if the feature is properly represented with correct callouts and dimensions
3. Note any discrepancies between what the profile expects and what the drawing shows
4. Evaluate ASME Y14.5 representation compliance for PRESENT/PARTIAL/DISCREPANT features:
   - representation_score: 0-100 (100 = fully ASME compliant callouts, tolerances, symbols)
   - representation_gaps: list specific ASME gaps (e.g., "missing tolerance", "non-standard symbol")
   - asme_compliance: COMPLIANT (score 80-100), MINOR_GAPS (60-79), MAJOR_GAPS (30-59), NON_COMPLIANT (0-29)
   - For MISSING features, set representation_score to null, representation_gaps to [], asme_compliance to null

Also check the view_expectations — does the drawing include the recommended views
and section cuts?

{asme_section}For each feature with status PRESENT or PARTIAL, also evaluate its representation
quality against the ASME checklist for that feature type. Report specific gaps
(e.g. missing diameter symbol, blind hole without depth dimension, hidden lines
not per Y14.2 convention).

## Output

Return ONLY a valid JSON object (no markdown fences, no commentary):

{{
  "part_number": "{part_number}",
  "part_name": "{part_name}",
  "drawing_overview": "Brief description of what views are present and overall impression.",
  "features": [
    {{
      "name": "<feature name from profile>",
      "type": "<feature type>",
      "expected_count": 1,
      "status": "PRESENT | MISSING | PARTIAL | DISCREPANT",
      "found_callout": "<exact callout text found on drawing, or null>",
      "found_on_page": "<page number where feature was found, or null>",
      "observation": "<what you see or don't see for this feature>",
      "severity": "CRITICAL | MAJOR | MINOR | INFO",
      "representation_score": "<integer 0-100, or null if MISSING>",
      "representation_gaps": ["<list of specific ASME gaps, empty array if compliant or MISSING>"],
      "asme_compliance": "COMPLIANT | MINOR_GAPS | MAJOR_GAPS | NON_COMPLIANT | null (if MISSING)"
    }}
  ],
  "view_assessment": {{
    "views_present": ["list of drawing views identified"],
    "section_cuts": ["list of section cuts if any"],
    "missing_views": "any recommended views not present",
    "view_notes": "observations about view layout and completeness"
  }},
  "gap_summary": {{
    "total_features": 0,
    "present": 0,
    "missing": 0,
    "partial": 0,
    "discrepant": 0,
    "critical_issues": ["list of critical findings"],
    "overall_completeness": "percentage estimate"
  }}
}}
"""

REPORT_SYSTEM = (
    "You are a quality control report writer for a precision machining company. "
    "You write clear, professional inspection reports that help engineers quickly "
    "understand what is wrong with an engineering drawing and what needs to be fixed. "
    "Your reports are concise but thorough, with actionable recommendations."
)

REPORT_PROMPT = """\
Write a QC inspection report based on the following automated drawing analysis.

The analysis compared the engineering drawing for part **{part_number}** ({part_name})
against its spatial inspection profile generated from the 3D CAD model.

## Analysis Results

```json
{findings_json}
```

## Report Format

Write a report with these sections:

1. **SUMMARY** — One paragraph overview
2. **DRAWING COMPLETENESS** — Percentage of features properly represented
3. **CRITICAL ISSUES** — MISSING or DISCREPANT features (if any)
4. **PARTIAL CALLOUTS** — Features visible but missing dimensions or tolerances
5. **VIEW ASSESSMENT** — Are the right views and sections present?
6. **RECOMMENDATIONS** — Specific actions to fix the drawing (if needed)

Keep it concise and actionable. If the drawing is complete, say so clearly.
"""

VIEW_NAMES = ["front", "top", "right", "isometric"]


def _format_checklists_as_text(checklists: dict[str, dict]) -> str:
    """Format ASME checklists as readable text for injection into the prompt.

    Args:
        checklists: Dict of category name -> checklist dict.

    Returns:
        Formatted text string, or empty string if no checklists.
    """
    if not checklists:
        return ""

    lines: list[str] = []
    for category, cl in sorted(checklists.items()):
        ref = cl.get("asme_reference", "")
        lines.append(f"### {category} ({ref})")

        required = cl.get("required", [])
        if required:
            lines.append("**Required:**")
            for item in required:
                lines.append(f"  - {item}")

        recommended = cl.get("recommended", [])
        if recommended:
            lines.append("**Recommended:**")
            for item in recommended:
                lines.append(f"  - {item}")

        errors = cl.get("common_errors", [])
        if errors:
            lines.append("**Common Errors to Check:**")
            for item in errors:
                lines.append(f"  - {item}")

        lines.append("")  # blank line between categories

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Part number candidate extraction
# (Enhanced version — scans ALL filename segments, not just the first)
# ---------------------------------------------------------------------------

def _extract_pn_candidates(filename: str) -> list[str]:
    """Extract part number candidates from a drawing filename."""
    name = os.path.splitext(filename)[0]
    name = re.sub(r"\s*\(\d+\)$", "", name)
    name = re.sub(r"[\s_]*(Paint|PAINT)$", "", name, flags=re.IGNORECASE)
    segments = re.split(r"[\s_]+", name)

    candidates: list[str] = []
    for seg in segments:
        if len(seg) < 3 or seg.isalpha() or not re.search(r"\d", seg):
            continue
        candidates.append(seg)
        no_hyp = seg.replace("-", "")
        if no_hyp != seg:
            candidates.append(no_hyp)
        if seg[-1].isalpha() and len(seg) > 1:
            candidates.append(seg[:-1])
            candidates.append(seg[:-1].replace("-", ""))
        rev_match = re.match(r"^(.+)-(\d{1,2})$", seg)
        if rev_match:
            candidates.append(rev_match.group(1))
            candidates.append(rev_match.group(1).replace("-", ""))
        rev_alpha = re.match(r"^(.+?)[-_]?REV[-_]?[A-Z0-9]*$", seg, re.IGNORECASE)
        if rev_alpha:
            candidates.append(rev_alpha.group(1))
            candidates.append(rev_alpha.group(1).replace("-", ""))
        temp = no_hyp
        while len(temp) > 5:
            temp = temp[:-1]
            candidates.append(temp)

    seen: set[str] = set()
    return [c for c in candidates if c and c not in seen and not seen.add(c)]


# ---------------------------------------------------------------------------
# Main engine class
# ---------------------------------------------------------------------------

class SpatialInspector:
    """Spatial drawing inspection engine.

    Usage::

        inspector = SpatialInspector("400S_Sorted_Library")
        profiles = inspector.list_profiles()

        with open("drawing.png", "rb") as f:
            result = inspector.inspect(f.read(), "drawing.png")
    """

    def __init__(self, library_dir: str = "400S_Sorted_Library"):
        load_dotenv()

        self._anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        self._openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not self._anthropic_key:
            raise ValueError("Missing ANTHROPIC_API_KEY in environment / .env")
        if not self._openai_key:
            raise ValueError("Missing OPENAI_API_KEY in environment / .env")

        self._library = Path(library_dir)
        if not self._library.is_dir():
            raise FileNotFoundError(f"Library directory not found: {library_dir}")

        self._profile_index: dict[str, tuple[str, Path]] = {}
        self._profiles_cache: list[dict] | None = None
        self._build_profile_index()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_profiles(self) -> list[dict]:
        """Return all available inspection profiles."""
        if self._profiles_cache is not None:
            return self._profiles_cache

        profiles: list[dict] = []
        seen_paths: set[Path] = set()
        for _pn, (orig_pn, path) in self._profile_index.items():
            if path in seen_paths:
                continue
            seen_paths.add(path)

            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            has_views = (self._library / f"{orig_pn}_view_front.png").exists()
            profiles.append({
                "part_number": data.get("part_number", orig_pn),
                "part_name": data.get("part_name", ""),
                "feature_count": len(data.get("features", [])),
                "has_views": has_views,
            })

        profiles.sort(key=lambda p: p["part_number"])
        self._profiles_cache = profiles
        return profiles

    def detect_part_number(self, filename: str) -> dict:
        """Match a filename to an inspection profile.

        Returns dict with ``part_number``, ``match_type``, ``candidate`` keys.
        ``part_number`` is None if no match found.
        """
        pn, _path, candidate, match_type = self._match_to_profile(filename)
        return {
            "part_number": pn,
            "match_type": match_type,
            "candidate": candidate,
        }

    def get_reference_views(self, part_number: str) -> dict[str, str]:
        """Return base64-encoded CAD reference view images for a part.

        Args:
            part_number: The part number to look up views for.

        Returns:
            Dict mapping view name to base64 JPEG string.
            Example: ``{"front": "base64...", "top": "base64...", ...}``
            Empty dict if no views found.
        """
        views = self._load_reference_views(part_number)
        return {vn: self._encode_image(img) for vn, img in views.items()}

    def inspect(
        self,
        drawing_bytes: bytes,
        filename: str,
        part_number: str = "auto",
        send_reference_views: bool = True,
        vision_model: str = "claude-sonnet-4-20250514",
        report_model: str = "gpt-4o-mini",
    ) -> dict:
        """Run the full spatial inspection pipeline.

        Args:
            drawing_bytes: Raw file content (PNG, JPEG, or PDF).
            filename: Original filename (used for auto-detection and format).
            part_number: ``"auto"`` to detect from filename, or an explicit PN.
            send_reference_views: Include CAD model views in the API call.
            vision_model: Claude model for drawing analysis.
            report_model: GPT model for report generation.

        Returns:
            Dict with findings, report, gap_summary, features list, and metadata.

        Raises:
            FileNotFoundError: If no matching profile is found.
            ValueError: If Claude returns unparseable JSON.
        """
        start = time.time()

        # --- Resolve part number ---
        if part_number.lower() == "auto":
            matched = self._match_to_profile(filename)
            if matched[0] is None:
                candidates = _extract_pn_candidates(filename)
                raise FileNotFoundError(
                    f"No profile matched for '{filename}'. "
                    f"Candidates tried: {candidates[:10]}"
                )
            part_number = matched[0]
            profile_path = matched[1]
        else:
            profile_path = self._resolve_profile_path(part_number)

        with open(profile_path, "r", encoding="utf-8") as f:
            profile = json.load(f)

        part_name = profile.get("part_name", "Unknown")

        # --- Load & encode drawing pages ---
        drawing_pages = self._load_drawing_pages(drawing_bytes, filename)
        drawing_b64 = [self._encode_image(pg) for pg in drawing_pages]

        # --- Load & encode reference views ---
        ref_b64: dict[str, str] = {}
        if send_reference_views:
            ref_views = self._load_reference_views(part_number)
            ref_b64 = {vn: self._encode_image(img) for vn, img in ref_views.items()}

        # --- Load ASME checklists ---
        asme_text = ""
        try:
            from .checklist_loader import load_checklists_for_profile
            checklists = load_checklists_for_profile(profile)
            if checklists:
                asme_text = _format_checklists_as_text(checklists)
        except Exception as exc:
            logger.warning("Failed to load ASME checklists: %s (continuing without)", exc)

        # --- Claude Vision ---
        findings, claude_in, claude_out = self._call_claude_vision(
            drawing_b64, ref_b64, profile, part_number, part_name, vision_model,
            asme_text=asme_text,
        )

        # --- GPT Report ---
        report_text, gpt_tokens = self._call_gpt_report(
            findings, part_number, part_name, report_model
        )

        elapsed = time.time() - start

        gap = findings.get("gap_summary", {})

        # --- Compute representation summary ---
        rep_summary = self._compute_representation_summary(
            findings.get("features", [])
        )

        return {
            "part_number": part_number,
            "part_name": part_name,
            "findings": findings,
            "report_markdown": report_text,
            "gap_summary": {
                "total_features": gap.get("total_features", 0),
                "present": gap.get("present", 0),
                "missing": gap.get("missing", 0),
                "partial": gap.get("partial", 0),
                "discrepant": gap.get("discrepant", 0),
                "completeness": gap.get("overall_completeness", "?"),
                "critical_issues": gap.get("critical_issues", []),
            },
            "features": findings.get("features", []),
            "view_assessment": findings.get("view_assessment", {}),
            "representation_summary": rep_summary,
            "profile_used": profile_path.name,
            "reference_views_sent": list(ref_b64.keys()),
            "drawing_pages": len(drawing_pages),
            "tokens": {
                "claude_input": claude_in,
                "claude_output": claude_out,
                "gpt_total": gpt_tokens,
            },
            "elapsed_seconds": round(elapsed, 1),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_representation_summary(features: list[dict]) -> Optional[dict]:
        """Compute aggregate representation/ASME compliance summary.

        Returns None if no features have representation data.
        """
        scores = []
        compliance_counts = {
            "compliant": 0,
            "minor_gaps": 0,
            "major_gaps": 0,
            "non_compliant": 0,
        }
        all_gaps: list[str] = []

        for f in features:
            score = f.get("representation_score")
            compliance = f.get("asme_compliance")

            if score is not None:
                scores.append(score)

            if compliance is not None:
                key = compliance.lower()
                if key in compliance_counts:
                    compliance_counts[key] += 1

            gaps = f.get("representation_gaps", [])
            if gaps:
                all_gaps.extend(gaps)

        total_evaluated = sum(compliance_counts.values())

        # If no features have representation data, return None
        if total_evaluated == 0 and not scores:
            return None

        overall_score = round(sum(scores) / len(scores), 1) if scores else None

        # Deduplicate and pick the most important gaps (limit to top 10)
        seen_gaps: set[str] = set()
        critical_gaps: list[str] = []
        for g in all_gaps:
            g_lower = g.lower()
            if g_lower not in seen_gaps:
                seen_gaps.add(g_lower)
                critical_gaps.append(g)
        critical_gaps = critical_gaps[:10]

        return {
            "overall_score": overall_score,
            "total_evaluated": total_evaluated,
            "compliant": compliance_counts["compliant"],
            "minor_gaps": compliance_counts["minor_gaps"],
            "major_gaps": compliance_counts["major_gaps"],
            "non_compliant": compliance_counts["non_compliant"],
            "critical_gaps": critical_gaps,
        }

    def _build_profile_index(self) -> None:
        for p in self._library.glob("*_inspection_profile.json"):
            pn = p.name.replace("_inspection_profile.json", "")
            self._profile_index[pn] = (pn, p)
            norm = re.sub(r"[-_\s]", "", pn).lower()
            if norm not in self._profile_index:
                self._profile_index[norm] = (pn, p)

    def _match_to_profile(
        self, filename: str
    ) -> tuple[Optional[str], Optional[Path], Optional[str], Optional[str]]:
        candidates = _extract_pn_candidates(filename)
        for candidate in candidates:
            if candidate in self._profile_index:
                pn, path = self._profile_index[candidate]
                return pn, path, candidate, "exact"
            norm = re.sub(r"[-_\s]", "", candidate).lower()
            if norm in self._profile_index:
                pn, path = self._profile_index[norm]
                return pn, path, candidate, "normalized"
        return None, None, None, None

    def _resolve_profile_path(self, part_number: str) -> Path:
        path = self._library / f"{part_number}_inspection_profile.json"
        if path.exists():
            return path
        # Try normalized lookup
        norm = re.sub(r"[-_\s]", "", part_number).lower()
        if norm in self._profile_index:
            return self._profile_index[norm][1]
        raise FileNotFoundError(f"No inspection profile found for part {part_number}")

    def _load_drawing_pages(
        self, drawing_bytes: bytes, filename: str
    ) -> list[Image.Image]:
        ext = os.path.splitext(filename)[1].lower()
        if ext == ".pdf":
            import fitz

            doc = fitz.open(stream=drawing_bytes, filetype="pdf")
            pages = []
            for page in doc:
                pix = page.get_pixmap(dpi=200)
                pages.append(
                    Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                )
            doc.close()
            return pages

        img = Image.open(io.BytesIO(drawing_bytes)).convert("RGB")
        return [img]

    def _load_reference_views(self, part_number: str) -> dict[str, Image.Image]:
        views: dict[str, Image.Image] = {}
        for vn in VIEW_NAMES:
            vp = self._library / f"{part_number}_view_{vn}.png"
            if vp.exists():
                views[vn] = Image.open(vp).convert("RGB")
        return views

    @staticmethod
    def _encode_image(img: Image.Image, max_dim: int = 1568) -> str:
        w, h = img.size
        if max(w, h) > max_dim:
            scale = max_dim / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=85)
        return base64.standard_b64encode(buf.getvalue()).decode("utf-8")

    def _call_claude_vision(
        self,
        drawing_b64: list[str],
        ref_b64: dict[str, str],
        profile: dict,
        part_number: str,
        part_name: str,
        model: str,
        asme_text: str = "",
    ) -> tuple[dict, int, int]:
        """Send images + prompt to Claude, return parsed findings."""
        ref_section = ""
        ref_instruction = ""
        if ref_b64:
            ref_section = (
                "\n## 3D CAD Reference Views\n\n"
                "Above you can see rendered views of the 3D CAD model "
                "(front, top, right, isometric). Use these as visual reference "
                "to understand the part geometry and locate features. "
                "Compare these views against the engineering drawing sheets "
                "that follow.\n"
            )
            ref_instruction = (
                "Use the 3D reference views above to help locate and "
                "identify features on the drawing. "
            )

        # Format ASME section for the prompt template
        asme_section = ""
        if asme_text:
            asme_section = (
                "The ASME REPRESENTATION STANDARDS section below lists the "
                "required drawing conventions for the feature types in this part. "
            )

        profile_text = json.dumps(profile, indent=2)
        prompt = INSPECTION_PROMPT.format(
            ref_section=ref_section,
            ref_instruction=ref_instruction,
            asme_section=asme_section,
            part_number=part_number,
            part_name=part_name,
            profile_json=profile_text,
        )

        # Build content: ref views → drawing pages → text prompt
        content: list[dict] = []

        if ref_b64:
            content.append(
                {"type": "text", "text": "=== 3D CAD MODEL REFERENCE VIEWS ==="}
            )
            for vn in VIEW_NAMES:
                if vn in ref_b64:
                    content.append(
                        {"type": "text", "text": f"[CAD {vn.upper()} VIEW]"}
                    )
                    content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": ref_b64[vn],
                        },
                    })

        content.append(
            {"type": "text", "text": "=== ENGINEERING DRAWING TO INSPECT ==="}
        )
        num_pages = len(drawing_b64)
        for i, b64 in enumerate(drawing_b64, 1):
            if num_pages > 1:
                content.append(
                    {"type": "text", "text": f"[DRAWING PAGE {i} of {num_pages}]"}
                )
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": b64,
                },
            })

        # Inject ASME checklists as text (lightweight, ~200-300 tokens each)
        if asme_text:
            content.append(
                {"type": "text", "text": "=== ASME REPRESENTATION STANDARDS ===\n\n" + asme_text}
            )

        content.append({"type": "text", "text": prompt})

        client = anthropic.Anthropic(api_key=self._anthropic_key)
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=INSPECTION_SYSTEM,
            messages=[{"role": "user", "content": content}],
        )

        raw = ""
        for block in response.content:
            if block.type == "text":
                raw += block.text

        tokens_in = response.usage.input_tokens
        tokens_out = response.usage.output_tokens

        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        findings = json.loads(text)

        # Post-process: ensure representation fields have fallback defaults
        for feature in findings.get("features", []):
            # Default representation_score to None if not present
            if "representation_score" not in feature:
                feature["representation_score"] = None
            # Default representation_gaps to empty array if not present
            if "representation_gaps" not in feature:
                feature["representation_gaps"] = []
            # Default asme_compliance to None if not present
            if "asme_compliance" not in feature:
                feature["asme_compliance"] = None
            # Force null for MISSING features (can't evaluate representation)
            if feature.get("status") == "MISSING":
                feature["asme_compliance"] = None
                feature["representation_score"] = None
                feature["representation_gaps"] = []

        return findings, tokens_in, tokens_out

    def _call_gpt_report(
        self,
        findings: dict,
        part_number: str,
        part_name: str,
        model: str,
    ) -> tuple[str, int]:
        """Generate QC report via GPT."""
        prompt = REPORT_PROMPT.format(
            part_number=part_number,
            part_name=part_name,
            findings_json=json.dumps(findings, indent=2),
        )

        client = OpenAI(api_key=self._openai_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": REPORT_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2000,
            temperature=0.3,
        )

        report_text = response.choices[0].message.content
        total_tokens = response.usage.total_tokens if response.usage else 0
        return report_text, total_tokens
