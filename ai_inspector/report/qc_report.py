"""QC Report generation using GPT-4o-mini.

Generates human-readable inspection reports from comparison results.
The report summarizes what was found, what matched, and what needs attention.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, List
import json

from ..config import default_config
from ..comparison.diff_result import DiffResult
from ..classifier.drawing_classifier import DrawingType


# Report prompt template
REPORT_PROMPT_TEMPLATE = '''You are a Quality Control engineer reviewing an engineering drawing inspection.

Generate a concise QC report based on the inspection data below.

## Drawing Information
- Part Number: {part_number}
- Drawing Type: {drawing_type}
- Has SolidWorks CAD Data: {has_sw_data}

## Inspection Results
- Match Rate: {match_rate:.1%}
- Features Matched: {matched_count}
- Features Missing from Drawing: {missing_count}
- Extra Features on Drawing: {extra_count}
- Tolerance Failures: {tolerance_fail_count}

## Detailed Findings
{detailed_findings}

## Drawing Quality Notes
{quality_notes}

---

Generate a QC report with these sections:
1. **Summary** (2-3 sentences: PASS/FAIL status, key findings)
2. **Critical Issues** (list any missing features or tolerance failures that need correction)
3. **Verification Notes** (features that matched correctly)
4. **Recommendations** (if any issues found)

Keep the report concise and actionable. Use bullet points.
If match rate is 100% and no issues, state "DRAWING APPROVED" clearly.
If there are missing features, state "DRAWING REQUIRES REVISION" and list what's missing.
'''


@dataclass
class QCReport:
    """
    Generated QC inspection report.

    Attributes:
        part_number: Part number inspected
        drawing_type: Type of drawing (MACHINED_PART, etc.)
        status: PASS or FAIL
        match_rate: Feature match rate (0.0-1.0)
        generated_at: ISO timestamp
        report_text: Full report markdown text
        summary: Quick summary line
        critical_issues: List of issues requiring attention
        model_used: LLM model that generated the report
    """
    part_number: str = ""
    drawing_type: str = ""
    status: str = "UNKNOWN"
    match_rate: float = 0.0
    generated_at: str = ""
    report_text: str = ""
    summary: str = ""
    critical_issues: List[str] = field(default_factory=list)
    model_used: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "partNumber": self.part_number,
            "drawingType": self.drawing_type,
            "status": self.status,
            "matchRate": self.match_rate,
            "generatedAt": self.generated_at,
            "reportText": self.report_text,
            "summary": self.summary,
            "criticalIssues": self.critical_issues,
            "modelUsed": self.model_used,
        }

    def to_markdown(self) -> str:
        """Generate full markdown report."""
        header = f"""# QC Inspection Report

**Part Number:** {self.part_number}
**Drawing Type:** {self.drawing_type}
**Status:** {"✅ " if self.status == "PASS" else "❌ "}{self.status}
**Match Rate:** {self.match_rate:.1%}
**Generated:** {self.generated_at}
**Model:** {self.model_used}

---

"""
        return header + self.report_text


class QCReportGenerator:
    """
    Generate QC reports using GPT-4o-mini.

    Uses OpenAI API to generate human-readable inspection reports
    from DiffResult comparison data.

    Usage:
        generator = QCReportGenerator(api_key="sk-...")
        report = generator.generate(diff_result, drawing_type)

        print(report.status)  # "PASS" or "FAIL"
        print(report.to_markdown())

    Attributes:
        model_id: OpenAI model to use (default: gpt-4o-mini)
        max_tokens: Maximum tokens for response
        temperature: Sampling temperature
    """

    def __init__(
        self,
        api_key: str = None,
        model_id: str = None,
        max_tokens: int = None,
        temperature: float = None,
    ):
        """
        Initialize report generator.

        Args:
            api_key: OpenAI API key (or set OPENAI_API_KEY env var)
            model_id: Model to use (default from config)
            max_tokens: Max response tokens (default from config)
            temperature: Sampling temperature (default from config)
        """
        self.api_key = api_key
        self.model_id = model_id or default_config.report_model_id
        self.max_tokens = max_tokens or default_config.report_max_tokens
        self.temperature = temperature or default_config.report_temperature
        self._client = None

    def _get_client(self):
        """Lazy-load OpenAI client."""
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key)
        return self._client

    def generate(
        self,
        diff_result: DiffResult,
        drawing_type: DrawingType = None,
        quality_notes: str = "",
    ) -> QCReport:
        """
        Generate QC report from comparison results.

        Args:
            diff_result: Comparison result from compare_drawing()
            drawing_type: Drawing type classification
            quality_notes: Additional notes about drawing quality

        Returns:
            QCReport with generated content
        """
        # Build prompt
        prompt = self._build_prompt(diff_result, drawing_type, quality_notes)

        # Call GPT-4o-mini
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {"role": "system", "content": "You are a Quality Control engineer writing inspection reports."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            report_text = response.choices[0].message.content
        except Exception as e:
            report_text = f"Error generating report: {str(e)}\n\nRaw data:\n{json.dumps(diff_result.to_dict(), indent=2)}"

        # Determine status
        status = "PASS" if diff_result.passed else "FAIL"

        # Extract critical issues from diff
        critical_issues = []
        for entry in diff_result.entries:
            if entry.status in ["missing", "tolerance"]:
                critical_issues.append(f"{entry.category}: {entry.notes}")

        # Build summary
        if diff_result.passed:
            summary = f"PASS - {diff_result.match_rate:.0%} match rate, all features verified"
        else:
            summary = f"FAIL - {diff_result.missing_count} missing features, {diff_result.match_rate:.0%} match rate"

        return QCReport(
            part_number=diff_result.part_number,
            drawing_type=drawing_type.value if drawing_type else "UNKNOWN",
            status=status,
            match_rate=diff_result.match_rate,
            generated_at=datetime.now().isoformat() + "Z",
            report_text=report_text,
            summary=summary,
            critical_issues=critical_issues,
            model_used=self.model_id,
        )

    def _build_prompt(
        self,
        diff: DiffResult,
        drawing_type: DrawingType,
        quality_notes: str,
    ) -> str:
        """Build the prompt for GPT-4o-mini."""
        # Format detailed findings
        findings_lines = []
        for entry in diff.entries:
            status_icon = {
                "matched": "✓",
                "missing": "✗ MISSING",
                "extra": "? EXTRA",
                "tolerance": "⚠ TOLERANCE",
                "unverified": "○",
            }.get(entry.status, entry.status)

            line = f"- [{status_icon}] {entry.category}: {entry.drawing_value or entry.sw_value}"
            if entry.notes:
                line += f" ({entry.notes})"
            findings_lines.append(line)

        detailed_findings = "\n".join(findings_lines) if findings_lines else "No features to compare"

        return REPORT_PROMPT_TEMPLATE.format(
            part_number=diff.part_number,
            drawing_type=drawing_type.value if drawing_type else "UNKNOWN",
            has_sw_data="Yes" if diff.has_sw_data else "No",
            match_rate=diff.match_rate,
            matched_count=diff.matched_count,
            missing_count=diff.missing_count,
            extra_count=diff.extra_count,
            tolerance_fail_count=diff.summary.get("tolerance_fail", 0),
            detailed_findings=detailed_findings,
            quality_notes=quality_notes or "None provided",
        )


def generate_report(
    diff_result: DiffResult,
    drawing_type: DrawingType = None,
    api_key: str = None,
    quality_notes: str = "",
) -> QCReport:
    """
    Convenience function to generate a QC report.

    Args:
        diff_result: Comparison result from compare_drawing()
        drawing_type: Drawing type classification
        api_key: OpenAI API key (or uses OPENAI_API_KEY env var)
        quality_notes: Additional notes about drawing quality

    Returns:
        QCReport with generated content

    Example:
        diff = compare_drawing(evidence, sw_data)
        report = generate_report(diff, DrawingType.MACHINED_PART)
        print(report.to_markdown())
    """
    generator = QCReportGenerator(api_key=api_key)
    return generator.generate(diff_result, drawing_type, quality_notes)


def generate_from_pipeline(
    result,
    extracted_callouts: List[Dict[str, Any]] = None,
    validated_callouts: List[Dict[str, Any]] = None,
    sw_identity: Dict[str, Any] = None,
    api_key: str = None,
    model: str = "gpt-4o",
) -> QCReport:
    """
    Generate QC report from PipelineResult with full JSON context.

    Passes the complete inspection data as structured JSON to GPT-4o.
    This prevents hallucination by giving the model ALL facts upfront.

    Args:
        result: PipelineResult from VisionPipeline or YOLOPipeline
        extracted_callouts: Raw callouts from extraction (list of dicts)
        validated_callouts: Callouts after normalization/validation
        sw_identity: Part identity dict from SW JSON (partNumber, description, etc.)
        api_key: OpenAI API key (or uses OPENAI_API_KEY env var)
        model: OpenAI model to use (default: gpt-4o)

    Returns:
        QCReport with generated content
    """
    from collections import Counter

    # --- Serialize match results ---
    match_results_data = [r.to_dict() for r in result.match_results]

    # --- Group by severity ---
    CRITICAL_TYPES = {"TappedHole", "Hole", "CounterBore", "CounterSink"}
    critical_missing = []
    minor_missing = []
    matched_features = []
    tolerance_failures = []
    extra_features = []

    for r in result.match_results:
        rd = r.to_dict()
        status = r.status.value
        if status == "missing":
            ft = r.sw_feature.feature_type if r.sw_feature else "Unknown"
            if ft in CRITICAL_TYPES:
                critical_missing.append(rd)
            else:
                minor_missing.append(rd)
        elif status == "matched":
            matched_features.append(rd)
        elif status == "tolerance_fail":
            tolerance_failures.append(rd)
        elif status == "extra":
            extra_features.append(rd)

    # --- Feature breakdown ---
    type_status = Counter()
    for r in result.match_results:
        ft = ""
        if r.sw_feature:
            ft = r.sw_feature.feature_type
        elif r.drawing_callout:
            ft = r.drawing_callout.get("calloutType", "Unknown")
        type_status[(ft, r.status.value)] += 1

    feature_breakdown = {}
    for (ft, st), count in sorted(type_status.items()):
        feature_breakdown.setdefault(ft, {})[st] = count

    # --- Build full context ---
    inspection_context = {
        "partIdentity": sw_identity or {},
        "inspectionDate": datetime.now().isoformat(),
        "pipelineType": result.packet_summary.get("pipeline_type", "unknown"),
        "scores": result.scores,
        "expansionSummary": result.expansion_summary,
        "validationStats": result.validation_stats,
        "matchResults": match_results_data,
        "criticalMissing": critical_missing,
        "minorMissing": minor_missing,
        "matchedFeatures": matched_features,
        "toleranceFailures": tolerance_failures,
        "extraFeatures": extra_features,
        "featureBreakdown": feature_breakdown,
        "extractedCallouts": extracted_callouts or [],
        "validatedCallouts": validated_callouts or [],
        "pageUnderstanding": result.page_understanding or {},
        "matingContext": result.mating_context or {},
        "mateSpecs": result.mate_specs or {},
    }

    context_json = json.dumps(inspection_context, indent=2, ensure_ascii=False, default=str)

    # --- Prompt ---
    prompt = (
        "You are a senior QC inspector writing an actionable inspection report.\n\n"
        "Below is the COMPLETE inspection context as JSON. It contains ALL the data:\n"
        "- partIdentity: part number, description, material, revision\n"
        "- scores: match counts and rates\n"
        "- matchResults: every feature comparison (status, drawing value, SW value, delta)\n"
        "- criticalMissing: holes/tapped holes missing from drawing\n"
        "- minorMissing: fillets/chamfers missing (cosmetic)\n"
        "- matchedFeatures: features that passed verification\n"
        "- toleranceFailures: features outside tolerance\n"
        "- extraFeatures: callouts on drawing not found in CAD\n"
        "- extractedCallouts: raw callouts found on the drawing\n"
        "- matingContext/mateSpecs: assembly relationships\n\n"
        "Write a concise QC report (20-30 lines). Structure:\n\n"
        "1. **VERDICT**: PASS or FAIL\n"
        "   - PASS if: no critical missing AND no tolerance failures\n"
        "   - FAIL if: any critical missing OR any tolerance failures\n\n"
        "2. **PART**: part number, description (from partIdentity)\n\n"
        "3. **CRITICAL**: Missing holes/tapped holes. If none, say so.\n\n"
        "4. **MINOR**: Missing fillets/chamfers. Summarize count, don't list each.\n\n"
        "5. **VERIFIED**: Matched features with delta values.\n\n"
        "6. **NEXT STEPS**: 2-3 concrete actions.\n\n"
        "RULES:\n"
        "- Use ONLY data from the JSON below. Do NOT invent values.\n"
        "- Quote exact values from the data (diameters, deltas, raw text).\n"
        "- If a field is missing or empty, say 'not available'.\n\n"
        "```json\n" + context_json + "\n```"
    )

    # --- Call GPT ---
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a QC inspector. Use ONLY the provided JSON data. Never fabricate data."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1500,
            temperature=0.15,
        )
        report_text = response.choices[0].message.content
        tokens_used = response.usage.total_tokens if response.usage else 0
    except Exception as e:
        report_text = f"Error generating report: {e}\n\nContext:\n{context_json}"
        tokens_used = 0

    # --- Determine status from data ---
    has_critical = len(critical_missing) > 0
    has_tolerance_fail = len(tolerance_failures) > 0
    status = "FAIL" if (has_critical or has_tolerance_fail) else "PASS"

    part_number = (sw_identity or {}).get("partNumber", "")
    match_rate = result.scores.get("instance_match_rate", 0.0)

    critical_issues = []
    for rd in critical_missing:
        critical_issues.append(f"{rd.get('swFeature', {}).get('calloutType', '?')}: {rd.get('notes', '')}")
    for rd in tolerance_failures:
        critical_issues.append(f"Tolerance: {rd.get('notes', '')}")

    return QCReport(
        part_number=part_number,
        drawing_type=(result.page_understanding or {}).get("drawingType", "UNKNOWN"),
        status=status,
        match_rate=match_rate,
        generated_at=datetime.now().isoformat() + "Z",
        report_text=report_text,
        summary=f"{status} - {match_rate:.0%} match rate, {len(critical_missing)} critical, {len(minor_missing)} minor",
        critical_issues=critical_issues,
        model_used=model,
    ), inspection_context


def generate_report_without_llm(
    diff_result: DiffResult,
    drawing_type: DrawingType = None,
) -> QCReport:
    """
    Generate a basic report without using LLM (for testing/fallback).

    Args:
        diff_result: Comparison result
        drawing_type: Drawing type classification

    Returns:
        QCReport with template-based content
    """
    status = "PASS" if diff_result.passed else "FAIL"

    # Build report text without LLM
    lines = [
        "## Summary",
        "",
    ]

    if diff_result.passed:
        lines.append(f"**DRAWING APPROVED** - All {diff_result.matched_count} features verified.")
        lines.append(f"Match rate: {diff_result.match_rate:.0%}")
    else:
        lines.append(f"**DRAWING REQUIRES REVISION** - {diff_result.missing_count} features missing.")
        lines.append(f"Match rate: {diff_result.match_rate:.0%}")

    lines.extend(["", "## Feature Summary", ""])
    lines.append(f"- Matched: {diff_result.matched_count}")
    lines.append(f"- Missing: {diff_result.missing_count}")
    lines.append(f"- Extra: {diff_result.extra_count}")
    lines.append(f"- Tolerance Issues: {diff_result.summary.get('tolerance_fail', 0)}")

    if diff_result.missing_count > 0:
        lines.extend(["", "## Missing Features", ""])
        for entry in diff_result.entries:
            if entry.status == "missing":
                lines.append(f"- {entry.category}: {entry.sw_value} - {entry.notes}")

    if diff_result.matched_count > 0:
        lines.extend(["", "## Verified Features", ""])
        for entry in diff_result.entries:
            if entry.status == "matched":
                lines.append(f"- {entry.category}: {entry.drawing_value}")

    report_text = "\n".join(lines)

    # Extract critical issues
    critical_issues = []
    for entry in diff_result.entries:
        if entry.status in ["missing", "tolerance"]:
            critical_issues.append(f"{entry.category}: {entry.notes}")

    summary = f"{status} - {diff_result.match_rate:.0%} match rate"

    return QCReport(
        part_number=diff_result.part_number,
        drawing_type=drawing_type.value if drawing_type else "UNKNOWN",
        status=status,
        match_rate=diff_result.match_rate,
        generated_at=datetime.now().isoformat() + "Z",
        report_text=report_text,
        summary=summary,
        critical_issues=critical_issues,
        model_used="template (no LLM)",
    )
