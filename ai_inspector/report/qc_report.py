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
