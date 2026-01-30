"""Quality audit prompt for Qwen VLM."""

QUALITY_AUDIT_PROMPT = '''Examine this engineering drawing for completeness and best practices. Return a JSON object with:

{
  "titleBlockCompleteness": {
    "hasPartNumber": true/false,
    "partNumberValue": "the part number if visible",
    "hasDescription": true/false,
    "descriptionValue": "the description if visible",
    "hasMaterial": true/false,
    "materialValue": "the material if visible",
    "hasRevision": true/false,
    "revisionValue": "the revision if visible",
    "hasScale": true/false,
    "scaleValue": "the scale if visible",
    "hasDate": true/false,
    "dateValue": "the date if visible",
    "hasDrawnBy": true/false,
    "drawnByValue": "name if visible",
    "hasApprovedBy": true/false,
    "approvedByValue": "name if visible"
  },
  "drawingQuality": {
    "viewsLabeled": true/false,
    "viewsLabeledComment": "are views clearly labeled (FRONT, TOP, etc)?",
    "dimensionsReadable": true/false,
    "dimensionsComment": "are dimensions clear and not overlapping?",
    "tolerancesPresent": true/false,
    "tolerancesComment": "are tolerances specified on critical dimensions?",
    "surfaceFinishSpecified": true/false,
    "surfaceFinishComment": "is surface finish callout present?",
    "generalToleranceBlock": true/false,
    "generalToleranceComment": "is there a general tolerance note/block?",
    "thirdAngleProjection": true/false,
    "projectionComment": "is projection symbol visible (third angle)?",
    "unitsSpecified": true/false,
    "unitsValue": "INCHES or MM if specified"
  },
  "overallAssessment": {
    "completenessScore": "1-10 rating",
    "majorIssues": ["list any major issues found"],
    "minorIssues": ["list any minor issues found"],
    "recommendations": ["suggestions for improvement"]
  }
}

Be thorough and critical - this is a quality audit. Only return valid JSON, no other text.'''
