"""
QC Report Generator

Uses GPT-4o-mini to generate comprehensive QC reports from inspection data.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional


def generate_qc_report(
    diff_result: Dict,
    evidence: Dict,
    sw_data: Optional[Dict],
    drawing_quality: Dict,
    bom_data: Dict,
    mfg_notes: Dict,
    classification_info: Optional[Dict] = None,
    assembly_context: Optional[Dict] = None,
    openai_client=None,
    api_key: Optional[str] = None,
) -> str:
    """
    Generate a comprehensive QC inspection report using GPT-4o-mini.

    Args:
        diff_result: Comparison results (from comparison.matcher)
        evidence: Merged evidence from OCR + Qwen
        sw_data: SolidWorks part data (can be None)
        drawing_quality: Quality audit results from Qwen
        bom_data: BOM extraction results from Qwen
        mfg_notes: Manufacturing notes from Qwen
        classification_info: Drawing classification details
        assembly_context: Assembly hierarchy and mate data
        openai_client: Pre-initialized OpenAI client (optional)
        api_key: OpenAI API key (used if client not provided)

    Returns:
        Markdown-formatted QC report string
    """
    from openai import OpenAI

    # Initialize client
    if openai_client is None:
        if api_key is None:
            raise ValueError("Either openai_client or api_key must be provided")
        client = OpenAI(api_key=api_key)
    else:
        client = openai_client

    # Determine if SW comparison is available
    has_sw_comparison = sw_data is not None and diff_result.get('summary', {}).get('totalRequirements', 0) > 0

    # Build the prompt
    prompt = _build_report_prompt(
        diff_result=diff_result,
        evidence=evidence,
        sw_data=sw_data,
        has_sw_comparison=has_sw_comparison,
        drawing_quality=drawing_quality,
        bom_data=bom_data,
        mfg_notes=mfg_notes,
        classification_info=classification_info or {},
        assembly_context=assembly_context,
    )

    # Generate report
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "You are a senior QC engineer who writes clear, comprehensive inspection reports. You assess feature accuracy, drawing quality, and manufacturing specifications."
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        max_tokens=2500
    )

    return response.choices[0].message.content


def _build_report_prompt(
    diff_result: Dict,
    evidence: Dict,
    sw_data: Optional[Dict],
    has_sw_comparison: bool,
    drawing_quality: Dict,
    bom_data: Dict,
    mfg_notes: Dict,
    classification_info: Dict,
    assembly_context: Optional[Dict],
) -> str:
    """Build the full prompt for GPT-4o-mini."""

    # Extract data
    part_number = diff_result.get('partNumber', 'Unknown')
    summary = diff_result.get('summary', {})
    details = diff_result.get('details', {})
    drawing_info = evidence.get('drawingInfo', {})

    # Part info
    if sw_data:
        identity = sw_data.get('identity', {})
        part_desc = identity.get('description') or drawing_info.get('partDescription', '')
        material = identity.get('material') or drawing_info.get('material', '')
    else:
        part_desc = drawing_info.get('partDescription', 'Unknown')
        material = drawing_info.get('material', 'Not specified')

    # Format items
    found_items = _format_found_items(details.get('found', []))
    missing_items = _format_missing_items(details.get('missing', []))
    extra_items = _format_extra_items(details.get('extra', []))
    drawing_notes = evidence.get('drawingInfo', {}).get('notes', [])

    # Build comparison section
    comparison_section = _build_comparison_section(
        has_sw_comparison, part_number, part_desc, material,
        summary, found_items, missing_items, extra_items, drawing_notes
    )

    # Build assembly context section
    assembly_context_section = _build_assembly_context_section(assembly_context)

    # Build quality audit section
    title_block_items, quality_items, overall_assessment = _build_quality_section(drawing_quality)

    # Build BOM section
    bom_section = _build_bom_section(bom_data)

    # Build manufacturing section
    mfg_items, general_notes, special_processes, certifications, insp = _build_mfg_section(mfg_notes)

    # Classification info
    drawing_type = classification_info.get('overall_type', 'UNKNOWN')
    total_pages = classification_info.get('total_pages', 1)
    pages_ocr = classification_info.get('pages_with_ocr', 0)
    pages_bom = classification_info.get('pages_with_bom', 0)
    ocr_was_skipped = classification_info.get('ocr_skipped', False)

    # Build final prompt
    prompt = f"""You are a Quality Control engineer reviewing an engineering drawing inspection report. You have comprehensive data from AI vision analysis including:
1. CAD-to-drawing feature comparison (if available)
2. Drawing quality/completeness audit
3. Bill of Materials extraction (if applicable)
4. Manufacturing notes and special requirements

Your job is to write a COMPREHENSIVE QC report covering ALL aspects of the drawing.

---

## DRAWING CLASSIFICATION

**Drawing Type:** {drawing_type}
**Total Pages:** {total_pages}
**Processing Summary:**
- Pages analyzed with OCR: {pages_ocr}
- Pages with BOM: {pages_bom}
- OCR was skipped: {"Yes (assembly/BOM drawing)" if ocr_was_skipped else "No"}

{"**NOTE:** This is an ASSEMBLY/BOM drawing. Focus on BOM completeness and assembly instructions rather than individual part dimensions." if drawing_type in ['ASSEMBLY_BOM', 'MULTI_PAGE_ASSEMBLY'] else ""}
{"**NOTE:** This is a PART DETAIL drawing. Focus on dimensional accuracy, tolerances, and feature verification." if drawing_type == 'PART_DETAIL' else ""}
{"**NOTE:** This is a MIXED drawing with both assembly views and detail drawings. Report on both aspects." if drawing_type == 'MIXED' else ""}

---

{comparison_section}

{assembly_context_section}

---

## PART 2: DRAWING QUALITY AUDIT

### Title Block Completeness:
{chr(10).join(title_block_items)}

### Drawing Best Practices:
{chr(10).join(quality_items)}

### Overall Quality Score: {overall_assessment.get('completenessScore', 'N/A')}/10

### Issues Identified:
- Major: {', '.join(overall_assessment.get('majorIssues', [])) if overall_assessment.get('majorIssues') else 'None'}
- Minor: {', '.join(overall_assessment.get('minorIssues', [])) if overall_assessment.get('minorIssues') else 'None'}

---

## PART 3: BILL OF MATERIALS
{bom_section}

---

## PART 4: MANUFACTURING SPECIFICATIONS

### Manufacturing Requirements:
{chr(10).join(mfg_items)}

### Special Processes:
{chr(10).join(f"- {sp.get('process', 'Unknown')}: {sp.get('specification', 'N/A')}" for sp in special_processes) if special_processes else "None specified"}

### General Manufacturing Notes:
{chr(10).join(f"- {note}" for note in general_notes[:8]) if general_notes else "None"}

### Inspection Requirements:
{chr(10).join(f"- {req}" for req in insp.get('requirements', [])) if insp.get('specified') else "None specified"}

### Certifications Required:
{chr(10).join(f"- {cert}" for cert in certifications) if certifications else "None specified"}

---

## YOUR TASK

Write a professional, comprehensive QC inspection report in markdown format.

{"Include:" if has_sw_comparison else "NOTE: No CAD comparison data available. Focus on drawing quality and visual analysis. Include:"}

1. **Executive Summary** - Overall {"PASS/FAIL/REVIEW NEEDED" if has_sw_comparison else "REVIEW NEEDED (no CAD baseline)"} verdict with key findings
2. **{"Feature Verification Results" if has_sw_comparison else "Drawing Analysis Results"}** - {"CAD vs drawing comparison summary" if has_sw_comparison else "Features identified from visual analysis (no CAD baseline to compare)"}
3. **Drawing Quality Assessment** - Title block, views, dimensions, tolerances
4. **Bill of Materials Review** - If present, comment on completeness
5. **Assembly Context** - If available, explain how this part fits in its assembly and why mate-derived requirements matter
6. **Manufacturing Specifications** - Heat treat, finish, coatings, special processes
7. **Issues & Action Items** - Specific problems and what needs to be fixed
8. **Confidence Level** - HIGH/MEDIUM/LOW with justification{"" if has_sw_comparison else " (note: confidence is inherently lower without CAD comparison)"}

{"" if has_sw_comparison else "**IMPORTANT:** Since no CAD data is available, you cannot verify if the drawing matches the 3D model. Focus your report on drawing completeness, quality, and readability rather than feature accuracy."}

Be specific and actionable. This report goes to manufacturing, engineering, and QC teams.
"""
    return prompt


def _format_found_items(found: List[Dict]) -> List[str]:
    """Format found items for the prompt."""
    items = []
    for item in found:
        req = item.get('requirement', {})
        ev = item.get('evidence', {})
        if req.get('type') == 'TappedHole':
            thread = req.get('thread', {})
            items.append(f"- {thread.get('callout', 'Thread')} (count: {req.get('count', 1)}) - Drawing shows: {ev.get('raw', 'N/A')}")
        elif req.get('type') == 'Hole':
            items.append(f"- ø{req.get('diameterInches', 0):.4f}\" {'THRU' if req.get('isThrough') else 'BLIND'} (count: {req.get('count', 1)}) - Drawing shows: {ev.get('raw', 'N/A')}")
        else:
            items.append(f"- {req.get('type')}: {req.get('canonical', 'N/A')} - Drawing shows: {ev.get('raw', 'N/A')}")
    return items


def _format_missing_items(missing: List[Dict]) -> List[str]:
    """Format missing items for the prompt."""
    items = []
    for item in missing:
        req = item.get('requirement', {})
        if req.get('type') == 'TappedHole':
            thread = req.get('thread', {})
            items.append(f"- {thread.get('callout', 'Thread')} (count: {req.get('count', 1)})")
        elif req.get('type') == 'Hole':
            items.append(f"- ø{req.get('diameterInches', 0):.4f}\" {'THRU' if req.get('isThrough') else 'BLIND'} (count: {req.get('count', 1)})")
        else:
            items.append(f"- {req.get('type')}: {req.get('canonical', 'N/A')}")
    return items


def _format_extra_items(extra: List[Dict]) -> List[str]:
    """Format extra items for the prompt."""
    items = []
    for item in extra:
        ev = item.get('evidence', {})
        items.append(f"- {ev.get('calloutType', 'Unknown')}: {ev.get('raw', 'N/A')}")
    return items


def _build_comparison_section(
    has_sw_comparison: bool,
    part_number: str,
    part_desc: str,
    material: str,
    summary: Dict,
    found_items: List[str],
    missing_items: List[str],
    extra_items: List[str],
    drawing_notes: List[str],
) -> str:
    """Build the comparison section of the prompt."""
    notes_text = '\n'.join(f"- {note}" for note in drawing_notes[:5]) if drawing_notes else "None noted"

    if has_sw_comparison:
        return f"""## PART 1: CAD FEATURE COMPARISON

**Part Number:** {part_number}
**Description:** {part_desc}
**Material (from drawing):** {material}

**CAD Model Requirements:** {summary.get('totalRequirements', 0)} features
**Drawing Match Rate:** {summary.get('matchRate', 'N/A')}

### Verified Features (Found in Drawing):
{chr(10).join(found_items) if found_items else "None"}

### Missing from Drawing (Required by CAD):
{chr(10).join(missing_items) if missing_items else "None"}

### Extra in Drawing (Not in CAD):
{chr(10).join(extra_items) if extra_items else "None"}

### Drawing Notes Observed:
{notes_text}
"""
    else:
        return f"""## PART 1: DRAWING IDENTIFICATION (No CAD Comparison Available)

**Part Number:** {part_number}
**Description:** {part_desc}
**Material (from drawing):** {material}

> **NOTE:** No SolidWorks CAD data was found for part number "{part_number}".
> CAD feature comparison is NOT available for this drawing.
> This report is based on **visual analysis only** (Qwen + OCR).

**Possible reasons:**
- Part not yet added to sw_json_library
- Part number mismatch between drawing and CAD filename
- This is an assembly drawing (assemblies may not have individual CAD JSON)
- New part without CAD model

**Recommendation:** Add this part's SolidWorks JSON to the library for future comparisons.

### Drawing Notes Observed:
{notes_text}
"""


def _build_assembly_context_section(assembly_context: Optional[Dict]) -> str:
    """Build the assembly context section."""
    if not assembly_context:
        return ""

    hierarchy = assembly_context.get('hierarchy', {})
    mating = assembly_context.get('mating', {})
    siblings = hierarchy.get('siblings', [])
    mates = mating.get('mates_with', [])
    mate_reqs = mating.get('requirements_from_mates', [])

    sibling_lines = []
    for s in siblings[:6]:
        sibling_lines.append(f"  - {s.get('pn', s.get('name', '?'))} ({s.get('desc', s.get('description', ''))})")

    mate_lines = []
    for m in mates[:6]:
        tinfo = f" [{m['thread']}x{m.get('pitch', '')}]" if m.get('thread') else ''
        mate_lines.append(f"  - {m.get('mate_type', 'MATE')}: {m.get('part', '?')} ({m.get('description', '')}){tinfo}")

    req_lines = [f"  - {r}" for r in mate_reqs[:8]]

    return f"""## ASSEMBLY CONTEXT

**Parent Assembly:** {hierarchy.get('parent_assembly', 'Unknown')}
**Hierarchy:** {hierarchy.get('hierarchy_path', 'N/A')}

### Sibling Parts (in same subassembly):
{chr(10).join(sibling_lines) if sibling_lines else "No siblings found"}

### Mate Relationships:
{chr(10).join(mate_lines) if mate_lines else "No mates found"}

### Mate-Derived Requirements:
{chr(10).join(req_lines) if req_lines else "None"}

---
"""


def _build_quality_section(drawing_quality: Dict) -> tuple:
    """Build quality audit section."""
    tb = drawing_quality.get('titleBlockCompleteness', {})
    dq = drawing_quality.get('drawingQuality', {})
    oa = drawing_quality.get('overallAssessment', {})

    title_block_items = [
        f"- Part Number: {'✓ Present' if tb.get('hasPartNumber') else '✗ MISSING'} - {tb.get('partNumberValue', 'N/A')}",
        f"- Description: {'✓ Present' if tb.get('hasDescription') else '✗ MISSING'} - {(tb.get('descriptionValue', 'N/A') or 'N/A')[:50]}",
        f"- Material: {'✓ Present' if tb.get('hasMaterial') else '✗ MISSING'} - {tb.get('materialValue', 'N/A')}",
        f"- Revision: {'✓ Present' if tb.get('hasRevision') else '✗ MISSING'} - {tb.get('revisionValue', 'N/A')}",
        f"- Scale: {'✓ Present' if tb.get('hasScale') else '✗ MISSING'} - {tb.get('scaleValue', 'N/A')}",
        f"- Date: {'✓ Present' if tb.get('hasDate') else '✗ MISSING'} - {tb.get('dateValue', 'N/A')}",
        f"- Drawn By: {'✓ Present' if tb.get('hasDrawnBy') else '✗ MISSING'} - {tb.get('drawnByValue', 'N/A')}",
        f"- Approved By: {'✓ Present' if tb.get('hasApprovedBy') else '✗ MISSING'} - {tb.get('approvedByValue', 'N/A')}",
    ]

    quality_items = [
        f"- Views Labeled: {'✓ Yes' if dq.get('viewsLabeled') else '✗ No'} - {dq.get('viewsLabeledComment', '')}",
        f"- Dimensions Readable: {'✓ Yes' if dq.get('dimensionsReadable') else '✗ No'} - {dq.get('dimensionsComment', '')}",
        f"- Tolerances Present: {'✓ Yes' if dq.get('tolerancesPresent') else '✗ No'} - {dq.get('tolerancesComment', '')}",
        f"- Surface Finish Specified: {'✓ Yes' if dq.get('surfaceFinishSpecified') else '✗ No'} - {dq.get('surfaceFinishComment', '')}",
        f"- General Tolerance Block: {'✓ Yes' if dq.get('generalToleranceBlock') else '✗ No'} - {dq.get('generalToleranceComment', '')}",
        f"- Third Angle Projection Symbol: {'✓ Yes' if dq.get('thirdAngleProjection') else '✗ No'}",
        f"- Units Specified: {'✓ Yes' if dq.get('unitsSpecified') else '✗ No'} - {dq.get('unitsValue', 'N/A')}",
    ]

    return title_block_items, quality_items, oa


def _build_bom_section(bom_data: Dict) -> str:
    """Build BOM section."""
    if bom_data.get('hasBOM'):
        bom_items_text = []
        for item in bom_data.get('bomItems', [])[:15]:
            bom_items_text.append(f"  - Item {item.get('itemNumber', '?')}: {item.get('partNumber', 'N/A')} - {item.get('description', 'N/A')} (Qty: {item.get('quantity', 1)})")
        return f"""
### Bill of Materials (BOM):
**BOM Present:** Yes (Location: {bom_data.get('bomLocation', 'N/A')})
**Total Items:** {bom_data.get('totalItems', len(bom_data.get('bomItems', [])))}

{chr(10).join(bom_items_text) if bom_items_text else "No items extracted"}

**BOM Notes:** {bom_data.get('bomNotes', 'None')}
"""
    else:
        return """
### Bill of Materials (BOM):
**BOM Present:** No - This appears to be a part/detail drawing without a parts list.
"""


def _build_mfg_section(mfg_notes: Dict) -> tuple:
    """Build manufacturing section."""
    ht = mfg_notes.get('heatTreatment', {})
    sf = mfg_notes.get('surfaceFinish', {})
    pc = mfg_notes.get('platingOrCoating', {})
    wn = mfg_notes.get('weldingNotes', {})
    insp = mfg_notes.get('inspectionRequirements', {})

    mfg_items = [
        f"- Heat Treatment: {'✓ ' + ht.get('specification', 'Specified') if ht.get('specified') else '✗ Not specified'}",
        f"- Surface Finish: {'✓ ' + sf.get('generalFinish', 'Specified') if sf.get('specified') else '✗ Not specified'}",
        f"- Plating/Coating: {'✓ ' + pc.get('type', 'Specified') if pc.get('specified') else '✗ Not specified'}",
        f"- Welding: {'✓ ' + wn.get('weldSpec', 'Specified') if wn.get('specified') else '✗ Not specified'}",
        f"- Inspection Requirements: {'✓ Specified' if insp.get('specified') else '✗ Not specified'}",
    ]

    general_notes = mfg_notes.get('generalNotes', [])
    special_processes = mfg_notes.get('specialProcesses', [])
    certifications = mfg_notes.get('certifications', [])

    return mfg_items, general_notes, special_processes, certifications, insp


def save_qc_report(
    report_content: str,
    part_number: str,
    output_path: str,
    drawing_path: Optional[str] = None,
) -> str:
    """
    Save a QC report to a markdown file.

    Args:
        report_content: The report content from generate_qc_report
        part_number: Part number for header
        output_path: Path to save the report
        drawing_path: Optional path to the source drawing

    Returns:
        Path to saved report
    """
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"# QC Inspection Report: {part_number}\n\n")
        f.write(f"**Generated:** {datetime.now().isoformat()}\n\n")
        if drawing_path:
            f.write(f"**Drawing:** {drawing_path}\n\n")
        f.write("---\n\n")
        f.write(report_content)

    return output_path
